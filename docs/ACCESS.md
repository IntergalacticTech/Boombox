# Access — LAN remote, network share, and USB drives

How guests control the boombox from a phone or larger screen, get music
*onto* the boombox, and how a plugged-in USB stick joins the library
automatically.

---

## Web access and auth

The physical touchscreen is the trusted local device. Chromium loads
`http://localhost/` through nginx on loopback port 80 and does **not** need a
password.

Anything from the LAN uses nginx's authenticated web port, default `8090`:

```text
http://<pi-ip>:8090/
```

The installer generates one static remote credential and stores it in:

```bash
sudo cat /etc/boombox/web-auth.env
```

The touchscreen Settings drawer shows this web login. The same password is
used for the SMB share. One exception: the `/api/remote/` path has
`auth_basic off` in the nginx config — the remote API carries its own bearer
tokens, so phones go straight to the token handshake instead of hitting the
Basic-auth modal first.

## Remote access — the `boombox-remote` API

`boombox-remote` is the single phone-facing backend. It's a boot-enabled
user service on `127.0.0.1:6685`, proxied as `/api/remote/` by nginx. It
serves the CYD hardware remote (over BLE and HTTP), the phone web app at
`/remote/`, and any other HTTP client on the LAN.

> **What's real today.** Phase 1 delivered the consolidated *API*, the
> enable toggle, and PIN pairing. Phase 2A added the installable phone
> web app: an offline-capable PWA served by nginx at
> `http://<pi-ip>:8090/remote/` — the same URL the touchscreen's web-QR
> overlay encodes. Open it on a phone, redeem the PIN displayed on the
> touchscreen, and you get a Now Playing screen with transport controls
> (play/pause/next/previous/stop, shuffle, mute, volume) themed to match
> the active skin. Use the browser's **Add to Home Screen** to install it
> as a standalone app. The next phase adds the remaining screens
> (sources, video, playlists, file browser, extras) and a Web Bluetooth
> pairing flow for off-network Android control; the CYD hardware remote
> already uses this same API and is unaffected.

The remote API can:

- read consolidated player state (source, track, volume, skin, theme) and
  push it over a WebSocket
- fire transport + system commands through the shared `actions.fire()`
  dispatcher
- serve resized album art
- browse / download / upload / delete library files
- search the Mopidy library, create and play M3U playlists, replace the queue
- proxy Jellyfin video-transport commands

### The `remote_enabled` toggle

The phone-facing surface is gated by a single on/off flag, **off by
default**, persisted in `~/.config/boombox-remote/state.json`
(`{"enabled": bool}`). You flip it from the touchscreen Settings drawer's
**Phone remote** panel.

