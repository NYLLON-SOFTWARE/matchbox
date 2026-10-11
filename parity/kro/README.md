# KRO browser checks

Build the Rust binary and put OpenSSL with `req -addext` support on `PATH`, then run:

```sh
npm ci --prefix parity
npx --prefix parity playwright install chromium
npm run test:kro --prefix parity
```

`EMBER_BIN` can select another built binary (default `target/debug/ember`); `MATCHBOX_BIN` and
`CAMPFIRE_BIN` remain accepted as fallbacks. These checks start fresh Ember processes on dynamically
chosen ports, with private temporary SQLite and file storage. They never connect to the development server or use its accounts. A Rails seed and
Docker are not needed for this gate; the seed-backed integration and Rails parity gates remain
separate checks.

The test owns the first-run screen's visual expectations: a centered, bounded form card on desktop,
no horizontal overflow at 320 pixels, visible labels above their controls, usable input dimensions,
visible keyboard focus, and contrasting light/dark colors. Screenshots of the 320-pixel and desktop
layouts in both modes are saved to ignored `parity/out/kro/`. Geometry and color assertions avoid
platform-dependent system-font rasterization baselines. Inspect these screenshots when changing
the design; the assertions complement human visual review rather than replace it.

Behavior checks cover required fields, the eight-character password minimum (including server rejection
when native validation is bypassed), multipart signup with/without an avatar, avatar preview and
persistence, sign-in, repeat-setup protection, JavaScript-free signup, existing appearance preferences and
OS changes, application of the saved appearance before the body is parsed, password visibility and absence of language/appearance selectors, and the full-document
transition into legacy pages (including Turbo frames). Authenticated message requests check stable
ETags, matching cached HTML, conditional 304 responses, and invalidation after posting a message.
A navigation fixture exercises Turbo cached restoration before an
account is created, because the real setup route correctly becomes unavailable afterward.

Protected setup checks exercise the private fragment link over a disposable HTTPS proxy. Chromium
trusts only that fixture certificate's public key, and Node probes verify its exact certificate.
The checks hold the application module until the form is visible, then verify native submission
before Turbo starts and submission after Turbo starts. Both paths must preserve same-origin CSRF
checks, return the password validation form, retain name/email, clear the password, and complete
signup with automatic sign-in. Locked setup, query rejection, private-link headers, and cookie
invalidation remain covered without retaining credentials in diagnostics. Run this case alone with:

```sh
node --test --test-name-pattern="protected setup" parity/kro/protected-setup.test.mjs
```

Translation visibility checks cover the hidden default, persistence, administrator changes,
public and authenticated pages, Turbo document reloads, and rejection of changes by members.

The exact first-run and administrator settings states are listed in `allowlist.yml` as intentional
differences from Rails. A completed setup also hides the welcome card's translation control;
its cable traffic remains subject to comparison. For other legacy comparisons the candidate
image explicitly enables translation controls in its disposable copied seed, matching Rails.
This does not change production defaults. Member settings pages retain strict comparisons.

Branding checks require Ember on setup, page titles, the welcome screen, the web app manifest,
and the static startup page. Rails parity normalizes the deliberate product-name and logo-path
differences; application text is equalized before screenshots, while chat contents are left alone.
The stock account-logo responses normalize only the exact reference and Ember icon bytes; uploaded
workspace logo bytes, response status, and headers remain strict.
