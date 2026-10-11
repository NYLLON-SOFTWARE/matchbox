import assert from "node:assert/strict"
import { after, before, test } from "node:test"
import { execFile, spawn } from "node:child_process"
import { createHash, randomBytes, X509Certificate } from "node:crypto"
import { once } from "node:events"
import fs from "node:fs/promises"
import http from "node:http"
import https from "node:https"
import net from "node:net"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"
import { chromium } from "playwright"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const binary = path.resolve(process.env.EMBER_BIN || process.env.MATCHBOX_BIN || process.env.CAMPFIRE_BIN || path.join(repo, "target/debug/ember"))
const password = "protected-setup-disposable-password"
let browser, certificateDir, certificate, privateKey

before(async () => {
  await fs.access(binary)
  certificateDir = await fs.mkdtemp(path.join(os.tmpdir(), "ember-setup-tls-"))
  const keyFile = path.join(certificateDir, "proxy.key")
  const certificateFile = path.join(certificateDir, "proxy.pem")
  await promisify(execFile)("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
    "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
    "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,digitalSignature,keyEncipherment",
    "-keyout", keyFile, "-out", certificateFile])
  privateKey = await fs.readFile(keyFile)
  certificate = await fs.readFile(certificateFile)
  const publicKey = new X509Certificate(certificate).publicKey.export({ type: "spki", format: "der" })
  const spki = createHash("sha256").update(publicKey).digest("base64")
  // Chromium trusts this disposable certificate key only; Node requests trust the exact certificate below.
  browser = await chromium.launch({ args: ["--ignore-certificate-errors-spki-list=" + spki] })
})
after(async () => {
  await browser?.close()
  if (certificateDir) await fs.rm(certificateDir, { recursive: true, force: true })
})

async function freePort(excluded = []) {
  const listener = net.createServer()
  listener.listen(0, "127.0.0.1")
  await once(listener, "listening")
  const port = listener.address().port
  await new Promise(resolve => listener.close(resolve))
  return excluded.includes(port) ? freePort(excluded) : port
}

async function protectedServer(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ember-protected-setup-"))
  const token = randomBytes(32).toString("hex")
  const port = await freePort()
  const targetPort = await freePort([port])
  const tlsPort = await freePort([port, targetPort])
  const origin = `https://127.0.0.1:${tlsPort}`
  const proxy = https.createServer({ key: privateKey, cert: certificate }, (request, response) => {
    const upstream = http.request({ hostname: "127.0.0.1", port, method: request.method, path: request.url,
      headers: { ...request.headers, "x-forwarded-proto": "https" } }, remote => {
      response.writeHead(remote.statusCode, remote.headers)
      remote.pipe(response)
    })
    upstream.on("error", () => { response.writeHead(502); response.end() })
    request.pipe(upstream)
  })
  proxy.listen(tlsPort, "127.0.0.1")
  await once(proxy, "listening")
  const env = { ...process.env }
  for (const key of Object.keys(env)) {
    if (/^(EMBER_|MATCHBOX_|CAMPFIRE_|THRUSTER_|VAPID_)/.test(key)) delete env[key]
  }
  delete env.DISABLE_SSL
  Object.assign(env, {
    SECRET_KEY_BASE: "protected-setup-disposable-browser-secret".repeat(4),
    EMBER_SETUP_TOKEN: token,
    EMBER_STORAGE_PATH: path.join(dir, "storage"),
    EMBER_DATABASE_PATH: path.join(dir, "storage/db/production.sqlite3"),
    EMBER_FILES_PATH: path.join(dir, "storage/files"),
    EMBER_BACKUPS_PATH: path.join(dir, "storage/backups"),
    RAILS_ENV: "production",
    RAILS_LOG_LEVEL: "error",
    THRUSTER_HTTP_PORT: String(port),
    THRUSTER_TARGET_PORT: String(targetPort),
    THRUSTER_TARGET_BIND: "127.0.0.1",
    THRUSTER_TLS_DOMAIN: "",
    THRUSTER_STORAGE_PATH: path.join(dir, "thruster"),
    THRUSTER_LOG_REQUESTS: "false",
    TOKIO_WORKER_THREADS: "2",
    RAILS_MAX_THREADS: "2",
    JOB_CONCURRENCY: "1",
  })
  // Protected setup diagnostics never retain server transcripts, cookie values, or bearer URLs.
  const child = spawn(binary, [], { cwd: dir, env, stdio: "ignore" })
  let spawnError
  child.on("error", error => { spawnError = error })
  t.after(async () => {
    await new Promise(resolve => proxy.close(resolve))
    if (child.exitCode === null && !spawnError) {
      const exited = once(child, "exit")
      child.kill("SIGTERM")
      const timer = setTimeout(() => child.kill("SIGKILL"), 5000)
      await exited
      clearTimeout(timer)
    }
    await fs.rm(dir, { recursive: true, force: true })
  })
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    if (spawnError) throw new Error("Could not start disposable Ember process")
    if (child.exitCode !== null) throw new Error(`Disposable Ember process exited with code ${child.exitCode}`)
    try {
      const response = await fetch(`http://127.0.0.1:${port}/up`, { signal: AbortSignal.timeout(1000) })
      if (response.ok) return { origin, token }
    } catch { /* The listening sockets are not ready yet. */ }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error("Disposable Ember process did not become ready")
}

async function holdApplicationModule(context) {
  let release, observed
  const gate = new Promise(resolve => { release = resolve })
  const blocked = new Promise(resolve => { observed = resolve })
  await context.route("**/assets/**", async route => {
    if (/\/application-[0-9a-f]+\.js$/.test(new URL(route.request().url()).pathname)) {
      observed()
      await gate
    }
    await route.continue()
  })
  return { release, blocked }
}

