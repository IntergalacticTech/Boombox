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
| `GET/POST /api/theme` | Upload/remote page: match active skin palette |
| `GET/POST /api/upload/*` | UI: toggle PIN-gated LAN remote/upload service |
| `GET /api/usb/devices`, `POST /api/usb/copy` | UI: USB device list and pull-to-library copy |
| `POST /api/library/scan` | UI/upload service: trigger Mopidy local scan |

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

### `boombox-uploader` — LAN remote + file drop (off by default)

Toggled from the touchscreen Settings drawer. When on, hosts a PIN-gated
remote-control, playlist, upload, and download page at `/upload/` (proxied to
`127.0.0.1:6683`). PIN is regenerated on every start and cleared on stop.
The LAN nginx port requires the static web password first; the uploader PIN is
still a short-lived session gate for the remote/upload page itself.

- **Code:** [`services/boombox-uploader.py`](../services/boombox-uploader.py)
- **Unit:** `install/systemd/user/boombox-uploader.service` —
  intentionally not `--enable`d; toggled via `systemctl --user
  start|stop` from `boombox-state`.
- **Wire-format details:** see [ACCESS.md](./ACCESS.md).

### `boombox-remote` — wireless-remote HTTP API

**Listens on `127.0.0.1:6685`, proxied as `/api/remote/` by nginx.**

The HTTP/WS API for ESP32-based wireless remotes (and any other HTTP
client on the LAN). Exposes a consolidated state payload, a command
endpoint, a push-on-change WebSocket, and resized album art. Commands
flow through the shared `actions.fire()` dispatcher, so GPIO buttons and
wireless remotes share one code path.

| Endpoint | Used by |
|----------|---------|
| `GET  /api/remote/state` | Remote: consolidated state JSON |
| `POST /api/remote/command` | Remote: `{action, value?}` → `actions.fire()` |
| `GET  /api/remote/ws` | Remote: WebSocket, pushes state on change (~250 ms poll) |
| `GET  /api/remote/art/{hash}.jpg` | Remote: current track art, on-the-fly resized to 240×240 (ETag + 304) |

All endpoints require `Authorization: Bearer <token>` except the WS
endpoint, which accepts the token in the query string (`?token=...`).
Tokens live in `~/.config/boombox-remote/peers.json`:

```json
{
  "<32-byte-hex-token>": {"label": "my-remote", "paired_at": 0}
}
```

Until pairing UI ships (Phase 2), add a bootstrap token by hand to test:

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
    http://boombox.local:6685/api/remote/state
```

mDNS: advertised as `_boombox._tcp.local` with TXT records `id`, `name`,
`version`. Discover with `dns-sd -B _boombox._tcp` (macOS) or
`avahi-browse -r _boombox._tcp` (Linux).

- **Code:** [`services/boombox-remote.py`](../services/boombox-remote.py)
- **Logs:** `journalctl --user -u boombox-remote -f`
- **Env knobs:** `BOOMBOX_REMOTE_PORT` (default `6685`),
  `BOOMBOX_REMOTE_PEERS` (default `~/.config/boombox-remote/peers.json`),
  `BOOMBOX_REMOTE_ART_CACHE` (default `~/.cache/boombox-remote/art/`),
  `BOOMBOX_REMOTE_WS_POLL_MS` (default `250`).

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
    boombox-bt-volume boombox-kiosk-guard

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
drift after a manual edit; reinstall from the templates with
`boombox-update --force`.
