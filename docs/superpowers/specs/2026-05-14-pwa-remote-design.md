# PWA phone remote for Boombox

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-05-14
**Owner:** jwc

## Goal

Give the user an installable phone app — a Progressive Web App — that is a
*killer remote* for the boombox: the full transport surface, source switching,
video control, playlist creation, and live theming that matches the device.

The backend for this is largely already built. `boombox-remote`
(`services/boombox-remote.py`) exposes a consolidated REST + WebSocket control
API at `/api/remote/`, with bearer-token pairing, mDNS discovery, album art,
and a BLE GATT peripheral — all built for the CYD hardware remote. A PWA is
mostly a new *client* of that API.

This spec also consolidates a second, overlapping service.
`boombox-uploader` (`services/boombox-uploader.py`) is a hand-written one-page
HTML "LAN remote + file drop" that grew its own playback controls and its own
PIN system. Two services aimed at "a phone controlling the boombox" is one too
many. The PWA work **retires `boombox-uploader` and folds its still-wanted
capabilities (playlist creation, file upload/management) into `boombox-remote`
and the PWA.**

## Non-goals (v1)

- **iOS Bluetooth.** A PWA in iOS Safari cannot use Web Bluetooth — Apple has
  never shipped it. iOS is WiFi-only. This is a platform wall, not a scope
  cut.
- **Playlist editing/reordering.** v1 creates playlists (search → draft →
  save) and plays them. Reordering tracks within a saved playlist, renaming,
  and deleting playlists are deferred.
- **Jellyfin library browsing from the PWA.** Video control is *transport*
  (play/pause/seek/volume) of whatever Jellyfin session is active on the
  boombox. Browsing the Jellyfin library and starting playback from the phone
  is deferred — use the touchscreen or the native Jellyfin app for that.
- **Multi-boombox.** One PWA install controls one paired boombox. mDNS already
  carries the groundwork; multi-device is a later pass.
- **Replacing the native Jellyfin apps.** The PWA controls video on the
  boombox; it is not a video player itself.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Connectivity | WiFi (HTTP + WebSocket) is the universal transport. Web Bluetooth is an Android-only fallback when HTTP is unreachable. iOS is WiFi-only. |
| Backend consolidation | Full merge. `boombox-remote` absorbs the uploader's wanted capabilities; `boombox-uploader.py` + its unit + its nginx block are retired. Port 6683 is freed. |
| PWA hosting | Built as a static SPA (`remote-ui/`, new Vite/React/TS project), served by nginx at `/remote/` with `auth_basic off` — parallels how the kiosk SPA is served at `/`. |
| Access control | A persisted `remote_enabled` flag, **default off**, gates the phone-facing surface. The touchscreen Settings drawer toggles it. |
| Authorization durability | Pairing produces a bearer token in `peers.json` (already persisted). That token survives reboots, PIN rotation, and toggling the function off→on. **A device is paired once, ever.** |
| PIN model | Unchanged from today — ephemeral minted PIN (`/pair/start` mints, `/pair` redeems, short TTL, single-use). No persistent PIN. |
| BLE vs the toggle | The `remote_enabled` flag gates the phone/PWA HTTP surface, **not** the BLE peripheral — the CYD hardware remote must keep working without anyone toggling anything. |
| Video | Real transport control via Jellyfin's REST API, proxied server-side through `boombox-remote` (no Jellyfin creds or CORS in the browser). |
| Source switching | New `source` action in `actions.py`, value-parameterized — fixes the long-standing gap where the CYD firmware sends `source` but the dispatcher rejects it. |
| Playlists | First-class PWA screen, **available on mobile** — it is curation, not file management. Library search → draft → save as a Mopidy playlist → play. |
| File management | Upload + library browse/download/delete, migrated from the uploader. **Desktop-only** — shown only above a width breakpoint in the responsive PWA. |
| Theming | The PWA dynamically matches the device's active skin. The WS state payload carries a `theme` object; the PWA restyles live when the skin changes on the device. |

## Architecture

```
        Phone (PWA, installed)                 Raspberry Pi
   ┌───────────────────────────┐        ┌───────────────────────────────┐
   │  remote-ui (React SPA)    │        │  nginx :8090                  │
   │  ┌─────────────────────┐  │        │   /remote/    → static SPA    │
   │  │ Transport layer     │  │  HTTP  │   /api/remote/→ :6685         │
   │  │  HttpTransport ─────┼──┼────────┼─▶ boombox-remote :6685        │
   │  │  BleTransport ──────┼──┼─ BLE ──┼─▶  ├─ control API (exists)    │
   │  └─────────────────────┘  │  (GATT)│    ├─ pair / peers (exists)   │
   │  Screens: Now Playing,    │        │    ├─ BLE peripheral (exists) │
   │  Sources, Video,          │        │    ├─ admin enable/disable ✦  │
   │  Playlists, (desktop)     │        │    ├─ source action ✦         │
   │  Files                    │        │    ├─ files/* ✦               │
   └───────────────────────────┘        │    ├─ library + playlists ✦   │
                                        │    ├─ video/* (Jellyfin) ✦    │
                                        │    └─ theme in state ✦        │
                                        │  actions.py ── Mopidy / state │
                                        │  Jellyfin :8096               │
                                        └───────────────────────────────┘
                                          ✦ = new in this spec
```

