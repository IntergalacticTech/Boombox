# Changelog

Notable changes per ship. Newest first. Conventional-commit scopes match the
prefixes in `git log`.

---

## Unreleased — Home Library + RFID

Boombox now carries your Navidrome catalog with it. A new
`boombox-library` service syncs the Subsonic catalog into a local
SQLite cache, manages a USB offline-cache drive, and surfaces the
whole thing through a Settings panel, a Home Library browse root in
the touchscreen, a sync indicator in the chrome, and a source badge
on the NowPlayingBar. A second new service, `boombox-rfid`, reads
USB HID-keyboard RFID readers so you can bind a card to an album /
artist / playlist and tap to play. See
[docs/HOME-LIBRARY.md](./docs/HOME-LIBRARY.md) and
[docs/RFID.md](./docs/RFID.md).

### Added

- **`boombox-library`** service (`127.0.0.1:6687`, `/api/library/*`):
  Subsonic API client with token+salt auth, SQLite catalog with FTS5
  search, marker-file USB cache drive detection + adoption, FIFO
  eviction over streamed (non-pinned) cache, atomic-rename downloader,
  playback resolver that emits `file://` when cached and a direct
  Navidrome `stream.view` URL when online, pin manager (USER /
  FAVORITE / RFID / STARRED sources with rank-based precedence), and a
  pin sidecar (`<cache>/meta/pins.json`) for write-ahead durability.
  Config at `/etc/boombox/library.yml` (URL + Fernet-encrypted password
  keyed off `/etc/machine-id`).
- **`boombox-rfid`** service (`127.0.0.1:6688`, `/api/rfid/*`): reads a
  USB HID-keyboard RFID reader via `EVIOCGRAB` (so card digits don't
  leak to Chromium), looks up the UID in the `rfid_bindings` table,
  expands the binding to a track list, and plays it via Mopidy. Binding
  also writes a pin (`source='rfid'`) so the bound content pre-caches.
  Config at `/etc/boombox/rfid.yml`.
- **Home Library UI** (Phase 2):
  - `LibraryDrawer` gains a "Home Library" root with Artists / Albums /
    Playlists / Cached-only sub-roots.
  - `SettingsDrawer` mounts `LibraryPanel` (source config + Test/Save/
    Sync) and `CachePanel` (stacked-bar reserved/pinned/streamed/free
    + Clear streamed).
  - `SyncIndicator` chip in every skin's chrome row; tap → opens
    Settings scrolled to Home Library.
  - `PinButton` with four visual states (unpinned / downloading /
    cached / error), `StatusBadge` glyph for track rows
    (📌 / ⬇ / ⚡ / ☁ / ⚠), and a source badge on `NowPlayingBar`
    (Cache / Stream / Spotify / USB / AirPlay / BT).
  - `CacheAdoptOverlay`: pops when a new writable USB drive is
    plugged in and no cache is currently adopted. Read-only mounts
    are filtered out.
  - `homeLibrary.ts` pub/sub store with `useSyncStatus` +
    `useCacheStats` hooks fed by a single ref-counted poll, so chrome,
    settings, and row badges share one fetch pair.
  - Favorites auto-pin coupling: `toggleFavorite()` on a Home Library
    URI also calls `pin/unpin(source='favorite')`.
- **RFID UI**:
  - `RfidBindOverlay` polls `/api/rfid/recent` and pops when a
    previously-unbound card is tapped. Per-UID dismissal.
  - LibraryDrawer enters a "BIND MODE" banner state when the
    overlay starts a bind, auto-navigates to Home Library, and
    completes the bind on first album/artist/playlist tap.
- **Mopidy compatibility patch**: `install.sh` patches
  `mopidy/audio/scan.py` at install time so the audio scanner handles
  Debian Trixie's `python3-gi` `StructureWrapper` return type. Without
  this patch every http:// stream URL silently drops at scan time.
- **PWA pairing UX**: the touchscreen Settings row is now labeled
  **"Pair a remote"** (was "Pair wireless remote") because the same
  6-digit PIN works for phones and ESP32 remotes.
- **`docs/HOME-LIBRARY.md`** and **`docs/RFID.md`** — full user guides.

### Performance

- **nginx gzip** on JSON/JS/CSS/SVG: ~10× transfer reduction on the
  Home Library browse responses (~700 KB → ~80 KB for an 8.7 k album
  catalog).
- **Precomputed JSON snapshots** for `/api/library/browse` written
  after each sync, served with ETags. Navigation never blocks on a
  SQLite scan; revalidations return 304 with no body.
- **sort_name indexes** on `albums` and `artists`, so browse queries
  are index-ordered range scans instead of full-table-scan + memsort.
- **Incremental rendering** of large library lists via
  IntersectionObserver — first 100 rows render immediately, more on
  scroll.
- **Local cover-art proxy** with on-disk cache at
  `/opt/boombox/state/art-cache/`, fronted by
  `/api/library/art/{art_id}`.
