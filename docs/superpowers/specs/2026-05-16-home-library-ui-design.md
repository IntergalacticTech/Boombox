# Home library Phase 2: touchscreen UI

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-05-16
**Owner:** jwc

## Goal

Bring the Phase 1 backend service to life on the touchscreen kiosk UI. Users
configure the Navidrome source from Settings instead of `curl`, browse the
home library through the existing `LibraryDrawer`, pin albums/artists/
playlists for offline play, and see live status (sync state, cache fullness,
playback source) through dedicated affordances in the existing chrome.

Builds entirely on top of the Phase 1 backend at `:6687`. No backend
features added other than small surface extensions noted below (a
`FAVORITE` pin source, optional `source` field on `/api/library/pin`,
plus the three small endpoints the UI calls: `/cache/adopt`,
`/cache/streamed`, `/cache/clear`).

This is **Phase 2 (touchscreen UI)** of a 3-phase milestone. PWA-remote
parity, migration of the `~/Music` SMB workflow, install-time bug fixes,
and docs come in Phase 3.

## Non-goals (v2)

- **PWA remote-ui parity.** The phone remote stays read-only against
  Mopidy until Phase 3.
- **Retire `~/Music` SMB share.** Stays parallel for now. Phase 3.
- **Tag cleanup utility.** Real library has known artist-name chaos
  ("AC/DC" / "ACDC" / "Ac/Dc"). UI must degrade gracefully under messy
  metadata — argues for search-first defaults — but no rewriting here.
- **Custom Home Library browse model.** No tile-art grids, no
  mood-based exploration, no collector-tier visual treatment. We reuse
  `LibraryDrawer`'s list-with-drilldown. Visual design lifts can come
  later as their own spec.
- **Track-level pin button.** Pin lives on album / artist / playlist
  detail pages only. Adding it to track rows clutters the dense
  scrollable list with rare-need affordance.
- **Cache budget enforcement UI.** Phase 1's eviction runs
  automatically. UI surfaces cache stats and lets the user manually
  unpin or clear streamed cache — no separate "set hard cap"
  configuration. That can come later if real-world use needs it.
- **Install-time bug fixes for existing Pis.** mopidy.conf perms,
  library.yml perms, and `/etc/boombox` + `/etc/mopidy` directory
  ownership currently require manual fix on upgrade-from-pre-Phase-1
  Pis. Real fix is an `install/upgrade-from-pre-phase1.sh` script in
  Phase 3.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Where does Home Library live in the existing UI? | **New root inside `LibraryDrawer`.** Add to `ROOTS` alongside Albums / Artists / Tracks. Browse calls `/api/library/browse` instead of `core.library.browse`. Reuses drilldown chrome, search bar, breadcrumbs. |