Single client contract: the PWA talks **only** to `/api/remote/*` with one
bearer token. It never reaches Mopidy, `boombox-state`, or Jellyfin directly —
`boombox-remote` proxies those server-side. This is what lets the old
uploader's reverse-proxy hack be deleted entirely.

## Pi-side: `boombox-remote` changes

`boombox-remote.py` stays a single asyncio aiohttp service on `127.0.0.1:6685`,
boot-enabled (it must be — the BLE peripheral and CYD depend on it). All new
routes live under the existing `/api/remote/` prefix.

### Access control — `remote_enabled` flag

- A persisted flag in `~/.config/boombox-remote/state.json` (`{"enabled":
  false}`), alongside the existing `peers.json`. **Default: off** — a missing
  file reads as off.
- New middleware: when the flag is off, the phone-facing routes (`state`,
  `command`, `ws`, `art`, `files/*`, `library/*`, `playlists/*`, `video/*`)
  return `403 {"ok": false, "error": "remote_disabled"}`. The WS handler closes
  with a custom code (`4403`). Pairing routes (`pair/start`, `pair`) are also
  gated — you cannot pair while the function is off.
- New localhost-only admin routes for the touchscreen:
  - `GET  /api/remote/admin/status` → `{enabled, peers: [{label, paired_at}], pin?}`
  - `POST /api/remote/admin/enable`  → flips the flag on
  - `POST /api/remote/admin/disable` → flips the flag off (does **not** clear
    `peers.json` — authorization is durable)
  - `POST /api/remote/admin/unpair`  → `{token}` removes one peer
- The BLE peripheral is **not** gated by this flag. Rationale: the toggle is a
  privacy gate against arbitrary phones on the WiFi; the CYD is a physical
  device you own and have already paired.

### Pairing — unchanged

Keep the existing `/pair/start` (localhost-only, mints an ephemeral 6-digit
PIN) and `/pair` (LAN-open, redeems PIN → 32-byte hex bearer token, persisted
to `peers.json`). The PWA stores its token in `localStorage`. Because the
token is durable and PIN-independent, rotating or expiring the PIN never
disconnects an already-paired device.

### `source` action — `services/actions.py`

Add a value-parameterized handler:

```python
@_handler("source")
async def _h_source(d: Dispatcher, value=None):
    # value ∈ {"mopidy"/"library", "airplay", "spotify", "bluetooth", "movies"}
    # dispatches to the existing per-source handlers
```

It routes to the existing `_h_library` / `_h_airplay` / `_h_spotify` /
`_h_bluetooth` / `_h_movies` logic by name. This is shared dispatcher code, so
the GPIO buttons service and the CYD firmware (which already sends `source`)
benefit too.

### File endpoints — migrated from `boombox-uploader`

Bearer-token-gated, under `/api/remote/files/`:

- `GET  /api/remote/files/browse?path=` → directory listing
- `GET  /api/remote/files/download/{path}` → file stream
- `POST /api/remote/files/upload` → multipart, audio→`~/Music/uploads`,
  video→`~/Videos/uploads`, triggers the relevant library scan
- `POST /api/remote/files/delete` → `{path}`

Lift the safe-path logic verbatim from `boombox-uploader.py` — `safe_compose`,
`under_root`, `safe_filename`, `unique_path`, `AUDIO_EXTS`/`VIDEO_EXTS`,
`_trigger_scan`, `_trigger_jellyfin_scan`. The only change is the auth gate:
bearer token instead of the `bbx_pin` cookie.

### Library + playlists — wrap Mopidy server-side

Bearer-token-gated; thin server-side wrappers over Mopidy JSON-RPC so the PWA
never speaks Mopidy directly:

- `GET  /api/remote/library/search?q=` → tracks (`core.library.search`)
- `GET  /api/remote/playlists` → saved playlists (`core.playlists.as_list`)
- `POST /api/remote/playlists` → `{name, uris}` create + save
  (`core.playlists.create` / `save` / `refresh`)
- `GET  /api/remote/playlists/{uri}/items` → track URIs in a playlist
- `POST /api/remote/queue` → `{uris, play: true}` replace the tracklist and
  play (`core.tracklist.clear` / `add` / `core.playback.play`)

### Video proxy — Jellyfin

