# Access — upload mode and USB drives

How guests get music *onto* the boombox, and how a plugged-in USB stick
joins the library automatically.

---

## Upload mode

The boombox runs a tiny upload web app on its LAN, **off by default**.
You toggle it from the touchscreen Settings drawer; while it's on, the
touchscreen displays the URL and a 4-digit PIN. Anyone on the same Wi-Fi
opens the URL on a phone or laptop, types the PIN, and can drop audio
files or download anything in the library.

```
       Touchscreen                         Phone / laptop on the LAN
   ┌──────────────────┐                ┌────────────────────────┐
   │  Settings →      │                │  Boombox · Drop        │
   │  Upload mode     │   nginx :80    │  ┌────────────────┐    │
   │  ┌──────────┐    │ ──────────────▶│  │ drop files here│    │
   │  │ TURN ON  │    │   /upload/     │  └────────────────┘    │
   │  └──────────┘    │                │  Library [filter…]     │
   │                  │                │   • track-1.flac  ⇣    │
   │  http://192…/up… │                │   • track-2.mp3   ⇣    │
   │  PIN  4 8 1 7    │                │                        │
   └──────────────────┘                └────────────────────────┘
```

### What turning it on does

1. The touchscreen calls `POST /api/upload/enable` on `boombox-state`.
2. `boombox-state` runs `systemctl --user start boombox-uploader.service`.
3. The uploader generates a fresh 4-digit PIN, writes it to
   `$XDG_RUNTIME_DIR/boombox-uploader.pin`, and starts listening on
   `127.0.0.1:6683`.
4. nginx, which is always running, proxies `/upload/` → `127.0.0.1:6683`.
5. The touchscreen polls `/api/upload/status` every 4 s and shows the
   URL + PIN.

Turning it **off** stops the unit, clears the PIN file, and removes the
`/upload` reachability — nginx still serves the path but proxy attempts
get a 502 because nothing is listening on 6683.

The PIN regenerates on every start. There's no way to "remember" a PIN
across toggle cycles, by design.

### Where uploads go

Files land in `~/Music/uploads/` (the `BOOMBOX_MUSIC_DIR` env var
overrides). Filename collisions get suffixed (`track.mp3` → `track-1.mp3`,
`track-2.mp3`, …). Only audio extensions in this allowlist are accepted:

```
.mp3 .m4a .aac .flac .ogg .oga .opus .wav .aiff .alac .wma
```

Per-file size cap: **1 GB** (configured both in nginx via
`client_max_body_size 1100M` and in the uploader via `MAX_FILE_BYTES`).

After every successful upload, the uploader fires a best-effort
`POST /api/library/scan` so Mopidy picks up the new tracks within a few
seconds.

### What the upload page can do

| Action | How |
|--------|-----|
| Authenticate | Type the 4-digit PIN. The page sets a 12-hour cookie; subsequent visits skip the PIN unless the boombox restarts. |
| Upload | Drag-and-drop, or tap "choose files". Uploads stream with a progress bar; failures surface inline. |
| Browse the library | Filter box at the bottom; lists every audio file under `~/Music/`, including symlinked USB drives. |
| Download | Each row has a `download` link. Files are streamed via aiohttp's `FileResponse`. |

### Security posture

This is **not** a hardened public-internet service. It is a friction gate
for a LAN appliance. Specifically:

- **PIN is a 4-digit number.** A determined attacker on the same LAN can
  brute-force it in about 30 seconds. The mitigation is "the toggle is
  off by default."
- **No HTTPS.** Everything is plaintext on port 80. Don't enable upload
  mode on a Wi-Fi network you don't trust.
- **Path-traversal defense:** filenames are sanitized
  (`safe_filename()`), uploads are pinned to `~/Music/uploads/` via
  `under_root()`, and downloads validate that the resolved path is
  inside `MUSIC_ROOT`. Symlink-following downloads do let you grab files
  from mounted USB drives — that's the point.
- **No quotas.** A guest could fill the SD card. The 1 GB per-file cap is
  the only limit.

If you ever want to expose this to the internet (don't), wrap it in
something with rate-limiting and TLS.

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

The drive stays read-only by default. Push-to-drive (see below)
remounts read-write transparently for the duration of the copy. (TODO:
not yet implemented — current drives need to be mounted RW manually if
you want the push direction to work.)

### Pull and push from the touchscreen

The Settings drawer shows every mounted drive with two bulk actions:

- **PULL → LIBRARY** — copies every audio file on the drive into
  `~/Music/from-usb/<drive-id>/` and triggers a scan.
- **PUSH → DRIVE** — copies every audio file in the local library to
  `<drive>/from-boombox/`.

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

| Endpoint | Method | What |
|---|---|---|
| `/api/upload/status` | GET | `{enabled, pin, url, ip}` |
| `/api/upload/enable` | POST | start the uploader unit |
| `/api/upload/disable` | POST | stop the uploader unit |
| `/api/usb/devices` | GET | mounted-drive list with disk usage |
| `/api/usb/copy` | POST | bulk copy in either direction |
| `/api/library/scan` | POST | trigger a Mopidy local scan |
| `/upload/` | GET | the public upload page (proxied) |
| `/upload/upload` | POST | multipart upload (PIN-gated) |
| `/upload/list` | GET | library JSON (PIN-gated) |
| `/upload/download/{path}` | GET | file download (PIN-gated) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Upload toggle says "TURN ON" but nothing happens after | `boombox-uploader.service` failed to start | `journalctl --user -u boombox-uploader -n 50` — usually a missing dep in the venv |
| URL field shows "(no LAN IP yet)" | `hostname -I` returned nothing | Wi-Fi not connected; or you're on link-local only |
| PIN keeps regenerating | Service is restart-looping | Check `systemctl --user status boombox-uploader` |
| USB drive plugged in, nothing happens | udev didn't match (rule not loaded?) | `sudo udevadm control --reload-rules`, then re-plug the drive |
| Drive mounted but tracks don't appear in Mopidy | Library scan didn't fire | `curl -X POST http://127.0.0.1:6681/library/scan`, then check Mopidy logs |
| "Pull → library" reports "copy failed" | Filesystem not mounted; or out of space | `df -h /home/$USER/Music`; `dmesg \| tail` for FS errors |
| `sudo: a password is required` in mopidyctl scan | Sudoers fragment didn't install | `sudo visudo -c` and check `/etc/sudoers.d/boombox` exists with correct username |
| Phone uploads get "413 Request Entity Too Large" | nginx `client_max_body_size` mismatch | The default is 1100M; raise both nginx and `MAX_FILE_BYTES` if you need more |