| Pin button vs Favorite button | **Two buttons (coexist), with auto-pin on favorite.** Heart icon and pin icon both visible on Home Library rows. Favoriting also creates a backend pin with `source='favorite'`; unfavoriting removes that pin (only if its source is `favorite`). Explicit pin is `source='user'`. Stronger sources override weaker ones on update (USER > FAVORITE > STARRED). |
| Pin button on track rows | **No.** Album/artist/playlist detail only. Reduces row clutter for the most common browse activity. |
| Settings architecture | **Two new sub-panels in `SettingsDrawer`** mirroring `UpdatesPanel.tsx`: `LibraryPanel.tsx` (source config) + `CachePanel.tsx` (cache stats). Not bound by the 60 px collapsed-row rule; panels expand as needed like Updates does. |
| Sync indicator | **Header chrome chip** in `ChromeButtons.tsx` (green / amber / blue / grey / red). Tap → opens SettingsDrawer scrolled to LibraryPanel. |
| Cache adoption flow | **`CacheAdoptOverlay.tsx` via the existing `OverlayRoot` mechanism.** Triggered by a small polling effect that watches `/api/library/cache` for "new unadopted drive detected, no cache drive currently adopted." Existing `SourceInstructionOverlay` is the model. |
| Now Playing source badge | **Small icon in `NowPlayingBar.tsx`** showing ⬇ Cache / ⚡ Stream / 🎵 Spotify / 🎵 USB / 📱 AirPlay / 🎙 BT. Resolved from current track URI + cache_state lookup. |
| Search results grouping | **Three groups** when the user types in `LibraryDrawer`'s search bar: Home Library / Spotify / USB-when-mounted. Each collapsible. Default order: Home Library first when its root is active; Mopidy aggregation continues to feed Spotify+Local results. |
| Status badges on rows | **Inline glyph** on each track row: 📌 (pinned) · ⬇ (cached, streamed) · ⚡ (currently streaming) · ☁ (catalog-only) · *dimmed row* (offline + catalog-only). Offline-miss rows replace the play button with `[+ Pin for next time]`, disabled while offline. |
| "Cached only" view | **Top-level entry in the Home Library root** so the offline-portable mode is one tap away. Filter: `cache_status='present'` items only. |
| Component library | **Plain CSS + React 19**, matching the rest of `ui/`. No new dependencies. |
| State sharing | **`homeLibrary.ts`** — module-level pub/sub on the lines of `favorites.ts` (Set-based, persistent only through API not localStorage). Subscribers re-render when pin state changes anywhere in the app. |

## Component map

### New files

| File | Responsibility |
|---|---|
| `ui/src/lib/libraryApi.ts` | Typed client for `/api/library/*` (mirrors `updaterApi.ts`) |
| `ui/src/lib/LibraryPanel.tsx` | Home Library section in SettingsDrawer: source form, Test/Save, status, Sync Now |
| `ui/src/lib/CachePanel.tsx` | Offline Cache section: stacked bar, drive info, Clear Streamed |
| `ui/src/lib/PinButton.tsx` | Reusable pin icon with the 4 visual states; long-press → manage sheet |
| `ui/src/lib/StatusBadge.tsx` | Small inline glyph for track rows (presentational only) |
| `ui/src/lib/SyncIndicator.tsx` | Header chrome chip with status color + tap-to-open |
| `ui/src/lib/homeLibrary.ts` | Pub/sub for pin state and last-sync time; subscribers re-render on change |
| `ui/src/overlays/CacheAdoptOverlay.tsx` | Modal prompting the user to adopt a fresh USB drive |

### Modified files

| File | Change |
|---|---|
| `ui/src/lib/LibraryDrawer.tsx` | Adds "Home Library" entry to `ROOTS`; when active, `browse()` retargets to `libraryApi.browse`; rows render `<PinButton/>` + `<StatusBadge/>`; `[+ Pin for next time]` CTA on offline-miss |
| `ui/src/lib/SettingsDrawer.tsx` | Mounts `<LibraryPanel/>` and `<CachePanel/>` |
| `ui/src/lib/ChromeButtons.tsx` | Adds `<SyncIndicator/>` |
| `ui/src/lib/NowPlayingBar.tsx` | Adds source badge to the right of the title |
| `ui/src/lib/favorites.ts` | `toggleFavorite()` for Home Library URIs (subsonic IDs) also calls `libraryApi.pin/unpin` with `source: 'favorite'` |

### Backend extensions

Small additions to Phase 1; no schema migration:

| File | Change |
|---|---|
| `services/boombox_library/models.py` | Add `PinSource.FAVORITE` enum value |
| `services/boombox_library/pins.py` | `unpin(conn, kind, target_id, source=None)` accepts optional source filter so removing a favorite-driven pin doesn't nuke a parallel user-driven pin; precedence logic in `pin()` so stronger sources override weaker ones on UPSERT |
| `services/boombox_library/api.py` | `_pin` accepts optional `source` field in request body (defaults `'user'` for backwards compat); add `POST /api/library/cache/adopt` (path arg → writes marker via `cache_drive.adopt_drive`); add `POST /api/library/cache/streamed?id=` (UI fires after stream playback starts; enqueues for streamed-cache download); add `POST /api/library/cache/clear` (CachePanel button; deletes all streamed cache rows + files) |

