# Changelog

Notable changes per ship. Newest first. Conventional-commit scopes match the
prefixes in `git log`.

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
