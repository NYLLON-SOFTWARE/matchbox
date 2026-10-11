#!/usr/bin/env python3
"""Fresh native QEMU guests. All trust overrides exist only on the disposable runner."""
import argparse
import atexit
import contextlib
import hashlib
import http.server
import json
import os
import platform
from pathlib import Path
import re
import selectors
import shlex
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'tmp/installer-verification'
HOST = '192.0.2.1'
GUEST = '192.0.2.10'
DOMAIN = 'chat.ember.test'
INSTALL_COMMAND = 'curl -fsSL https://get.nyllon.com/ember | sh --'
HOSTNAME_PROMPT = 'Hostname pointing to this server (for example chat.example.com): '
# Ubuntu arm64 under TCG reached cloud-final at 759s; allow bounded slow guest boots.
GUEST_BOOT_TIMEOUT = 1200
VERIFICATION_STARTED = time.monotonic()
VERIFICATION_STAGES = frozenset(('guest-boot', 'guest-ssh', 'guest-cloud-init', 'guest-packages',
    'preflight', 'first-install', 'browser-setup', 'managed-rerun', 'backup', 'reboot',
    'reboot-ssh', 'reboot-health', 'update', 'explicit-recovery', 'restore', 'complete'))
PEBBLE = 'ghcr.io/letsencrypt/pebble@sha256:d9080f68f6cb6af8d82134ab26de0aaaf312ac9cba42aecc6d3aede6cb63007b'


def run(*args, capture=False, check=True, timeout=600, **kwargs):
    return subprocess.run([str(x) for x in args], check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, timeout=timeout, **kwargs)


def report_stage(stage):
    if stage not in VERIFICATION_STAGES:
        raise ValueError('Unknown verification stage')
    progress = {'stage': stage, 'elapsed_seconds': round(max(0, time.monotonic() - VERIFICATION_STARTED), 1)}
    try:
        print('Guest verification progress: ' + json.dumps(progress, sort_keys=True), file=sys.stderr, flush=True)
    except OSError:
        pass


class InteractiveProgress:
    markers = (
        (b'Reading package lists', 'package-manager-output'),
        (b'Building dependency tree', 'package-manager-output'),
        (b'https://download.docker.com/linux/', 'docker-repository-output'),
        (b'Unpacking docker-ce', 'docker-package-output'),
        (b'Setting up docker-ce', 'docker-package-output'),
        (b'Unpacking containerd.io', 'docker-package-output'),
        (b'Setting up containerd.io', 'docker-package-output'),
        (b'Pulling from nyllon-software/ember', 'image-pull-output'),
        (b'Pulling fs layer', 'image-pull-output'),
        (b'Pull complete', 'image-pull-output'),
        (b'is ready. Open this private link to create the first administrator:', 'ready-message-output'),
        (b'is already managed at https://', 'managed-installation-output'),
    )

    def __init__(self, report):
        self.report = report
        self.started = self.last_activity = self.last_report = time.monotonic()
        self.bytes_received = 0
        self.prompt_observed = self.reply_sent = False
        self.observed_output = 'unknown'
        self.previous = None
        self.pending = b''

    def observe(self, block):
        self.bytes_received += len(block)
        self.last_activity = time.monotonic()
        window = self.pending + block
        matches = [(window.rfind(marker), label) for marker, label in self.markers if marker in window]
        if matches:
            self.observed_output = max(matches)[1]
        self.pending = window[-max(len(marker) for marker, _label in self.markers):]

    def snapshot(self):
        now = time.monotonic()
        return {'observed_output': self.observed_output, 'prompt_observed': self.prompt_observed,
                'reply_sent': self.reply_sent, 'bytes_received': self.bytes_received,
                'elapsed_seconds': round(max(0, now - self.started), 1),
                'last_activity_seconds': round(max(0, self.last_activity - self.started), 1),
                'quiet_seconds': round(max(0, now - self.last_activity), 1)}

    def emit(self, force=False):
        current = (self.observed_output, self.prompt_observed, self.reply_sent)
        now = time.monotonic()
        if self.report and (force or current != self.previous or now - self.last_report >= 60):
            self.report(self.snapshot())
            self.last_report, self.previous = now, current


def interactive_progress_detail(progress):
    return 'Installer interactive progress: ' + json.dumps(progress, sort_keys=True)


class InteractiveCommandFailure(subprocess.CalledProcessError):
    def __init__(self, code, progress):
        super().__init__(code, ['interactive command omitted'], stderr=interactive_progress_detail(progress))