**Source precedence (already in spec but worth being explicit):**

- Pin INSERT via `ON CONFLICT(target_kind, target_id) DO UPDATE SET source = CASE ...`:
  - If `pin(USER)` is called over an existing FAVORITE/STARRED/RFID pin → upgrade source to USER.
  - If `pin(FAVORITE)` is called over an existing USER pin → leave source as USER.
  - If `pin(STARRED)` is called over any existing pin → no source change.
- Unpin with source filter: `DELETE FROM pins WHERE target_kind=? AND target_id=? AND source=?` — only removes when the requested source matches. Unpin without filter is the existing "force delete" path used by the explicit pin button.

## Per-component detail

### `libraryApi.ts`

Mirrors `updaterApi.ts`:

```ts
export type SourceConfig = { url: string; username: string };  // password NEVER round-tripped
export type Health = {
  service_version: string;
  navidrome_reachable: boolean;
  cache_present: boolean;
  cache_mount: string | null;
};
export type BrowseType = "artists" | "albums" | "playlists";
export type BrowseItem = { id: string; name: string; /* type-specific fields */ };
export type SearchResult = { content_type: "artist" | "album" | "track"; id: string; title: string };
export type PinKind = "album" | "artist" | "playlist" | "track";
export type PinMode = "pin" | "unpin";
export type PinSource = "user" | "favorite";   // STARRED/RFID are backend-internal
export type CacheStats = {
  present: boolean; mount_path: string | null;
  capacity: number; free: number;
  pinned_bytes: number; streamed_bytes: number; reserved: number;
};
export type PlaybackResolution = {
  source: "cache" | "stream" | "offline_miss";
  uri: string | null;
  cache_status: "present" | "absent" | "queued" | "downloading" | "error";
};

export async function getHealth(): Promise<Health>;
export async function getSource(): Promise<SourceConfig>;
export async function putSource(s: SourceConfig & { password: string }): Promise<{ ok: boolean; error?: string }>;
export async function testSource(s: SourceConfig & { password: string }): Promise<{ ok: boolean; error?: string }>;
export async function browse(type: BrowseType): Promise<BrowseItem[]>;
export async function search(q: string): Promise<SearchResult[]>;
export async function getAlbum(id: string): Promise<...>;
export async function getArtist(id: string): Promise<...>;
export async function getPlaylist(id: string): Promise<...>;
export async function getResolver(trackId: string): Promise<PlaybackResolution>;
export async function pin(kind: PinKind, id: string, source?: PinSource): Promise<void>;
export async function unpin(kind: PinKind, id: string, source?: PinSource): Promise<void>;
export async function runSync(): Promise<void>;
export async function getCacheStats(): Promise<CacheStats>;
export async function adoptCache(mountPath: string): Promise<void>;
export async function clearStreamedCache(): Promise<void>;
export async function triggerStreamedCacheDownload(trackId: string): Promise<void>;
```

### `LibraryPanel.tsx`

Sits inside `SettingsDrawer`. Shape:

```
┌─ Home Library ──────────────────────────────────────────┐
│  Source URL    [ http://192.168.1.223:4533           ]  │
│  Username      [ boombox                              ]  │
│  Password      [ ●●●●●●●●●                            ]  │
│                                                          │
│  Status        ● Connected — last sync 12 min ago       │
│  Catalog       3,961 artists · 6,234 albums              │
│                                                          │
│  [ Test ]  [ Save ]  [ Sync now ]                        │
└──────────────────────────────────────────────────────────┘
```

- Polls `getHealth()` every 5 s while panel is mounted (matches
  `UpdatesPanel` cadence).
- "Test" runs `testSource` against the in-form values without saving.
  Inline result toast: ✓ Connected / ✗ <reason>.
- "Save" runs `putSource` (which itself validates server-side); on
  success, triggers a sync and refreshes status. Disabled while
  `Test`/`Save` are in flight.
