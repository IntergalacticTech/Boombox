# Services reference

Every long-running process on the boombox, what it does, what it depends on,
and how to debug it.

For the high-level picture see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## System services (root-owned, start at boot)

### `mopidy`

The music server. Exposes HTTP/WS on `127.0.0.1:6680`, MPD on
`127.0.0.1:6600`. Backed by `mopidy-local` (file scan) and
`mopidy-iris` (the bundled web UI), plus whatever extensions you've
configured.

- **Config:** `/etc/mopidy/mopidy.conf`
- **Logs:** `sudo journalctl -u mopidy -f`
- **Restart:** `sudo systemctl restart mopidy`
- **Scan local library:** `sudo mopidyctl local scan`
- **Known gotcha:** on Debian Trixie the `python3-gi` upgrade broke
  `mopidy.audio.scan`. `install.sh` applies
  [`services/scan-py-fix.diff`](../services/scan-py-fix.diff) at install
  time; if you ever upgrade Mopidy manually, re-apply it. Symptom: stream
  URLs add to the queue but never play.

### `nginx`

Reverse proxy and static-file server. The kiosk uses unauthenticated
`http://localhost/` on loopback. LAN clients use the uncommon web port
configured in `/etc/boombox/web-auth.env` (default `8090`) and must pass
HTTP Basic auth. The generated htpasswd file lives at
`/etc/nginx/boombox.htpasswd`.

- **Config:** `/etc/nginx/sites-available/boombox` (a copy of
  `install/config/nginx.conf`)
- **Logs:** `sudo tail -F /var/log/nginx/{access,error}.log`
- **Reload:** `sudo nginx -t && sudo systemctl reload nginx`

### `smbd`

Samba publishes the music library as a password-protected SMB share:
`smb://<pi-ip>/boombox-music`. It uses the desktop user as the Samba user and
the same generated password/PIN as the authenticated LAN web UI.

- **Config:** `/etc/samba/smb.conf` (a copy of `install/config/smb.conf`)
- **Credentials:** `/etc/boombox/web-auth.env`
- **Restart:** `sudo systemctl restart smbd`

### `shairport-sync`, `raspotify` (optional), `bluetooth`

Standard system services. AirPlay receiver, Spotify Connect daemon, BlueZ
stack. They feed PipeWire as ordinary audio sources; the boombox doesn't
configure them beyond installing them.

---

## User services (`boombox-*`, live in `~/.config/systemd/user/`)

All run as the desktop user, depend on `graphical-session.target`, and
restart on failure with a 3-second backoff. Lingering is enabled so they
come up at boot.

### `boombox-state` — MPRIS aggregator + `/api/*` helpers

**Listens on `127.0.0.1:6681`, proxied as `/api/` by nginx.**

Polls `playerctl` (which itself uses `playerctld` to track which MPRIS
player is "active") every 500 ms. When a non-Mopidy player is in
`playing` or `paused` state, it surfaces the player's metadata at
`/api/state` so the SPA can override Mopidy's display. The same service
exposes:

| Endpoint | Used by |
|----------|---------|
| `GET  /api/state` | UI: live source detection |
| `POST /api/control/{toggle\|next\|previous}` | UI: transport for external sources |
| `GET  /api/volume`, `POST /api/volume` | UI: sleep timer, settings |
| `GET  /api/info` | UI: settings drawer (host, ip, uptime) |
| `GET  /api/sinks`, `POST /api/sinks/default` | UI: audio sink picker |
| `GET  /api/karaoke`, `POST /api/karaoke/{on,off}` | UI: karaoke mode toggle |
| `POST /api/bluetooth/pair` | UI: temporary Bluetooth discoverable/pairable mode |
| `GET  /api/lyrics?artist=&title=` | UI: lyrics drawer |
| `GET  /api/art?artist=&album=&track=` | UI: album-art lookup with cache |
| `POST /api/mopidy/restart` | UI: settings → restart mopidy |
| `GET/POST /api/theme` | Remote API + kiosk: match active skin palette |
| `GET /api/usb/devices`, `POST /api/usb/copy` | UI: USB device list and pull-to-library copy |
| `POST /api/library/scan` | UI / `boombox-remote` file API: trigger Mopidy local scan |