async function trustedGet(server, pathname, cookie) {
  return await new Promise((resolve, reject) => {
    const request = https.get(new URL(pathname, server.origin), {
      ca: certificate, agent: false, headers: cookie ? { Cookie: cookie } : {},
    }, response => {
      response.resume()
      response.on("end", () => resolve({ status: response.statusCode, headers: response.headers }))
      response.on("error", () => reject(new Error("Disposable HTTPS response failed")))
    })
    request.setTimeout(5000, () => request.destroy(new Error("Disposable HTTPS request timed out")))
    request.on("error", () => reject(new Error("Disposable HTTPS request failed")))
  })
}

async function openProtectedSetup(page, context, server) {
  const locked = await trustedGet(server, "/first_run")
  assert.equal(locked.status, 403)
  assert.equal(locked.headers["cache-control"], "no-store")
  assert.equal(locked.headers["referrer-policy"], "no-referrer")
  for (const endpoint of ["/first_run", "/first_run/access"]) {
    // Query rejection does not need to expose a real bearer credential in a request URL.
    assert.equal((await trustedGet(server, endpoint + "?token=not-a-credential")).status, 400)
  }
  const access = await trustedGet(server, "/first_run/access")
  assert.equal(access.status, 200)
  assert.equal(access.headers["referrer-policy"], "no-referrer")
  assert.equal(access.headers["cache-control"], "no-store")
  await page.goto("/first_run/access#token=" + server.token, { waitUntil: "commit" })
    .catch(() => { throw new Error("Private setup navigation failed") })
  await page.locator("#user_name").waitFor()
  assert.equal(new URL(page.url()).pathname, "/first_run")
  assert.equal(new URL(page.url()).hash === "", true, "setup clears its bearer fragment")
  const cookie = (await context.cookies()).find(value => value.name === "__Host-ember_setup")
  assert.ok(cookie?.secure && cookie.httpOnly && cookie.sameSite === "Strict" && cookie.path === "/")
}

async function rejectedPassword(page, server, native) {
  await page.locator("#user_name").fill("Protected Setup Admin")
  await page.locator("#user_email_address").fill("protected-admin@example.test")
  await page.locator("#user_password").fill("short")
  const posted = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/first_run")
  // Exercise server validation using the same submit event a person generates, before or after Turbo starts.
  await page.locator("form").first().evaluate(form => { form.noValidate = true; form.requestSubmit() })
  const response = await posted
  assert.equal(response.request().isNavigationRequest(), native, "submission uses the intended native or Turbo path")
  assert.equal((await response.request().allHeaders()).origin, server.origin, "native and Turbo submissions retain the same origin")
  assert.equal(response.status(), 422)
  assert.equal(response.headers()["cache-control"], "no-store")
  assert.equal(response.headers()["referrer-policy"], "same-origin")
  const html = await response.text()
  assert.equal(html.includes('aria-invalid="true"'), true, "422 contains password validation markup")
  assert.equal(html.includes("Password must be at least 8 characters."), true, "422 is the rejected form rather than a generic CSRF error")
  assert.equal(html.includes(server.token), false, "setup bearer is not reflected in response HTML")
}

test("protected setup accepts native submissions before Turbo and normal Turbo validation", { timeout: 60_000 }, async t => {
  for (const native of [true, false]) {
    await t.test(native ? "visible form before application module is ready" : "initialized Turbo form", async t => {
      const server = await protectedServer(t)
      const context = await browser.newContext({ baseURL: server.origin })
      const page = await context.newPage()
      page.setDefaultTimeout(10_000)
      let leakedToken = false, scriptErrors = 0
      page.on("request", request => { if (request.url().includes(server.token)) leakedToken = true })
      page.on("pageerror", () => { scriptErrors++ })
      const held = native ? await holdApplicationModule(context) : null
      try {
        await openProtectedSetup(page, context, server)
        if (native) {
          await held.blocked
          assert.equal(await page.evaluate(() => typeof window.Turbo), "undefined", "the form is visible before Turbo starts")
          assert.notEqual(await page.evaluate(() => document.readyState), "complete")
        } else {
          await page.waitForLoadState("load")
          await page.waitForFunction(() => window.Turbo?.session?.started === true)
        }
        await rejectedPassword(page, server, native)
        held?.release()
        await page.locator('#user_password[aria-invalid="true"]').waitFor()
        assert.equal(await page.locator("#user_name").inputValue(), "Protected Setup Admin")
        assert.equal(await page.locator("#user_email_address").inputValue(), "protected-admin@example.test")
        assert.equal(await page.locator("#user_password").inputValue(), "")
        assert.equal(await page.locator("#composer").count(), 0)
        await page.waitForLoadState("load")
        await page.locator("#user_password").fill(password)
        const created = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/first_run")
        await page.getByRole("button", { name: "Continue", exact: true }).click()
        assert.ok([302, 303].includes((await created).status()), "valid setup creates the account")
        await page.locator("#composer").waitFor()
        const cookie = (await context.cookies()).map(({ name, value }) => name + "=" + value).join("; ")
        assert.equal((await trustedGet(server, new URL(page.url()).pathname, cookie)).status, 200, "setup signs the administrator in")
        const repeated = await trustedGet(server, "/first_run")
        assert.ok([302, 303].includes(repeated.status), "completed setup cannot be reopened")
        assert.equal((await context.cookies()).some(value => value.name === "__Host-ember_setup"), false)
        assert.equal(leakedToken, false, "setup credential never enters a request URL")
        assert.equal(scriptErrors, 0, "setup has no browser script errors")
      } finally {
        held?.release()
        await context.close()
      }
    })
  }
})
