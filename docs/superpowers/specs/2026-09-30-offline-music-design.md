# LAN app — sub-project 2A: offline music + Storage page

Date: 2026-09-30 · Status: draft for review · Branch: `feat/offline-music` (from `feat/lan-app`)

## Context and goal

The boombox is going **on the road**: it must play music with the homelab
(`music.coblr.io`) unreachable and no internet. Sub-project 2 ("storage &
video") is split into **2A offline music + Storage page (this spec)**,
**2B offline video** (downloads converted on the homelab, uploads, built-in
kiosk player, watch queue) and **2C road mode** (boombox Wi-Fi hotspot when
no known network). Each gets its own spec → plan → build.

### What the owner decided
- Keep offline: albums / artists / playlists the owner marks **"keep
  offline"** in the LAN app, **plus everything starred in Navidrome**,
  downloaded automatically as **original files** (no re-encoding).
- Storage lives on the boombox's **internal drive** (MarkII: ~870 GB free
  NVMe). No external drive required.

### Success criteria
- With the homelab unreachable, the kiosk, the LAN app and RFID cards play
  every kept track; un-kept tracks are visibly unavailable (greyed, "not
  offline") instead of failing silently.
- In the LAN app the owner can mark an album / artist / playlist "keep
  offline", see its download progress, and remove it; a Storage page shows
  drive size, free space, music bytes kept, and the download queue.
- Downloads never starve the Pi: ≤ 2 at a time, paused while a stream is
  playing, backed off when the SoC is hot, and they stop before the drive
  gets full.

### Non-goals
Video (2B), hotspot / offline networking (2C), re-encoding music, syncing
play counts back to Navidrome, multiple storage locations at once.

## Architecture (reuse what exists)

`boombox-library` already has: pins (`album|artist|playlist|track`, sources
`user|favorite|starred|rfid`), `reconcile_starred` (hourly), a
`DownloadQueue` + `download_track` into `<drive>/audio/`, `cache_state`
rows, eviction, a resolver that prefers `present` cache rows, and
`cache_poll` which adopts a drive found under `/media` carrying the
`.boombox-cache` marker. 2A changes *where* the cache lives and *how* the
queue behaves, and surfaces it in the LAN app.

### Internal storage
- New config `cache.internal_path` (default `/opt/boombox/storage/music`).
  `cache_poll` treats it as an **always-present drive**: created (0755,
  boombox user) and adopted automatically with the marker, preferred over
  `/media` drives. A drive under `/media` is still adopted only if the
  internal path is disabled (`internal_path: ""`) — the existing removable
  drive path keeps working as a fallback.
- `cache.reserve_bytes` default becomes **20 GiB** (was 1 GiB); the
  downloader reads it from config (today it hard-codes 1 GiB). A download
  that would cross the reserve is skipped with status `no_space` and the
  Storage page says so.
- Existing `cache_state` rows are untouched; on MarkII there are none.

### Download scheduler behaviour (in `DownloadQueue`)
- Concurrency ≤ `sync.max_concurrent_downloads` (already 2 on MarkII).
- **Pause while streaming**: if Mopidy is playing a stream-proxy URI
  (`/api/library/stream/`), don't start new downloads (in-flight finish).
- **Thermal backoff**: before each start read
  `/sys/class/thermal/thermal_zone0/temp`; ≥ 70 °C → wait 60 s and
  re-check (absent file → no backoff; hardware-optional rule).
- **Offline**: when Navidrome is unreachable, the queue idles (no retry
  storms) and resumes when the reachability check succeeds.
- Failed downloads keep `status = failed` with a reason; retried on the next
  hourly sync, never in a tight loop.

### Pins from the LAN app
New pair-token routes on `boombox-remote` (proxy to `boombox-library`,
same pattern as `/api/remote/home/*`):
- `POST /api/remote/home/keep {kind: "album"|"artist"|"playlist", id}` →
  `pin(source=user)` + enqueue its tracks.
- `DELETE /api/remote/home/keep {kind, id}` → `unpin(source=user)`; tracks
  no longer pinned by any source become evictable (files removed by the
  existing eviction when space is needed, or immediately via Storage
  "Remove").
- `GET /api/remote/home/{album|artist|playlist}/{id}` responses gain
  `keep: {state: "none"|"kept"|"starred", tracks_total, tracks_present}`
  and each track gains `offline: bool` (present on disk).

### Offline state in the app
- `GET /api/remote/home/status` → `{online: bool, internal_storage: bool}`
  (Navidrome reachability from `boombox-library` health).
- Music section: an **"Offline — showing kept music"** banner when
  `online` is false; browse lists and search come from the local catalog
  (already the case) but tiles/rows whose tracks aren't present are dimmed
  with "not offline", and play/queue sends only present tracks (existing
  resolver drops `offline_miss`).
- Album/artist/playlist pages get a **Keep offline** toggle with progress
  ("32 / 40 on the boombox").

### Storage page (LAN app, admin tier)
New admin section `#/storage` (sidebar + More, lock icon like Accounts),
backed by `boombox-setup` `/api/accounts/storage*` (admin session) which
proxies `boombox-library`:
- **Drive:** total / free / reserve, music bytes kept, kept track count.
- **Kept items:** each kept album / artist / playlist with size, progress,
  source (you / starred) and **Remove** (user pins only; starred items say
  "unstar in Navidrome to remove").
- **Downloads:** queue length, in-flight items, paused reason (streaming /
  hot / offline / low space), failed count with **Retry failed**.
- **Uploads:** the existing Files browser/uploader moves here from the
  household Files tab (Files tab then shows a pointer to Storage for
  admins; household users keep read-only browse).

## Error handling
- Every storage call degrades to a message with Retry; missing
  thermal file / Mopidy / Navidrome never crash the queue.
- Disk-full protection: reserve check before each download and a hard stop
  if `free < reserve` at any time.
- Keep/remove are idempotent; removing a kept album while its downloads run
  cancels the queued ones.

## Testing
- Python: internal-path adoption (created, marker, preferred over /media,
  disabled → /media fallback), reserve read from config, scheduler gates
  (streaming pause, thermal backoff with a fake sysfs file, offline idle,
  failed-retry cadence), keep/unkeep routes (pin/unpin/enqueue/cancel), the
  `keep` + `offline` fields, storage admin endpoints (token required).
- UI: Keep offline toggle + progress, offline banner + dimmed rows, play
  sends only present tracks, Storage page states (downloading, paused
  reasons, no space, remove, retry), uploads moved.
- On MarkII: keep an album → files appear under
  `/opt/boombox/storage/music/audio/`; block `music.coblr.io` (e.g.
  `/etc/hosts` → 127.0.0.1 temporarily) → the kept album still plays from
  the kiosk, the app shows Offline, an un-kept album is dimmed; unblock →
  back online. Starred albums download automatically.
