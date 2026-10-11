<p align="center">
  <img src="crates/assets/overrides/ember-icon.png" alt="Ember logo" width="160" height="160">
</p>

# How does this differ from Campfire in Rust?

**Ember is a fork of [Campfire in Rust](https://github.com/basecamp/once-campfire-rust) with a
redesigned workspace and new ways to organize rooms, start conversations, and manage preferences.**
It keeps the Rust server and Campfire chat features, along with compatibility with existing
SQLite databases, uploaded files, and current signed/encrypted cookies.

[MIT licensed](MIT-LICENSE) · [Ember on GitHub](https://github.com/nyllon-software/ember) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

Ember is independently maintained by [NYLLON-SOFTWARE](https://github.com/nyllon-software).
Campfire was created by [37signals](https://37signals.com); the Rust implementation is based on
the original [ONCE Campfire Rails application](https://github.com/basecamp/once-campfire).
This repository preserves the upstream Git history and the pinned Rails source in `reference/`.

The comparison below uses Campfire in Rust at our
[fork point, `5eb6d2d`](https://github.com/basecamp/once-campfire-rust/commit/5eb6d2d3b3090aa1680b80e19d077455fe413119),
and describes the implementation in this checkout. Ember is an independent project, not an
official 37signals or Basecamp release.

## Feature comparison

| Area | Campfire in Rust at the fork point | What Ember adds or changes |
|---|---|---|
| Workspace | Campfire's original application interface | A neutral workspace with a navigation rail, conversation sidebar, compact room header, and redesigned settings and authentication screens. |
| Mobile navigation | Original responsive Campfire layout | A dismissible conversation drawer, backdrop, keyboard focus handling, and larger touch controls. |
| Unread activity | Existing unread room state | An Activity control that filters the sidebar to unread conversations and shows their count. |
| Appearance | System-responsive light and dark styling | An explicit **Light / Dark / System** picker with a saved browser preference, cross-tab updates, and live system changes. |
| Favorite rooms | No personal starred-room feature | Star rooms, keep them above other rooms, and choose your own favorite order. |
| Shared room order | Alphabetical shared-room list | Administrators arrange rooms in workspace settings and explicitly save the shared order; members retain their own starred order. |
| Room icons | Original room-type icons | Searchable Lucide icons for open and private rooms, shown in the sidebar and room header. |
| Starting DMs | Existing direct-message page and group-DM support | A people-search modal with multiple recipients, pagination, keyboard selection, and retry handling. |
| Room editing | Ordinary create/edit forms | An **Unsaved Changes** dialog and draft preservation when switching between open and private room forms. |
| Message actions | Existing boosts, replies, edit, copy link, download, and share | A compact toolbar, three quick reactions, an expanded reaction tray, and a redesigned custom-reaction form. |
| Message layout | Original message presentation | Revised spacing, left-aligned messages, follow-up timestamps on hover/focus, and corrected grouping after rapid sends. |
| Attachment uploads | Existing upload queue and percentage progress | A 250 MB per-file limit, clearer transfer/processing display, file sizes, actionable errors, and continued uploads after individual failures. |
| SVG uploads | Downloadable file cards | Lazy image previews for SVG files up to 5 MiB, while retaining the original download. |
| Translation controls | Language-help buttons beside interface fields | An administrator setting to hide them for everyone, enabled by default. |
| Notification enrollment | Existing Web Push and room notification settings | Permission requested directly from the click, readiness after subscription saving, specific error guidance, and manual retry using the bell. |
| First-run setup | Original setup form | A Basecoat form card, avatar preview, password visibility toggle, and an enforced eight-character initial password minimum. |
| Logos and avatars | Existing upload and removal support | Large camera-style pickers, separate removal controls, and the workspace logo in the navigation rail. |
| Product identity | Campfire name and executable | Ember branding, an `ember` executable, configuration aliases, and the actual release version in the footer and response header. |
| Frontend verification | Rails compatibility and shared regression checks | Ember DOM snapshots and disposable-account browser checks for the redesigned interface. |

## Known differences

### Protected setup and independent releases

Installer-managed deployments require a private setup link before the existing first-run form can
be opened. `EMBER_SETUP_TOKEN` is optional for existing manual deployments. The link exchanges a
fragment-only credential over HTTPS for a Secure, HttpOnly, encrypted cookie that expires after
15 minutes. Account creation invalidates setup access. The form, avatar upload, validation, and
automatic sign-in remain the same. Query-string setup credentials are rejected. Authorized,
token-free setup forms and their validation responses use `Referrer-Policy: same-origin` so
native submissions work before JavaScript loads without sending cross-origin referrers.
Other protected setup responses retain `no-referrer`; all protected setup responses remain
`no-store`. First-run paths omit query and error details from logs for all deployments. Their
HTTP-to-HTTPS redirects use no-store/no-referrer and reject queries before constructing a
redirect, including manual installs.

NYLLON's reviewed Docker installer and `emberctl` live in `deploy/installer/`. They support fresh
Ubuntu 24.04 and Debian 13 servers on amd64 and arm64, preserve deployment secrets, pin images by
digest, and use manual updates with complete offline backups. They refuse unmanaged Campfire/ONCE
installations. Upstream changes enter through ordinary review; upstream releases cannot update
an Ember server. Public installation remains unavailable until the stable release and public
verification gates pass. See [release operation](deploy/release/README.md) for the rollout gates.

### Rejected sign-in forms

Sign-in uses a native form submission so a rejected password displays the original HTTP 401
response, retains the email, and clears the password. The frozen Rails form uses Turbo, whose
reload directive otherwise replaces that response with a fresh sign-in page and loses the alert
and email. Successful sign-in and session cookies retain their existing behavior.

### Message identity and inactive-user notifications

Persisted message DOM IDs and edit/delete/reaction targets use database IDs. Client-supplied IDs
remain correlation metadata for optimistic messages, reconciled only within the current user's
room. Pending elements have a separate namespace. Two authors reusing a client ID can no longer
replace or hide each other's displayed messages. Existing database rows require no migration.
Open browser tabs should reload after an upgrade to pick up the new DOM identity and optimistic-message code.

Both Web Push recipient queries exclude inactive users. Banning a user preserves subscriptions
and notification preferences for possible reactivation, while stopping newly selected deliveries.
Notifications already queued or accepted by a push provider cannot be recalled.

### Workspace navigation and appearance

Ember replaces the application-page presentation with a shared workspace layout: a left navigation
rail, a conversation sidebar, a compact room header, an invitation card, and a full-width composer.
The rail provides Home, DMs, Activity, Search, workspace settings, appearance, and your profile.
The navigation rail has 56 × 56 px buttons with rounded corners and padded 80px-wide spacing.
Navigation uses actual room memberships. **Activity** filters the existing sidebar to unread
conversations and shows an unread conversation count. **Search** opens the inherited full message
search, with recent searches shown once above the results.

Rooms appear directly beneath the workspace name, followed by the **DMs** section. Room creation lives
in **Workspace settings**, alongside the existing administrator-only room-creation permission
control. That permission still determines who can create rooms. The new-room back button returns
to workspace settings, including after switching room access types. Ember uses “rooms” consistently
throughout the interface.

On small screens, conversations open in a drawer with a dismissible backdrop, Escape support,
focus handling, and touch-sized controls. The workspace styling also covers search, bots, room
management, profiles, and account settings. Sign-in and invitation signup use labeled form cards.
Account custom CSS remains supported.

The appearance control above your profile avatar offers **Light**, **Dark**, and **System**.
The preference is saved in the browser, persists across visits, synchronizes across tabs, and is
applied before paint. Solid-color palettes and a keyboard-accessible fallback menu support browsers
without light-dark() or native popovers. System mode follows operating-system changes as they happen. First-run setup
shares this preference and defaults to the system palette; it has no separate appearance selector.

### Favorite rooms and shared ordering

The star beside a room name saves a **personal favorite**. Starred rooms stay at the top of your
sidebar in your chosen order. Hold and drag a starred room, or focus it and use **Alt + Up/Down**,
to reorder your favorites. Starring an already-starred room leaves its position intact.

Administrators manage the **shared room order** in Workspace settings. Drag handles and
**Alt + Up/Down** stage a draft; **Save order** applies it to everyone and refreshes connected
sidebars. **Cancel** discards the draft. Failed saves keep the draft available for retry.

Unstarred rooms follow the administrator's saved order. New or unranked rooms follow the ranked
entries alphabetically. Each member's favorites and favorite order survive shared-order changes.
Saving the shared order removes legacy personal overrides for unstarred rooms from earlier versions
of this fork.

Order submissions are checked against visible shared-room memberships. The administrator endpoint
rechecks the role inside the write transaction and preserves ranked private rooms that the
submitting administrator cannot see. Personal reordering accepts only a permutation of the caller's
current visible favorites. Change broadcasts contain no room IDs; each browser fetches its own
authorized sidebar.

### Custom room icons

Room creators and administrators can choose a [Lucide](https://lucide.dev/icons/) icon while
creating or editing an open or private room. The searchable picker supports keyboard navigation,
stages the selection, and offers **Use icon** and cancel actions. Saving the room persists the icon
for everyone; the default hashtag can be restored.

Icons appear in the sidebar and room header, including live sidebar updates. Without JavaScript,
the full catalog is available in a native select. Only canonical catalog names are accepted;
unknown names return 422 before other room changes are applied. Changing a room's access type
retains its icon, and deleting the room removes the preference. The changed room's timestamp is
updated without changing the account timestamp or message fragment caches.

The catalog is pinned to `lucide-static` 1.53.0 and contains 1,869 canonical icons. Chat pages embed
only the selected icons. The picker loads and caches the catalog on first opening and shows
72 results at a time. Uploaded SVGs or user-provided markup cannot become room icons.

### A faster way to start direct messages

The sidebar's new-DM action and the rail's **DMs** button open a shared people-search modal.
Search by full name, choose one or more recipients, and start or reopen a conversation using the
existing direct-room endpoint. A leading `@` is accepted as a search convenience; it does not
introduce unique usernames.

The picker supports keyboard selection, pagination, mobile layouts, and retries after failed
searches. Background sidebar updates preserve the search and selected recipients. Empty people
lists and searches with no matches have separate feedback. The original direct-message page
remains the link destination when the modal enhancement is unavailable.

### Protection for unsaved room edits

New-room and edit-room forms preserve name, icon, and membership drafts when switching between
open and private access. In-app navigation and same-document Back/Forward open an
**Unsaved Changes** dialog with **Discard** and **Save** actions. Escape or closing the dialog
returns to editing. Save validates and persists the room before continuing to the requested
destination; a failed save leaves the draft intact. Reverting the edited values removes the prompt.

Discarded drafts do not reappear from Turbo snapshots. Tab close, reload, and cross-document history
use the browser's standard unsaved-changes warning. Other forms retain their existing save behavior.
Room create/update requests with `Prefer: return=minimal` receive a 204 acknowledgment after saving,
allowing navigation to finish even when the edit removes your own membership. Ordinary form
submissions retain their redirects.

### Message readability, actions, and reactions

Ember changes the presentation of existing message features. Messages are left-aligned with
revised author grouping, spacing, avatars, and date separators. The first message in a group keeps
its header timestamp; follow-up timestamps appear beside the body on hover or keyboard focus,
with space reserved so text does not shift.

Message options open a compact toolbar with three quick reactions, reply or attachment actions,
copy link, edit, and **More reactions**. The expanded tray contains the remaining reactions and
the existing custom boost action. The inline **Add a boost** control opens that same tray, including
after Turbo replaces the reactions; Escape returns focus to the inline control.

On desktop, hovering a message opens its toolbar and keeps it reachable while moving the pointer
onto it. Clicking **Message options** keeps it open for interaction. Only one toolbar opens at a
time. Keyboard and touch users can open it explicitly; Escape dismisses it. Placement stays within
the conversation, and the additional reaction tray opens above the toolbar when necessary near
the composer. Open menus close before Turbo caches a page.

The custom-reaction form has a labeled input, explicit **Add reaction / Cancel** actions, and the
existing 16-character limit. Without JavaScript, the native disclosure includes the full reaction
tray and the inline boost link still opens its original form. Existing message submission,
rich-text editing, reply, boost, attachment, and permission contracts are retained.

Rapid sends also recheck author grouping and day separators when optimistic messages are replaced.
A confirmed message no longer retains a hidden author after the preceding pending message
disappears; the conversation displays correctly without a reload.

### Attachment limits and upload progress

Multipart attachments are capped at **250 MB each (250,000,000 bytes)** while streaming to temporary
storage. Oversized files return 413 before attachment records are created. The composer also rejects
oversized files on selection, paste, or drop before uploading them.

The existing percentage progress now appears with a progress bar, file size, and explicit
uploading/processing states until the attachment is ready. A failed file shows an actionable error
and does not prevent other selected files from uploading. Existing stored files remain downloadable.
The inherited 16 MiB limits on non-file
request bodies and direct-upload requests remain in place.

### SVG attachment previews

SVG uploads up to **5 MiB** gain a lazy browser image preview. The browser reads the existing
download into an isolated `<img>` data URL. Uploaded markup is never inserted into the page DOM;
scripts and external resources do not run in that image context.

The original remains a download served as `application/octet-stream` with attachment disposition.
Oversized or undecodable SVGs retain their file card. This adds no server-side SVG parser or
rendering service and does not change the inherited image/video processing pipeline.

### Translation-button visibility

Administrators can toggle **Hide translation buttons** in Workspace settings. Hiding is enabled
by default for new and existing installs and applies to everyone, including sign-in, invitations,
room forms, profiles, and the welcome card.

These buttons provide language help for interface labels. The setting controls their visibility;
it does not add automatic message translation or full application localization. The choice is
stored in the account's existing settings JSON. Changing it reloads the document to clear Turbo
snapshots; other open browsers pick up the choice on their next page load.

### More reliable notification setup

The room-header bell requests browser permission within the original click, waits for service-worker
activation, and saves the subscription before exposing per-room preferences. Denied permission,
unsupported browsers, missing server configuration, and retryable failures receive distinct
feedback. A failed new subscription is rolled back and the bell becomes available for a manual
retry. This enrollment flow does not add automatic notification-delivery retries.

Web Push delivery and per-room notification preferences come from the Rust base. Ember improves
the enrollment flow. Browsers without Push support show instructions to use a supported browser;
iOS/iPadOS users must install the Home Screen app.

### First-run setup and settings polish

The `/first_run` screen uses a responsive Basecoat form card with visible labels, input icons,
an optional camera-style avatar picker, a password visibility toggle, and a **Continue** button.
It omits translation popups and the appearance selector, while honoring the saved browser palette.
Crossing between the setup and workspace stylesheet profiles reloads the document, including
Turbo frame requests that would otherwise embed the setup form in a workspace page.

The initial administrator password must contain **at least eight characters**, enforced by both
the browser and server. Rejected setup submissions create no account and retain the name and email
for correction. This change applies to first-run setup; existing accounts and sign-in retain their
existing behavior. Multipart setup, optional avatars, and signed sessions retain their contracts.

Workspace logos and profile avatars use a single large preview with an overlaid camera picker
and a separate removal action. Uploads still save immediately, with a submit button available
without JavaScript. The rail displays the uploaded workspace logo and falls back to the Ember mark.
Uploaded logos in the rail and welcome card use the current canvas color behind transparent images.

Entering an editable single-line field selects its current value so typing replaces it; a subsequent
click can position the caret normally. Multiline editors keep their usual behavior. Opening your
profile or workspace settings does not autofocus the name field. The workspace name also keeps
normal caret selection and uses a subtle border change instead of an outer focus ring.
Save confirmations show one checkmark centered
in the content pane; errors and descriptive notices keep their text. Immediate account switches
save without success flashes. Custom CSS saves use a full page navigation so the stylesheet reload
does not consume the confirmation. Membership badges use the shared control styling.

### Branding, release version, and upgrade compatibility

Application copy, page titles, sharing prompts, the web app manifest, installation instructions,
and documentation use **Ember**. New workspaces default to Ember. Existing workspace names exactly
equal to `Campfire` or `Matchbox` display as Ember without rewriting the stored name; custom names
and message contents retain their values.

The supplied Ember flame artwork is the default workspace mark, browser favicon, Home Screen/PWA
icon, setup/sign-in branding, and the startup page. The original PNG is saved as
`crates/assets/overrides/ember-icon.png`; the stock account-logo endpoint serves 512- and 192-pixel
versions from `overrides/logos/`. Fresh installs use these assets without adding an uploaded logo
to the account. Existing custom workspace
logos keep precedence, and removing a custom logo restores the Ember artwork.
Account-logo ETags include the bundled artwork digest and requested size so an upgrade invalidates
cached stock icons without rewriting account data; conditional requests retain their behavior.

The executable is `ember`, with `matchbox` retained as a compatibility alias. Scripts that invoke
the upstream `campfire` executable must use `ember`; there is no `campfire` executable alias.
Rust crate names, the application source directory (`crates/ember/`), frontend asset paths,
JavaScript identifiers, and owned snapshot paths use `ember`.
Sidebar markup retains legacy browser attributes and the room-order stream action so tabs left
open through an upgrade keep filtering, unread counts, and live room ordering. New scripts also
recognize older cached sidebar markup.

Configuration uses `EMBER_*`, accepting `MATCHBOX_*` and then `CAMPFIRE_*` as fallbacks.
The first defined value wins, including an explicitly empty value. Style-profile headers use
`X-Ember-Style-Profile`, with legacy header names still accepted. Appearance preferences use
`ember:appearance`, with reads of earlier `matchbox:appearance` and `campfire:appearance` values.
Account settings use `ember_*` keys while accepting earlier `matchbox_*` keys on read; existing
room order, favorites, and icons survive the rename without a database migration. Reads leave
stored JSON untouched; the next settings update writes the canonical Ember keys.

Ember's additional preferences use the existing `accounts.settings` JSON column:

| Preference | Stored key |
|---|---|
| Language-help button visibility | `hide_translation_buttons` |
| Shared room order | `ember_default_room_order` |
| Per-user favorites and their order | `ember_favorite_channels` |
| Shared-room icon choices | `ember_channel_icons` |

These additions require no schema migration. The SQLite schema, Active Storage file layout,
`_campfire_session` cookie, current signed/encrypted cookie formats, GlobalID namespace, mention
MIME type, and inherited asset module paths remain compatible. Keep the existing storage volume,
secrets, and deployment identity when upgrading to preserve data and sessions.

The footer and `X-Version` header now default to the compiled Cargo release version, currently
`1.0.0` displayed as `1.0`, instead of `0`. `APP_VERSION`, then `GIT_REVISION`, still override it.
`X-Rev` carries an explicitly configured Git revision. Version information comes from build or
deployment configuration rather than an editable database setting.

### Verification of the redesigned interface

Ember owns the presentation of its application pages. Reviewed Ember DOM snapshots and native
browser checks cover the redesign, including setup, sign-in, workspace navigation, room preferences,
conversations, settings, and responsive layouts. The browser checks start temporary app instances
with disposable accounts and storage, without requiring a Rails seed or Docker.

The Rails reference and historical golden fixtures remain in the repository. Unchanged fragments,
HTTP behavior, network traffic, and Cable messages still have compatibility checks. Presentation
exceptions do not blanket-exempt status, network, or Cable checks. Full Rails browser comparison
requires separate review of changed asset requests, body hashes, and sidebar broadcasts; Ember
does not claim visual parity with the original interface. Message show/index/create snapshots and
the three message-fragment presentation exceptions cover the compact-action changes.

### Inherited differences from the original Rails application

The Rust base already made deliberate changes to the Rails implementation. Ember retains the
behavior and limits below; these are part of the inherited baseline rather than new Ember features.

<details>
<summary>Rust-versus-Rails behavior and compatibility limits</summary>

- **Frontend corrections:** session-transfer auto-submit forms explicitly close their form tag;
  the pinned Rails reference omitted it. Background sidebar refreshes preserve the legacy New Ping
  form. Sidebar connection refresh waits for the current Turbo frame to finish loading, preventing
  an aborted response on startup or reconnect. Obsolete connections and removed frames do not reload.
- **WebSockets:** `permessage-deflate` without context takeover compresses each broadcast once
  for all subscribers. Decoded messages remain identical.
- **CSRF:** `Sec-Fetch-Site` replaces tokens. Writes accept `same-origin` and `same-site`, reject
  `cross-site` and missing headers over HTTPS with 422, and retain the `Origin` check. Plain HTTP
  accepts missing headers with `SameSite=Lax` cookies. Pages omit CSRF tags and fields; old tabs
  still work, but HTTPS forms require a browser that sends the header (Safari 16.4 or newer).
- **Jobs:** Redis and Resque are replaced by in-process queues with `JOB_CONCURRENCY` workers per
  job kind. Queued pushes and webhooks are lost on a crash; slow webhooks don't block pushes.
- **Push:** invalid VAPID keys disable push at boot. Subscriptions survive TLS/configuration
  failures and are deleted only on 404/410 or an invalid subscription P-256 key. Notification
  bodies are truncated with an ellipsis at 3 KB and titles at 256 bytes. `VAPID_SUBJECT` is configurable.
  Delivery timeouts are 10 seconds per connect/read and 30 seconds overall.
- **Cookies:** sessions are written only on change and deleted when empty; `last_room` only on
  change. `session_token` is re-signed on the hourly activity refresh, retaining its rolling
  20-year expiry. Other authenticated reads avoid the database writer.
- **Caching:** room, messages and search ETags hash cached page parts rather than the body.
  Copy-link buttons cache paths and resolve them against the page URL; bot JSON is cached per
  base URL, preventing a request's Host from changing other users' links.
- **SQLite:** boot adds `index_messages_on_room_id_and_created_at` and
  `index_messages_on_room_id_and_updated_at` if missing. They remain compatible with Rails.
  Memory mapping is disabled; reads use SQLite's page cache.
- **Media formats:** libvips 8.16.1 and ffmpeg 7.1.5 use the Rails image's Debian sources, with
  byte-identical thumbnails, posters and metadata for supported formats. libvips omits loaders
  Rails already blocks. ffmpeg omits external-library-only formats: tracker modules, game-console
  music, JPEG XL/SVG frames, codec2, teletext and DASH/IMF. Tracker/game-console uploads lack
  duration and bit rate. Unused encoders, muxers, hardware and network support are omitted.
- **Media processing:** message uploads are copied and checksummed before saving their rows, then
  deleted if saving fails. The redundant MD5 reread is skipped; analysis, variants, posters and
  client direct-upload checksums still validate files. At most four media jobs run off the database
  writer. Variants/posters are saved already analyzed; concurrent transforms keep the first saved
  result and delete duplicates. ffmpeg posters time out at 60 seconds, ffprobe at 30.
- **Request limits:** non-file-upload bodies and direct uploads are capped at 16 MiB (413).
  Nonnumeric direct-upload sizes and oversized QR codes return 422. Page numbers cap at a billion.
- **Cable limits:** 64 subscriptions per connection, 4 KiB identifiers and 1 MiB messages.
  Clients that don't read for 30 seconds disconnect. Banning/deactivating a user closes their
  connections after commit.
- **Unfurling:** 10 seconds overall, 5 per connect/read, at most 16 concurrent unfurls, and only
  the first 256 attributes of a `meta` tag are read. Timed-out pages unfurl nothing.
- **Webhooks:** 60 seconds overall, 7 per connect/read. Replies over 100 MB after decompression
  fail delivery without posting a response.
- **Front server:** `TARGET_PORT` binds loopback and enforces front-server timeouts and
  `MAX_REQUEST_BODY`. Cache keys count toward `CACHE_SIZE`, preserve raw paths/queries, skip URIs
  over 2 KB and forward range requests. Idle HTTP/1 connections close at the shorter of
  `HTTP_IDLE_TIMEOUT` and `HTTP_READ_TIMEOUT` until request headers arrive (30 seconds with defaults,
  60 with image settings); HTTP/2 uses the idle timeout. Response header lines containing DEL are omitted.
- **Passwords:** bcrypt runs outside database connections/transactions. Unknown emails still
  perform one bcrypt check.
- **JSON:** floats use the shortest equivalent digits. The web app manifest properly JSON-escapes
  account names and URLs.
- **Search:** words are literal full-text terms, including `NOT`, `AND`, `OR` and `NEAR`.
  The newest 100 matches are selected by message id, as in current Rails. Imported messages
  with creation times out of id order follow id order in search. A bounded global scan
  falls back to a membership-scoped query when most recent matches are inaccessible.
- **Routes and UI:** `/rooms/directs/:id` redirects to the room; infinite `Accept` q-values sort
  first or last by sign; EdgeHTML install instructions include the missing image; the new-ping
  picker requests JSON so suggestions appear.
- **Rich text attributes:** autolinking escapes `<`/`>` in attributes to prevent stored XSS.
  Sanitization drops `name` attributes to prevent DOM clobbering. Styles retain only `color` and
  `background-color` with plain keyword/hex/RGB/HSL values or CSS variables in bot/webhook HTML;
  message pages drop styles.
- **Rich text attachments:** content attachments nest at most eight levels; deeper content is
  empty. Deleted-user mentions render ☒ and are omitted in the editor. Active Storage attachments
  embedded in message bodies, which the composer can't create, render ☒.
- **Malformed rich text:** plain-text extraction failures are logged and use empty text or an
  attachment filename; messages are still indexed, pushed, broadcast and sent to bots. Bodies
  beyond 400 nesting levels or 400 attributes per element are stored unchanged with empty plain
  text. These messages render as unrenderable.
- **Not ported:** Active Storage streaming's duplicate `session_token` cookie or legacy AES-CBC
  cookies; Ember uses AES-GCM.

HTTP-01 ACME validation is only unit-tested; TLS-ALPN-01 is tested end to end against a local ACME
server. Rich text is checked against Rails on 658 cases, including 400 fuzzed cases.

</details>

## Features retained from Campfire in Rust

These capabilities were already present in the base fork and remain part of Ember:

| Capability | Retained behavior |
|---|---|
| Rooms and conversations | Open and private rooms, memberships, direct and group conversations, unread state, presence, and typing notifications. |
| Messaging | Rich-text composition, mentions, replies, boosts/custom reactions, message editing, and message links. |
| Files and media | Uploads, downloads, image variants, video posters, and media metadata using libvips and ffmpeg. |
| Search | Full-text message search scoped to accessible rooms, with recent searches. |
| People and administration | Invitations, account roles, user management, bans/deactivation, avatars, and workspace logos. |
| Integrations | Bot accounts, webhook delivery, and link unfurling. |
| Browser installation and notifications | Web app manifest, service worker, platform installation guidance, Web Push delivery, and room notification preferences. |
| Customization | Workspace name, logo, and account custom CSS. |
| Server | One Rust application executable with built-in TLS/Let's Encrypt, HTTP/2, and Action Cable-compatible WebSockets. |
| Persistence and operations | Existing SQLite/storage formats, current Rails-compatible cookies, backup/restore hooks, in-process jobs, and response/fragment caches. |

The single executable replacing Ruby, Puma, Redis, Resque, and Thruster is work from Campfire in
Rust. Ember still uses libvips and ffmpeg for media. The server architecture and historical
performance improvements are inherited; the [benchmark figures below](#performance) are upstream
measurements rather than new Ember measurements.

## Running it

Build Ember from this repository, including the pinned upstream submodule:

```sh
git clone --recurse-submodules https://github.com/nyllon-software/ember.git
cd ember
docker build -t ember .
```

Run the resulting image with persistent storage:

```sh
docker run -d -p 80:80 -p 443:443 \
  -e SECRET_KEY_BASE=... -e VAPID_PUBLIC_KEY=... -e VAPID_PRIVATE_KEY=... \
  -e TLS_DOMAIN=chat.example.com \
  -v ember:/rails/storage \
  ember
```

[ONCE](https://github.com/basecamp/once) can also deploy an image you build and publish to your
own registry. The executable is `ember`; `matchbox` remains available as a compatibility alias.
The application crate lives in `crates/ember/`. Configuration uses `EMBER_*` names, with
`MATCHBOX_*` and `CAMPFIRE_*` accepted for existing deployments, in that order of precedence.

- `TLS_DOMAIN` enables automatic Let's Encrypt certificates. For plain HTTP, leave it unset and
  set `DISABLE_SSL=1`; any nonblank `DISABLE_SSL` value disables application SSL enforcement.
- `/rails/storage` holds the database, uploads, backups and certificates. Existing installs must
  keep their storage volume (including its existing name) and secrets.
- Web Push needs a valid P-256 VAPID key pair in URL-safe Base64. `VAPID_SUBJECT` sets the contact
  URL; its default is `https://` plus the first `TLS_DOMAIN`, or the project's URL. Keep this pair
  stable across restarts. The room-header bell requests browser permission and saves the subscription
  before showing per-room settings. Embedded browsers without Push support show instructions to
  use a supported browser; iOS/iPadOS users must install the Home Screen app.
- The release version comes from the binary's Cargo package metadata (currently `1.0.0`, displayed
  as `1.0`). `APP_VERSION`, then `GIT_REVISION`, retain their deployment-override precedence.
  The footer and `X-Version` header use the same value; `X-Rev` carries an explicitly configured
  Git revision. Version information is build configuration, not an editable database preference.
- The app listener on `TARGET_PORT` (3000) binds loopback. `TARGET_BIND` overrides this; that listener
  trusts `X-Forwarded-*` from whoever reaches it. Other settings are in
  [`config.rs`](crates/ember/src/config.rs).
- The Dockerfile supports amd64 and arm64.

## Performance

These are historical measurements from the upstream Campfire comparison, retained with attribution.
They are not new benchmarks of Ember.

Measured with 16 concurrent clients on an AMD Ryzen AI MAX+ 395 with 32 GB RAM,
with four hardware cores allocated to each app.

| HTTP workload (requests/sec) | Rails | [Django](https://github.com/basecamp/once-campfire-django) | [Laravel](https://github.com/basecamp/once-campfire-laravel) | [Express](https://github.com/basecamp/once-campfire-express) | [Elixir](https://github.com/basecamp/once-campfire-elixir) | [Go](https://github.com/basecamp/once-campfire-go) | [Rust](https://github.com/basecamp/once-campfire-rust) | [C](https://github.com/basecamp/once-campfire-c) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Room page | 230 | 62 | 760 | 2,622 | 942 | 31,673 | 35,484 | 141,834 |
| Messages page | 402 | 70 | 924 | 3,245 | 1,267 | 30,746 | 40,674 | 151,564 |
| Sidebar | 468 | 229 | 1,383 | 34,938 | 2,515 | 18,586 | 34,479 | 159,850 |
| Search | 399 | 118 | 1,135 | 6,613 | 1,814 | 29,765 | 34,432 | 155,456 |
| Post a message | 248 | 112 | 498 | 2,088 | 1,400 | 9,073 | 8,998 | 7,460 |

[Shared verification](https://github.com/basecamp/once-campfire-verification) · [Detailed results](https://github.com/basecamp/once-campfire-verification/blob/main/docs/performance-review.md).

Database scheduling, rich text rendering and cached-page gzip improvements contributed by
Daniel Collin ([emoon](https://github.com/emoon)) in
[#43](https://github.com/basecamp/once-campfire-rust/pull/43).

## Development

Check out the `reference/` submodule before building. Rust 1.98.1 is available through mise;
native media dependencies are specified in the [`Dockerfile`](Dockerfile).

```sh
git submodule update --init
parity/bin/reference build
parity/bin/seed build
EMBER_REQUIRE_SEED=1 cargo test --workspace --exclude html5ever
cargo clippy --workspace --exclude html5ever --all-targets
cargo fmt --all --check
parity/bin/candidate build
parity/bin/candidate compare
bench/run
```

Seed generation and parity checks need Docker. Tests without the seed skip app integration tests.
For local HTTP development, leave `TLS_DOMAIN` unset and run:

```sh
SECRET_KEY_BASE_DUMMY=1 DISABLE_SSL=1 HTTP_PORT=8080 \
  cargo run --bin ember -- server
```

Open `http://localhost:8080`. The dummy secret is regenerated on every start; use a stable
`SECRET_KEY_BASE` when sessions must survive restarts. If Rust is not on your PATH, use
`mise exec rust@1.98.1 -- cargo ...` for Cargo commands. Build a production image with
`docker build -t ember .`.

The reference harness compares HTML, DOM, accessibility trees, assets, Cable frames and screenshots
against Rails. Ember now owns application-page presentation: reviewed Ember DOM snapshots and
native browser checks cover its redesign. Presentation exceptions do not exempt HTTP status,
network, or Cable checks. The full Rails browser comparison requires a separate review of changed
asset requests, HTML body hashes, and sidebar broadcasts; it is not a claim of visual parity.
See [`parity/SCREENS.md`](parity/SCREENS.md) for the historical coverage and masks,
[`AGENTS.md`](AGENTS.md) for repository layout and working rules,
[`CONTRIBUTING.md`](CONTRIBUTING.md) for contributions, and [`SECURITY.md`](SECURITY.md) for security reports.

### Ember frontend

All pages use compiled Askama templates and the existing form helpers for field names, escaping,
and multipart handling. Port-owned frontend changes live in
[`crates/assets/overrides/`](crates/assets/overrides/), which shadows upstream assets by logical
path; leave `reference/` unchanged.
The workspace interface is styled in
[`zz-ember.css`](crates/assets/overrides/zz-ember.css), loaded after the original stylesheets
so rich-text editor and interaction styles remain available. Shared navigation,
unread activity, and the mobile drawer live in
[`ember/shell.js`](crates/assets/overrides/ember/shell.js). Edit these two files for shared
workspace behavior and appearance; page markup remains in `crates/views/templates/`.

The workspace bundle contains 68,365 bytes of CSS (12,474 gzip) and 7,497 bytes of shell JavaScript
(2,444 gzip), measured with gzip level 9. Room ordering, icon selection, and SVG previews use separate Stimulus
controllers, discovered through the digested importmap alongside the inherited controllers.
The compact message-actions controller adds 8,566 bytes (2,298 gzip).
The composer upload override is 7,703 bytes (2,636 gzip), with a 1,814-byte uploader (734 gzip).
The shared appearance adapter adds 3,237 bytes (1,178 gzip),
built from `basecoat/src/workspace-appearance.js` with the shared preference helpers.
Assets use the existing digested URLs and compression pipeline. Message fragment recording and
content-addressed response caches retain their existing mechanisms; the message presentation digest
and index ETag version change when introducing SVG markup and compact actions so old HTML is not reused.

Room icons use [Lucide](https://lucide.dev/icons/), pinned to `lucide-static` 1.53.0. The committed
`crates/assets/overrides/lucide/catalog.json` contains 1,869 canonical icons; the build emits a
sorted Rust lookup table. Chat pages embed only their selected icons, with no icon-library request.
The picker fetches the digested catalog on first opening (990,964 bytes; 111,212 gzip), shows 72
results at a time, and shares that cached catalog across Turbo visits. The icon picker controller
is 7,851 bytes (2,656 gzip). Geometric SVG elements and attributes are validated during generation;
uploads and user-provided markup cannot become room icons. ISC and Feather MIT attribution is
included in `crates/assets/overrides/lucide/LICENSE.txt`.

The setup screen keeps its separate Basecoat Vega profile. Its shared controls live in
`crates/views/templates/components/ui.html`; colors, fonts, radii and component overrides live in
`crates/assets/overrides/basecoat/src/theme.css`. The internal `Legacy` asset profile now includes the
Ember workspace override; it does not mean those pages retain the original appearance. Basecoat's
bundle and the workspace styles are never loaded together.

Frontend dependencies are pinned. After editing the frontend sources or adding Tailwind classes,
regenerate the assets and rebuild the Rust app:

```sh
npm ci --prefix crates/assets/overrides/basecoat
npm run build --prefix crates/assets/overrides/basecoat
npm test --prefix crates/assets/overrides/basecoat
cargo build --bin ember
```

Generated CSS, JavaScript, and the Lucide catalog are checked in and embedded with digested URLs, so ordinary Cargo and
Docker builds do not require Node.js. CI runs the frontend build in check mode to detect stale output.
Basecoat build inputs and npm dependencies are excluded from the served asset inventory.
Stylesheets still require rebuilding the executable; they are not loaded from disk at runtime.

The Ember browser checks start temporary app instances and never use the normal storage directory:

```sh
npm ci --prefix parity
npm exec --prefix parity -- playwright install chromium
npm run test:kro --prefix parity
```

Set `EMBER_BIN` to test a different binary. Native browser checks cover setup, authentication,
workspace navigation, conversations, settings, and responsive layouts without Docker. They create
real disposable accounts and messages rather than using the development database. They do not
replace the reference-seeded integration suite.

Reviewed page DOM snapshots live under `crates/views/tests/golden/ember/{a,b}` and render the
frozen Rails fixture inputs. To intentionally update them after reviewing a UI change:

```sh
EMBER_UPDATE_VIEWS=1 cargo test -p ember_views
cargo test -p ember_views
```

Inspect the resulting snapshot diff. Historical Rails goldens remain unchanged; unchanged message,
rich-text, and protocol fragments still compare against them. See the
[snapshot notes](crates/views/tests/golden/ember/README.md).

## License and attribution

Ember is distributed under the [MIT License](MIT-LICENSE), the same license as the upstream
Campfire projects. The original 37signals copyright and permission notice are preserved.
Ember contributions are also MIT licensed. Third-party assets and vendored dependencies retain
their own notices, including [Basecoat and Tailwind](crates/assets/overrides/basecoat/LICENSES.txt).

Credit for Campfire, the original Rails application, and the Rust port belongs to their respective
upstream authors and contributors. The Campfire name and original artwork identify that lineage;
this fork is maintained and released as Ember.