- Password field is plain `<input type="password">` — no special
  treatment; never echoed back on GET; cleared when leaving the panel.
- Disconnected state shows `● Library unreachable — last successful
  sync HH:MM`; Test/Save still enabled so the user can retry.

### `CachePanel.tsx`

```
┌─ Offline Cache ─────────────────────────────────────────┐
│  Drive   /media/usb-music   (label: BOOMBOX_CACHE)      │
│                                                          │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  ■ reserved 1 GB   ■ pinned 80 GB   ■ streamed 45 GB     │
│  ░ free 74 GB                                            │
│                                                          │
│  Total 200 GB · 74 GB free · 125 GB used                 │
│                                                          │
│  [ Clear streamed cache ]                                │
└──────────────────────────────────────────────────────────┘
```

Stacked bar is pure CSS — four `<div>`s with computed width %, no
chart library. Numbers update via `getCacheStats()` poll (5 s while
panel mounted, 30 s otherwise). Clear-streamed calls
`clearStreamedCache()`, then refreshes stats.

If `present=false`: panel shows "● Cache drive offline — plug in a
USB drive to enable downloads" with the bar greyed out.

### `LibraryDrawer.tsx` modifications

Add to `ROOTS`:

```ts
{ uri: "home:root", name: "Home Library", type: "directory" }
```

When `here.uri` starts with `home:`, route through `libraryApi`
instead of `library.browse`:

```ts
async function browseHomeLibrary(uri: string): Promise<Ref[]> {
  if (uri === "home:root") return [
    { uri: "home:recently-added", name: "Recently Added", type: "directory" },
    { uri: "home:starred", name: "Starred", type: "directory" },
    { uri: "home:artists", name: "Artists", type: "directory" },
    { uri: "home:albums", name: "Albums", type: "directory" },
    { uri: "home:playlists", name: "Playlists", type: "directory" },
    { uri: "home:cached-only", name: "Cached only", type: "directory" },
  ];
  if (uri === "home:artists") {
    const items = await libraryApi.browse("artists");
    return items.map(a => ({ uri: `home:artist:${a.id}`, name: a.name, type: "artist" }));
  }
  // ...similar for albums, playlists, etc.
}
```

Search bar, when Home Library root is active, calls
`libraryApi.search(q)` in parallel with the existing
`library.search(q)` and merges results into the three groups
(Home Library / Spotify / USB-when-mounted).

Pin button + Favorite button render inline on every Home Library row
(album/artist/playlist detail pages and the breadcrumb-pinning at the
top of a drilldown). Track-level rows show only the favorite heart.

### `PinButton.tsx`

```tsx
type Props = {
  kind: PinKind;
  id: string;
  state: "unpinned" | "downloading" | "cached" | "error";
  progress?: number;     // 0–1, used in downloading state
  onTogglePin: () => void;
  onLongPress?: () => void;  // → manage-pin sheet
};
```

Renders an SVG pin icon (filled / outline) plus an overlay ring for
downloading progress, ✓ for cached, ⚠ for error. Touch targets ≥
44 px for the 5″ kiosk. Long-press opens a small `<dialog>` showing
source (user/favorite/starred/rfid), downloaded date, size, and an
explicit unpin button.

### `StatusBadge.tsx`

Pure presentational. Takes `cacheStatus: 'present'|'absent'|...` and
`isCurrentTrack: boolean` (for the ⚡ streaming-now state). Picks the
glyph and renders it in a 20×20 inline span. Memoizable.

### `SyncIndicator.tsx`

```tsx
type SyncState = "online_idle" | "syncing" | "online_due" | "offline" | "error";
```

A 16×16 dot in the chrome with a tooltip on hover (touchscreen
long-press alternative). Tap → fires a custom event that
`SettingsDrawer` listens for to auto-open scrolled to the Library
panel.

Polls `getHealth()` every 5 s. Computes state from
`navidrome_reachable` + `last_sync_ts` + active sync flag (the latter
needs a new field on `getHealth()` — or we infer from a counter that
changes during sync).

