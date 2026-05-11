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

### `boombox-buttons` — GPIO transport

Reads `/dev/gpiochip0` for falling edges on the configured BCM pins,
fires Mopidy JSON-RPC for each. Pin map defaults to
`{play_pause: 17, next: 27, previous: 22, volume_up: 23, volume_down: 24}`,
overridable via `/etc/boombox/buttons.json`.

- **Code:** [`services/boombox-buttons.py`](../services/boombox-buttons.py)
- **Requires:** user in the `gpio` group (the installer handles this; a
  reboot is needed after first install).
- **Wiring:** each button shorts its pin to GND when pressed; the SoC's
  internal pull-up holds it high otherwise.

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