class InteractiveCommandTimeout(subprocess.TimeoutExpired):
    def __init__(self, timeout, progress):
        super().__init__(['interactive command omitted'], timeout, stderr=interactive_progress_detail(progress))


def run_interactive(command, responses, check=True, timeout=900, progress=None):
    """Drive the remote terminal; diagnostics contain only fixed labels and counters."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = bytearray()
    answered = set()
    state = InteractiveProgress(progress)
    deadline = state.started + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        state.emit()
        while selector.get_map():
            state.emit()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InteractiveCommandTimeout(timeout, state.snapshot())
            for key, _events in selector.select(min(remaining, 1)):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(block)
                state.observe(block)
                for index, (prompt, reply) in enumerate(responses):
                    if index not in answered and prompt.encode() in output:
                        state.prompt_observed = True
                        state.emit()
                        process.stdin.write((reply + '\n').encode())
                        process.stdin.flush()
                        answered.add(index)
                        state.reply_sent = True
                state.emit()
        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
    except BaseException as error:
        process.kill()
        process.wait()
        state.emit(force=True)
        if isinstance(error, subprocess.TimeoutExpired):
            raise InteractiveCommandTimeout(timeout, state.snapshot()) from None
        raise
    finally:
        selector.close()
        process.stdin.close()
        process.stdout.close()
    state.emit(force=True)
    result = subprocess.CompletedProcess(command, code, output.decode(errors='replace'), '')
    if check and code:
        # The terminal can contain a setup link; retain only allowlisted progress metadata.
        raise InteractiveCommandFailure(code, state.snapshot())
    return result


class PreflightFailure(AssertionError):
    pass


def sanitized_output(value, limit=4096, secrets=()):
    if isinstance(value, bytes):
        value = value.decode(errors='replace')
    for secret in secrets:
        if secret and value:
            value = value.replace(secret, '[redacted]')
    value = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value or '')
    value = ''.join(character for character in value if character in '\n\t' or character.isprintable())
    value = re.sub(r'(?im)\b(SECRET_KEY_BASE|VAPID_PUBLIC_KEY|VAPID_PRIVATE_KEY|EMBER_SETUP_TOKEN)\s*=\s*[^\n]*', r'\1=[redacted]', value)
    value = re.sub(r'(?im)^\s*(authorization|cookie|set-cookie)\s*:[^\n]*', r'\1: [redacted]', value)
    value = re.sub(r'(?i)(\btoken\s*[=:]\s*)[^\s&#<>"\']+', r'\1[redacted]', value)
    return value if len(value) <= limit else '[truncated]\n' + value[-limit:]


def write_diagnostic(name, detail, emit=False):
    try:
        (WORK / 'diagnostics' / name).write_text(detail)
    except OSError:
        pass
    if emit:
        try:
            print(detail, file=sys.stderr, flush=True)
        except OSError:
            pass


def report_install_progress(progress):
    write_diagnostic('install.log', interactive_progress_detail(progress), emit=True)


class SSHTransportFailure(subprocess.CalledProcessError):
    def __init__(self, stderr, command):
        super().__init__(255, ['ssh', '[remote command omitted]'],
                         stderr=sanitized_output(stderr, secrets=(command,)))


class SSHTransportTimeout(subprocess.TimeoutExpired):
    def __init__(self, timeout, stderr, command):
        super().__init__(['ssh', '[remote command omitted]'], timeout,
                         stderr=sanitized_output(stderr, secrets=(command,)))


def require_preflight_refusal(result, expected, message):
    expected = (expected,) if isinstance(expected, str) else expected
    if result.returncode not in (0, 255) and any(marker.lower() in result.stderr.lower() for marker in expected):
        return
    raise PreflightFailure(f"{message}; exit={result.returncode}\n"
                           f"stdout:\n{sanitized_output(result.stdout)}\n"
                           f"stderr:\n{sanitized_output(result.stderr)}")


def require_privilege_refusal(result):
    # install.sh either reports missing sudo or delegates to sudo's explicit refusal.
    expected = ('Run this installer as root (or install sudo).',
                'sudo: a terminal is required to read the password',
                'sudo: a password is required',
                'nobody is not in the sudoers file',
                'user nobody is not allowed to execute',
                'sudo: nobody is not allowed to run sudo')
    require_preflight_refusal(result, expected,
                              'Unprivileged installation must fail without sudo authorization')


def installer_session_command(command=INSTALL_COMMAND):
    # Explicit disposable-host trust configuration; the public command itself has no flags.
    return ('export EMBER_INSTALL_RUNTIME_ENV=/root/ember-runtime.env '
            'EMBER_INSTALL_TEST_CA=/root/ember-test-ca.pem; ' + command)


def wait_for(action, timeout=600):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return action()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(3)


class Guest:
    def __init__(self):
        self.key = WORK / 'ssh'
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', self.key)

    def ssh_command(self, command, tty=False):
        return ['ssh', *(['-tt'] if tty else []), '-i', str(self.key), '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'LogLevel=ERROR', '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4',
                'root@' + GUEST, command]

    def ssh(self, command, check=True, timeout=900):
        try:
            result = run(*self.ssh_command(command), capture=True, check=False, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise SSHTransportTimeout(error.timeout, error.stderr, command) from None
        if result.returncode == 255:
            raise SSHTransportFailure(result.stderr, command) from None
        if check:
            result.check_returncode()
        return result

    def reboot(self):
        command = 'cat /proc/sys/kernel/random/boot_id'
        before = self.ssh(command).stdout.strip()
        assert before, 'Guest boot ID unavailable before reboot'
        try:
            self.ssh('systemctl reboot', timeout=15)
        except (SSHTransportFailure, SSHTransportTimeout):
            pass  # A reboot may disconnect SSH before systemctl returns.
        time.sleep(10)

        def rebooted():
            after = self.ssh(command, timeout=15).stdout.strip()
            assert after and after != before, 'Guest has not rebooted'

        report_stage('reboot-ssh')
        wait_for(rebooted, timeout=GUEST_BOOT_TIMEOUT)

    def install(self, command=INSTALL_COMMAND, check=True, fresh=False):
        session = installer_session_command(command)
        withheld = 'Interactive stderr unavailable: terminal output intentionally omitted to protect setup credentials.'
        timeout = 3600 if fresh and os.environ.get('GUEST_ARCH') == 'arm64' else 900
        try:
            result = run_interactive(self.ssh_command(session, tty=True),
                                     [(HOSTNAME_PROMPT, DOMAIN)], check=check, timeout=timeout, progress=report_install_progress)
        except subprocess.TimeoutExpired as error:
            detail = withheld + ('\n' + error.stderr if isinstance(error, InteractiveCommandTimeout) else '')
            raise SSHTransportTimeout(error.timeout, detail, session) from None
        except subprocess.CalledProcessError as error:
            if error.returncode == 255:
                detail = withheld + ('\n' + error.stderr if isinstance(error, InteractiveCommandFailure) else '')
                raise SSHTransportFailure(detail, session) from None
            raise
        if result.returncode == 255:
            raise SSHTransportFailure(withheld, session) from None
        return result

    def copy(self, source, destination):
        run('scp', '-q', '-i', self.key, '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
            source, 'root@' + GUEST + ':' + destination, capture=True, timeout=120)

    def boot(self, os_name, arch):
        report_stage('guest-boot')
        item = json.loads((ROOT / 'deploy/verification/guests.lock.json').read_text())[os_name + '/' + arch]
        image = WORK / 'base.qcow2'
        run('curl', '--fail', '--location', '--retry', '3', '--output', image, item['url'])
        digest = hashlib.new(item['algorithm'])
        with image.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        assert digest.hexdigest() == item['checksum'], 'Official guest image checksum mismatch'
        run('qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', image, WORK / 'disk.qcow2', '24G')
        public_key = self.key.with_suffix('.pub').read_text().strip()
        (WORK / 'user-data').write_text('#cloud-config\ndisable_root: false\nssh_pwauth: false\nusers:\n  - name: root\n    ssh_authorized_keys:\n      - ' + public_key + '\n')
        (WORK / 'meta-data').write_text('instance-id: ember-installer-test\nlocal-hostname: ember-test\n')
        (WORK / 'network-config').write_text(f'version: 2\nethernets:\n  ember0:\n    match:\n      macaddress: "52:54:00:12:34:56"\n    set-name: ember0\n    addresses: [{GUEST}/24]\n    routes:\n      - to: default\n        via: {HOST}\n    nameservers:\n      addresses: [{HOST}]\n')
        run('cloud-localds', '--network-config=' + str(WORK / 'network-config'), WORK / 'seed.iso', WORK / 'user-data', WORK / 'meta-data')
        command = ['qemu-system-x86_64', '-machine', 'q35', '-cpu', 'max'] if arch == 'amd64' else ['qemu-system-aarch64', '-machine', 'virt', '-cpu', 'max', '-bios', '/usr/share/qemu-efi-aarch64/QEMU_EFI.fd']
        command += ['-accel', 'tcg', '-smp', '2', '-m', '4096', '-nographic', '-drive', f'file={WORK}/disk.qcow2,format=qcow2,if=virtio', '-drive', f'file={WORK}/seed.iso,format=raw,if=virtio,readonly=on', '-netdev', 'tap,id=net0,ifname=embertap0,script=no,downscript=no', '-device', 'virtio-net-pci,netdev=net0,mac=52:54:00:12:34:56']
        log = (WORK / 'diagnostics/console.log').open('w')
        self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        atexit.register(self.process.terminate)
        report_stage('guest-ssh')
        self.wait_for_ssh()
        report_stage('guest-cloud-init')
        self.ssh('cloud-init status --wait')
        report_stage('guest-packages')
        self.ssh('apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y curl ca-certificates python3')

    def wait_for_ssh(self):
        def ready():
            if self.process.poll() is not None:
                raise RuntimeError('QEMU exited before SSH became available; inspect console.log')
            return self.ssh('true', timeout=15)

        try:
            wait_for(ready, timeout=GUEST_BOOT_TIMEOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, RuntimeError) as error:
            console = WORK / 'diagnostics/console.log'
            tail = b''
            try:
                with console.open('rb') as source:
                    source.seek(max(0, console.stat().st_size - 16384))
                    tail = source.read(16384)
            except OSError:
                pass
            status = self.process.poll()
            detail = (f'Guest SSH readiness failed; QEMU exit status: {status}\n'
                      f'Final SSH/error: {sanitized_output(getattr(error, "stderr", None) or str(error))}\n'
                      f'Console tail:\n{sanitized_output(tail, limit=16384)}\n')
            write_diagnostic('boot.log', detail, emit=True)
            raise


def network(public):
    run('sysctl', '-w', 'net.ipv4.ip_forward=1')
    run('ip', 'link', 'add', 'emberbr0', 'type', 'bridge')
    run('ip', 'addr', 'add', HOST + '/24', 'dev', 'emberbr0')
    run('ip', 'link', 'set', 'emberbr0', 'up')
    run('ip', 'tuntap', 'add', 'dev', 'embertap0', 'mode', 'tap')
    run('ip', 'link', 'set', 'embertap0', 'master', 'emberbr0')
    run('ip', 'link', 'set', 'embertap0', 'up')
    run('iptables', '-t', 'nat', '-A', 'POSTROUTING', '-s', '192.0.2.0/24', '-j', 'MASQUERADE')
    run('iptables', '-I', 'FORWARD', '-i', 'emberbr0', '-j', 'ACCEPT')
    run('iptables', '-I', 'FORWARD', '-o', 'emberbr0', '-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED', '-j', 'ACCEPT')
    args = ['dnsmasq', '--keep-in-foreground', '--bind-interfaces', '--interface=emberbr0', '--listen-address=' + HOST,
            '--no-resolv', '--server=1.1.1.1', '--address=/' + DOMAIN + '/' + GUEST, '--address=/pebble.ember.test/' + HOST]
    if not public:
        args += ['--address=/github.com/' + HOST, '--address=/get.nyllon.com/' + HOST]
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=(WORK / 'diagnostics/dns.log').open('w'))
    atexit.register(process.terminate)
    with open('/etc/hosts', 'a') as hosts:
        hosts.write(f'\n{GUEST} {DOMAIN}\n{HOST} pebble.ember.test\n')


def mirror_certificates(certs):
    # Python 3.13 verifies RFC 5280 strictly, including CA key usage and critical constraints.
    (certs / 'ca.cnf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca_extensions\n[dn]\n'
                                '[ca_extensions]\nbasicConstraints=critical,CA:TRUE\n'
                                'keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n'
                                'authorityKeyIdentifier=keyid:always,issuer\n')
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '3', '-subj', '/CN=Ember isolated runner CA', '-config', certs / 'ca.cnf', '-keyout', certs / 'ca.key', '-out', certs / 'ca.pem', capture=True)
    run('openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-subj', '/CN=pebble.ember.test', '-keyout', certs / 'server.key', '-out', certs / 'server.csr', capture=True)
    (certs / 'extensions').write_text('subjectAltName=DNS:pebble.ember.test,DNS:github.com,DNS:get.nyllon.com\n'
                                    'extendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n'
                                    'keyUsage=critical,digitalSignature,keyEncipherment\n'
                                    'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
    run('openssl', 'x509', '-req', '-sha256', '-in', certs / 'server.csr', '-CA', certs / 'ca.pem', '-CAkey', certs / 'ca.key', '-CAcreateserial', '-days', '3', '-extfile', certs / 'extensions', '-out', certs / 'server.pem', capture=True)


def certificates():
    certs = WORK / 'certs'
    certs.mkdir()
    mirror_certificates(certs)
    config = {'pebble': dict(listenAddress='0.0.0.0:14000', managementListenAddress='0.0.0.0:15000', certificate='/test/server.pem', privateKey='/test/server.key', httpPort=80, tlsPort=443, externalAccountBindingRequired=False)}
    (certs / 'pebble.json').write_text(json.dumps(config))
    run('docker', 'run', '-d', '--name', 'ember-pebble', '--network', 'host', '-e', 'PEBBLE_VA_NOSLEEP=1', '--mount', f'type=bind,source={certs},target=/test,readonly', PEBBLE, '-config', '/test/pebble.json', '-dnsserver', HOST + ':53')
    atexit.register(lambda: run('docker', 'rm', '-f', 'ember-pebble', check=False, capture=True))
    root = wait_for(lambda: run('curl', '--fail', '--silent', '--connect-timeout', '5', '--max-time', '15', '--cacert', certs / 'ca.pem', 'https://pebble.ember.test:15000/roots/0', capture=True).stdout)
    (certs / 'issuer.pem').write_text(root)
    (certs / 'combined.pem').write_text((certs / 'ca.pem').read_text() + root)
    # Chromium must perform normal certificate verification; never ignore HTTPS errors.
    nss = Path.home() / '.pki/nssdb'
    nss.mkdir(parents=True, exist_ok=True)
    run('certutil', '-N', '--empty-password', '-d', 'sql:' + str(nss), check=False, capture=True)
    for name in ('ca', 'issuer'):
        run('certutil', '-A', '-d', 'sql:' + str(nss), '-n', 'ember-test-' + name, '-t', 'C,,', '-i', certs / (name + '.pem'))
    return certs


def public_get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Ember-public-release-verification'})
    return urllib.request.urlopen(request, timeout=30)


def mirror(assets, certs, public):
    overrides = {}
    manifest = json.loads((assets / 'release.json').read_text())
    version = manifest['version']
    bundle_name = 'ember-installer-' + version + '.tar.gz'

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = self.path.split('?')[0]
            name = Path(path).name
            body = overrides.get(path)
            if body is None and path == '/ember':
                body = (assets / 'bootstrap.sh').read_bytes()
            if body is None and path == '/releases/stable.json':
                body = (assets / 'release.json').read_bytes()
            if body is None and path.startswith('/NYLLON-SOFTWARE/ember/releases/download/v' + version + '/') and name in (bundle_name, 'release.json', 'SHA256SUMS'):
                body = (assets / name).read_bytes()
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer((HOST, 443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certs / 'server.pem', certs / 'server.key')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    atexit.register(server.shutdown)
    if public:
        bootstrap = run('curl', '-fsSL', '--connect-timeout', '5', '--max-time', '30', 'https://get.nyllon.com/ember', capture=True).stdout.encode()
        assert bootstrap == (assets / 'bootstrap.sh').read_bytes(), 'Public bootstrap differs from tested bytes'
        live = json.loads(run('curl', '-fsSL', '--connect-timeout', '5', '--max-time', '30', 'https://get.nyllon.com/releases/stable.json', capture=True).stdout)
        assert live == manifest, 'Public stable manifest differs from tested identity'
        with public_get(manifest['bundle']['url']) as response:
            digest = hashlib.sha256(response.read()).hexdigest()
        assert digest == manifest['bundle']['sha256'], 'Public bundle checksum mismatch'
        with public_get('https://get.nyllon.com/') as response:
            assert response.status == 200 and response.headers.get_content_type() == 'text/html', 'Public installation guide must be HTML'
            guide = response.read()
        expected_guide = (ROOT / 'deploy/release/guide.html').read_bytes().replace(b'{{VERSION}}', version.encode())
        assert guide == expected_guide, 'Public installation guide differs from the tested version and instructions'
    return overrides


def browser(phase, token=None):
    env = {**os.environ, 'EMBER_TEST_ORIGIN': 'https://' + DOMAIN, 'EMBER_BROWSER_PROFILE': str(WORK / 'browser-profile'), 'EMBER_TEST_PHASE': phase, 'NODE_EXTRA_CA_CERTS': str(WORK / 'certs/combined.pem')}
    if token:
        env['EMBER_TEST_TOKEN'] = token
    command = ['node', ROOT / 'deploy/verification/browser.mjs']
    try:
        result = run(*command, env=env, timeout=300, capture=True, check=False)
    except subprocess.TimeoutExpired as error:
        browser_output(error.stdout, error.stderr, token)
        raise subprocess.TimeoutExpired(command, error.timeout) from None
    browser_output(result.stdout, result.stderr, token)
    if result.returncode:
        # Playwright call logs can include the private fragment URL. Never retain the transcript.
        raise subprocess.CalledProcessError(result.returncode, command)


def browser_output(stdout, stderr, token=None):
    for value, destination in ((stdout, sys.stdout), (stderr, sys.stderr)):
        safe = sanitized_output(value, limit=16384, secrets=(token,))
        if safe:
            print(safe, end='' if safe.endswith('\n') else '\n', file=destination, flush=True)


@contextlib.contextmanager
def docker_override(guest, contents):
    """Fail only the selected Docker operation; all other daemon calls remain real."""
    wrapper = WORK / 'docker-wrapper'
    wrapper.write_text(contents)
    guest.ssh('test ! -e /usr/bin/docker-real && mv /usr/bin/docker /usr/bin/docker-real')
    try:
        guest.copy(wrapper, '/usr/bin/docker')
        guest.ssh('chmod 755 /usr/bin/docker')
        yield
    finally:
        guest.ssh('mv /usr/bin/docker-real /usr/bin/docker')


def acceptance(guest, assets, certs, overrides, public):
    report_stage('preflight')
    guest.copy(certs / 'ca.pem', '/usr/local/share/ca-certificates/ember-runner.crt')
    guest.copy(certs / 'issuer.pem', '/usr/local/share/ca-certificates/ember-issuer.crt')
    guest.ssh('update-ca-certificates')
    guest.copy(certs / 'combined.pem', '/root/ember-test-ca.pem')
    runtime = WORK / 'runtime.env'
    runtime.write_text('ACME_DIRECTORY=https://pebble.ember.test:14000/dir\nSSL_CERT_FILE=/run/ember-test-ca.pem\n')
    guest.copy(runtime, '/root/ember-runtime.env')
    guest.ssh('chmod 600 /root/ember-runtime.env /root/ember-test-ca.pem')
    failure_command = installer_session_command('curl -fsSL https://get.nyllon.com/ember | sh -s -- --domain ' + DOMAIN)
    assert guest.ssh('command -v docker', check=False).returncode != 0, 'Guest must start without Docker'
    if not public:
        manifest = json.loads((assets / 'release.json').read_text())
        bundle_name = 'ember-installer-' + manifest['version'] + '.tar.gz'
        bundle_path = '/NYLLON-SOFTWARE/ember/releases/download/v' + manifest['version'] + '/' + bundle_name
        bundle = (assets / bundle_name).read_bytes()
        overrides[bundle_path] = bundle[:len(bundle) // 2]
        try:
            interrupted = guest.ssh(failure_command, check=False)
            require_preflight_refusal(interrupted, 'checksum', 'A partial bundle must fail its advertised SHA256 before installation')
        finally:
            del overrides[bundle_path]
        guest.ssh('test ! -e /etc/ember && test ! -e /etc/apt/sources.list.d/docker.sources && ! command -v docker')
    unprivileged = guest.ssh("su -s /bin/sh nobody -c " + shlex.quote(failure_command), check=False)
    require_privilege_refusal(unprivileged)
    assert guest.ssh('test ! -e /etc/ember').returncode == 0
    # Unsupported OS is a real shell preflight, with the guest's OS metadata restored immediately.
    guest.ssh('cp /etc/os-release /root/os-release.saved && printf "ID=unsupported\\nVERSION_ID=99\\n" > /etc/os-release')
    try:
        unsupported = guest.ssh(failure_command, check=False)
        require_preflight_refusal(unsupported, 'Supported systems', 'Unsupported OS must refuse installation')
    finally:
        guest.ssh('cp /root/os-release.saved /etc/os-release')
    port_pid = guest.ssh('nohup python3 -m http.server 80 >/dev/null 2>&1 & echo $!').stdout.strip()
    try:
        wait_for(lambda: guest.ssh('curl -fsS --connect-timeout 3 --max-time 10 http://127.0.0.1/ >/dev/null', timeout=15))
        conflict = guest.ssh(failure_command, check=False)
        require_preflight_refusal(conflict, '80', 'Occupied port must refuse installation')
    finally:
        guest.ssh('kill ' + str(int(port_pid)))
    guest.ssh('DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y runc')
    conflicting_package = guest.ssh(failure_command, check=False)
    require_preflight_refusal(conflicting_package, 'Conflicting package runc', 'Conflicting runc package must refuse installation')
    guest.ssh("dpkg-query -W -f='${Status}' runc | grep -q 'install ok installed'")
    guest.ssh('test ! -e /etc/apt/sources.list.d/docker.sources && test ! -e /etc/ember')
    guest.ssh('DEBIAN_FRONTEND=noninteractive apt-get remove -y runc')
    report_stage('first-install')
    result = guest.install(fresh=True)
    assert result.stdout.count(HOSTNAME_PROMPT) == 1, 'The advertised command must prompt for the hostname through the real terminal'
    state = json.loads(guest.ssh('cat /etc/ember/state.json').stdout)
    manifest = json.loads((assets / 'release.json').read_text())
    assert state['domain'] == DOMAIN and state['release']['image'] == manifest['image'], 'The real prompt must select the hostname without changing the candidate image'
    expected_runtime = {'ACME_DIRECTORY': 'https://pebble.ember.test:14000/dir', 'SSL_CERT_FILE': '/run/ember-test-ca.pem'}
    assert json.loads(guest.ssh('cat /etc/ember/runtime.json').stdout) == expected_runtime
    container = json.loads(guest.ssh('docker container inspect ember').stdout)[0]
    assert container['Config']['Image'] == manifest['image'] and container['Config']['User'] == '1000:1000'
    assert all(key + '=' + value in container['Config']['Env'] for key, value in expected_runtime.items())
    assert any(mount['Source'] == '/etc/ember/test-ca.pem' and mount['Destination'] == '/run/ember-test-ca.pem' and mount['RW'] is False for mount in container['Mounts']), 'The explicit test CA must be mounted read-only'
    token = re.search(r'/first_run/access#token=([a-f0-9]{64})', result.stdout).group(1)
    report_stage('browser-setup')
    browser('setup', token)
    report_stage('managed-rerun')
    baseline = guest.ssh('sha256sum /etc/ember/app.env').stdout
    repeated = guest.install()  # Working Docker and existing managed deployment; preserve all state.
    assert HOSTNAME_PROMPT not in repeated.stdout, 'Rerunning the advertised command must retain the managed hostname'
    assert guest.ssh('sha256sum /etc/ember/app.env').stdout == baseline
    report_stage('backup')
    guest.ssh('emberctl backup')
    backup = guest.ssh('find /var/lib/ember/backups -mindepth 1 -maxdepth 1 -type d | sort | tail -1').stdout.strip().split('/')[-1]
    report_stage('reboot')
    run('docker', 'stop', 'ember-pebble', capture=True)  # Cached certificates must survive without the CA.
    guest.reboot()
    report_stage('reboot-health')
    wait_for(lambda: guest.ssh('emberctl status', timeout=15))
    wait_for(lambda: guest.ssh('curl -fsS --connect-timeout 3 --max-time 10 https://' + DOMAIN + '/up', timeout=15))
    assert guest.ssh('sha256sum /etc/ember/app.env').stdout == baseline
    browser('persist')
    run('docker', 'start', 'ember-pebble', capture=True)
    if not public:
        report_stage('update')
        manifest = json.loads((assets / 'release.json').read_text())
        parts = list(map(int, manifest['version'].split('.')))
        parts[2] += 1

        def stage_release(selected_version):
            directory = WORK / ('release-' + selected_version)
            run('python3', ROOT / 'deploy/installer/build-bundle.py', '--version', selected_version,
                '--source-sha', manifest['source_sha'], '--image-digest', manifest['image'].split('@')[1], '--output-dir', directory)
            for file in directory.iterdir():
                overrides['/NYLLON-SOFTWARE/ember/releases/download/v' + selected_version + '/' + file.name] = file.read_bytes()

        next_version = '.'.join(map(str, parts))
        stage_release(next_version)
        state_before = guest.ssh('sha256sum /etc/ember/state.json /etc/ember/app.env').stdout
        container_before = guest.ssh("docker inspect --format '{{.Id}} {{.State.Running}} {{.State.StartedAt}}' ember").stdout
        backup_before = guest.ssh('find /var/lib/ember/backups -mindepth 1 -maxdepth 1 -type d | sort').stdout
        pull_failure = '#!/bin/sh\nif [ "$1" = pull ]; then echo "Registry unavailable (acceptance injection)" >&2; exit 69; fi\nexec /usr/bin/docker-real "$@"\n'
        with docker_override(guest, pull_failure):
            unavailable = guest.ssh('emberctl update ' + next_version, check=False)
            require_preflight_refusal(unavailable, 'Registry unavailable', 'A failed registry pull must abort the update')
            assert guest.ssh('sha256sum /etc/ember/state.json /etc/ember/app.env').stdout == state_before
            assert guest.ssh("docker inspect --format '{{.Id}} {{.State.Running}} {{.State.StartedAt}}' ember").stdout == container_before, 'Registry failure must not stop or recreate the live container'
            assert guest.ssh('find /var/lib/ember/backups -mindepth 1 -maxdepth 1 -type d | sort').stdout == backup_before
            guest.ssh('test ! -e /var/lib/ember/recovery.json && test -z "$(find /var/lib/ember -maxdepth 1 -name \".update-bundle-*\" -print)"')
        browser('persist')
        guest.ssh('emberctl update ' + next_version)
        browser('persist')
        # Startup fault injection uses the real daemon, backup, journal, and health deadline.
        parts[2] += 1
        failed_version = '.'.join(map(str, parts))
        stage_release(failed_version)
        startup_failure = '#!/bin/sh\nif [ "$1" = create ]; then shift; exec /usr/bin/docker-real create --entrypoint /bin/false "$@"; fi\nexec /usr/bin/docker-real "$@"\n'
        with docker_override(guest, startup_failure):
            failed = guest.ssh('emberctl update ' + failed_version, check=False)
            require_preflight_refusal(failed, 'restore', 'Failed startup must require explicit recovery')
        report_stage('explicit-recovery')
        journal = json.loads(guest.ssh('cat /var/lib/ember/recovery.json').stdout)
        guest.ssh('emberctl restore ' + shlex.quote(journal['backup']) + ' --accept-data-loss')
        browser('persist')
    report_stage('restore')
    guest.ssh('emberctl restore ' + shlex.quote(backup) + ' --accept-data-loss')
    assert guest.ssh('sha256sum /etc/ember/app.env').stdout == baseline
    browser('persist')
    assert guest.ssh('emberctl setup-link', check=False).returncode != 0, 'Completed setup cannot be reopened'
    summary = {'os': os.environ['GUEST_OS'], 'arch': os.environ['GUEST_ARCH'], 'public': public, 'gates': ['anonymous-install', 'advertised-command-real-terminal-hostname', 'private-browser-setup', 'chat', 'upload', 'websocket', 'push-enrollment', 'rerun', 'offline-ca-reboot', 'complete-backup-restore'] + ([] if public else ['interrupted-download', 'registry-unavailable-preserves-running-app', 'update', 'failed-start-explicit-recovery'])}
    (WORK / 'diagnostics/result.json').write_text(json.dumps(summary, indent=2) + '\n')
    report_stage('complete')


def failure_diagnostics(guest, error):
    if isinstance(error, (SSHTransportFailure, SSHTransportTimeout)):
        reason = f'timeout={error.timeout}s' if isinstance(error, SSHTransportTimeout) else f'exit={error.returncode}'
        detail = f'Guest SSH transport failed; {reason}\nstderr:\n{error.stderr}\n'
        write_diagnostic('transport.log', detail, emit=True)
    if isinstance(error, PreflightFailure):
        write_diagnostic('preflight.log', str(error) + '\n')
    # Do not upload environment files, cookies, tokens, databases, or raw HTTP traces.
    try:
        log = sanitized_output(guest.ssh('docker logs --tail 100 ember', check=False, timeout=15).stdout, limit=16384)
    except (SSHTransportFailure, SSHTransportTimeout, OSError):
        # Diagnostic collection must preserve the original failure and its transport evidence.
        return
    write_diagnostic('application.log', log)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path, required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0 and platform.system() == 'Linux' and os.environ.get('GITHUB_ACTIONS') == 'true', 'Run only as root on a disposable Linux GitHub runner'
    expected = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    assert expected == os.environ['GUEST_ARCH'], 'Use a native runner for each architecture'
    assert not WORK.exists(), 'Use a fresh runner for each guest'
    (WORK / 'diagnostics').mkdir(parents=True)
    os.chmod(WORK, 0o700)
    public = os.environ.get('PUBLIC_INSTALLER') == 'true'
    network(public)
    certs = certificates()
    overrides = mirror(args.assets.resolve(), certs, public)
    guest = Guest()
    try:
        guest.boot(os.environ['GUEST_OS'], os.environ['GUEST_ARCH'])
        acceptance(guest, args.assets.resolve(), certs, overrides, public)
    except BaseException as error:
        failure_diagnostics(guest, error)
        raise


if __name__ == '__main__':
    main()