### `homeLibrary.ts`

```ts
// Mirrors favorites.ts shape but state lives server-side (not
// localStorage). We cache + subscribe locally so the UI doesn't
// re-fetch on every render.

export function usePinStatus(kind: PinKind, id: string):
  { isPinned: boolean; source: PinSource | null; cacheStatus: CacheStatus };
export function useSyncStatus(): { reachable: boolean; lastSyncTs: number; syncing: boolean };
export function useCacheStats(): CacheStats | null;

// imperative:
export async function togglePin(kind: PinKind, id: string, source?: PinSource): Promise<void>;
```

Internally backed by polling `/api/library/health` + per-item lookups
on detail pages. Pub/sub so any heart/pin click anywhere in the app
re-renders every subscribed component.

### `CacheAdoptOverlay.tsx`

Triggered by a 5 s poll inside `App.tsx` that watches the diff
between mounted USB drives and adopted cache drive. When a *new*
drive appears without the marker AND no cache drive is currently
adopted, the overlay pops:

```
┌─────────────────────────────────────────────────────────┐
│  New drive detected                                      │
│  Brand: SanDisk · Free: 230 GB                           │
│                                                          │
│  Use this as the boombox offline cache?                  │
│  Existing files on the drive stay where they are.        │
│                                                          │
│  [ Yes, use for cache ]   [ No, browse as media ]        │
└─────────────────────────────────────────────────────────┘
```

Yes → `adoptCache(path)` writes the marker, the service picks it up
on next poll, panel updates. No → overlay closes; existing
boombox-usb-mount.sh handling proceeds (treats as ad-hoc browse
root).

The "what's plugged in vs what's adopted" diff requires a small new
API on the backend — likely `GET /api/library/cache/candidates`
returning a list of mounted-but-unadopted drives. Documented as an
open question in §Open questions.

### `NowPlayingBar.tsx` source badge

Adds one extra element to the right of the track-info block:

```
[Album art] [Title / artist]                    [⬇ Cache] [⏯]
```

Source resolution:
- Current track URI starts with `file://` → resolve cache_state for
  the track's Subsonic ID (back-mapped via local_path) → ⬇ Cache.
- Starts with `subsonic:` → ⚡ Stream.
- Starts with `spotify:` → 🎵 Spotify.
- Starts with `local:` (Mopidy-Local ad-hoc) → 🎵 USB.
- AirPlay source active (per `useActiveSource`) → 📱 AirPlay.
- Bluetooth → 🎙 BT.

## Data flows

### Source configuration flow

```
User opens Settings → LibraryPanel
  ↓
Panel fetches getSource() + getHealth() → render
  ↓
User edits fields, taps Test
  ↓
Panel calls testSource({url, username, password})
  ↓
toast: ✓ Connected / ✗ <reason>
  ↓
User taps Save
  ↓
Panel calls putSource(...) — backend validates again, saves,
  rewrites mopidy.conf, restarts mopidy, triggers sync
  ↓
Status row goes amber-pulse "Syncing…" until next health poll shows
  navidrome_reachable=true + new sync timestamp
```

### Pin flow (explicit pin button)

```
User taps PinButton on album detail
  ↓
homeLibrary.togglePin('album', id, 'user')
  ↓
libraryApi.pin('album', id, source='user')
  ↓
Backend: INSERT pin row (or UPDATE source if existing FAVORITE/etc.),
  trigger_sync() → enqueue downloads
  ↓
Pin button enters "downloading" state with progress ring
  ↓
homeLibrary subscribers re-render (StatusBadges on track rows light up
  one by one as cache_state.status flips to 'present')
  ↓
When all tracks present → pin button shows ✓
```

### Favorite flow with auto-pin

```
User taps heart on Home Library track row
  ↓
favorites.toggleFavorite(uri)  — adds to localStorage Set, publishes
  ↓
If URI is a Home Library URI (subsonic ID extractable):
    libraryApi.pin('track', subsonicId, source='favorite')
  ↓
Backend INSERTs pin (source=favorite) unless USER pin already exists
  (in which case ON CONFLICT preserves USER)
  ↓
Both heart fill and pin icon fill render. Album thumbnail in
  LibraryDrawer shows both indicators.
```