`boombox-remote` calls Jellyfin's REST API server-side using the stored key
(`/etc/boombox/jellyfin-api-key`), targeting the Jellyfin session running on
the boombox's own kiosk:

- `GET  /api/remote/video/state` → `{playing, title, position_s, duration_s,
  volume, muted}` for the active local session, or `{active: false}` when
  nothing is playing
- `POST /api/remote/video/command` → `{action, value?}` where action ∈
  `play_pause | stop | next | previous | seek | volume | mute`, mapped to
  Jellyfin `Sessions/{id}/Playing/*` and `Sessions/{id}/Command`

Session targeting: pick the Jellyfin session on the local device. If none is
active, `video/state` reports `active: false` and the PWA's Video screen shows
"nothing playing — start a movie on the boombox."

### Theme in the state payload

`StateAggregator.consolidated_state()` pulls `boombox-state`'s `GET /theme`
and populates the existing `skin` field plus a new `theme` object (the 9 CSS
custom-property values: `bg, panel, ink, ink2, accent, accent2, rule, font,
mono`). The WS already pushes the consolidated payload on change, so the PWA
restyles live when the skin changes on the device.

## Pi-side: other service changes

### `boombox-state.py`

Remove `/upload/{status,enable,disable}` and the `UPLOADER_UNIT` systemctl
plumbing — there is no uploader unit to start/stop anymore. The touchscreen
now drives `boombox-remote`'s `/api/remote/admin/*` routes instead.

### Retire `boombox-uploader`

- Delete `services/boombox-uploader.py` (it has no test coverage today).
- Delete `install/systemd/user/boombox-uploader.service`.
- Remove the `location /upload/` block from
  `install/config/nginx-boombox-common.conf`.
- Port 6683 is freed — one fewer always-reserved loopback port.

### Kiosk SPA (`ui/`)

- `ui/src/lib/SettingsDrawer.tsx` — replace the uploader on/off toggle + PIN
  display with a **Phone Remote** panel: the `remote_enabled` toggle (default
  off), the pairing PIN (minted via `/pair/start` on demand), and the list of
  paired devices with a revoke control. Calls `/api/remote/admin/*`.
- `ui/src/overlays/QrOverlay.tsx` — point the QR at `/remote/` instead of
  `/upload/`, and enable remote access (call `/api/remote/admin/enable`) when
  shown, mirroring today's behavior.

## PWA: `remote-ui/`

A new top-level Vite/React/TypeScript project, sibling to `ui/`. Independent
`package.json` and build. Installable PWA via `vite-plugin-pwa` — web app
manifest (name, icons, theme color, `display: standalone`) and a service
worker caching the app shell so it launches offline (it then shows a
connection state until it reaches the boombox).

### Transport layer

A `Transport` interface with two implementations behind it, so the UI is
transport-agnostic:

- `HttpTransport` — `fetch` for commands/queries, WebSocket (`/api/remote/ws`)
  for live state. The default; works on every phone.
- `BleTransport` — Web Bluetooth against the existing GATT peripheral
  (`services/ble_peripheral.py`, service UUID `0000bbbb-…`): read `device_info`,
  write PIN to `pair_request`, read token from `pair_response`, subscribe to
  `state`, write `command`. Offered **only** when `navigator.bluetooth` exists
  and HTTP is unreachable — i.e. Android off-network. iOS never sees it.

A token paired over either transport works on both — `boombox-remote` shares
`peers.json` across HTTP and BLE.

### Screens

- **Pairing** — discover/enter the boombox address, enter PIN, store token. If
  remote access is off, show "remote access is off — enable it on the boombox."
- **Now Playing** — album art, title/artist/album, play-pause/next/prev/stop/
  shuffle, a seek scrubber, volume + mute. All via `/api/remote/command`.
- **Sources** — the `sources_available` list; switch via the new `source`
  action.
- **Video** — shown when the movies source is active: Jellyfin transport
  (play-pause/seek/volume) via `/api/remote/video/*`.
- **Playlists** (mobile included) — library search, build a client-side draft,
  save as a Mopidy playlist, play drafts and saved playlists, via
  `/api/remote/library/*`, `/playlists/*`, `/queue`.
- **Files** (desktop-only, above a width breakpoint) — upload + library
  browse/download/delete via `/api/remote/files/*`.
- **Extras** — sleep timer, record toggle, mic/karaoke, skin cycle (all already
  in `actions.py`).

### Theming

The `theme` object from the WS payload is applied as CSS custom properties on
the document root. No skin-registry code is shipped in the PWA — the device is
the source of truth and pushes theme values over the wire.

## Deploy

This targets the post-auto-update layout already on `main`: `/opt/boombox` is
a `releases/<ref>/` + `current` symlink structure, and nginx serves the kiosk
SPA directly from `/opt/boombox/current/ui/dist`.