- **Code:** [`services/boombox-state.py`](../services/boombox-state.py)
- **Logs:** `journalctl --user -u boombox-state -f`

### `boombox-audio` — visualizer

**Listens on `127.0.0.1:6682`, proxied as `/audio/` by nginx.**

Captures the default PipeWire sink's `.monitor` source via `parec`, runs a
1024-sample FFT, and broadcasts `{bins, peaks, rms, ts}` over `/audio/ws`
at ~21 fps. Auto-restarts the `parec` subprocess if it stalls (typically
because Wireplumber restarted).

- **Code:** [`services/boombox-audio.py`](../services/boombox-audio.py)
- **Health:** `curl 127.0.0.1:6682/health`
- **Tune:** `LEVEL_SCALE`, `PEAK_DECAY`, `RMS_GAIN` constants near the top
  of the file. Defaults aim for "normal music fills 60–90 % of bars".

### `boombox-orchestrator` — most-recent-wins auto-pause

No socket. Polls `pw-dump` every 500 ms; when a new source starts while
another is playing, pauses everyone except the newest. See
[ARCHITECTURE.md](./ARCHITECTURE.md#data-flow-make-a-new-source-pause-the-old-one)
for the full rationale.

- **Code:** [`services/boombox-orchestrator.py`](../services/boombox-orchestrator.py)
- **Debug:** start it in the foreground with `BOOMBOX_LOG=DEBUG`
  (currently it logs at INFO; bump the `logging.basicConfig` if you need
  more detail).

### `boombox-buttons` — full GPIO control surface

**Listens on `127.0.0.1:6684`, proxied as `/api/buttons/` by nginx.**

Reads `/dev/gpiochip0` for falling edges on 17 button pins plus the A/B/push
lines of one rotary encoder, runs each through a press classifier (short /
long / hold) and a quadrature decoder, then dispatches to the matching
handler. Configuration is hot-reloaded from `/etc/boombox/buttons.json` via
a `watchdog` observer — edits via the Settings panel or `vim` apply
immediately, no service restart.

**Action inventory (17 buttons + encoder):**

| Action | Routing |
|--------|---------|
| `play_pause`, `next`, `previous`, `stop`, `shuffle`, `repeat` | Mopidy JSON-RPC direct (`mopidy:6680/rpc`) |
| `airplay`, `spotify`, `bluetooth`, `library`, `movies` | `boombox-state` `/api/control/source` + kiosk DevTools `Page.navigate` |
| `web` | Emits `boombox:web-qr` (kiosk shows LAN URL + QR overlay) |
| `mic_karaoke` | `boombox-state` `/api/karaoke/{on,off}` toggle |
| `sleep_timer` | Cycles 15/30/60 min on rapid presses; emits `boombox:sleep-timer`; on expiry pauses Mopidy, sleeps the display, emits `boombox:sleep-expired`. Long-press cancels. |
| `skin_cycle` | Emits `boombox:skin-cycle`; SPA advances skin index |
| `record` | `parec --device=@DEFAULT_MONITOR@ \| flac` to `~/Music/Recordings/<ts>.flac`; emits `boombox:record` |
| `power` | Short: backlight toggle (`wlr-randr`). Long (≥ 2 s): emits `boombox:shutdown-countdown` then `boombox:shutdown-confirm`; runs `sudo systemctl poweroff` |
| Encoder rotate | `/api/volume` delta (default ±5 per detent) |
| Encoder push | `/api/volume/mute` toggle |

**Custom DOM events emitted on the kiosk page** (via DevTools
`Runtime.evaluate`): `boombox:web-qr`, `boombox:sleep-timer`,
`boombox:sleep-expired`, `boombox:record`, `boombox:source-overlay`,
`boombox:skin-cycle`, `boombox:shutdown-countdown`, `boombox:shutdown-confirm`.
The SPA's overlay components listen on `window.addEventListener('boombox:<event>')`.

**HTTP API** (used by the touchscreen Settings → Buttons panel):

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/buttons/config` | Current config (pins, enables, debounce/hold values) |
| `POST /api/buttons/config` | Atomic write of new config to `/etc/boombox/buttons.json` |
| `POST /api/buttons/learn` | "Press a button" capture mode — returns the pin that next went low |
| `POST /api/buttons/test`  | Fire an action by name without a physical press (verify wiring/handler) |

- **Code:** [`services/boombox-buttons.py`](../services/boombox-buttons.py)
- **Config:** `/etc/boombox/buttons.json` (hot-reloaded; template at `install/config/buttons.json`).
  Set any `pin` to `null` or `enabled: false` to disable an action; the schema
  carries `long_press_ms`, `power_hold_ms`, and `encoder_step` as the only
  tuning knobs.
- **Logs:** `journalctl --user -u boombox-buttons -f`
- **Requires:** user in the `gpio` group (installer handles; reboot after
  first install). Linux gpiod via the `gpiod` python binding.
- **Wiring:** each button shorts its pin to GND when pressed; the SoC's
  internal pull-up holds it high otherwise. Encoder uses standard
  quadrature A/B with a push switch on a third pin.
- **GPIO budget:** the full surface needs 20 pins. The installer disables
  SPI (`/boot/firmware/usercfg.txt`) and UART0 (no console-on-serial)
  to free up GPIO 14/15 and the SPI block for buttons. If you re-enable
  SPI on a fork, remap or disable the actions on those pins.

### `boombox-updater` — GitHub release poller + scheduled A/B installer

**Listens on `127.0.0.1:6686`, proxied as `/api/update/` by nginx.**

Polls GitHub for new releases hourly (and once on boot): the latest
published release on the `stable` channel, or `main` HEAD on `edge`. A
scheduler wakes inside the configured install window (default 03:00–04:00)
and, if a newer version is available and nothing is playing, runs the
install. The install state machine drives
[`install/apply-release.sh`](../install/apply-release.sh): fetch the ref,
build into `releases/<ref>/`, swap the `current` symlink, smoke-test, and on
failure flip `current` back to `previous` and restart.

**HTTP API** (used by the touchscreen Settings → Updates panel and the
`bin/boombox-update` CLI):

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/update/status` | Installed + available versions, last attempt result |
| `GET  /api/update/config` | Current channel, install window, auto-update enable |
| `PUT  /api/update/config` | Update channel / window / auto toggle |
| `POST /api/update/check` | Force a poll now (refresh available version) |
| `POST /api/update/install` | Install latest (or a named ref) now |
| `POST /api/update/rollback` | Flip `current` back to `previous` |
| `GET  /api/update/log` | Tail the most recent install attempt's log |

- **Code:** [`services/boombox-updater.py`](../services/boombox-updater.py)
- **Config:** `/etc/boombox/updater.json` (channel, window, auto-update flag)
- **Runtime state:** `/opt/boombox/state/updater.json` (installed/available
  versions, last attempt) and per-attempt logs under
  `/opt/boombox/state/logs/`
- **Logs:** `journalctl --user -u boombox-updater -f`
- **Disable auto-updates:** `systemctl --user disable --now
  boombox-updater.service`. `bin/boombox-update` still works with the
  service disabled — it falls back to running `apply-release.sh` directly
  (no auto-rollback on that path).

### `boombox-resume` — playback resume across reboots

Snapshots `{state, current_track_uri, tracklist_uris, position_ms}` to
`~/.local/state/boombox/last.json` every 5 seconds while music plays. At
startup, if Mopidy is idle and the snapshot is fresh (≤24 h), it restores
the tracklist and seeks back to where you were.

- **Code:** [`services/boombox-resume.py`](../services/boombox-resume.py)
- **Snapshot path:** override with `BOOMBOX_RESUME_FILE`.
- **Why not a Mopidy extension?** Keeps Mopidy unmodified (fewer pieces
  to break on apt upgrade), and matches every other audio path in this
  project — HTTP/RPC into `mopidy:6680`.

### `boombox-bt-volume` — AVRCP → PipeWire bridge

WirePlumber 0.5 on Trixie doesn't propagate AVRCP 1.6 absolute volume from
a connected phone to the matching `bluez_input` node. This service
listens on D-Bus for `MediaTransport1.Volume` `PropertiesChanged` and
mirrors the value (0..127) onto the live `bluez_input` node via
`wpctl set-volume`.

- **Code:** [`services/boombox-bt-volume.py`](../services/boombox-bt-volume.py)
- **Requires:** `python3-dbus` and `python3-gi` (system-site-packages in
  the venv).
- **Symptom this fixes:** phone slider used to mute/unmute only; with the
  service running, it scales linearly as expected.

### `boombox-kiosk-guard` — keep Chromium pinned

Polls Chromium's DevTools `/json` endpoint and, if any tab has drifted off
`localhost`, navigates it back via the WebSocket `Page.navigate` call.
(The HTTP `/json/page/<id>/navigate` endpoint was removed in modern
Chromium and returns 404 now.) Closes duplicate tabs.

- **Code:** [`services/boombox-kiosk-guard.py`](../services/boombox-kiosk-guard.py)
- **Pause it temporarily:** `./pi guard pause` (creates a sentinel file in
  `$XDG_RUNTIME_DIR`). `./pi guard resume` removes it.
- **Env knobs:** `BOOMBOX_KIOSK_CDP` (DevTools URL), `BOOMBOX_KIOSK_HOME`
  (target URL), `BOOMBOX_KIOSK_POLL` (seconds).

### `boombox-osk` — on-screen keyboard

Runs `wvkbd-mobintl --hidden --layer overlay` so a Wayland virtual
keyboard sits on the overlay layer (above Chromium's `--kiosk` fullscreen
surface) and listens for `SIGUSR2` (show) / `SIGUSR1` (hide). The kiosk
extension (`install/kiosk-extension/`) listens for `focusin` / `focusout`
on text-like inputs and posts to `POST /api/osk/show` / `POST /api/osk/hide`
on boombox-state, which signals wvkbd.

- **Code:** unit at `install/systemd/user/boombox-osk.service`;
  endpoints in [`services/boombox-state.py`](../services/boombox-state.py);
  focus hooks in [`install/kiosk-extension/content.js`](../install/kiosk-extension/content.js);
  service-worker fetch in [`install/kiosk-extension/background.js`](../install/kiosk-extension/background.js).
- **wvkbd binary:** Trixie's apt-installed `wvkbd` 0.15 lacks the
  `--layer` flag, so `install.sh` clones the upstream repo and builds a
  current binary to `/usr/local/bin/wvkbd-mobintl` (build deps in the apt
  list: `libwayland-dev libxkbcommon-dev wayland-protocols pkg-config
  build-essential`).
- **Override the height:** edit `ExecStart` in
  `~/.config/systemd/user/boombox-osk.service` to change the `-H` /
  `-L` values (portrait / landscape px). Reload with
  `systemctl --user daemon-reload && systemctl --user restart boombox-osk`.

### `boombox-remote` — the consolidated phone + wireless-remote API

**Listens on `127.0.0.1:6685`, proxied as `/api/remote/` by nginx
(`auth_basic off`). Boot-enabled.**

The single phone-facing backend: the HTTP/WS API for the CYD hardware
remote, the forthcoming phone web app (Phase 2 — not built yet), and any
other HTTP client on the LAN. It exposes consolidated state, a command
endpoint, a push-on-change WebSocket, resized album art, a file surface
(browse / download / upload / delete), a library/playlist/queue surface
over Mopidy, and a Jellyfin video-transport proxy. Commands flow through
the shared `actions.fire()` dispatcher, so GPIO buttons and remotes share
one code path. A BLE peripheral runs alongside the HTTP server as the
primary transport for the CYD hardware remote.

| Endpoint | Used by |
|----------|---------|
| `GET  /api/remote/state` | Consolidated state JSON (also carries `skin` + `theme`) |
| `POST /api/remote/command` | `{action, value?}` → `actions.fire()` |
| `GET  /api/remote/ws` | WebSocket, pushes state on change (~250 ms poll) |
| `GET  /api/remote/art/{hash}.jpg` | Current track art, on-the-fly resized to 240×240 (ETag + 304) |
| `POST /api/remote/pair/start` | **localhost-only:** mint an ephemeral 6-digit pairing PIN |
| `POST /api/remote/pair` | Redeem a PIN → durable 32-byte-hex bearer token |
| `GET  /api/remote/admin/status` | **localhost-only:** `{ok, enabled, peers:[{label, paired_at}]}` |
| `POST /api/remote/admin/enable` / `disable` | **localhost-only:** flip the `remote_enabled` flag |
| `POST /api/remote/admin/unpair` | **localhost-only:** `{token}` removes one paired peer |
| `GET  /api/remote/files/browse?path=` | Bearer: directory listing under `~/Music/` |
| `GET  /api/remote/files/download/{path}` | Bearer: stream a library file |
| `POST /api/remote/files/upload` | Bearer: multipart upload — audio → `~/Music/uploads/`, video → `~/Videos/uploads/` |
| `POST /api/remote/files/delete` | Bearer: delete a local library file |
| `GET  /api/remote/library/search?q=` | Bearer: Mopidy library search |
| `GET  /api/remote/playlists`, `POST /api/remote/playlists` | Bearer: list / create M3U playlists |
| `GET  /api/remote/playlists/{uri}/items` | Bearer: track URIs in a playlist |
| `POST /api/remote/queue` | Bearer: replace the tracklist and (optionally) play |
| `GET  /api/remote/video/state`, `POST /api/remote/video/command` | Bearer: Jellyfin video-transport proxy |

**The `remote_enabled` flag.** The phone-facing surface is gated by a
single on/off flag, **default off**, persisted in
`~/.config/boombox-remote/state.json` (`{"enabled": bool}`). The
touchscreen Settings drawer's "Phone remote" panel toggles it via the
`/api/remote/admin/enable` / `/disable` endpoints. While it's off, every
phone-facing route returns `403 {"error": "remote_disabled"}` and the WS
closes with code `4403`. The flag does **not** gate the BLE peripheral,
the already-paired CYD hardware remote, or the `/api/remote/admin/*`
routes — those stay reachable so the touchscreen can turn the function
back on. It's a privacy gate against arbitrary phones on the Wi-Fi, not a
master kill switch for paired hardware.

**Auth.** Bearer token — `Authorization: Bearer <token>`, or `?token=`
on the WebSocket (aiohttp WS clients can't set headers on the handshake).
Tokens live in `~/.config/boombox-remote/peers.json` and are **durable
across reboots** — the only way a peer loses access is
`/api/remote/admin/unpair`. The `/api/remote/admin/*` routes are
localhost-only (an in-handler peer-IP check) rather than token-gated.

```json
{
  "<32-byte-hex-token>": {"label": "my-remote", "paired_at": 1731600000}
}
```

**Pairing.** A real PIN-pairing flow exists. The kiosk (localhost) calls
`POST /api/remote/pair/start` to mint an ephemeral 6-digit PIN (default
120 s TTL, single-use, held only as a SHA-256 hash in memory). A client
redeems it with `POST /api/remote/pair {pin, label}` and gets back a
durable bearer token, which is persisted to `peers.json`. The PIN can
rotate or expire freely; the token persists. For headless testing you
can still hand-add a token to `peers.json` directly — it's no longer the
only way in:

```bash
mkdir -p ~/.config/boombox-remote
TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 -c "
import json, os, pathlib
t = os.environ['TOKEN']
pathlib.Path.home().joinpath('.config/boombox-remote/peers.json').write_text(
    json.dumps({t: {'label': 'bootstrap', 'paired_at': 0}}))
print(t)
"
curl -H "Authorization: Bearer $TOKEN" \
    http://localhost/api/remote/state   # remote must be enabled first
```

mDNS: advertised as `_boombox._tcp.local` with TXT records `id`, `name`,
`version`, and `path` (`/api/remote/`); the advertised port is the nginx
LAN port (`BOOMBOX_LAN_PORT`, default 8090). Discover with
`dns-sd -B _boombox._tcp` (macOS) or `avahi-browse -r _boombox._tcp`
(Linux).

For the full access model — the enable toggle, pairing, and the endpoint
reference — see [ACCESS.md](./ACCESS.md).

- **Code:** [`services/boombox-remote.py`](../services/boombox-remote.py)
  (HTTP/WS + pairing/admin), [`services/remote_access.py`](../services/remote_access.py)
  (the `remote_enabled` flag), [`services/remote_files.py`](../services/remote_files.py)
  (file surface), [`services/remote_library.py`](../services/remote_library.py)
  (library/playlist/queue), [`services/jellyfin_client.py`](../services/jellyfin_client.py)
  (video proxy).
- **Logs:** `journalctl --user -u boombox-remote -f`
- **Env knobs:** `BOOMBOX_REMOTE_PORT` (default `6685`),
  `BOOMBOX_REMOTE_PEERS` (default `~/.config/boombox-remote/peers.json`),
  `BOOMBOX_REMOTE_STATE` (the `remote_enabled` flag file, default
  `~/.config/boombox-remote/state.json`),
  `BOOMBOX_REMOTE_ART_CACHE` (default `~/.cache/boombox-remote/art/`),
  `BOOMBOX_REMOTE_WS_POLL_MS` (default `250`),
  `BOOMBOX_REMOTE_PAIR_TTL_S` (default `120`),
  `BOOMBOX_REMOTE_BLE` (default `1`; set `0` to disable the BLE peripheral).

### `boombox-usb-mount@.service` — USB auto-mount (system template)

Instantiated by udev when a removable filesystem appears. Mounts under
`/media/boombox/<id>`, symlinks into `~/Music/.usb/<id>`, kicks a Mopidy
scan. `ExecStop` reverses everything on `udev remove`.

- **Code:** [`services/boombox-usb-mount.sh`](../services/boombox-usb-mount.sh)
- **Unit:** `install/systemd/system/boombox-usb-mount@.service`
- **udev rule:** `install/udev/99-boombox-usb.rules`
- **Owner mapping:** for FAT/exFAT/NTFS, the mount uses `uid=`/`gid=`
  matching `/etc/boombox/desktop-user`. ext4 / btrfs / etc. respect
  on-disk ownership; the mount is read-only by default so this is OK.

### `boombox-kiosk` — the Chromium kiosk itself

Launches Chromium with Wayland Ozone, kiosk flag, and
`--remote-debugging-port=9222` so the `pi` helper and the kiosk-guard can
drive it.

- **Unit:** `install/systemd/user/boombox-kiosk.service`
- **User-data dir:** `~/.config/chromium` (preserved across restarts).
- **Customize URL:** edit the unit or set `BOOMBOX_KIOSK_HOME` if you
  fork the launcher.

---

## Operational cheat sheet

```bash
# What's running?
systemctl --user list-units 'boombox-*' --state=active --no-legend
sudo systemctl is-active mopidy nginx

# Tail every boombox service together
journalctl --user -f -u 'boombox-*'

# Restart the whole user-side stack
systemctl --user restart boombox-state boombox-audio \
    boombox-orchestrator boombox-buttons boombox-resume \
    boombox-bt-volume boombox-kiosk-guard boombox-updater

# From your laptop
./pi status            # one-screen summary
./pi logs mopidy       # tail mopidy
./pi logs chrome       # tail /tmp/chromium.log
./pi guard status      # is the kiosk watchdog active?
```

When something stops working, the first three things to check are:

1. `./pi status` — is the service running at all?
2. `journalctl --user -u <service> -n 100` — what did it last say?
3. `curl 127.0.0.1:<port>/<endpoint>` — is the HTTP path responding?

90% of incidents are "PipeWire restarted and a daemon needs a kick", which
the auto-restart handles within 3–5 seconds. The other 10% are config
drift after a manual edit; reinstall from the templates by re-running
`/opt/boombox/current/install/install.sh` (idempotent).