### Unfavorite with parallel user pin

```
User taps filled heart on a Home Library track that also has explicit
  pin
  ↓
favorites.toggleFavorite(uri)  — removes from localStorage
  ↓
libraryApi.unpin('track', subsonicId, source='favorite')
  ↓
Backend DELETE pin WHERE source='favorite' AND target=...
  → returns 0 rows affected (the user pin's source is 'user', not
    'favorite')
  ↓
Heart goes outline. Pin icon stays filled (user pin survives).
```

### Cache drive adoption

```
USB drive mounts → boombox-usb-mount.sh handles it (existing flow)
  ↓
App.tsx polling sees a new drive in `/api/library/cache/candidates`
  AND health.cache_present === false
  ↓
CacheAdoptOverlay opens
  ↓
User taps Yes
  ↓
adoptCache(path) → backend writes .boombox-cache marker + creates
  audio/meta/tmp subdirs
  ↓
Backend cache_poll picks it up on next 5 s tick, symlink updates,
  download queue initializes
  ↓
Overlay closes. SyncIndicator turns green. CachePanel populates.
```

## Failure modes

Inherited from Phase 1; UI behavior:

| State | What UI shows |
|---|---|
| Service down (no 6687) | SyncIndicator red. SettingsDrawer panels show "Library service unavailable — try restarting boombox-library." |
| Source not configured | SyncIndicator grey. LibraryPanel shows empty form. Home Library root in LibraryDrawer shows "Configure source in Settings → Home Library" inline. |
| Navidrome unreachable | SyncIndicator grey. Browse falls back to local SQLite cache (still works). Streaming play attempts surface inline error. |
| Cache drive missing | SyncIndicator red if source is configured, else grey. Pin requests queue silently; backend writes pin row but no downloads happen. UI shows pin in "queued, waiting for cache drive" state. |
| Cache drive yanked during playback | Currently-playing track errors (via Mopidy). NowPlayingBar shows "Cache drive disconnected." Subsequent cached plays fail until remount. |
| `/api/library/pin` 500 | Per Phase 1's defense-in-depth scrubbing, no creds in error message. Toast "Could not pin — try again" on the row. State doesn't change. |
| Test Connection fails (wrong creds) | Inline ✗ with backend message ("Wrong username or password"). Form stays editable. |
| First-boot: source unconfigured + cache absent + WiFi off | Home Library root shows the three states stacked: "● Library unreachable · ● Cache drive offline · No source configured — open Settings → Home Library." Other sources (Spotify/USB/BT/AirPlay) unaffected. |

## Testing strategy

**Unit / component tests** (Vitest + React Testing Library — new dev
dep, modest):

- `libraryApi` — HTTP shape, error handling, request/response typing
- `homeLibrary` store — subscriber publish on pin change, cache shape
- `PinButton` — all four visual states render correctly; tap fires
  `onTogglePin`; long-press fires `onLongPress`
- `StatusBadge` — picks the right glyph for each cache_status
- `LibraryPanel` — render with mocked `libraryApi`; Test+Save flow;
  disconnected state; password not echoed
- `CachePanel` — stacked bar widths sum to 100 %; clear-streamed
  fires the right API call; cache-absent state
- `SyncIndicator` — state machine over health responses
- `CacheAdoptOverlay` — adopt fires API; dismiss closes; doesn't
  re-trigger same drive
- `LibraryDrawer` — Home Library root navigation; search results
  grouping; offline-miss row renders the "Pin for next time" CTA

**E2E manual checklist (touchscreen + LAN web):**

- First-boot: SettingsDrawer → LibraryPanel; configure source; watch
  sync from grey → amber → green; catalog count updates.