- **nginx** (`install/config/nginx-boombox-common.conf`): replace the
  `location /upload/` block with `location /remote/` — `auth_basic off`,
  `alias /opt/boombox/current/remote-ui/dist/`, SPA fallback (`try_files $uri
  $uri/ /opt/boombox/current/remote-ui/dist/index.html`). The PWA flips
  atomically with the release symlink, exactly like the kiosk SPA. Add
  `client_max_body_size 1100M` and `proxy_request_buffering off` to the
  `/api/remote/` block to carry uploads.
- **install.sh / update.sh**: add a `remote-ui` build step (`npm ci && npm run
  build` in `remote-ui/`) producing `remote-ui/dist/` in place within the
  release dir — nginx serves it via the `current` symlink, mirroring how
  `ui/dist/` is built and served. No rsync to `/var/www`.
- **systemd**: delete `boombox-uploader.service`. `boombox-remote.service`
  stays boot-enabled, unchanged.
- **`requirements.txt`**: no new Python deps expected — `aiohttp`, `Pillow`,
  `zeroconf`, `bless` already cover it.

## Testing

### Unit / integration (pytest, `services/tests/`)

Extend the existing `test_remote_*.py` and `test_actions.py`:

- `remote_enabled` gate: phone routes 403 when off, 200 when on, WS closes
  `4403`; pairing blocked when off; admin routes localhost-gated.
- Authorization durability: a token in `peers.json` still authenticates after
  the flag is toggled off→on.
- `source` action: each `value` routes to the right per-source handler;
  unknown value → `{ok: false}`.
- File endpoints: path-traversal rejection (lifted tests still pass),
  bearer-token gate, audio vs video routing.
- Library/playlists endpoints: against a mocked Mopidy JSON-RPC — search,
  create/save round-trip, queue replace+play.
- Video proxy: against a mocked Jellyfin — state mapping, command mapping,
  `active: false` when no session.
- Theme: `consolidated_state()` includes `skin` + `theme` from a mocked
  `boombox-state /theme`.

### Frontend (Vitest, `remote-ui/`)

- Transport abstraction: `HttpTransport` command/query/WS lifecycle;
  `BleTransport` feature-detection and graceful absence on iOS.
- Pairing flow: PIN → token → `localStorage`; "remote disabled" state.
- State store: WS payload → screen state reducer, including live theme
  application.

### Manual smoke (Pi — checklist in the plan, not automated)

- Install the PWA on iOS Safari and Android Chrome; pair each once.
- Control: transport, sources, volume, sleep/record/mic/skin.
- Video: start a movie on the touchscreen, control it from the phone.
- Playlists: search, build, save, play.
- Desktop file panel: upload an audio + a video file, browse, download, delete.
- **Reboot the Pi → both phones reconnect with no re-pairing.**
- Toggle remote access off → phones show the disabled screen; toggle on →
  they reconnect automatically.
- Android off-network: Web Bluetooth fallback connects.

## Risks & coordination

- **Built on the merged auto-update layout.** Auto-update has landed on `main`
  — `/opt/boombox` is now `releases/<ref>/` + a `current` symlink, and nginx
  serves SPAs from `current/.../dist`. This spec already targets that layout.
  The one thing to watch: `install.sh`/`update.sh` and the nginx config are now
  release-layout-aware, so the `remote-ui` build + `/remote/` location must
  follow the same in-release-dir pattern as `ui/`, not the old rsync-to-
  `/var/www` pattern.
- **Web Bluetooth is fiddly.** The Android fallback is genuinely useful but
  Web Bluetooth pairing UX is clunky and Chrome-only. It is a *fallback*, not
  the primary path — if it proves unreliable, the PWA still fully works over
  WiFi everywhere. Keep the BLE transport behind a clean interface so it can be
  cut without touching the UI.
- **Jellyfin session targeting.** "The local session" detection may need
  iteration depending on how Jellyfin reports the kiosk's Chromium session. If
  it proves unreliable, v1 can fall back to "control the most-recently-active
  session" and refine later.
- **Coordinated multi-file change.** Retiring `boombox-uploader` touches the
  service, its unit, nginx, `boombox-state.py`, and two kiosk SPA files at
  once. The plan must land these together so the touchscreen Settings drawer is
  never left calling a dead endpoint.

## Out of scope (explicit)

- iOS Web Bluetooth (platform wall).
- Playlist editing/reordering/renaming/deleting.
- Jellyfin library browsing from the PWA.
- Multi-boombox control from one PWA install.
- Cryptographic auth beyond the existing bearer-token model.

## Open items deferred to v2

- Playlist editing and reordering.
- Jellyfin library browse + start-playback from the phone.
- Multi-boombox discovery and switching in the PWA.
- Push notifications (e.g. "an update is available") on the PWA surface.