While it's off, every phone-facing route returns `403 {"error":
"remote_disabled"}` and the WebSocket closes with code `4403`. The flag is a
privacy gate against arbitrary phones on the Wi-Fi — it does **not** gate the
BLE peripheral, the already-paired CYD hardware remote, or the
`/api/remote/admin/*` routes, so the touchscreen can always turn the function
back on.

```
       Touchscreen                          Phone / CYD remote on the LAN
   ┌──────────────────┐                ┌────────────────────────┐
   │  Settings →      │                │  pair: POST /pair      │
   │  Phone remote    │  localhost     │   { pin: "481762" }    │
   │  ┌──────────┐    │ ──────────────▶│        │               │
   │  │ ENABLE   │    │  admin/enable  │        ▼               │
   │  └──────────┘    │                │  durable bearer token  │
   │  pairing PIN     │  admin/status  │        │               │
   │   4 8 1 7 6 2    │ ◀──────────────│        ▼               │
   │  (120 s, rotates)│   peers list   │  GET /api/remote/state │
   └──────────────────┘                └────────────────────────┘
```

### What turning it on does

1. The touchscreen calls `POST /api/remote/admin/enable` on `boombox-remote`
   (localhost-only route).
2. `boombox-remote` writes `{"enabled": true}` to
   `~/.config/boombox-remote/state.json`. The enable-gate middleware now lets
   phone-facing routes through.
3. The touchscreen calls `POST /api/remote/pair/start` (also localhost-only)
   to mint an ephemeral 6-digit PIN and displays it.
4. A client redeems the PIN with `POST /api/remote/pair {pin, label}` and gets
   back a durable 32-byte-hex bearer token. The token is persisted to
   `~/.config/boombox-remote/peers.json`.
5. The client uses that token (`Authorization: Bearer <token>`, or `?token=`
   on the WebSocket) for every subsequent request.
6. The touchscreen polls `GET /api/remote/admin/status` to show the enable
   state and the list of paired peers.

Turning it **off** writes `{"enabled": false}`; the phone-facing routes start
returning `403` and open WebSockets are closed. Paired tokens are *not*
discarded — flip the toggle back on and existing devices work again without
re-pairing.

### Pairing — PINs are ephemeral, tokens are durable

The PIN exists only to bootstrap a token. It's a cryptographically random
6-digit number, held only as a SHA-256 hash in memory, single-use, with a
default 120-second TTL (`BOOMBOX_REMOTE_PAIR_TTL_S`). It can rotate or expire
freely.

The **bearer token** is what lasts: it's written to `peers.json` and survives
reboots. The only way a peer loses access is `POST /api/remote/admin/unpair`
with that peer's token (a localhost-only route, driven from the touchscreen).

```json
{
  "<32-byte-hex-token>": {"label": "kitchen-phone", "paired_at": 1731600000}
}
```

(`paired_at` is a Unix timestamp; `0` marks a hand-added bootstrap token.)

For headless testing you can still hand-add a token to `peers.json` directly
— pairing is the normal path, but it's no longer the only way in. Run the
`python3` block on the Pi (it writes the Pi's `~/.config`); the `curl` can run
from anywhere on the LAN, since `/api/remote/` has `auth_basic off` and needs
no Basic-auth credential:

```bash
mkdir -p ~/.config/boombox-remote
TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
python3 -c "
import json, pathlib
t = '$TOKEN'
p = pathlib.Path.home() / '.config/boombox-remote/peers.json'
p.write_text(json.dumps({t: {'label': 'bootstrap', 'paired_at': 0}}))
print(t)
"
# remote must be enabled first (touchscreen, or POST /api/remote/admin/enable)
curl -H "Authorization: Bearer $TOKEN" \
    http://<pi-ip>:8090/api/remote/state
```

### Uploading files

`POST /api/remote/files/upload` takes a multipart form. Files route by
extension:

- **audio** → `~/Music/uploads/` (`BOOMBOX_MUSIC_DIR` overrides the root)
- **video** → `~/Videos/uploads/` (`BOOMBOX_VIDEO_DIR` overrides the root)

Filename collisions get suffixed (`track.mp3` → `track-1.mp3`,
`track-2.mp3`, …). The accepted extensions:

```
audio: .mp3 .m4a .aac .flac .ogg .oga .opus .wav .aiff .alac .wma
video: .mp4 .m4v .mkv .mov .avi .webm .wmv .mpg .mpeg .ts .3gp
```

Per-file size cap: **4 GB** — enforced in the upload handler
(`remote_files.MAX_FILE_BYTES`) and matched by nginx's `client_max_body_size
4096M`. nginx is configured with `proxy_request_buffering off` so large
uploads stream straight through instead of buffering to `/tmp`.

After a successful audio upload, the handler fires a best-effort
`POST /api/library/scan` so Mopidy picks up the new tracks within a few
seconds. After a video upload it fires a Jellyfin library refresh.

### What the remote API can do

| Action | How |
|--------|-----|
| Authenticate | Redeem a pairing PIN for a durable bearer token; send it as `Authorization: Bearer <token>` (or `?token=` on the WebSocket). |
| Read state | `GET /api/remote/state` for a one-shot snapshot, or `GET /api/remote/ws` for push-on-change updates (~250 ms). |
| Remote control | `POST /api/remote/command {action, value?}` — play/pause/next/previous/stop, source switching, volume, etc., through `actions.fire()`. |
| Create playlists | `GET /api/remote/library/search?q=` to find tracks, `POST /api/remote/playlists` to save an M3U playlist via Mopidy. |
| Play playlists | `GET /api/remote/playlists` lists them; `GET /api/remote/playlists/{uri}/items` reads track URIs; `POST /api/remote/queue` loads and plays them. |
| Upload | `POST /api/remote/files/upload` — audio → `~/Music/uploads/`, video → `~/Videos/uploads/`. |
| Browse the library | `GET /api/remote/files/browse?path=` lists every audio file under `~/Music/`, including symlinked USB drives. |
| Download | `GET /api/remote/files/download/{path}` streams a file via aiohttp's `FileResponse`. |
| Delete | `POST /api/remote/files/delete` removes a local library file. USB/symlinked files are read-only. |
| Video transport | `GET /api/remote/video/state` and `POST /api/remote/video/command` proxy the local Jellyfin session. |

### SMB network share

The installer publishes the music library as:

```text
smb://<pi-ip>/boombox-music
```

Use the desktop user (`jwc` on the current appliance) and the password from
`/etc/boombox/web-auth.env`. The share is read/write, so adding, renaming, and
deleting files through Finder, Windows Explorer, or another SMB client changes
`~/Music/` directly. Run a library scan from the touchscreen Settings drawer if
you make large changes and Mopidy has not picked them up yet.

### Security posture

This is **not** a hardened public-internet service. It is a friction gate
for a LAN appliance. Specifically:

- **The remote API is off by default.** The `remote_enabled` flag has to be
  flipped on from the physical touchscreen before any phone-facing route
  responds — an attacker on the Wi-Fi can't reach the surface at all until a
  human at the device turns it on.
- **Bearer tokens, minted by PIN.** A device only gets a token by redeeming a
  PIN that's displayed on the touchscreen for ~120 seconds. The token is a
  32-byte random hex string — not brute-forceable — and is revocable via
  `admin/unpair`. The PIN is stored only as a SHA-256 hash and compared with
  `hmac.compare_digest`.
- **Admin routes are localhost-only.** `/api/remote/admin/*` and
  `/api/remote/pair/start` check the proxied peer IP in-handler and reject
  anything that isn't loopback, so only the kiosk on the Pi can enable the
  function, mint PINs, or unpair devices.
- **No HTTPS.** Everything is plaintext on the LAN web port. Don't enable the
  remote on a Wi-Fi network you don't trust.
- **Path-traversal defense:** filenames are sanitized (`safe_filename()`),
  uploads are pinned to the `uploads/` dirs via `under_root()`, and
  `safe_compose()` rejects `..` segments and absolute paths. Symlink-following
  downloads do let you grab files from mounted USB drives — that's the point.
- **Delete is intentionally narrower than download.** The file API deletes
  only audio files that resolve inside the local music library. USB/symlinked
  files are read-only there; use SMB or remount workflows for broader file
  work.
- **No quotas.** A guest could fill the SD card. The 4 GB per-file cap is the
  only limit.

If you ever want to expose this to the internet (don't), wrap it in
something with rate-limiting and TLS.

### Remote-first workflow ideas

These fit the phone/laptop client better than the 5" touchscreen and are
targeted at the next phase, beyond the Now Playing screen shipped today:

- **Playlist studio:** drag/reorder drafts, edit existing playlists, import
  current queue, duplicate playlists, and bulk-add search results.
- **Queue surgery:** multi-select queue rows, reorder blocks, save queue as
  playlist, clear played tracks.
- **Library maintenance:** batch rename uploaded files, delete duplicates,
  rescan by folder, show files added today.
- **Party mode:** guest request queue with approve/reject controls on the
  touchscreen.
- **Set builder:** timed blocks for events: warmup, peak, cooldown, karaoke.
- **Diagnostics:** service health, recent logs, audio sink graph, library scan
  progress, storage usage, and temperature history.

---

## USB drives

Plug in a USB stick or drive: a few seconds later, its tracks appear in
the library, mixed in with everything else.

### What happens when you plug in

1. **udev** sees a new block device with a filesystem.
   `/etc/udev/rules.d/99-boombox-usb.rules` matches it (removable, with
   `ID_FS_USAGE=filesystem`) and pushes
   `boombox-usb-mount@<sda1>.service` via `SYSTEMD_WANTS`.
2. **systemd** instantiates the unit template. It runs as root and calls
   `services/boombox-usb-mount.sh mount /dev/sda1`.
3. **The mount script:**
   - Reads the partition LABEL (or first 8 chars of UUID) → `<id>`.
   - Mounts read-only at `/media/boombox/<id>` with sane options
     (`nosuid,nodev,noatime`, plus `uid=`/`gid=` for FAT/exFAT/NTFS).
   - Symlinks the mountpoint to `~/Music/.usb/<id>`.
   - Triggers a Mopidy library scan via
     `POST http://127.0.0.1:6681/library/scan` (falls back to
     `mopidyctl local scan` if `boombox-state` is down).
4. **Mopidy** rescans and the tracks appear under that label inside the
   normal library browsing UI.

When you unplug:

1. udev fires `ACTION=="remove"` and the rule runs
   `systemctl stop boombox-usb-mount@sda1.service`.
2. The unit's `ExecStop` calls `boombox-usb-mount.sh unmount /dev/sda1`,
   which removes the symlink and unmounts. Falls back to `umount -l`
   (lazy unmount) if the kernel still has open handles.
3. Another scan fires so the tracks disappear from the library.

The drive stays read-only by default. Push-to-drive is still planned; current
drives need to be mounted read-write manually if you want that direction to
work outside the SMB/local library path.

### Pull and push from the touchscreen

The Settings drawer shows mounted drives and supports:

- **PULL → LIBRARY** — copies every audio file on the drive into
  `~/Music/from-usb/<drive-id>/` and triggers a scan.
- **PUSH → DRIVE** — planned, but disabled in the UI until the RW remount
  flow is implemented.

Both end-to-end loop through `POST /api/usb/copy`:

```json
{
  "direction": "to-library",
  "device_id": "VAN_HALEN_LIVE",
  "items": []
}
```

`items` may also be a list of relative paths to copy specifically; an
empty/missing list means "every audio file in the source root."

The endpoint walks files synchronously on a worker thread (`shutil.copy2`
preserves mtime) so the request stays open for the duration. This is
fine for a few hundred MB; for a 50 GB drive it'll be a slow request.
A future iteration will background the copy and stream progress.

### Why symlinks instead of editing `mopidy.conf`?

Mopidy-local has a single `media_dir`. Adding a per-drive `[file]` section
would force a reload on every plug/unplug, and the `[local]` library
wouldn't see those tracks anyway. Symlinking under `~/Music/.usb/`
lets the existing scan-the-music-dir flow Just Work; Mopidy follows
symlinks.

The dot-prefix (`.usb`) keeps the directory cosmetically out of the way.
File browsers ignore it; Mopidy doesn't.

---

## Endpoints summary

All `/api/remote/*` routes below sit behind nginx (`auth_basic off`) and the
`boombox-remote` service on `127.0.0.1:6685`. "Bearer" = requires a paired
bearer token. "localhost" = the in-handler peer-IP check rejects non-loopback
callers. The `boombox-state` `/api/*` routes are unchanged from before.

| Endpoint | Method | Auth | What |
|---|---|---|---|
| `/api/remote/state` | GET | Bearer | Consolidated state JSON (source, track, volume, skin, theme) |
| `/api/remote/command` | POST | Bearer | `{action, value?}` → `actions.fire()` |
| `/api/remote/ws` | GET | `?token=` | WebSocket, pushes state on change |
| `/api/remote/art/{hash}.jpg` | GET | Bearer | Resized album art (240×240, ETag) |
| `/api/remote/pair/start` | POST | localhost | Mint an ephemeral 6-digit pairing PIN |
| `/api/remote/pair` | POST | none | Redeem a PIN → durable bearer token |
| `/api/remote/admin/status` | GET | localhost | `{ok, enabled, peers}` |
| `/api/remote/admin/enable` | POST | localhost | Set `remote_enabled` on |
| `/api/remote/admin/disable` | POST | localhost | Set `remote_enabled` off |
| `/api/remote/admin/unpair` | POST | localhost | `{token}` removes one paired peer |
| `/api/remote/files/browse?path=` | GET | Bearer | Directory listing under `~/Music/` |
| `/api/remote/files/download/{path}` | GET | Bearer | Stream a library file |
| `/api/remote/files/upload` | POST | Bearer | Multipart upload (audio → Music, video → Videos) |
| `/api/remote/files/delete` | POST | Bearer | Delete a local library file |
| `/api/remote/library/search?q=` | GET | Bearer | Mopidy library search |
| `/api/remote/playlists` | GET / POST | Bearer | List / create M3U playlists |
| `/api/remote/playlists/{uri}/items` | GET | Bearer | Track URIs in a playlist |
| `/api/remote/queue` | POST | Bearer | Replace the tracklist and (optionally) play |
| `/api/remote/video/state` | GET | Bearer | Local Jellyfin session state |
| `/api/remote/video/command` | POST | Bearer | Jellyfin transport command |
| `/api/usb/devices` | GET | LAN web | Mounted-drive list with disk usage |
| `/api/usb/copy` | POST | LAN web | Bulk copy in either direction |
| `/api/library/scan` | POST | LAN web | Trigger a Mopidy local scan |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Phone gets `403 {"error": "remote_disabled"}` on every call | `remote_enabled` flag is off | Enable it from the touchscreen Settings → Phone remote, or `curl -X POST http://localhost/api/remote/admin/enable` on the Pi |
| WebSocket closes immediately with code `4403` | Same — remote disabled | As above |
| WebSocket closes with code `4401`, or REST returns `401 bad_token` | Token missing or not in `peers.json` | Re-pair, or check `~/.config/boombox-remote/peers.json` |
| `POST /api/remote/pair` returns `no_active_pin` | PIN expired (120 s TTL) or service restarted mid-pairing | Mint a fresh PIN from the touchscreen and redeem it promptly |
| `pair/start` or `admin/*` returns `403 forbidden` from the LAN | Those routes are localhost-only | Run them from the Pi itself; they're driven by the kiosk, not phones |
| Paired device stopped working after a reboot | Tokens *are* durable — check the service is up | `journalctl --user -u boombox-remote -n 50`; confirm `remote_enabled` is still on |
| Phone uploads get "413 Request Entity Too Large" | nginx `client_max_body_size` mismatch | Default is `4096M`; raise both nginx and `remote_files.MAX_FILE_BYTES` if you need more |
| Upload succeeds but track/movie never appears | Library scan didn't fire | Audio: `curl -X POST http://127.0.0.1:6681/library/scan`. Video: hit Jellyfin Dashboard → Scan Media Library |
| USB drive plugged in, nothing happens | udev didn't match (rule not loaded?) | `sudo udevadm control --reload-rules`, then re-plug the drive |
| Drive mounted but tracks don't appear in Mopidy | Library scan didn't fire | `curl -X POST http://127.0.0.1:6681/library/scan`, then check Mopidy logs |
| "Pull → library" reports "copy failed" | Filesystem not mounted; or out of space | `df -h /home/$USER/Music`; `dmesg \| tail` for FS errors |
| `sudo: a password is required` in mopidyctl scan | Sudoers fragment didn't install | `sudo visudo -c` and check `/etc/sudoers.d/boombox` exists with correct username |