- Browse Home Library → drill into an artist → drill into an album;
  pin the album; pin downloads (status badges flip on each track row);
  navigate back to root and verify "Cached only" view contains it.
- Favorite a Home Library track; verify heart + pin both fill, then
  unfavorite and verify both clear.
- Favorite a track, then explicitly pin (USER); unfavorite; pin
  survives.
- Search "beatles": grouped results show Home Library + Spotify
  sections; tap a result; correct source plays.
- Plug in a fresh USB drive; CacheAdoptOverlay appears; tap Yes;
  drive adopted; CachePanel populates.
- Cut WiFi; SyncIndicator turns grey; cached content still plays;
  uncached content shows offline-miss CTA; re-enable WiFi; recover.
- Yank cache drive mid-playback; verify NowPlayingBar message.
- Now Playing source badge cycles correctly: cache vs stream vs
  Spotify vs USB-ad-hoc vs AirPlay vs BT.

**Backend test additions** (small):

- `_pin` accepts `source` field; precedence on update (USER overrides
  FAVORITE).
- `unpin` with source filter only deletes matching rows.
- `POST /cache/adopt` writes marker file; subsequent poll adopts.
- `POST /cache/clear` deletes streamed entries + files; pinned
  untouched.
- `POST /cache/streamed` enqueues download for the given track id.

## Open questions for planning

1. **`/api/library/cache/candidates`** — how does the UI discover mounted-but-unadopted USB drives? Option A: the cache_drive module already scans `/media/*`; expose what it sees but doesn't adopt. Option B: query the existing `boombox-usb-mount.sh` state. Lean A — it's already polling, just doesn't expose negative results.

2. **Resolver back-mapping** for the Now Playing source badge — given a Mopidy `file://` URI in flight, how do we recover the Subsonic track ID? Options: store `subsonic_id` as an extra param on the URI (e.g., `file:///cache/audio/<id>.mp3?subsonic=<id>`), or maintain a `local_path → subsonic_id` reverse lookup on the resolver endpoint. Lean: filename is `<track_id>.<suffix>` already (per downloader.py), so `path.basename().split('.')[0]` recovers the ID with zero new infrastructure. Worth verifying in implementation.

3. **Polling cadence** for SyncIndicator vs LibraryPanel vs CachePanel — same 5 s? Different? Probably consolidate into a single `useHealth()` hook polling once per 5 s that all three components subscribe to, so we don't quadruple-poll the service.

4. **Vitest vs no-test-framework** — `ui/` currently has no unit test suite. Adding Vitest is one extra dev dep but unlocks the component tests above. The plan should either accept this cost (lean yes) or commit to manual E2E only.

5. **Subsonic ID propagation through Mopidy tracklist** — when we queue a `file://` cached track via Mopidy tracklist, does Mopidy preserve any custom metadata we set? Need to verify whether the resolver can pass `subsonic_id` along to the NowPlayingBar without a server-side reverse lookup.

6. **Track-level favorite store mismatch** — `favorites.ts` keys by Mopidy URI (e.g., `local:track:<md5>.mp3`). Home Library tracks have `file://` URIs from the resolver. We need a stable key — Subsonic ID. The favorite store probably needs to learn to also key by `subsonic:track:<id>` (the canonical identity), or use a wrapper that translates. Lean: extend favorites to support `subsonic:track:<id>` as a parallel key; that's also what the auto-pin path will use.

## Future work (Phase 3 and beyond)

- PWA remote-ui parity (browse + queue + pin from phone)
- Retire `~/Music` SMB share + Mopidy-Local-on-`~/Music`
- Stale-playlist scan
- Install-time fixes: chown `/etc/boombox` + `/etc/mopidy` to boombox user during `boombox-update install` (not just first-install)
- README / SERVICES / ARCHITECTURE / HOME-LIBRARY.md / CHANGELOG
- RFID hardware integration (uses the same `PinSource.RFID` enum value that's already there)
- Tag cleanup utility (beets / Picard) — separate sub-project
- Spotify-aware caching (prefer local copy when same album exists in both)
