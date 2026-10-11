import assert from 'node:assert/strict'
import { chromium } from '../../parity/node_modules/playwright/index.mjs'

const origin = process.env.EMBER_TEST_ORIGIN
const profilePath = process.env.EMBER_BROWSER_PROFILE
const phase = process.env.EMBER_TEST_PHASE
const password = 'Disposable-Ember-acceptance-password'
const messageText = 'Ember survives a reboot, update, and complete restore.'
const attachmentText = 'A persistent Ember acceptance attachment.\n'
// Chromium disables PushManager registration in incognito contexts. Keep this private
// disposable profile across phases so real push enrollment and sign-in survive reboots.
const context = await chromium.launchPersistentContext(profilePath, { baseURL: origin, channel: 'chromium', ignoreDefaultArgs: ['--disable-background-networking'], args: ['--no-sandbox'] })
const browser = context.browser()
try {
  const page = await context.newPage()
  page.setDefaultTimeout(30_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let cableConfirmed = false
  page.on('websocket', socket => {
    assert.equal(new URL(socket.url()).protocol, 'wss:')
    socket.on('framereceived', ({ payload }) => { if (String(payload).includes('confirm_subscription')) cableConfirmed = true })
  })
  if (phase === 'setup') {
    const token = process.env.EMBER_TEST_TOKEN
    assert.ok(typeof token === 'string' && /^[a-f0-9]{64}$/.test(token), 'Expected a disposable setup credential')
    const direct = await context.request.get('/first_run')
    assert.equal(direct.status(), 403)
    assert.equal(direct.headers()['cache-control'], 'no-store')
    assert.equal(direct.headers()['referrer-policy'], 'no-referrer')
    const query = await context.request.get('/first_run/access?token=not-a-credential')
    assert.equal(query.status(), 400)
    const bad = await context.request.post('/first_run/access', { form: { token: '0'.repeat(64) }, headers: { Origin: origin, 'Sec-Fetch-Site': 'same-origin' } })
    assert.equal(bad.status(), 403)
    const foreign = await context.request.post('/first_run/access', { form: { token }, headers: { Origin: 'https://attacker.example', 'Sec-Fetch-Site': 'cross-site' } })
    assert.equal(foreign.status(), 422)
    page.on('request', request => assert.ok(!request.url().includes(token), 'Setup credential must never enter a request URL'))
    await page.goto('/first_run/access#token=' + token).catch(() => { throw new Error('Private setup navigation failed') })
    await page.locator('#user_name').waitFor()
    assert.ok(new URL(page.url()).hash === '', 'Setup must clear its private fragment')
    const cookie = (await context.cookies()).find(value => value.name === '__Host-ember_setup')
    assert.ok(cookie?.secure && cookie.httpOnly && cookie.path === '/' && cookie.sameSite === 'Strict')
    assert.ok(cookie.expires > Date.now() / 1000 + 850 && cookie.expires < Date.now() / 1000 + 910)
    const expired = await browser.newContext({ baseURL: origin })
    await expired.addCookies([{ ...cookie, expires: Math.floor(Date.now() / 1000) - 1 }])
    assert.equal((await expired.request.get('/first_run')).status(), 403)
    await expired.close()
    await page.locator('#user_name').fill('Ember Acceptance Admin')
    await page.locator('#user_email_address').fill('admin@example.test')
    await page.locator('#user_password').fill('short')
    async function rejectShortPassword(native) {
      const invalidSetup = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/first_run')
      // Exercise the native fallback independently of Turbo initialization, then its fetch path.
      // Both bypass client minlength so server-side validation remains a required gate.
      await page.locator('form').first().evaluate((form, native) => {
        form.noValidate = true
        if (native) HTMLFormElement.prototype.submit.call(form)
        else form.requestSubmit()
      }, native)
      const response = await invalidSetup
      assert.equal(response.status(), 422)
      assert.equal(response.request().isNavigationRequest(), native)
      assert.equal((await response.request().allHeaders()).origin, origin)
      assert.equal(response.headers()['cache-control'], 'no-store')
      assert.equal(response.headers()['referrer-policy'], 'same-origin')
      const passwordInput = (await response.text()).match(/<input\b[^>]*\bid="user_password"[^>]*>/)?.[0]
      // Report a fixed assertion message, never the credential-bearing response body.
      assert.ok(passwordInput?.includes('aria-invalid="true"'), 'Server must return the invalid-password setup form')
      await page.locator('#user_password[aria-invalid="true"]').waitFor()
      assert.equal(await page.locator('#user_name').inputValue(), 'Ember Acceptance Admin')
      assert.equal(await page.locator('#user_email_address').inputValue(), 'admin@example.test')
      assert.equal(await page.locator('#user_password').inputValue(), '')
      assert.equal(await page.locator('#composer').count(), 0)
    }
    await rejectShortPassword(true)
    await page.waitForFunction(() => window.Turbo?.session?.started === true)
    await page.locator('#user_password').fill('short')
    await rejectShortPassword(false)
    await page.locator('#user_password').fill(password)
    await page.locator('#user_avatar').setInputFiles({ name: 'avatar.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64') })
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    await page.locator('#composer').waitFor()
    const roomPath = new URL(page.url()).pathname
    const editor = page.locator('#composer lexxy-editor [contenteditable="true"]')
    await editor.click()
    await editor.pressSequentially(messageText)
    const sent = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === roomPath + '/messages')
    await page.getByRole('button', { name: 'Send Message', exact: true }).click()
    assert.equal((await sent).status(), 200)
    await page.locator('.message[data-message-id]').filter({ hasText: messageText }).waitFor()
    const uploaded = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === roomPath + '/messages')
    await page.locator('#composer input[type="file"]').setInputFiles({ name: 'acceptance.txt', mimeType: 'text/plain', buffer: Buffer.from(attachmentText) })
    await page.getByRole('button', { name: 'Send Message', exact: true }).click()
    assert.equal((await uploaded).status(), 200)
    await page.locator('.message[data-message-id]').filter({ hasText: 'acceptance.txt' }).waitFor()
    await context.grantPermissions(['notifications'], { origin })
    const enrolled = page.waitForResponse(response => response.request().method() === 'POST' && /\/push_subscriptions$/.test(new URL(response.url()).pathname), { timeout: 60_000 })
    await page.locator('[data-action="click->notifications#attemptToSubscribe"]').click()
    assert.ok((await enrolled).ok(), 'Real browser PushManager enrollment must succeed')
    const subscription = await page.evaluate(async () => (await navigator.serviceWorker.ready).pushManager.getSubscription().then(value => value?.toJSON()))
    assert.ok(subscription?.endpoint.startsWith('https:') && subscription.keys?.p256dh && subscription.keys?.auth)
    const replay = await browser.newContext({ baseURL: origin })
    const response = await replay.request.post('/first_run/access', { form: { token }, headers: { Origin: origin, 'Sec-Fetch-Site': 'same-origin' }, maxRedirects: 0 })
    assert.ok([302, 303].includes(response.status()), 'Completed account invalidates setup token')
    await replay.close()
    // Verify ordinary sign-in independently of automatic setup sign-in.
    const login = await browser.newContext({ baseURL: origin })
    const loginPage = await login.newPage()
    await loginPage.goto('/session/new')
    await loginPage.locator('#email_address').fill('admin@example.test')
    await loginPage.locator('#password').fill('Wrong-disposable-password')
    const rejectedLogin = loginPage.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/session')
    await loginPage.locator('form').first().evaluate(form => form.requestSubmit())
    assert.equal((await rejectedLogin).status(), 401)
    await loginPage.getByText('Too many requests or unauthorized.', { exact: true }).waitFor()
    assert.equal(await loginPage.locator('#email_address').inputValue(), 'admin@example.test')
    assert.equal(await loginPage.locator('#password').inputValue(), '')
    assert.equal(await loginPage.locator('#composer').count(), 0)
    const unauthenticated = await login.request.get('/', { maxRedirects: 0 })
    assert.ok([302, 303].includes(unauthenticated.status()), 'Wrong password must not establish a session')
    assert.equal(new URL(unauthenticated.headers().location, origin).pathname, '/session/new')
    await loginPage.locator('#password').fill(password)
    await loginPage.locator('form').first().evaluate(form => form.requestSubmit())
    await loginPage.locator('#composer').waitFor()
    await login.close()
  } else {
    await page.goto('/')
    await page.locator('#composer').waitFor()
    await page.locator('.message[data-message-id]').filter({ hasText: messageText }).waitFor()
  }
  const attachment = page.locator('.message[data-message-id]').filter({ hasText: 'acceptance.txt' })
  const href = await attachment.locator('a[aria-label="Download"]').getAttribute('href')
  assert.equal(await (await context.request.get(href)).text(), attachmentText)
  await page.waitForFunction(() => document.querySelector('#message-area') !== null)
  const cableDeadline = Date.now() + 30_000
  while (!cableConfirmed && Date.now() < cableDeadline) await new Promise(resolve => setTimeout(resolve, 100))
  assert.ok(cableConfirmed, 'Action Cable subscription must complete over WSS')
  assert.deepEqual(errors, [], 'No browser script errors')
  console.log(`Browser ${phase}: setup/session, messages, upload, WSS, and push checks passed`)
} finally {
  await context.close()
}
