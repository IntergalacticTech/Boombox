# Home Library

The boombox's "Home Library" is a parallel browse tree backed by a
[Navidrome](https://www.navidrome.org/) (or any
[Subsonic-API-compatible](https://www.subsonic.org/pages/api.jsp)) server
on your LAN. Browse from the touchscreen or PWA, pin albums for offline
play to a USB cache drive, and stream the rest with one tap.

For the service internals see
[SERVICES.md → `boombox-library`](./SERVICES.md#boombox-library--navidrome-catalog-sync--usb-offline-cache).

---

## What you get

- **One-tap pinning.** Tap the pin on an album / artist / playlist and
  the tracks download to your USB cache drive. Pinned content survives
  reboots, network failures, and the boombox going home with you on a
  trip.
- **Favorite ↔ pin coupling.** Tapping the heart on a Home Library row
  also pins the track for offline play (`source='favorite'`); unfavoriting
  removes only the favorite-driven pin, so a parallel explicit pin still
  survives.
- **Online streaming when nothing's cached.** The playback resolver
  hands Mopidy a direct `/rest/stream.view?…` URL with token+salt auth
  so streams play through the same audio path as local files.
- **Source badge on the now-playing bar.** ⬇ Cache · ⚡ Stream · 🎵 USB
  · 📱 AirPlay · 🎙 BT — at a glance, you can tell which pipeline is
  feeding the speakers.
- **Sync chip in the chrome.** Green = connected and synced. Amber =
  syncing. Grey = unreachable or no source configured. Tap it to jump
  to **Settings → Home Library**.
- **Opportunistic streamed cache.** Tracks you stream get cached
  behind the scenes (subject to FIFO eviction) so re-listens are
  instant.

---

## First-run setup

### 1. Configure your source

Open **Settings → Home Library** on the touchscreen (or the LAN web UI):

| Field | What to enter |
|-------|---------------|
| Source URL | `http://<navidrome-host>:4533` (or your own port; `https://` works too) |
| Username | Your Navidrome user |
| Password | Your Navidrome password (encrypted at rest with a key derived from `/etc/machine-id` — moving the disk to a different Pi makes it unreadable) |

Tap **Test**. You should see ✓ Connected within a second or two. Tap
**Save**. The first full sync (catalog + FTS index) takes a few minutes
for a typical 5–10 k album library and runs hourly thereafter.

### 2. Adopt a USB cache drive

Plug in a USB stick formatted as ext4 / NTFS / exFAT (FAT32 works but
caps files at 4 GB). The kiosk pops a **"New drive detected"** overlay
showing the drive's label and free space. Tap **YES, USE FOR CACHE**:

- Writes a `.boombox-cache` marker file at the drive's root.
- Creates `audio/`, `meta/`, `tmp/` subdirs.
- Points the stable `/opt/boombox/cache-mount` symlink at the drive.
- The downloader starts pulling any already-pinned tracks.

Read-only mounts (common for auto-mounted vfat drives) are filtered out
of the candidate list — the adopt prompt won't fire for them.

You can also adopt manually:

```bash
sudo touch /media/<drive>/.boombox-cache
sudo mkdir -p /media/<drive>/{audio,meta,tmp}
systemctl --user restart boombox-library
```

### 3. Browse + pin

Open the **Library drawer** (the leftmost button in most skins or the
chrome's Library button). Tap **Home Library**. Sub-roots:

- **Artists / Albums / Playlists** — flat lists, FTS-searchable from
  the search bar at the top.
- **Cached only** — albums whose tracks are present locally (good for
  knowing what works offline).

Pin button states:

- *outline* — unpinned
- *filled with progress ring* — downloading (number shows %)
- *filled + ✓* — fully cached
- *filled + ⚠* — last download attempt errored (will retry on next sync)

Long-press the pin button to open a "manage pin" sheet with source
attribution (user / favorite / starred / rfid), download date, size,
and an explicit unpin.

---

## Settings → Offline Cache

The Cache panel shows a stacked bar:

```
▓ reserved 1 GB  ▓ pinned 80 GB  ▓ streamed 45 GB  ░ free 74 GB
Total 200 GB · Used 125 GB · Free 74 GB
```

| Segment | What it is |
|---------|------------|
| **reserved** | Headroom kept free for the OS / downloader temp files (default 1 GB) |
| **pinned** | Tracks belonging to any pin — never evicted |
| **streamed** | Opportunistic cache from one-off streams — evicted FIFO when full |
| **free** | Actual free bytes on the drive |

The **Clear streamed cache** button deletes every cache entry whose
track is NOT pin-protected (and removes the matching files). Pinned
content is untouched.

---

## Pin sources and precedence

| Source | Created by | Precedence |
|--------|------------|------------|
| `user` | Explicit pin button tap | Highest |
| `favorite` | Heart button on a Home Library row (auto-pin coupling) | |
| `rfid` | Binding a card to an album / artist / playlist / track | |
| `starred` | Navidrome's "star" sync (one-way: starred in Navidrome → pinned locally) | Lowest |

When two writers want the same target, the higher-precedence source
wins on UPSERT. Unpin operations can be source-filtered: removing a
favorite pin does NOT touch a parallel user pin. The "explicit unpin"
button in the manage-pin sheet IS unfiltered — it removes whichever pin
exists.

---

## Offline play

When the cache drive is present and the bound track is `present` in
`cache_state`, the resolver hands Mopidy a `file://<cache>/audio/<id>.<suffix>`
URI. GStreamer's built-in filesrc plays it directly — no Mopidy-Local
scan, no metadata round-trip.

When the track isn't cached but Navidrome is reachable, the resolver
emits a direct stream URL:

```
http://<navidrome-host>:4533/rest/stream.view?u=<user>&t=<token>&s=<salt>&v=1.16.1&c=boombox-library&f=json&id=<track-id>
```

Token+salt auth means the password never appears in URLs; salt is fresh
per call so signatures aren't replayable. Mopidy's built-in stream
backend pipes the HTTP body through GStreamer.

> **Note for Debian Trixie + Mopidy 3.4.2 setups:** the system
> `python3-gi` upgrade broke `mopidy/audio/scan.py`. `install.sh`
> applies an idempotent patch at install time so http:// stream URLs
> work. If you ever upgrade Mopidy manually, re-apply that patch.

---

## CLI cheat sheet

```bash
# Service health
curl -s http://127.0.0.1/api/library/health | jq

# Trigger a sync
curl -s -X POST http://127.0.0.1/api/library/sync/run

# Browse
curl -s 'http://127.0.0.1/api/library/browse?type=artists' | jq '.items[:5]'

# Pin an album from the CLI
curl -s -X POST http://127.0.0.1/api/library/pin \
    -H 'Content-Type: application/json' \
    -d '{"kind":"album","id":"<subsonic-album-id>","mode":"pin","source":"user"}'

# Inspect the catalog directly
sqlite3 /opt/boombox/state/library.db \
    'SELECT COUNT(*) FROM tracks; SELECT COUNT(*) FROM pins'

# Cache state
ls -la /opt/boombox/cache-mount/audio/ | head
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Sync chip stays grey | No source configured. Open Settings → Home Library. |
| Sync chip is red | `boombox-library` service is down. `systemctl --user status boombox-library` |
| "Library unreachable" with a saved source | Wrong URL / port, or Navidrome itself is down. `curl http://<navidrome>:4533/rest/ping.view?u=...&p=...&v=1.16.1&c=test&f=json` |
| Cache panel shows "Cache drive offline" | No drive with the `.boombox-cache` marker present under `/media`. Plug in a drive and accept the adopt prompt, or run the manual adopt commands above. |
| Pinned album never downloads | Cache drive missing, or the source isn't reachable. The downloader will retry as soon as both come back. |
| Streaming a non-cached track doesn't play | Mopidy scan patch missing — see the Trixie note above. |
| Adopt overlay keeps popping up | The drive is mounted read-only (common for vfat auto-mounts). The library service filters those out as of `058a4b8`. Run `git log --oneline -1 services/boombox_library/cache_drive.py` to confirm your install includes the fix. |

---

## Design choices worth knowing

- **Phase 1's `boombox-library` service ships the entire backend.**
  The kiosk UI lives entirely in the SPA — no service-side rendering.
- **Catalog source-of-truth is Navidrome.** The local SQLite cache is
  a read-through copy; resyncs are upserts. Deleting `library.db` and
  letting it rebuild is always safe.
- **The cache drive is portable.** Pull the USB stick, plug it into
  another boombox, and that boombox can play your pinned content
  offline. The pin sidecar at `<drive>/meta/pins.json` carries the
  pin set forward.
- **No PWA browse parity yet.** The phone PWA at `/remote/` doesn't
  yet have a Home Library browse view (that's roadmap). For now the
  phone gets state, queue, library search, and playlist editing
  through `/api/remote/`; pinning + browsing the Subsonic catalog
  happen on the touchscreen.
