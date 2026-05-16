# Home library: Navidrome on Synology, synced cache on the boombox

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-05-16
**Owner:** jwc

## Goal

Make the boombox a portable, offline-capable client of a self-hosted music
library that lives on the user's Synology NAS. Navidrome (already installed
on the Synology, scanning a ~10k-album CD-rip collection) serves the
canonical catalog over the Subsonic API. A new `boombox-library` service on
the Pi maintains a local metadata catalog, downloads pinned content to a
USB-mounted cache drive, and opportunistically caches streamed playback into
the leftover space. The Pi's existing music sources (Spotify, USB ad-hoc,
Bluetooth, AirPlay) are unaffected. The `~/Music` SMB share / Mopidy-Local
"drop files on the Pi" workflow is retired in favor of the single canonical
library on the NAS.

The boombox is treated as **a portable device that may not always have
network**. Anything pinned or recently-streamed plays offline. The metadata
cache means browse and search work offline too — uncached items appear
greyed-out with a "Pin for next time" affordance.

## Non-goals (v1)

- **RFID tags.** A separate, dependent sub-project — design will follow.
  This spec lays the foundation (tag content will be a Subsonic ID; the
  `boombox-library` service is the natural API surface for RFID-triggered
  pin/play) but no RFID hardware, service, or UI is included here.
- **Video / movies.** Jellyfin keeps doing what it does. USB video flow
  unchanged. The user's existing "library uploader" workflow for video
  content is untouched. This service is **audio only**.
- **Spotify offline / sync.** Spotify content is DRM-locked and stays
  online-only. The cache mechanism does not apply to it.
- **Multi-user / per-listener history.** A single dedicated Navidrome user
  (recommended name: `boombox`) is used by the Pi. Scrobbling is out of
  scope; can be added later by enabling Navidrome's Last.fm integration —
  no work needed in this service.
- **Tag cleanup.** Real-world CD-rip libraries have artist-name
  inconsistencies ("AC/DC" / "ACDC" / "Ac/Dc" all present, "The B-52's" /
  "The B-52S" both present, untitled albums with whitespace-only names).
  Cleaning these is its own sub-project (beets / MusicBrainz Picard); the
  v1 UX must merely degrade gracefully under messy metadata — argues for
  **search-first defaults** in the Home Library browse, but no tag
  rewriting in this service.
- **Custom Mopidy backend.** Cached and streamed playback are routed via
  the existing `Mopidy-Local` and a new `Mopidy-Subsonic` backend. A
  resolver in `boombox-state` picks which URI to play. No custom Mopidy
  extension is written.
- **Auto-extend artist pins.** Pinning an artist snapshots its current
  albums. Newly-added albums by that artist are not auto-pinned. A
  separate "auto-pin new releases by pinned artists" feature can come
  later.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Home server | **Navidrome** on the Synology (already installed, scanning). Subsonic API on `:4533`. Music dir bind-mounted read-only from `/volume1/music` (already done). |