- **sync_full** no longer holds the SQLite writer lock across HTTP
  awaits, so other writers (`boombox-rfid` bind, pin toggles) aren't
  starved during a 30-min cold-boot resync.

### Install / deploy

- **`apply-release.sh` restart sweep** now includes `boombox-library`
  and `boombox-rfid` (Phase 1's library was previously omitted, so
  deploys staged new code but old service processes kept running).
- **Auto-enable newly-added units** during a deploy so a fresh service
  doesn't require a manual `systemctl enable`.
- **Kiosk auto-reload** after each deploy via Chromium's DevTools port
  — long-running Chromium picks up the new SPA without a process
  restart.
- **`/api/rfid/`, `/local/`** in nginx use `^~` so the file-extension
  regex location doesn't hijack their requests on the LAN basic-auth
  block (the PWA's album-art fetches were popping a basic-auth modal).
- **PWA `/remote/` `try_files` fallback** is `/remote/index.html` (a
  URI) rather than an absolute filesystem path that nginx interprets as
  a URI internal-redirect into the auth-gated `location /`.
- **`/etc/boombox/library.yml`** and **`/etc/boombox/rfid.yml`**
  templates installed on first boot. Kiosk user added to the `input`
  group so RFID reader access doesn't need root.

### Fixed

- **`boombox-library` chunked sync**: HTTP `client.get_album()` calls
  no longer happen inside an open SQLite transaction — each section
  brackets its local upserts only. With `PRAGMA busy_timeout = 10000`
  on both library and rfid connections plus a 5 ms `asyncio.sleep`
  between album iterations, concurrent writers no longer starve.
- **`boombox-rfid` reader loop**: `O_NONBLOCK` open was raising
  EAGAIN on every read; switched to blocking open and treat zero-byte
  return as EOF.
- **Tap-to-play state landing in `paused`**: `MopidyClient.play_uris()`
  now passes `tlid` explicitly to `core.playback.play` and resumes if
  Mopidy somehow lands paused.
- **DeckOS skin overflow**: grid template uses `minmax(0, 1fr)` +
  `minWidth:0` so wide content (notably the progress bar's
  70-character ASCII bar) doesn't push the right column past the
  1280-design-wide skin.

### Removed

- **Mopidy-Subsonic plugin** is no longer installed by `install.sh`.
  The 1.0.0 wheel on PyPI is Python-2 bit-rotten (`unicode` undefined
  on Py3.13, a `[b'mopidy.ext']` entry-points bug, a `context + "/rest"`
  URL doubling bug). Streaming now flows through Mopidy's built-in
  stream backend with direct `/rest/stream.view` URLs from the
  resolver — no plugin needed.

---

## Unreleased — Auto-update

Devices keep themselves current: a new `boombox-updater` service discovers
GitHub releases, installs them unattended inside a nightly window with a
smoke-test + automatic rollback, and exposes the whole thing through a
Settings → Updates panel and an `/api/update/*` HTTP API.

### Added

- **`boombox-updater`** service: auto-discovers GitHub releases on the
  `stable` channel (or `main` HEAD on `edge`); installs unattended inside a
  daily window (default 03:00–04:00); skips if music is playing.
- **A/B install layout** (`releases/<ref>/` + `current`/`previous` symlinks)
  with smoke-test + automatic rollback on failure.
- **Settings → Updates panel** on the touchscreen + LAN web page.
- **`/api/update/*` HTTP API** on `127.0.0.1:6685`.

### Changed

- **`/opt/boombox` reorganised** to a release-pointer layout. First run of
  the installer migrates legacy flat checkouts in place.
- **nginx** now serves the SPA from `/opt/boombox/current/ui/dist/` instead
  of `/var/www/boombox/`.
- **`bin/boombox-update`** rewritten as a thin client of `/api/update/*`,
  with a fallback that runs `apply-release.sh` directly when the service is
  disabled.

---

## 2026-05-12 — Physical control surface

Full 17-button + rotary-encoder GPIO surface, hot-reloadable config, kiosk
overlay layer for non-touchscreen feedback, in-UI Settings panel with Learn /
Test flows. See [docs/BUTTONS.md](./docs/BUTTONS.md) for the user guide and
[docs/superpowers/specs/2026-05-12-gpio-buttons-design.md](./docs/superpowers/specs/2026-05-12-gpio-buttons-design.md)
for the design contract.

### Added

- **`boombox-buttons`** rewritten as a full control surface:
  17 panel buttons (transport, source selection, sleep timer, record, skin
  cycle, mic/karaoke, power) + 1 rotary encoder with push (volume / mute).
  Per-action `PressClassifier` (short / long-press / long-hold ticks for
  scrub) and a `EncoderDecoder` that emits one event per detent.
- **HTTP API on `127.0.0.1:6684`** (nginx-fronted at `/api/buttons/`):
  `GET/POST /config`, `POST /learn` (5 s capture window), `POST /test`.
- **`POST /api/volume/mute`** added to `boombox-state` so encoder push works
  without a separate code path.
- **Settings drawer → Buttons panel** (`ui/src/lib/ButtonsPanel.tsx`): all 17
  actions listed with current pin, enable toggle, Test button (dispatches
  without GPIO), Learn button (5 s falling-edge capture writes to
  `/etc/boombox/buttons.json` and hot-reloads).
- **Kiosk overlay layer** (`ui/src/overlays/`): `QrOverlay`, `SleepOsd`,
  `RecordIndicator`, `SourceInstructionOverlay`, `ShutdownOverlay`. Each
  listens for a `boombox:<event>` `CustomEvent` dispatched from the service
  via Chromium DevTools.
- **Watchdog-driven hot-reload** of `/etc/boombox/buttons.json`. Covers
  modify, create, and atomic-move events so editor saves, `sudo tee + mv`,
  and direct writes all trigger a clean GPIO loop rebuild without a service
  restart.
- **Graceful shutdown**: SIGTERM / SIGINT now installs a signal handler that
  sets the stop event, unwinds the GPIO request cleanly, and tears down the
  HTTP API. The reader thread surfaces unexpected crashes via `log.exception`
  rather than going zombie.
- **Power button shutdown auth**: `install/sudoers/boombox` now grants
  passwordless `systemctl poweroff` / `reboot` for the desktop user (user
  systemd units can't acquire polkit auth for `org.freedesktop.login1.power-off`).
- **`docs/BUTTONS.md`**: end-to-end builder guide — pin map, wiring,
  Settings-panel walkthrough, troubleshooting.
- **`services/tests/`**: pytest harness with 23 pure-logic cases (config
  parser, press classifier, encoder decoder, dispatcher routing).

### Changed

- **GPIO budget**: `install/config/usercfg.txt` now sets
  `dtparam=spi=off` and `dtparam=uart0=off` to free 7 GPIOs for buttons
  (verified idle: nothing opens `/dev/spidev*` or `/dev/serial0`; the
  active serial-getty is on `ttyAMA10`, the Pi 5 dedicated debug UART).
  Re-enable if a fork needs SPI or UART0, and remap the conflicting button
  pins in `buttons.json`.
- **`buttons.json` schema** expanded from 5 flat keys (play_pause, next,
  previous, volume_up, volume_down) to the full 17-action + encoder shape.
  `install.sh` detects the old schema (missing `"power"` key) and backs up
  the user's previous config to `/etc/boombox/buttons.json.pre-fullbuttons`
  before installing the new one.
- **`boombox-state` `/api/volume`** unchanged for set/get; mute now has its
  own endpoint at `/api/volume/mute` instead of overloading `volume_set`.
- **README, ARCHITECTURE, SERVICES, DEVELOPMENT** updated to reflect the
  new port (6684), action inventory, and the staged-rsync workaround for
  deploying UI builds into the `www-data`-owned `/var/www/boombox/`.
- **Recorder pipeline**: `parec --device=@DEFAULT_MONITOR@` (canonical
  PulseAudio/PipeWire form), explicit `s16le / 44.1 kHz / stereo` format
  flags on both sides of the pipe, and an `os.pipe()` for the parec → flac
  chain (asyncio's `StreamReader` can't be used as a child's `stdin`).

### Removed

- **`/usr/local/bin/boombox-button-handler.py`** and
  **`/usr/local/bin/boombox-mode-manager.py`** — pre-repo services that
  predate this codebase. `install/legacy/remove-legacy-buttons.sh`
  disables and deletes them (idempotent; runs from `install.sh` step 3b).

### Fixed

- gpiod 2.x rejects float seconds for `debounce_period`; we now pass
  `datetime.timedelta(milliseconds=...)`. Previously the loop would crash
  on first edge.
- Port 6683 was already used by `boombox-uploader`; moved the buttons API
  to 6684. `/upload/` and `/api/buttons/` no longer share a backend.
- `SleepOsd.tsx` `setTimeout(... setMins(prev => prev) ...)` was an identity
  setState — the pill never auto-hid. Now uses `setMins(null)` so the OSD
  disappears 2 s after the last update.
- Hot-reload watcher initially only listened for `on_modified`, which
  doesn't fire for `sudo tee tmp && sudo mv tmp config` atomic renames.
  Now covers `on_modified`, `on_created`, and `on_moved`.

### Known issues

- Reader-thread cleanup on SIGTERM occasionally logs a `RequestReleasedError`
  traceback when the gpiod context manager closes the request while the
  reader is mid-`wait_edge_events`. Cosmetic journal noise on shutdown;
  doesn't affect operation or the next start. Fix is to suppress the log
  when `stop.is_set()`; tracked for a follow-up commit.
- `./pi deploy <local> /var/www/boombox/` still requires staging via
  `/tmp/` + sudo-rsync; the helper itself doesn't detect www-data targets.
  Workaround documented in
  [DEVELOPMENT.md → Editing the UI](./docs/DEVELOPMENT.md#editing-the-ui).
- `./pi reload` is a soft reload that can hand back cached JS via the
  service worker. Force-reload with `./pi restart-kiosk` or a DevTools
  `Page.reload`.