| Why Navidrome over Jellyfin | Purpose-built for music; lightweight; native Subsonic API means the boombox's existing Mopidy can consume it via a battle-tested backend. Jellyfin keeps doing video. |
| Auth model | Subsonic API username + password, sent via **token+salt** (md5(password+salt)) — password never crosses the wire. Recommend a dedicated Navidrome user (`boombox`) per device. Navidrome 0.60.3 is OpenSubsonic-capable; if app-password / scoped-credential support is available, use it. |
| Library role | **Replace, not augment.** Navidrome is the single source of truth. `~/Music` SMB share + Mopidy-Local-on-`~/Music` are retired. Mopidy-Local is repointed to the cache drive. |
| USB ad-hoc drives | **Self-contained.** Surfaces as its own browse root only while mounted. Doesn't merge into Home Library search/browse. Existing `boombox-usb-mount.sh` flow + Jellyfin USB video unchanged. |
| Cache vs ad-hoc disambiguation | **Marker file.** A USB drive with `.boombox-cache` at its root is the cache drive. Absent → ad-hoc browse root. UI offers to "adopt" a fresh drive on first mount. |
| Offline behavior | **First-class.** Pinned content plays offline. Streamed content opportunistically caches into leftover space and also plays offline. Metadata cache means browse + search work offline (uncached items greyed-out). |
| Cache priority ladder | 1. Reserved headroom (1 GB, untouchable) → 2. Pinned content (download on pin, evict only on explicit unpin) → 3. Streamed content (FIFO eviction when pinned pressure rises) → 4. Free space. |
| Pin model | **Hybrid.** Pin = "download and protect from eviction." Streamed playback also opportunistically caches (FIFO). Pinned bytes are protected from eviction; streamed bytes are first to go when more room is needed. |
| FIFO vs LRU | **FIFO** on streamed cache (oldest `downloaded_at` first). Simpler and more predictable than LRU; user does not perceive a meaningful difference for music. |
| Streamed-cache trigger | Fire on every cache-miss play (not gated on play-duration). On LAN the doubled bandwidth is negligible; trade-off favors "next time you reach for this, it's there." |
| Pin persistence vs Navidrome stars | Pins survive un-starring in Navidrome. Different model than Spotify ("remove from library → delete download"). A pin has a `source` (`user`, `starred`, future `rfid`) so reconciliation can be precise. Only `source='starred'` pins follow Navidrome's starred state. Turning off `starred_auto_pin` later does **not** retroactively unpin existing `source='starred'` pins — it only stops new starreds from being added. User-curated state is never surprise-deleted by a config flip. |
| Pin sidecar | Pin state is **mirrored to a JSON sidecar** on the cache drive (write-ahead). Catalog and `cache_state` can be rebuilt from Navidrome; pins are user-precious and cheap to protect. |
| Canonical URI | The Subsonic ID is the canonical track identity at every layer (UI, queues, future RFID tags, playlists). The `local:` URI is an implementation detail of the cache; never leaks above the resolver. |
| Sync cadence | **Hourly** background reconcile. Event-driven syncs (user "Sync now", Settings change, download complete) fire immediately regardless of timer. First-boot triggers an immediate full sync. |
| Source library config | URL + username + password, stored in `/etc/boombox/library.yml`. Password encrypted at rest. User-editable via Settings → Home Library, with a "Test Connection" button that validates before save. |
| Stale Mopidy playlists | Playlists referencing old `local:` URIs from `~/Music` are **surfaced, not auto-pruned**. A one-time scan on first boot post-upgrade reports unresolvable URIs; user prunes manually. |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Synology (LAN)                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Navidrome (Docker, Container Manager)                  │    │
│  │  • indexes /volume1/music (bind-mount, ro)              │    │
│  │  • Subsonic API on :4533                                │    │
│  │  • stores: catalog, starred items, playlists, users     │    │
│  └─────────────────────────────────────────────────────────┘    │
└────────────────────────────┬────────────────────────────────────┘
                             │ LAN (HTTP, Subsonic token+salt)
                             │
┌────────────────────────────┴────────────────────────────────────┐
│                     Pi 5 (the boombox)                          │
│                                                                 │
│  NEW: boombox-library service ── :6686 ── /api/library/*        │
│   • SQLite catalog cache (NVMe)                                 │
│   • pin-state DB (NVMe) + JSON sidecar (cache drive)            │
│   • file downloader → USB cache drive                           │
│   • eviction (FIFO streamed; protect pinned)                    │
│   • cache-drive detection via .boombox-cache marker             │
│                                                                 │
│  Mopidy backends:                                               │
│   • Mopidy-Subsonic  → streams from Navidrome           (NEW)   │
│   • Mopidy-Local     → plays from USB cache audio dir (REPOINT) │
│   • Mopidy-Spotify   → unchanged                                │
│                                                                 │
│  boombox-state (existing) gains a resolver:                     │
│   play(subsonic_id) → ask boombox-library "cached?"             │
│     → cached:           Mopidy plays local: URI                 │
│     → not cached+online: Mopidy plays subsonic: URI             │
│                           + async download fires (streamed cache)│
│     → not cached+offline: friendly "needs sync" error           │
│                                                                 │
│  Storage layout:                                                │
│   NVMe   → OS, services, SQLite (~50–200 MB at full catalog)    │
│   USB    → cache drive with .boombox-cache marker → audio files │
│             • audio/         (downloaded tracks, named by id)   │
│             • meta/pins.json (sidecar, write-ahead)             │
│             • tmp/           (in-flight downloads)              │
│   USB    → ad-hoc drives (no marker) → existing browse root     │
│                                                                 │
│  Retired:                                                       │
│   • SMB share on ~/Music                                        │
│   • Mopidy-Local pointed at ~/Music (repointed)                 │
└─────────────────────────────────────────────────────────────────┘
```

**Invariants:**

1. Catalog metadata always lives on the Pi (browse/search work offline).
2. Audio files live on the USB cache drive (NVMe stays free for OS/services).
3. The Subsonic ID is canonical at every layer.
4. Every failure leaves the rest of the boombox working — per the
   project-wide rule that hardware-coupled additions must run cleanly when
   any subset is absent or unwired.

**New surface:** one new port (`:6686`), one new service, one new Mopidy
backend, one repointed backend, two new Settings sections, one new browse
root, one persistent status chip. The rest of the system is untouched.

## Components

### The `boombox-library` service

**Responsibilities:**

1. Maintain a local metadata catalog mirroring Navidrome's Subsonic API
2. Track pin state (what should be available offline) and reconcile with
   Navidrome's `starred` set
3. Download pinned content to the USB cache drive via Subsonic `/download`
4. Run the streamed-cache downloader (async, on cache-miss plays)
5. Manage eviction (FIFO over streamed; pinned protected)
6. Expose an HTTP API consumed by the UI and `boombox-state`
7. Manage source library config (URL + credentials + test-connection)
8. Detect the USB cache drive by marker file and degrade gracefully when
   absent

**HTTP API (`:6686`):**

```
GET  /api/library/health          → service + nav reachable + cache mounted
GET  /api/library/source          → URL, username (NOT password)
PUT  /api/library/source          → set source; validates + persists
POST /api/library/source/test     → dry-run ping with proposed creds

GET  /api/library/browse?type=artists|albums|tracks|playlists&...
GET  /api/library/search?q=...    → spans local SQLite via FTS5
GET  /api/library/album/{id}      → album + tracks + pin/cache status
GET  /api/library/artist/{id}     → artist + albums
GET  /api/library/playlist/{id}   → playlist + tracks
GET  /api/library/track/{id}/playback → resolver result (uri, source, cache_status)
GET  /api/library/artwork/{id}    → proxies/caches Navidrome cover art

POST /api/library/pin             → {kind: album|artist|playlist|track, id, mode: pin|unpin}
GET  /api/library/pins            → pinned items + per-track sync state
POST /api/library/sync/run        → kick a full reconcile now
GET  /api/library/sync/status     → progress: queued/downloading/done

GET  /api/library/cache           → drive present? mount path? free space?
GET  /api/library/cache/stats     → capacity, headroom, pinned, streamed, free
POST /api/library/cache/adopt     → write .boombox-cache marker to a USB drive
POST /api/library/cache/clear     → nuke streamed cache (keeps pins)

POST /api/library/cache/streamed?id=<track_id>
                                   → fire-and-forget async cache trigger
                                     called by boombox-state on stream playback
```

**Config (`/etc/boombox/library.yml`):**

```yaml
source:
  url: http://192.168.1.223:4533     # user-editable from Settings UI
  username: boombox                   # recommended dedicated NV user
  password_encrypted: "..."           # encrypted at rest (key from machine-id)
sync:
  interval_seconds: 3600              # hourly background reconcile
  starred_auto_pin: true              # mirror Navidrome's starred set
  max_concurrent_downloads: 2
cache:
  marker_filename: ".boombox-cache"
  search_paths: [/media]              # where to look for cache drives
  reserve_bytes: 1073741824           # 1 GB filesystem headroom
```

**SQLite schema (sketch, on NVMe):**

```
artists(id PK, name, sort_name, album_count, art_id, updated_at)
albums(id PK, name, sort_name, artist_id, year, genre, song_count,
       duration_s, art_id, is_compilation, navidrome_starred, updated_at)
tracks(id PK, album_id, title, track_no, disc_no, duration_s, suffix,
       size_bytes, content_type, navidrome_starred, updated_at)
playlists(id PK, name, song_count, owner, public, updated_at)
playlist_tracks(playlist_id, track_id, position, PRIMARY KEY (playlist_id, position))

pins(target_kind, target_id, source enum[user|starred|rfid], added_at,
     PRIMARY KEY (target_kind, target_id))
cache_state(track_id PK, status enum[absent|queued|downloading|present|error],
            local_path, size_bytes, downloaded_at, error_message)

-- FTS5 virtual table for cross-entity search
search_index(content_type, id, title, body)
```

`navidrome_starred` columns mirror upstream state so the auto-pin
reconciler is trivial. Pinned-protection during eviction is derived at
query time (or computed-and-cached as a `pinned_protected` boolean
refreshed on pin/unpin events).

**USB cache drive detection:**

- Poll loop (every few seconds) scans `cache.search_paths` (default
  `/media`) for mounted drives.
- For each: stat `<mount>/.boombox-cache`. If present → adopt as cache
  drive (create `audio/`, `meta/`, `tmp/` subdirs if missing; load
  `meta/pins.json` if present; mark `cache_present=true`).
- Exactly one cache drive is active at a time. A second-with-marker is
  treated as ad-hoc with a warning.
- First-time adoption: UI prompts when a fresh (unmarkered) drive mounts
  and no cache drive is currently active. `POST /cache/adopt` writes the
  marker.
- Drive yanked at runtime: `cache_present=false`; queued/in-flight
  downloads pause; current Mopidy playback errors; UI notifies. Re-mount
  resumes.

**Process lifecycle:** user systemd unit `boombox-library.service`,
matching the existing eight `boombox-*` user services. Restart on failure.
Network-up dependency but does NOT block on Navidrome reachability.

### Mopidy backends

- **Mopidy-Subsonic** (new) — `pip install` pinned version. Configured by
  the boombox-library service writing to `mopidy.conf` whenever source
  config changes (URL/user/pass). Service reloads Mopidy after writes.
- **Mopidy-Local** (repointed) — `media_dir` changes from `~/Music` to
  the fixed path `/var/lib/boombox/cache-mount/audio/`.

#### Cache-mount symlink (first-class concept)

`/var/lib/boombox/cache-mount` is a symlink maintained by
`boombox-library`. Its target points at the root of the currently-adopted
cache drive (e.g., `/media/usb-music`). The audio directory at
`cache-mount/audio/` is therefore always Mopidy-Local's `media_dir` —
Mopidy never needs to be reconfigured when a drive is swapped.

- **On adopt:** boombox-library writes/refreshes the symlink, ensures
  `audio/`, `meta/`, `tmp/` exist under it, then triggers a Mopidy-Local
  rescan so newly-visible files appear immediately.
- **On detach:** boombox-library removes the symlink. Mopidy-Local's
  `media_dir` becomes nonexistent — Mopidy treats it as empty, no crash.
- **No drive ever adopted:** symlink simply doesn't exist; same outcome.

This keeps the swap atomic and avoids Mopidy config rewrites on every
drive change.

### `boombox-state` resolver

Existing `boombox-state` service gains a thin resolver, called on every
play request:

```python
def resolve_playback(subsonic_id: str) -> PlaybackResolution:
    r = requests.get(f"http://localhost:6686/api/library/track/{id}/playback")
    # r.json() = { uri: str|null, source: "cache"|"stream"|"offline_miss",
    #              cache_status: "absent"|"present"|... }

    if r.source == "stream":
        # fire-and-forget cache trigger
        requests.post(f"http://localhost:6686/api/library/cache/streamed?id={id}")

    if r.uri is None:
        return error("not synced and library is offline")

    return mopidy_play(r.uri)
```

The resolver is the only place the `local:` vs `subsonic:` distinction is
made. All callers (UI, RFID later) pass Subsonic IDs.

## Data flows

### A. Catalog metadata sync (background, hourly)

```
Timer fires (or event-driven: settings change, manual "Sync now")
├─ Subsonic ping → reachable?
│   └─ No → no-op; UI shows "Library unreachable, last sync HH:MM"
├─ Fetch deltas: getArtists, getAlbumList2, getStarred2, getPlaylists
│   └─ Upsert changed rows in SQLite (compare updated_at / version)
├─ Reconcile starred → pins
│   └─ Newly starred: INSERT pin(source='starred') if not exists
│   └─ Un-starred: remove pin where source='starred' only
│                  (user/rfid pins survive)
└─ If any new pins surfaced → enqueue downloads (queued state)
```

### B. Pin → download

```
UI taps pin button
└─ POST /api/library/pin {kind, id, mode: pin}
    ├─ Compute byte cost (sum of constituent tracks' size_bytes)
    ├─ Check fit: pinned_pool + new_size ≤ (capacity − headroom)?
    │   ├─ Yes → INSERT pin row; enqueue downloads
    │   └─ No  → evict streamed FIFO until fits → enqueue
    │           └─ Still no fit → 507 "cache full"; UI suggests largest
    │             pinned items to unpin
    └─ Return 200 with sync job id; write pins.json sidecar

Background downloader (max_concurrent_downloads workers):
  For each queued track:
    GET /rest/download.view?id=<track_id> (Subsonic token+salt)
    → stream to <cache>/tmp/<track_id>.part
    → on complete: atomic rename to audio/<track_id>.<suffix>
    → UPDATE cache_state SET status='present', downloaded_at=now,
                              local_path, size_bytes
    → on failure: status='error', error_message, backoff schedule
```

Unpin is the inverse: remove pin row → write pins.json. **Does NOT
delete the file** — track becomes streamed-cache, subject to FIFO
eviction. Lazy delete is friendlier than destructive unpin (if you
re-pin within minutes, the file is still there).

### C. Playback resolution (the hot path)

```
User (or future RFID tap) selects track via Subsonic ID
└─ boombox-state.play(subsonic_id) called
    ├─ resolve = GET /api/library/track/<id>/playback
    │   Returns {uri, source, cache_status}
    │     cache_status='present' + reachable=*       → uri="local:<path>",   source="cache"
    │     cache_status≠'present' + reachable=true    → uri="subsonic:<id>", source="stream"
    │     cache_status≠'present' + reachable=false   → uri=null,             source="offline_miss"
    │
    ├─ source="stream" → POST /api/library/cache/streamed?id=<id>
    │                    (fire-and-forget; downloader picks it up;
    │                     does NOT block playback)
    │
    ├─ source ∈ {"cache","stream"} → mopidy.tracklist.add(uri); mopidy.playback.play()
    │
    └─ source="offline_miss"
        → return user-facing error "Can't play 'X' — not synced and library is offline"
          UI shows greyed-out item with "Pin for next time" CTA
          (CTA disabled while offline; enables on reconnect)
```

### D. Browse / search

Local SQLite is the only source — equally fast online and offline.

```
Browse (any state):
  UI → GET /api/library/browse?type=...
  Service → SQLite query → result list with
            pinned: bool + cache_status: enum on each item
  UI renders with badges:
    📌 pinned · ⬇ cached (streamed) · ⚡ streaming now · ☁ remote-only
  Offline + cache_status ≠ 'present' items → greyed-out, no play button,
                                              "Pin for next time" CTA

Search (any state):
  UI → GET /api/library/search?q=...
  Service → FTS5 against artist.name + album.name + track.title
  Results grouped (Home Library / Spotify / USB-if-mounted)
  Default order: Home Library first
```

### E. Streamed-cache eviction

```
Triggered by: pin request that doesn't fit, or periodic sweep when free < 1 GB

candidates = SELECT cached tracks WHERE not pinned ORDER BY downloaded_at ASC
need_bytes = required - currently_free
while need_bytes > 0 and candidates not empty:
    pop oldest streamed → rm file → UPDATE cache_state status='absent'
    need_bytes -= track.size_bytes
if need_bytes > 0:
    return ENOSPC to caller (HTTP 507)
```

Eviction never touches pinned content. Period.

## UI surface

All new work targets the React kiosk UI under `ui/`. The LAN-authenticated
mirror on `:8090` picks up the same code. The PWA (`remote-ui/`) consumes
the same `/api/library/*` endpoints incrementally (parity is a follow-up).

### Settings → Home Library (new section)

```
┌─ Home Library ──────────────────────────────────────┐
│  Source URL    [ http://192.168.1.223:4533       ] │
│  Username      [ boombox                          ] │
│  Password      [ ●●●●●●●●●                        ] │
│                                                     │
│  Status        ● Connected — last sync 12 min ago  │
│  Catalog       3961 artists · 6234 albums          │
│                                                     │
│  [ Test Connection ]   [ Sync now ]                 │
└─────────────────────────────────────────────────────┘
```

Save validates against `/source/test` first; refuses if creds fail.
Disconnected state shows "● Library unreachable — last successful sync
HH:MM" with both actions enabled.

### Settings → Offline Cache (new section)

```
┌─ Offline Cache ─────────────────────────────────────┐
│  Drive   /media/usb-music   (label: BOOMBOX_CACHE)  │
│                                                     │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  ■ reserved 1 GB   ■ pinned 80 GB   ■ streamed 45 GB│
│  ░ free 74 GB                                       │
│                                                     │
│  Total 200 GB · 74 GB free · 125 GB used            │
│                                                     │
│  [ Clear streamed cache ]                           │
└─────────────────────────────────────────────────────┘
```

Stacked bar is CSS-only (no chart library). Clear-streamed nukes only
FIFO content, never pinned.

### Home Library browse root

A new tile in the source landing, alongside Spotify / Bluetooth / etc.:

```
Home Library
├─ Recently Added       (from catalog metadata)
├─ Starred              (Navidrome starred ∪ boombox-pinned)
├─ Artists              (search-first given tag mess)
├─ Albums
├─ Playlists
└─ Cached only          (filter: cache_status='present')
```

"Cached only" is the offline-portable view — one tap to "what can I
actually play right now offline?" Lives top-level rather than buried as
a filter.

### Pin affordance

Pin button (📌 outline → filled) on album, artist, and playlist detail
pages. Track-level pin is **omitted** by default — rare need, clutters
rows.

States:

| State | Icon |
|---|---|
| Unpinned | 📌 outline |
| Pinned, downloading | 📌 filled + progress ring |
| Pinned, fully cached | 📌 filled + small ✓ |
| Pinned, error | 📌 filled + small ⚠ (tap → retry/details) |

Long-press → "Manage pin": pin source (user/starred/rfid), downloaded
date, total size, unpin button.

### Status badges (lists + Now Playing)

| Glyph | Meaning |
|---|---|
| 📌 | Pinned (implies downloaded) |
| ⬇ | Cached from streamed-cache (not pinned) |
| ⚡ | Currently streaming this track |
| ☁ | Catalog-only — no local copy |
| (dimmed row) | Offline + catalog-only — can't play |

Offline-miss items: play button replaced with **[+ Pin for next time]**,
disabled while offline, enabled while online.

Now Playing carries a source badge — ⬇ Cache / ⚡ Streaming / 🎵 Spotify /
🎵 USB / 📱 AirPlay — so the user can see what's eating bandwidth.

### Search — grouped results

```
Search: "ac/dc"

▼ Home Library (34 albums, 312 tracks)
   [list with badges]

▼ Spotify (8 albums)
   [Spotify rows]

▼ USB DRIVE (2 albums)    [only when USB ad-hoc mounted]
   [USB rows]
```

Each group independently scrollable. Default order: Home Library first.

### Sync indicator (persistent chrome)

Small chip in the kiosk UI header:

| Color | State |
|---|---|
| Green | Online, up-to-date |
| Amber pulse | Sync in progress |
| Blue | Online, idle, sync due in N min |
| Grey | Offline (library unreachable) |
| Red | Cache drive missing or sync error |

Tap → bottom-sheet: last sync time, items downloading, queue depth,
"Sync now" button.

### Cache drive adoption flow

```
USB drive mounts.
Marker file at <mount>/.boombox-cache present?
├─ Yes → silently adopt (toast: "Cache drive online")
└─ No
    ├─ Already have a cache drive adopted?
    │   └─ Yes → treat as ad-hoc browse root (existing flow, no prompt)
    └─ No
        └─ Modal:
           "New drive detected — Brand: SanDisk, Free: 230 GB
            Use this as the boombox offline cache?
            [ Yes, use for cache ]  [ No, browse as media ]"
           Yes → POST /api/library/cache/adopt → marker written → adopted
```

One-shot only on fresh drives.

### PWA (remote-ui) parity

Phased — the same `/api/library/*` endpoints support all of these:

- Phase 1: browse + search + queue (read-only against the boombox's library)
- Phase 2: pin/unpin from phone
- Phase 3: cache stats visibility

Tracked as follow-up; not in this spec's scope.

## Failure modes

Every failure listed leaves the rest of the boombox working
(Bluetooth / USB / AirPlay / Spotify / Jellyfin) — per the project-wide
"optional / independently-disabled features" rule.

| Failure | Behavior | Mitigation |
|---|---|---|
| Navidrome unreachable (short/long) | Sync no-ops; cached playback unaffected; streaming fails | UI status chip turns grey; exponential backoff retry; browse from local SQLite |
| Cache drive missing at boot | Service starts; `cache_present=false` | UI: "● Cache drive offline"; streaming still works; pin requests queue (don't error) until drive appears |
| Cache drive yanked during playback | Mopidy errors on current track; queued `local:` tracks fail at their turn | boombox-state catches → user-facing "Cache drive removed"; pause; queue is left intact (re-mounting the drive lets it resume); subsequent `local:` plays fail until remount; streaming-only items still work if Navidrome reachable |
| Cache drive corrupted | Treated as missing | Recovery: reformat → re-write marker → full re-pin re-download (catalog on NVMe survives) |
| Cache full / pin doesn't fit | 507 with byte deficit | UI: "Need X GB more — unpin Y?" with suggestions sorted by size |
| Download fails mid-transfer | `.part` file deleted; status='error' | Backoff retry on next sync; after N retries surface to user |
| Catalog mismatch (track gone from NAS, still cached) | Orphan stays | Lazy: orphan remains playable, gets evicted naturally; sync logs the divergence |
| Subsonic auth fails | Sync errors | UI: "● Library authentication failed" + Edit Source CTA; cached content plays fine |
| SQLite corruption | DB unreadable | Startup `PRAGMA integrity_check`; on fail, backup + rebuild from Navidrome. **Pins survive via JSON sidecar on cache drive.** |
| NVMe full | Catalog DB writes fail | UI: "● Cannot update catalog: NVMe full" + cleanup CTA; cached playback unaffected |
| Boombox boots offline + no cache drive | Both flags false | Home Library tile shows "Connect to Wi-Fi or attach cache drive"; other sources unaffected |

## Migration / install plan

One-time install (idempotent — fits the existing installer pattern):

1. **Mopidy backend changes:**
   - `pip install Mopidy-Subsonic` (version pinned)
   - Add `[subsonic]` block to `/etc/mopidy/mopidy.conf` with placeholder
     URL/creds (boombox-library overwrites when user saves Settings)
   - Repoint `[local] media_dir` from `~/Music` to
     `/var/lib/boombox/cache-mount/audio/` (symlink updated by
     boombox-library on adopt/detach)

2. **New service:**
   - Install `boombox-library.service` (user systemd unit)
   - Create `/etc/boombox/library.yml` with defaults
   - Catalog DB dir under existing service data path

3. **nginx:**
   - `location /api/library/ { proxy_pass http://127.0.0.1:6686; }`
   - Reload nginx

4. **Retire SMB / `~/Music` workflow:**
   - Remove smbd share definition for `~/Music`
   - Leave existing files in `~/Music` (user migrates to Synology
     manually if desired)
   - CHANGELOG documents the deprecation

5. **Stale Mopidy playlists:**
   - One-time scan on first boot post-upgrade; report unresolvable
     `local:` URIs from `~/Music`; user prunes manually

6. **First-run UX:**
   - Source unconfigured → kiosk pushes Settings → Home Library to front
   - Source configured but no cache drive → toast "Plug in a USB drive
     to enable offline music"
   - First sync shows progress modal

7. **Documentation:**
   - README services table (new line: `boombox-library | 6686`)
   - New `docs/HOME-LIBRARY.md`: setup, troubleshooting, Subsonic compat
     notes, "creating a dedicated Navidrome user"
   - Update `docs/SERVICES.md` and `docs/ARCHITECTURE.md`
   - CHANGELOG

## Testing strategy

**Unit (pytest, isolated):**

- Subsonic API client — mocked HTTP, token+salt construction, error paths
  (timeout / 401 / 5xx / malformed JSON)
- Pin/unpin state transitions; cascade (album pin → track pins; artist
  pin → snapshot of current albums)
- Cache-fit math (exact fit, headroom edges, zero-byte cache,
  evict-everything-and-still-fail)
- Eviction algorithm — FIFO ordering, pinned-protection invariant under
  random pin/unpin sequences
- Reconciliation — Navidrome `starred` ↔ local pins, source attribution
  preserved across un-star
- SQLite migrations forward; pin sidecar JSON round-trips

**Integration (against the dev Navidrome at 192.168.1.223:4533):**

- Full sync from empty DB → catalog counts match Navidrome
- Pin a small album → file appears on cache → Mopidy plays via `local:`
- Same flow with Navidrome stopped → cached playback continues,
  streaming-only items error gracefully
- Eject cache drive mid-sync → service stays up, downloads pause, resume
  on remount
- Settings → change source URL → reconnect + resync against new server
- Concurrent download + streaming playback → no playback stutter

**Manual verification (touchscreen + LAN web + future PWA):**

- First-time setup wizard flow
- Pin button visual states (4 states + long-press menu)
- Sync indicator states (green / amber / blue / grey / red)
- Cache drive adoption flow on a real fresh USB drive
- "Pin for next time" CTA on offline-miss item
- Search results grouping (Home Library / Spotify / USB when mounted)
- Now Playing source badge across cache / stream / Spotify / USB /
  AirPlay

**Failure injection:**

- Pull Wi-Fi during sync → recovers cleanly when restored
- Pull cache drive during play → graceful error, no Mopidy crash
- Corrupt SQLite catalog → rebuild from Navidrome on next boot, pins
  survive (sidecar)

**Scale / perf (not gating but checked on Pi 5):**

- Browse 6–10k album list — react-window virtualization smooth
- FTS5 search latency on full catalog (target <100 ms)
- Pinning a 100-album artist → background download doesn't block UI or
  playback

## Open questions for planning

These are intentional unknowns to verify during implementation planning,
not blockers:

1. **Mopidy-Subsonic version + Navidrome 0.60.3 compatibility.** The
   extension is mature but verify the specific version pairing — some
   Navidrome behaviors (e.g., compilation handling, multi-artist
   credits) may have changed. Pick a version, run the integration suite
   above, pin it.
2. **OpenSubsonic app-password mechanism.** Navidrome 0.60.3 reports
   `openSubsonic: true`. Determine whether scoped/app-password credential
   creation is available via API or web UI; if so, prefer it over
   reusing real user creds.
3. **Existing config-encryption pattern.** Check whether other services
   in the project already encrypt at-rest creds (Spotify? Jellyfin?) and
   reuse the same approach. Otherwise: `cryptography` library with a key
   derived from `/etc/machine-id`.
4. **Cache mount-path conventions.** The test drive is at
   `/media/usb-music/`. Existing `boombox-usb-mount.sh` may pick mount
   names automatically. Coordinate with the existing USB handling so
   cache drive paths are stable across reboots and don't collide with
   ad-hoc drives.
5. **Mopidy reload on Settings change.** Writing `mopidy.conf` requires
   a Mopidy restart. Confirm this can be done without disrupting an
   active playback (might require a "pending source change, restart on
   next idle" flow rather than immediate reload).
6. **Artwork caching strategy.** `getCoverArt` responses are cacheable
   but can be large. Decide: proxy-through (boombox-library serves
   thumbnails directly, hits Navidrome on first request and caches on
   disk) vs. let the UI hit Navidrome directly (simpler, but breaks
   offline). Lean: proxy-through with on-disk LRU.
7. **Cache drive filesystem.** ext4 is the obvious choice (POSIX
   semantics, no FAT32 4 GB limit). Document this in the setup guide;
   adoption flow should detect and warn on FAT32.

## Future work (explicit follow-ups, separate specs)

- **RFID tag layer** (`boombox-rfid` service + tag programming flow + UI).
  Tag URIs reference Subsonic IDs; tap triggers play via the resolver;
  a tap that resolves to uncached content while online triggers a pin
  (auto-sync for next time).
- **Tag cleanup utility** (beets / Picard integration) for the existing
  CD-rip mess.
- **Auto-extend artist pins** for new releases by pinned artists.
- **Scrobbling / per-user listening history** via Navidrome's existing
  integrations.
- **PWA Phase 2/3 parity** (pin from phone, cache stats visibility).
- **Spotify-aware caching** — when the same album exists in both Spotify
  and the home library, prefer the local copy for offline.
