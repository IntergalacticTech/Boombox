# Home Library Phase 2 — Touchscreen UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Phase 1 `boombox-library` backend service to the touchscreen kiosk UI — Home Library browse root inside `LibraryDrawer`, two new SettingsDrawer panels (`LibraryPanel` for source config + `CachePanel` for cache stats), pin button + status badges, sync indicator chip in the chrome, source badge on Now Playing, cache drive adoption modal, and pin/favorite reconciliation (two-button coexist + auto-pin on favorite via a new `PinSource.FAVORITE`).

**Architecture:** Plain React 19 + plain CSS, matching the rest of `ui/`. A typed client (`libraryApi.ts`) talks to the Phase 1 service over `/api/library/*` (nginx → `127.0.0.1:6687`). A small pub/sub module (`homeLibrary.ts`) wraps polling so any pin/heart click anywhere re-renders all subscribers. Settings panels mirror `UpdatesPanel.tsx`. The new browse root is `home:*` URIs handled by `LibraryDrawer` alongside the existing Mopidy `local:` and `boombox:` roots. Small backend extensions (FAVORITE pin source, source-aware pin/unpin, four new endpoints + a sync-status field on `/health`) ship first so UI tasks are testable against a real service.

**Tech Stack:** React 19 · TypeScript 6 · Vite 8 · plain CSS · Vitest (new dev dep) + @testing-library/react · Python 3.11+ aiohttp · stdlib sqlite3. Matches the patterns in `ui/src/lib/UpdatesPanel.tsx`, `ui/src/lib/updaterApi.ts`, `ui/src/lib/favorites.ts`, and `services/boombox_library/`.

**Scope split:**

- **Phase 1 (merged):** `boombox-library` service at `:6687` — Subsonic client, SQLite catalog, pin manager, USB cache drive, downloader, FIFO eviction, playback resolver, HTTP API.
- **Phase 2 (this plan):** touchscreen UI surface + the four small backend endpoints + `PinSource.FAVORITE` it depends on.
- **Phase 3 (separate plan):** PWA remote-ui parity, retire `~/Music` SMB share, install-time fixes for upgrade-from-pre-Phase-1 Pis, docs (README/SERVICES/ARCHITECTURE/HOME-LIBRARY.md/CHANGELOG).

---

## File structure

### Created (new)

| Path | Responsibility |
|---|---|
| `ui/src/lib/libraryApi.ts` | Typed client for `/api/library/*` (mirrors `updaterApi.ts`) |
| `ui/src/lib/homeLibrary.ts` | Pub/sub for pin state, sync status, cache stats; React hooks; subscribers re-render on change |
| `ui/src/lib/LibraryPanel.tsx` | SettingsDrawer section — source form, Test/Save, status, Sync now |
| `ui/src/lib/CachePanel.tsx` | SettingsDrawer section — stacked bar, drive info, Clear streamed |
| `ui/src/lib/PinButton.tsx` | Reusable pin icon with 4 visual states + long-press → manage sheet |
| `ui/src/lib/StatusBadge.tsx` | Inline glyph for track rows (📌 ⬇ ⚡ ☁) |
| `ui/src/lib/SyncIndicator.tsx` | Header chrome chip — color-coded sync state, tap → opens Settings@Library |
| `ui/src/overlays/CacheAdoptOverlay.tsx` | Modal prompting the user to adopt a fresh USB drive as the cache |
| `ui/vitest.config.ts` | Vitest configuration |
| `ui/src/test-setup.ts` | Vitest setup (jsdom + @testing-library cleanup) |
| `ui/src/lib/__tests__/libraryApi.test.ts` | HTTP shape / error handling tests |
| `ui/src/lib/__tests__/homeLibrary.test.ts` | Pub/sub publish-on-change tests |
| `ui/src/lib/__tests__/PinButton.test.tsx` | All 4 visual states + tap/long-press |
| `ui/src/lib/__tests__/StatusBadge.test.tsx` | Glyph pick per status |
| `ui/src/lib/__tests__/SyncIndicator.test.tsx` | State machine over health responses |
| `ui/src/lib/__tests__/LibraryPanel.test.tsx` | Test/Save flow + disconnected state |
| `ui/src/lib/__tests__/CachePanel.test.tsx` | Stacked bar widths + clear-streamed |
| `ui/src/overlays/__tests__/CacheAdoptOverlay.test.tsx` | Adopt + dismiss + no-retrigger |
| `ui/src/lib/__tests__/LibraryDrawer.homeLibrary.test.tsx` | Home Library root navigation + offline-miss CTA |

### Modified

| Path | Change |
|---|---|
| `services/boombox_library/models.py` | Add `PinSource.FAVORITE` enum value |
| `services/boombox_library/pins.py` | `pin()` UPSERT with source precedence (USER > FAVORITE > STARRED); `unpin()` accepts optional `source=` filter |
| `services/boombox_library/api.py` | `_pin` accepts optional `source` field; add `POST /cache/adopt`, `POST /cache/streamed`, `POST /cache/clear`, `GET /cache/candidates`; `/health` reports `last_sync_ts` + `syncing` |
| `services/boombox-library.py` | Expose `last_sync_ts` + `syncing` + cache adoption + clear-streamed hooks on `ServiceContext` |
| `services/boombox_library/downloader.py` | `enqueue(track_id, *, streamed=False)` — flag stored so eviction never picks pinned, and so `/cache/clear` knows what to delete (uses pin set, but the keyword surfaces intent for callers) |
| `services/tests/test_library_pins.py` | Tests for source-precedence UPSERT + source-filtered unpin |
| `services/tests/test_library_api.py` | Tests for the four new endpoints + source field on `/pin` + `last_sync_ts` on `/health` |
| `ui/src/lib/LibraryDrawer.tsx` | Add "Home Library" entry to `ROOTS`; route `home:*` through `libraryApi`; rows render `<PinButton/>` + `<StatusBadge/>`; `[+ Pin for next time]` CTA on offline-miss; grouped search results |
| `ui/src/lib/SettingsDrawer.tsx` | Mount `<LibraryPanel/>` and `<CachePanel/>`; listen for `boombox:open-settings-library` to auto-scroll |
| `ui/src/lib/ChromeButtons.tsx` | Render `<SyncIndicator/>` between source button and queue/skin cluster |
| `ui/src/lib/NowPlayingBar.tsx` | Adds source badge to the right of the title (resolves track URI → cache/stream/Spotify/USB/AirPlay/BT) |
| `ui/src/lib/favorites.ts` | `toggleFavorite()` for Home Library URIs (`subsonic:track:<id>` form) also calls `libraryApi.pin/unpin` with `source: 'favorite'` |
| `ui/src/App.tsx` | Poll `/api/library/cache/candidates` every 5 s; mount `<CacheAdoptOverlay/>` |
| `ui/src/overlays/OverlayRoot.tsx` | Add `<CacheAdoptOverlay/>` |
| `ui/package.json` | Add `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` devDependencies + `test` script |

### Out of scope (Phase 2)

- PWA remote-ui parity at `remote-ui/`
- Retiring `~/Music` SMB share / Mopidy-Local on `~/Music`
- Install-time bug fixes for pre-Phase-1 Pis
- Documentation updates (README/SERVICES/ARCHITECTURE/HOME-LIBRARY.md/CHANGELOG)
- Track-level pin button (album/artist/playlist detail only — see spec §Non-goals)

---

## Conventions matched from the existing codebase

- React function components, no class components
- Inline `style={{...}}` props — no CSS-in-JS library, no Tailwind
- Touch targets ≥ 44 px on every actionable control (kiosk is a 5″ resistive touchscreen)
- Panel pattern: see `UpdatesPanel.tsx` — 5 s `setInterval` poll, mutable state via hooks, errors inline, never throw
- `fetch("/api/...")` directly for one-shot calls; typed wrappers in `*Api.ts` files
- Pub/sub with `Set<subscriber>` module-level — see `favorites.ts`
- `from __future__ import annotations` on every Python module
- Atomic SQLite UPSERT via `ON CONFLICT DO UPDATE`
- Tests adjacent to source: Python in `services/tests/`, TypeScript in `ui/src/**/__tests__/`
- Vitest config: jsdom env, globals enabled, `setupFiles` includes `@testing-library/jest-dom`
- Skin chrome buttons live INSIDE the skin's 1280×800 design coordinate space — `SyncIndicator` follows the same `btnStyle` pattern from `ChromeButtons.tsx`

---

## Backend extensions checklist

These four small backend changes must land before any UI task — they're the contract the UI codes against:

- `PinSource.FAVORITE` enum value
- `pin(conn, kind, target_id, source)` UPSERT with precedence rules
- `unpin(conn, kind, target_id, source=None)` source filter
- `POST /api/library/pin` accepts `source` field
- `POST /api/library/cache/adopt`
- `POST /api/library/cache/streamed`
- `POST /api/library/cache/clear`
- `GET /api/library/cache/candidates`
- `/api/library/health` reports `last_sync_ts` + `syncing` fields

Phase 1's `boombox-library` service is already running at `:6687` and proxied by nginx under `/api/library/`. Both verified in commit `0e14bef`.

---

## Tasks

### Task 1: Add `PinSource.FAVORITE` enum + source precedence in `pin()`

**Files:**
- Modify: `services/boombox_library/models.py:67-71`
- Modify: `services/boombox_library/pins.py:46-54`
- Modify: `services/tests/test_library_pins.py`

- [ ] **Step 1: Write failing test for FAVORITE enum**

Append to `services/tests/test_library_pins.py`:

```python
def test_pin_source_has_favorite_value():
    """FAVORITE source represents auto-pins from the heart/favorites button."""
    assert PinSource.FAVORITE.value == "favorite"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jwc/code/Boombox
pytest services/tests/test_library_pins.py::test_pin_source_has_favorite_value -v
```

Expected: FAIL with `AttributeError: FAVORITE`.

- [ ] **Step 3: Add `FAVORITE` to the enum**

Edit `services/boombox_library/models.py:67-71`:

```python
class PinSource(str, Enum):
    USER = "user"
    FAVORITE = "favorite"
    STARRED = "starred"
    RFID = "rfid"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest services/tests/test_library_pins.py::test_pin_source_has_favorite_value -v
```

Expected: PASS.

- [ ] **Step 5: Write failing tests for source precedence on UPSERT**

Append to `services/tests/test_library_pins.py`:

```python
def test_pin_user_upgrades_favorite(tmp_path: Path):
    """USER > FAVORITE: pinning with USER over an existing FAVORITE pin upgrades source."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.FAVORITE)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert len(rows) == 1
    assert rows[0]["source"] == "user"


def test_pin_favorite_does_not_overwrite_user(tmp_path: Path):
    """FAVORITE < USER: favoriting after explicit pin leaves source=USER."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    pin(conn, PinKind.ALBUM, "al1", PinSource.FAVORITE)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "user"


def test_pin_user_upgrades_starred(tmp_path: Path):
    """USER > STARRED: pinning over a starred-source pin upgrades to user."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.STARRED)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "user"


def test_pin_starred_does_not_overwrite_favorite(tmp_path: Path):
    """STARRED is the weakest source — never upgrades over FAVORITE or USER."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.FAVORITE)
    pin(conn, PinKind.ALBUM, "al1", PinSource.STARRED)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "favorite"
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
pytest services/tests/test_library_pins.py -v -k "upgrades or does_not_overwrite"
```

Expected: 2 FAIL (the UPSERT currently does NOTHING on conflict, so source never changes).

- [ ] **Step 7: Implement source precedence in `pin()`**

Replace the body of `pin()` in `services/boombox_library/pins.py:46-54`:

```python
# Precedence (high → low): USER > FAVORITE > STARRED > RFID.
# When inserting over an existing pin we upgrade source iff the new source
# outranks the stored one; we never downgrade. STARRED only inserts if no
# pin exists.
_SOURCE_RANK = {
    PinSource.USER: 4,
    PinSource.FAVORITE: 3,
    PinSource.RFID: 2,
    PinSource.STARRED: 1,
}


def pin(conn: Connection, kind: PinKind, target_id: str, source: PinSource) -> None:
    """Insert or upgrade a pin row.

    Idempotent. If an existing pin's source ranks lower than the new one, the
    row's source is upgraded; otherwise the existing source is preserved.
    """
    existing = conn.execute(
        "SELECT source FROM pins WHERE target_kind=? AND target_id=?",
        (kind.value, target_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO pins(target_kind, target_id, source, added_at) "
            "VALUES (?, ?, ?, ?)",
            (kind.value, target_id, source.value, time.time()),
        )
        return
    try:
        existing_src = PinSource(existing["source"])
    except ValueError:
        existing_src = PinSource.STARRED  # unknown → lowest rank
    if _SOURCE_RANK[source] > _SOURCE_RANK[existing_src]:
        conn.execute(
            "UPDATE pins SET source=? WHERE target_kind=? AND target_id=?",
            (source.value, kind.value, target_id),
        )
```

- [ ] **Step 8: Run all pins tests to verify**

```bash
pytest services/tests/test_library_pins.py -v
```

Expected: all green (precedence rules satisfied; existing idempotent test still passes because identical-source pin is a no-op via the rank-equality branch).

- [ ] **Step 9: Commit**

```bash
git add services/boombox_library/models.py services/boombox_library/pins.py services/tests/test_library_pins.py
git commit -m "feat(library): PinSource.FAVORITE + source-precedence UPSERT"
```

---

### Task 2: Source-filtered `unpin()` + `source` field on `POST /pin`

**Files:**
- Modify: `services/boombox_library/pins.py:56-60`
- Modify: `services/boombox_library/api.py:130-150`
- Modify: `services/tests/test_library_pins.py`
- Modify: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing test for source-filtered unpin**

Append to `services/tests/test_library_pins.py`:

```python
def test_unpin_with_source_filter_only_deletes_matching(tmp_path: Path):
    """Unpinning with source='favorite' must not nuke a user pin."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    # Caller asks to unpin only favorite-sourced rows — there are none.
    unpin(conn, PinKind.ALBUM, "al1", source=PinSource.FAVORITE)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert len(rows) == 1 and rows[0]["source"] == "user"


def test_unpin_without_source_filter_deletes_any(tmp_path: Path):
    """Backwards compat: unpin(kind, id) without source still force-deletes."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    unpin(conn, PinKind.ALBUM, "al1")
    assert list(conn.execute("SELECT * FROM pins")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_pins.py -v -k "source_filter or without_source"
```

Expected: first test FAIL (current `unpin` deletes regardless of source).

- [ ] **Step 3: Implement source filter in `unpin()`**

Replace `unpin()` in `services/boombox_library/pins.py:56-60`:

```python
def unpin(
    conn: Connection,
    kind: PinKind,
    target_id: str,
    source: PinSource | None = None,
) -> None:
    """Delete a pin row. If `source` is given, only rows with that source are
    deleted — so removing a favorite-driven pin doesn't nuke a parallel
    user-driven pin. Without `source`, force-deletes any pin for (kind, id).
    """
    if source is None:
        conn.execute(
            "DELETE FROM pins WHERE target_kind=? AND target_id=?",
            (kind.value, target_id),
        )
    else:
        conn.execute(
            "DELETE FROM pins WHERE target_kind=? AND target_id=? AND source=?",
            (kind.value, target_id, source.value),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_pins.py -v
```

Expected: all green.

- [ ] **Step 5: Write failing test for `source` field on API**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_pin_endpoint_accepts_source(client):
    """POST /api/library/pin with {source:'favorite'} stores source=favorite."""
    c, ctx, conn = client
    # Need an album to pin
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al1", "mode": "pin", "source": "favorite",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "favorite"


@pytest.mark.asyncio
async def test_pin_endpoint_defaults_source_to_user(client):
    """Omitting source field keeps backwards compat — stores source=user."""
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al1", "mode": "pin",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "user"


@pytest.mark.asyncio
async def test_unpin_endpoint_accepts_source(client):
    """POST /api/library/pin with {mode:'unpin', source:'favorite'} respects filter."""
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    conn.execute("INSERT INTO pins(target_kind,target_id,source,added_at) "
                 "VALUES('album','al1','user',0)")
    # Unfavoriting an item that was user-pinned — pin must survive.
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al1", "mode": "unpin", "source": "favorite",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT * FROM pins WHERE target_id='al1'"))
    assert len(rows) == 1
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
pytest services/tests/test_library_api.py -v -k "accepts_source or defaults_source"
```

Expected: FAIL (current `_pin` hard-codes `PinSource.USER`).

- [ ] **Step 7: Update `_pin` to accept source field**

Replace `_pin` in `services/boombox_library/api.py:130-150`:

```python
async def _pin(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    try:
        kind = PinKind(body["kind"])
    except (KeyError, ValueError):
        return web.json_response({"error": "invalid kind"}, status=400)
    target_id = body.get("id")
    if not target_id:
        return web.json_response({"error": "missing id"}, status=400)
    mode = body.get("mode", "pin")
    # source defaults to USER for backwards compat with Phase 1 callers.
    raw_source = body.get("source", "user")
    try:
        source = PinSource(raw_source)
    except ValueError:
        return web.json_response({"error": "invalid source"}, status=400)
    if mode == "pin":
        _pin_fn(ctx.conn, kind, target_id, source)
        # Kick a sync so downloads start immediately rather than waiting
        # for the next hourly tick. Sync is no-op if NAS unreachable.
        await ctx.trigger_sync()
    elif mode == "unpin":
        # If a source was explicitly passed, filter by it; otherwise force-delete.
        if "source" in body:
            _unpin_fn(ctx.conn, kind, target_id, source=source)
        else:
            _unpin_fn(ctx.conn, kind, target_id)
    else:
        return web.json_response({"error": "invalid mode"}, status=400)
    return web.json_response({"ok": True})
```

- [ ] **Step 8: Run API tests to verify**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add services/boombox_library/pins.py services/boombox_library/api.py services/tests/test_library_pins.py services/tests/test_library_api.py
git commit -m "feat(library): source-aware /pin endpoint + source-filtered unpin"
```

---

### Task 3: `last_sync_ts` + `syncing` fields on `/health`

**Files:**
- Modify: `services/boombox-library.py:53-95`
- Modify: `services/boombox_library/api.py:53-61`
- Modify: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing test for sync status fields on /health**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_health_reports_last_sync_ts_and_syncing(client):
    """UI's SyncIndicator polls /health for last_sync_ts + syncing flag."""
    c, ctx, _ = client
    ctx.last_sync_ts = 12345.0
    ctx.syncing = False
    r = await c.get("/api/library/health")
    body = await r.json()
    assert body["last_sync_ts"] == 12345.0
    assert body["syncing"] is False


@pytest.mark.asyncio
async def test_health_reports_syncing_true_during_sync(client):
    """While a sync is in flight syncing=true so the chip can pulse amber."""
    c, ctx, _ = client
    ctx.syncing = True
    r = await c.get("/api/library/health")
    body = await r.json()
    assert body["syncing"] is True
```

Also extend `FakeContext` in the same file (near line 19) to expose the two new fields:

```python
class FakeContext:
    def __init__(self, conn, cfg=None, cache_state=None, ping_ok=True):
        self.conn = conn
        self.cfg = cfg or DEFAULT_CONFIG
        self.cache_state = cache_state
        self._ping_ok = ping_ok
        self.synced = 0
        self.last_sync_ts = 0.0
        self.syncing = False
        self.candidates = []  # see Task 7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_api.py::test_health_reports_last_sync_ts_and_syncing -v
```

Expected: FAIL — fields missing from `/health` response.

- [ ] **Step 3: Add fields to `Context` Protocol and `_health` route**

Edit `services/boombox_library/api.py`. Extend the `Context` Protocol (around line 26):

```python
class Context(Protocol):
    conn: object  # sqlite3.Connection
    cfg: LibraryConfig
    last_sync_ts: float
    syncing: bool

    async def is_online(self) -> bool: ...
    async def trigger_sync(self) -> None: ...
    def cache_drive_state(self): ...
    def save_config(self, cfg: LibraryConfig) -> None: ...
    async def test_source(self, url: str, username: str, password: str) -> tuple[bool, str]: ...
    def cache_candidates(self) -> list[dict]: ...  # Task 7 stub for forward compat
    async def adopt_cache(self, mount_path: str) -> None: ...  # Task 4
    async def clear_streamed_cache(self) -> int: ...  # Task 6
    def enqueue_streamed_download(self, track_id: str) -> None: ...  # Task 5
```

Replace `_health` (around line 53):

```python
async def _health(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    drive = ctx.cache_drive_state()
    return web.json_response({
        "service_version": __version__,
        "navidrome_reachable": await ctx.is_online(),
        "cache_present": bool(drive and drive.present) if drive else False,
        "cache_mount": str(drive.mount_path) if drive and drive.mount_path else None,
        "last_sync_ts": ctx.last_sync_ts,
        "syncing": ctx.syncing,
    })
```

- [ ] **Step 4: Add fields to `ServiceContext`**

Edit `services/boombox-library.py:53-95`. Add to `__init__`:

```python
self.last_sync_ts: float = 0.0
self.syncing: bool = False
```

Wrap `_sync_once` body with syncing flag + timestamp on success:

```python
async def _sync_once(self) -> None:
    if not self.cfg.source.url:
        log.info("no source configured; skipping sync")
        return
    self.syncing = True
    try:
        async with SubsonicClient(self.cfg.source.url,
                                  self.cfg.source.username,
                                  self.cfg.source.password) as client:
            try:
                await client.ping()
                self._online = True
            except (SubsonicAuthError, SubsonicUnreachable) as e:
                log.warning("ping failed: %s", e)
                self._online = False
                return
            try:
                await sync_full(client, self.conn)
                if self.cfg.sync.starred_auto_pin:
                    reconcile_starred(self.conn)
                self._enqueue_pinned_downloads()
                self._persist_pins_sidecar()
                self.last_sync_ts = time.time()
            except Exception as e:
                log.exception("sync failed: %s", e)
    finally:
        self.syncing = False
```

Add `import time` to the top of the file (alphabetized with stdlib).

- [ ] **Step 5: Run API tests to verify**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add services/boombox-library.py services/boombox_library/api.py services/tests/test_library_api.py
git commit -m "feat(library): /health surfaces last_sync_ts + syncing"
```

---

### Task 4: `POST /api/library/cache/adopt`

**Files:**
- Modify: `services/boombox_library/api.py`
- Modify: `services/boombox-library.py`
- Modify: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing test**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_cache_adopt_writes_marker(client, tmp_path):
    """POST /cache/adopt asks the service to bless a drive at the given path."""
    c, ctx, _ = client
    # FakeContext records adoption calls (added in Step 3 of this task).
    drive_path = str(tmp_path / "fake-drive")
    r = await c.post("/api/library/cache/adopt",
                     json={"mount_path": drive_path})
    assert r.status == 200
    assert ctx.adopted == [drive_path]


@pytest.mark.asyncio
async def test_cache_adopt_rejects_missing_mount_path(client):
    """Missing mount_path → 400."""
    c, _, _ = client
    r = await c.post("/api/library/cache/adopt", json={})
    assert r.status == 400
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest services/tests/test_library_api.py::test_cache_adopt_writes_marker -v
```

Expected: 404 (route not registered).

- [ ] **Step 3: Extend `FakeContext` for adoption tracking**

In `services/tests/test_library_api.py`, add to `FakeContext.__init__`:

```python
self.adopted: list[str] = []
self.streamed_enqueued: list[str] = []
self.cleared_count = 0
```

And add methods:

```python
async def adopt_cache(self, mount_path: str) -> None:
    self.adopted.append(mount_path)

def enqueue_streamed_download(self, track_id: str) -> None:
    self.streamed_enqueued.append(track_id)

async def clear_streamed_cache(self) -> int:
    self.cleared_count += 1
    return 0

def cache_candidates(self) -> list[dict]:
    return self.candidates
```

- [ ] **Step 4: Add `/cache/adopt` route**

In `services/boombox_library/api.py`, register in `build_app()`:

```python
app.router.add_post("/api/library/cache/adopt", _cache_adopt)
app.router.add_post("/api/library/cache/streamed", _cache_streamed)
app.router.add_post("/api/library/cache/clear", _cache_clear)
app.router.add_get("/api/library/cache/candidates", _cache_candidates)
```

Append the handler:

```python
async def _cache_adopt(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    mount_path = body.get("mount_path")
    if not mount_path:
        return web.json_response({"error": "missing mount_path"}, status=400)
    await ctx.adopt_cache(mount_path)
    return web.json_response({"ok": True})
```

(Stubs for the other three handlers will be filled in by Tasks 5–7. For now, add empty stubs that return 501 so build_app doesn't reference missing names — they'll be replaced.)

```python
async def _cache_streamed(req: web.Request) -> web.Response:
    return web.json_response({"error": "not implemented"}, status=501)


async def _cache_clear(req: web.Request) -> web.Response:
    return web.json_response({"error": "not implemented"}, status=501)


async def _cache_candidates(req: web.Request) -> web.Response:
    return web.json_response({"error": "not implemented"}, status=501)
```

- [ ] **Step 5: Implement `adopt_cache` on `ServiceContext`**

In `services/boombox-library.py`, import `adopt_drive` and add the method:

```python
from boombox_library.cache_drive import (
    CacheDriveState, detect_cache_drive,
    update_symlink, remove_symlink,
    adopt_drive,
    DEFAULT_SYMLINK,
)
```

Add to `ServiceContext`:

```python
async def adopt_cache(self, mount_path: str) -> None:
    """Bless a USB drive as the boombox cache. Writes the marker file and
    creates required subdirs; cache_poll picks it up on the next tick."""
    p = Path(mount_path)
    adopt_drive(p, marker=self.cfg.cache.marker_filename)
    log.info("adopted cache drive at %s (marker written)", p)
```

- [ ] **Step 6: Run tests to verify**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: adopt tests green; streamed/clear/candidates tests don't exist yet.

- [ ] **Step 7: Commit**

```bash
git add services/boombox_library/api.py services/boombox-library.py services/tests/test_library_api.py
git commit -m "feat(library): POST /cache/adopt blesses a USB drive as the cache"
```

---

### Task 5: `POST /api/library/cache/streamed`

**Files:**
- Modify: `services/boombox_library/api.py`
- Modify: `services/boombox-library.py`
- Modify: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing test**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_cache_streamed_enqueues_track(client):
    """POST /cache/streamed?id=X enqueues a streamed (non-pinned) download."""
    c, ctx, conn = client
    # Seed a track so the request has a meaningful target
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al1','T',0,'mp3',0,'audio/mpeg',0,0)")
    r = await c.post("/api/library/cache/streamed?id=t1")
    assert r.status == 200
    assert ctx.streamed_enqueued == ["t1"]


@pytest.mark.asyncio
async def test_cache_streamed_rejects_missing_id(client):
    c, _, _ = client
    r = await c.post("/api/library/cache/streamed")
    assert r.status == 400
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest services/tests/test_library_api.py -v -k "streamed_enqueues or streamed_rejects"
```

Expected: FAIL (handler is a 501 stub).

- [ ] **Step 3: Replace `_cache_streamed` handler**

In `services/boombox_library/api.py`, replace the stub:

```python
async def _cache_streamed(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    track_id = req.query.get("id", "").strip()
    if not track_id:
        return web.json_response({"error": "missing id"}, status=400)
    ctx.enqueue_streamed_download(track_id)
    return web.json_response({"ok": True})
```

- [ ] **Step 4: Implement on `ServiceContext`**

In `services/boombox-library.py`, add to `ServiceContext`:

```python
def enqueue_streamed_download(self, track_id: str) -> None:
    """Queue an opportunistic streamed-cache download for a track the user
    is currently streaming. No-op if no cache drive is adopted."""
    if self._download_queue is None:
        log.info("no cache drive; skipping streamed-cache enqueue of %s", track_id)
        return
    self._download_queue.enqueue(track_id)
```

- [ ] **Step 5: Run tests to verify**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add services/boombox_library/api.py services/boombox-library.py services/tests/test_library_api.py
git commit -m "feat(library): POST /cache/streamed enqueues opportunistic downloads"
```

---

### Task 6: `POST /api/library/cache/clear`

**Files:**
- Modify: `services/boombox_library/api.py`
- Modify: `services/boombox-library.py`
- Modify: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing test**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_cache_clear_calls_service(client):
    """POST /cache/clear invokes ServiceContext.clear_streamed_cache."""
    c, ctx, _ = client
    r = await c.post("/api/library/cache/clear")
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    assert ctx.cleared_count == 1


@pytest.mark.asyncio
async def test_cache_clear_returns_count(client):
    """Response includes the number of entries cleared, for UI feedback."""
    c, ctx, _ = client
    async def fake_clear() -> int:
        ctx.cleared_count += 1
        return 7
    ctx.clear_streamed_cache = fake_clear  # type: ignore
    r = await c.post("/api/library/cache/clear")
    body = await r.json()
    assert body["cleared"] == 7
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest services/tests/test_library_api.py -v -k "cache_clear"
```

Expected: FAIL (stub).

- [ ] **Step 3: Replace `_cache_clear` handler**

In `services/boombox_library/api.py`:

```python
async def _cache_clear(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    cleared = await ctx.clear_streamed_cache()
    return web.json_response({"ok": True, "cleared": cleared})
```

- [ ] **Step 4: Implement on `ServiceContext`**

In `services/boombox-library.py`, add to `ServiceContext`:

```python
async def clear_streamed_cache(self) -> int:
    """Delete every cache_state row whose track is NOT pin-protected, and
    remove the corresponding files. Returns the number of entries cleared.
    No-op if no cache drive is adopted.
    """
    if not self.cache_state.present or not self.cache_state.mount_path:
        return 0
    pinned = all_pinned_track_ids(self.conn)
    rows = list(self.conn.execute(
        "SELECT track_id, local_path FROM cache_state WHERE status='present'"
    ))
    cleared = 0
    for r in rows:
        if r["track_id"] in pinned:
            continue
        path = r["local_path"]
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as e:
                log.warning("could not delete %s: %s", path, e)
        self.conn.execute(
            "UPDATE cache_state SET status='absent', local_path=NULL, "
            "size_bytes=NULL WHERE track_id=?", (r["track_id"],),
        )
        cleared += 1
    return cleared
```

- [ ] **Step 5: Run tests + commit**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: all green.

```bash
git add services/boombox_library/api.py services/boombox-library.py services/tests/test_library_api.py
git commit -m "feat(library): POST /cache/clear deletes streamed (non-pinned) cache"
```

---

### Task 7: `GET /api/library/cache/candidates`

**Files:**
- Modify: `services/boombox_library/api.py`
- Modify: `services/boombox_library/cache_drive.py`
- Modify: `services/boombox-library.py`
- Modify: `services/tests/test_library_api.py`
- Modify: `services/tests/test_library_cache_drive.py`

- [ ] **Step 1: Write failing test for new helper `list_candidate_drives`**

Append to `services/tests/test_library_cache_drive.py`:

```python
def test_list_candidate_drives_returns_unadopted(tmp_path: Path):
    """Drives that are mounted but lack the marker file appear as candidates."""
    from boombox_library.cache_drive import list_candidate_drives
    # Two children of /media: one with marker (adopted), one without
    (tmp_path / "DRIVE_A").mkdir()
    (tmp_path / "DRIVE_A" / ".boombox-cache").touch()
    (tmp_path / "DRIVE_B").mkdir()
    out = list_candidate_drives([tmp_path], marker=".boombox-cache")
    paths = [c["mount_path"] for c in out]
    assert str(tmp_path / "DRIVE_B") in paths
    assert str(tmp_path / "DRIVE_A") not in paths


def test_list_candidate_drives_includes_disk_usage(tmp_path: Path):
    """Each candidate has free_bytes + total_bytes (best-effort)."""
    from boombox_library.cache_drive import list_candidate_drives
    (tmp_path / "DRIVE").mkdir()
    out = list_candidate_drives([tmp_path])
    assert out[0]["free_bytes"] is not None
    assert out[0]["total_bytes"] is not None
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest services/tests/test_library_cache_drive.py::test_list_candidate_drives_returns_unadopted -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `list_candidate_drives`**

Append to `services/boombox_library/cache_drive.py`:

```python
def list_candidate_drives(
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> list[dict]:
    """Mounted directories that look like USB drives but lack the marker.

    UI uses this to prompt the user to adopt a fresh drive as the cache.
    Already-adopted drives (marker present) are excluded so the prompt
    doesn't re-fire after the user has chosen.
    """
    out: list[dict] = []
    for root in search_paths:
        root = Path(root)
        if not root.exists():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError as e:
            log.warning("could not scan %s: %s", root, e)
            continue
        for child in entries:
            if not child.is_dir():
                continue
            if (child / marker).exists():
                continue
            free, total = _disk_usage(child)
            out.append({
                "mount_path": str(child),
                "label": child.name,
                "free_bytes": free,
                "total_bytes": total,
            })
    return out
```

- [ ] **Step 4: Run cache_drive tests to verify**

```bash
pytest services/tests/test_library_cache_drive.py -v
```

Expected: all green.

- [ ] **Step 5: Write failing test for `/cache/candidates` endpoint**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_cache_candidates_returns_list(client):
    """GET /cache/candidates exposes mounted-but-unadopted drives."""
    c, ctx, _ = client
    ctx.candidates = [{
        "mount_path": "/media/DRIVE_B", "label": "DRIVE_B",
        "free_bytes": 230_000_000_000, "total_bytes": 250_000_000_000,
    }]
    r = await c.get("/api/library/cache/candidates")
    assert r.status == 200
    body = await r.json()
    assert body["candidates"] == ctx.candidates
```

- [ ] **Step 6: Replace `_cache_candidates` stub**

In `services/boombox_library/api.py`:

```python
async def _cache_candidates(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response({"candidates": ctx.cache_candidates()})
```

- [ ] **Step 7: Implement on `ServiceContext`**

In `services/boombox-library.py`. Import:

```python
from boombox_library.cache_drive import (
    ...
    list_candidate_drives,
)
```

Add to `ServiceContext`:

```python
def cache_candidates(self) -> list[dict]:
    """List drives that could be adopted as the cache (marker absent)."""
    return list_candidate_drives(
        [Path(p) for p in self.cfg.cache.search_paths],
        marker=self.cfg.cache.marker_filename,
    )
```

- [ ] **Step 8: Run all backend tests + commit**

```bash
pytest services/tests/ -v --ignore=services/tests/test_library_integration.py
```

Expected: all green.

```bash
git add services/boombox_library/api.py services/boombox_library/cache_drive.py services/boombox-library.py services/tests/test_library_api.py services/tests/test_library_cache_drive.py
git commit -m "feat(library): GET /cache/candidates lists unadopted USB drives"
```

---

### Task 8: Vitest + @testing-library setup

**Files:**
- Modify: `ui/package.json`
- Create: `ui/vitest.config.ts`
- Create: `ui/src/test-setup.ts`

- [ ] **Step 1: Add dev dependencies**

```bash
cd /Users/jwc/code/Boombox/ui
npm install --save-dev vitest@^3 @testing-library/react@^16 @testing-library/jest-dom@^6 jsdom@^25
```

- [ ] **Step 2: Add `test` script to `ui/package.json`**

In the `scripts` block, add:

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: Create `ui/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
```

- [ ] **Step 4: Create `ui/src/test-setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 5: Verify Vitest runs**

```bash
cd /Users/jwc/code/Boombox/ui
npx vitest run
```

Expected: `No test files found` (zero tests is fine; we want the runner to start successfully).

- [ ] **Step 6: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/vitest.config.ts ui/src/test-setup.ts
git commit -m "test(ui): add Vitest + @testing-library scaffolding"
```

---

### Task 9: `libraryApi.ts` — typed client

**Files:**
- Create: `ui/src/lib/libraryApi.ts`
- Create: `ui/src/lib/__tests__/libraryApi.test.ts`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/libraryApi.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as api from "../libraryApi";

const realFetch = globalThis.fetch;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.restoreAllMocks();
  globalThis.fetch = realFetch;
});

function mockJson(body: unknown, ok = true, status = 200) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok, status, json: async () => body, text: async () => JSON.stringify(body),
  } as Response);
}

describe("libraryApi", () => {
  it("getHealth parses last_sync_ts + syncing", async () => {
    mockJson({
      service_version: "0.1.0", navidrome_reachable: true,
      cache_present: true, cache_mount: "/media/X",
      last_sync_ts: 123, syncing: false,
    });
    const h = await api.getHealth();
    expect(h.last_sync_ts).toBe(123);
    expect(h.syncing).toBe(false);
  });

  it("pin sends source field when provided", async () => {
    mockJson({ ok: true });
    await api.pin("album", "al1", "favorite");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/library/pin");
    expect(JSON.parse(call[1].body)).toMatchObject({
      kind: "album", id: "al1", mode: "pin", source: "favorite",
    });
  });

  it("unpin sends mode=unpin and source filter when provided", async () => {
    mockJson({ ok: true });
    await api.unpin("track", "t1", "favorite");
    const body = JSON.parse((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body);
    expect(body).toMatchObject({ kind: "track", id: "t1", mode: "unpin", source: "favorite" });
  });

  it("putSource throws on non-2xx with backend message", async () => {
    mockJson({ ok: false, error: "auth: wrong password" }, false, 400);
    await expect(
      api.putSource({ url: "u", username: "x", password: "y" })
    ).rejects.toThrow(/auth: wrong password/);
  });

  it("adoptCache posts mount_path", async () => {
    mockJson({ ok: true });
    await api.adoptCache("/media/DRIVE_B");
    const body = JSON.parse((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body);
    expect(body).toMatchObject({ mount_path: "/media/DRIVE_B" });
  });

  it("triggerStreamedCacheDownload uses query string id", async () => {
    mockJson({ ok: true });
    await api.triggerStreamedCacheDownload("t1");
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toBe("/api/library/cache/streamed?id=t1");
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd /Users/jwc/code/Boombox/ui
npx vitest run src/lib/__tests__/libraryApi.test.ts
```

Expected: `Failed to load url ../libraryApi`.

- [ ] **Step 3: Implement `libraryApi.ts`**

Create `ui/src/lib/libraryApi.ts`:

```ts
// libraryApi — typed client for the boombox-library service (port 6687,
// fronted by nginx at /api/library/*). Mirrors updaterApi.ts.
//
// Passwords flow PUT-only — they're never read back via GET /source.

export type SourceConfig = { url: string; username: string };
export type SourceConfigWithPassword = SourceConfig & { password: string };

export type Health = {
  service_version: string;
  navidrome_reachable: boolean;
  cache_present: boolean;
  cache_mount: string | null;
  last_sync_ts: number;        // 0 if never synced
  syncing: boolean;
};

export type BrowseType = "artists" | "albums" | "playlists";

export type BrowseItem = {
  id: string;
  name: string;
  artist_id?: string;
  year?: number;
  album_count?: number;
  song_count?: number;
  art_id?: string;
};

export type SearchResult = {
  content_type: "artist" | "album" | "track";
  id: string;
  title: string;
};

export type PinKind = "album" | "artist" | "playlist" | "track";
export type PinSource = "user" | "favorite";  // STARRED / RFID are backend-internal

export type CacheStats = {
  present: boolean;
  mount_path?: string | null;
  capacity: number;
  free: number;
  pinned_bytes: number;
  streamed_bytes: number;
  reserved: number;
};

export type CacheCandidate = {
  mount_path: string;
  label: string;
  free_bytes: number | null;
  total_bytes: number | null;
};

export type PlaybackResolution = {
  source: "cache" | "stream" | "offline_miss";
  uri: string | null;
  cache_status: "present" | "absent" | "queued" | "downloading" | "error";
};

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(body.error || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  return jsonOrThrow(await fetch("/api/library/health"));
}

export async function getSource(): Promise<SourceConfig> {
  return jsonOrThrow(await fetch("/api/library/source"));
}

export async function putSource(s: SourceConfigWithPassword): Promise<{ ok: boolean }> {
  return jsonOrThrow(await fetch("/api/library/source", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  }));
}

export async function testSource(s: SourceConfigWithPassword): Promise<{ ok: boolean; error?: string }> {
  // /source/test always returns 200 (with ok:false on failure); don't throw.
  const r = await fetch("/api/library/source/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  return r.json();
}

export async function browse(type: BrowseType): Promise<BrowseItem[]> {
  const r = await fetch(`/api/library/browse?type=${type}`);
  const body = await jsonOrThrow<{ items: BrowseItem[] }>(r);
  return body.items;
}

export async function search(q: string): Promise<SearchResult[]> {
  if (!q.trim()) return [];
  const r = await fetch(`/api/library/search?q=${encodeURIComponent(q)}`);
  const body = await jsonOrThrow<{ results: SearchResult[] }>(r);
  return body.results;
}

export async function pin(
  kind: PinKind, id: string, source: PinSource = "user",
): Promise<void> {
  await jsonOrThrow(await fetch("/api/library/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, id, mode: "pin", source }),
  }));
}

export async function unpin(
  kind: PinKind, id: string, source?: PinSource,
): Promise<void> {
  const payload: Record<string, unknown> = { kind, id, mode: "unpin" };
  if (source) payload.source = source;
  await jsonOrThrow(await fetch("/api/library/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }));
}

export async function runSync(): Promise<void> {
  await jsonOrThrow(await fetch("/api/library/sync/run", { method: "POST" }));
}

export async function getCacheStats(): Promise<CacheStats> {
  return jsonOrThrow(await fetch("/api/library/cache/stats"));
}

export async function adoptCache(mountPath: string): Promise<void> {
  await jsonOrThrow(await fetch("/api/library/cache/adopt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mount_path: mountPath }),
  }));
}

export async function clearStreamedCache(): Promise<{ cleared: number }> {
  return jsonOrThrow(await fetch("/api/library/cache/clear", { method: "POST" }));
}

export async function triggerStreamedCacheDownload(trackId: string): Promise<void> {
  await jsonOrThrow(await fetch(
    `/api/library/cache/streamed?id=${encodeURIComponent(trackId)}`,
    { method: "POST" },
  ));
}

export async function getCacheCandidates(): Promise<CacheCandidate[]> {
  const body = await jsonOrThrow<{ candidates: CacheCandidate[] }>(
    await fetch("/api/library/cache/candidates"),
  );
  return body.candidates;
}

export async function getResolver(trackId: string): Promise<PlaybackResolution> {
  return jsonOrThrow(await fetch(
    `/api/library/track/${encodeURIComponent(trackId)}/playback`,
  ));
}
```

- [ ] **Step 4: Run tests to verify**

```bash
cd /Users/jwc/code/Boombox/ui
npx vitest run src/lib/__tests__/libraryApi.test.ts
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/libraryApi.ts ui/src/lib/__tests__/libraryApi.test.ts
git commit -m "feat(ui): typed libraryApi client for /api/library/*"
```

---

### Task 10: `homeLibrary.ts` — pub/sub store + React hooks

**Files:**
- Create: `ui/src/lib/homeLibrary.ts`
- Create: `ui/src/lib/__tests__/homeLibrary.test.ts`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/homeLibrary.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { _resetForTests, useSyncStatus, useCacheStats, applyHealth, applyCacheStats } from "../homeLibrary";

beforeEach(() => { _resetForTests(); });

describe("homeLibrary store", () => {
  it("useSyncStatus reflects latest health snapshot", () => {
    const { result } = renderHook(() => useSyncStatus());
    expect(result.current.reachable).toBe(false);
    act(() => {
      applyHealth({
        service_version: "0.1", navidrome_reachable: true, cache_present: true,
        cache_mount: "/m", last_sync_ts: 100, syncing: false,
      });
    });
    expect(result.current.reachable).toBe(true);
    expect(result.current.lastSyncTs).toBe(100);
  });

  it("useCacheStats publishes on update", () => {
    const { result } = renderHook(() => useCacheStats());
    expect(result.current).toBeNull();
    act(() => {
      applyCacheStats({
        present: true, mount_path: "/m", capacity: 100, free: 50,
        pinned_bytes: 10, streamed_bytes: 20, reserved: 5,
      });
    });
    expect(result.current?.free).toBe(50);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/lib/__tests__/homeLibrary.test.ts
```

Expected: Cannot find module `../homeLibrary`.

- [ ] **Step 3: Implement `homeLibrary.ts`**

Create `ui/src/lib/homeLibrary.ts`:

```ts
// homeLibrary — module-level pub/sub for the Phase 2 Home Library state
// (sync status, cache stats). Mirrors favorites.ts in shape; backed by
// periodic polling of /api/library/health + /api/library/cache/stats
// rather than localStorage (state lives server-side).
//
// Components subscribe via the React hooks; any apply*() call publishes
// to every subscriber so the chrome chip, the SettingsDrawer panels,
// the status badges on rows, etc. all stay in lockstep without each
// running its own poll.

import { useEffect, useState } from "react";
import {
  getCacheStats,
  getHealth,
  type CacheStats,
  type Health,
} from "./libraryApi";

export type SyncStatus = {
  reachable: boolean;
  lastSyncTs: number;
  syncing: boolean;
  cachePresent: boolean;
  cacheMount: string | null;
};

const EMPTY_SYNC: SyncStatus = {
  reachable: false, lastSyncTs: 0, syncing: false,
  cachePresent: false, cacheMount: null,
};

let _sync: SyncStatus = EMPTY_SYNC;
let _stats: CacheStats | null = null;

const _syncSubs = new Set<(s: SyncStatus) => void>();
const _statsSubs = new Set<(s: CacheStats | null) => void>();

let _pollHandle: number | null = null;
let _pollRefs = 0;          // ref-count: only one poll loop runs

function publishSync() {
  for (const s of _syncSubs) s(_sync);
}
function publishStats() {
  for (const s of _statsSubs) s(_stats);
}

export function applyHealth(h: Health): void {
  _sync = {
    reachable: h.navidrome_reachable,
    lastSyncTs: h.last_sync_ts,
    syncing: h.syncing,
    cachePresent: h.cache_present,
    cacheMount: h.cache_mount,
  };
  publishSync();
}

export function applyCacheStats(s: CacheStats | null): void {
  _stats = s;
  publishStats();
}

async function pollOnce(): Promise<void> {
  try { applyHealth(await getHealth()); } catch { /* leave previous */ }
  try { applyCacheStats(await getCacheStats()); } catch { applyCacheStats(null); }
}

function startPolling() {
  if (_pollHandle !== null) return;
  pollOnce();
  _pollHandle = window.setInterval(pollOnce, 5000);
}

function stopPolling() {
  if (_pollHandle !== null) {
    window.clearInterval(_pollHandle);
    _pollHandle = null;
  }
}

/** Subscribe to the global sync status. The poller starts on first
 * subscriber and stops when the last one unmounts (ref-counted). */
export function useSyncStatus(): SyncStatus {
  const [state, setState] = useState<SyncStatus>(_sync);
  useEffect(() => {
    const sub = (s: SyncStatus) => setState(s);
    _syncSubs.add(sub);
    _pollRefs += 1;
    if (_pollRefs === 1) startPolling();
    return () => {
      _syncSubs.delete(sub);
      _pollRefs -= 1;
      if (_pollRefs === 0) stopPolling();
    };
  }, []);
  return state;
}

/** Subscribe to current cache stats. Same ref-counted poll as useSyncStatus. */
export function useCacheStats(): CacheStats | null {
  const [state, setState] = useState<CacheStats | null>(_stats);
  useEffect(() => {
    const sub = (s: CacheStats | null) => setState(s);
    _statsSubs.add(sub);
    _pollRefs += 1;
    if (_pollRefs === 1) startPolling();
    return () => {
      _statsSubs.delete(sub);
      _pollRefs -= 1;
      if (_pollRefs === 0) stopPolling();
    };
  }, []);
  return state;
}

/** Force a single refresh (e.g., right after a Save in LibraryPanel). */
export function refreshNow(): Promise<void> {
  return pollOnce();
}

// Used by Vitest tests to reset between cases.
export function _resetForTests(): void {
  _sync = EMPTY_SYNC; _stats = null;
  _syncSubs.clear(); _statsSubs.clear();
  if (_pollHandle !== null) { window.clearInterval(_pollHandle); _pollHandle = null; }
  _pollRefs = 0;
}
```

- [ ] **Step 4: Run tests to verify**

```bash
npx vitest run src/lib/__tests__/homeLibrary.test.ts
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/homeLibrary.ts ui/src/lib/__tests__/homeLibrary.test.ts
git commit -m "feat(ui): homeLibrary pub/sub store + useSyncStatus/useCacheStats hooks"
```

---

### Task 11: `StatusBadge.tsx`

**Files:**
- Create: `ui/src/lib/StatusBadge.tsx`
- Create: `ui/src/lib/__tests__/StatusBadge.test.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/StatusBadge.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders ⬇ for cached (present + not playing)", () => {
    const { container } = render(<StatusBadge cacheStatus="present" isCurrentTrack={false} pinned={false} />);
    expect(container.textContent).toContain("⬇");
  });

  it("renders ⚡ when streaming (isCurrentTrack + absent)", () => {
    const { container } = render(<StatusBadge cacheStatus="absent" isCurrentTrack={true} pinned={false} />);
    expect(container.textContent).toContain("⚡");
  });

  it("renders 📌 when pinned and not yet downloaded", () => {
    const { container } = render(<StatusBadge cacheStatus="queued" isCurrentTrack={false} pinned={true} />);
    expect(container.textContent).toContain("📌");
  });

  it("renders ☁ for catalog-only (absent, not playing, not pinned)", () => {
    const { container } = render(<StatusBadge cacheStatus="absent" isCurrentTrack={false} pinned={false} />);
    expect(container.textContent).toContain("☁");
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/lib/__tests__/StatusBadge.test.tsx
```

Expected: Cannot find module.

- [ ] **Step 3: Implement `StatusBadge.tsx`**

Create `ui/src/lib/StatusBadge.tsx`:

```tsx
// StatusBadge — inline glyph for Home Library track rows.
// Tells the user at a glance whether a track is pinned, cached, streaming
// right now, or catalog-only. Pure presentational; no state of its own.

type CacheStatus = "present" | "absent" | "queued" | "downloading" | "error";

type Props = {
  cacheStatus: CacheStatus;
  isCurrentTrack: boolean;   // currently playing AND streaming
  pinned: boolean;
};

export function StatusBadge({ cacheStatus, isCurrentTrack, pinned }: Props) {
  // Resolution priority: ⚡ (live stream) > 📌 (pinned, downloading) > ⬇ (cached) > ☁ (catalog).
  let glyph = "";
  let title = "";
  if (isCurrentTrack && cacheStatus !== "present") {
    glyph = "⚡"; title = "Streaming";
  } else if (pinned && cacheStatus !== "present") {
    glyph = "📌"; title = "Pinned · download pending";
  } else if (cacheStatus === "present") {
    glyph = "⬇"; title = pinned ? "Pinned · cached" : "Cached";
  } else if (cacheStatus === "error") {
    glyph = "⚠"; title = "Download error";
  } else {
    glyph = "☁"; title = "Catalog only";
  }
  return (
    <span
      title={title}
      aria-label={title}
      style={{
        display: "inline-grid",
        placeItems: "center",
        width: 20, height: 20,
        fontSize: 12,
        opacity: 0.85,
        flexShrink: 0,
      }}
    >{glyph}</span>
  );
}
```

- [ ] **Step 4: Run test to verify**

```bash
npx vitest run src/lib/__tests__/StatusBadge.test.tsx
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/StatusBadge.tsx ui/src/lib/__tests__/StatusBadge.test.tsx
git commit -m "feat(ui): StatusBadge inline glyph for track rows"
```

---

### Task 12: `PinButton.tsx`

**Files:**
- Create: `ui/src/lib/PinButton.tsx`
- Create: `ui/src/lib/__tests__/PinButton.test.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/PinButton.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { PinButton } from "../PinButton";

describe("PinButton", () => {
  it("renders unpinned state with outline icon", () => {
    const { getByRole } = render(
      <PinButton kind="album" id="al1" state="unpinned" onTogglePin={() => {}} />
    );
    const btn = getByRole("button");
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  it("renders cached state with check overlay", () => {
    const { container } = render(
      <PinButton kind="album" id="al1" state="cached" onTogglePin={() => {}} />
    );
    expect(container.textContent).toContain("✓");
  });

  it("renders error state", () => {
    const { container } = render(
      <PinButton kind="album" id="al1" state="error" onTogglePin={() => {}} />
    );
    expect(container.textContent).toContain("⚠");
  });

  it("calls onTogglePin on click", () => {
    const cb = vi.fn();
    const { getByRole } = render(
      <PinButton kind="album" id="al1" state="unpinned" onTogglePin={cb} />
    );
    fireEvent.click(getByRole("button"));
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("touch target is at least 44 × 44 px", () => {
    const { getByRole } = render(
      <PinButton kind="album" id="al1" state="unpinned" onTogglePin={() => {}} />
    );
    const btn = getByRole("button") as HTMLButtonElement;
    expect(parseInt(btn.style.minWidth, 10)).toBeGreaterThanOrEqual(44);
    expect(parseInt(btn.style.minHeight, 10)).toBeGreaterThanOrEqual(44);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/lib/__tests__/PinButton.test.tsx
```

Expected: module not found.

- [ ] **Step 3: Implement `PinButton.tsx`**

Create `ui/src/lib/PinButton.tsx`:

```tsx
// PinButton — pin/unpin affordance for Home Library album/artist/playlist
// detail rows. Four visual states; long-press for "manage pin" sheet.
//
// Touch targets are ≥ 44 × 44 px for the 5″ resistive kiosk.

import { useRef } from "react";
import type { PinKind } from "./libraryApi";

export type PinButtonState =
  | "unpinned"
  | "downloading"
  | "cached"
  | "error";

type Props = {
  kind: PinKind;
  id: string;
  state: PinButtonState;
  /** 0..1 download progress; only shown in downloading state. */
  progress?: number;
  onTogglePin: () => void;
  onLongPress?: () => void;
};

const LONG_PRESS_MS = 500;

export function PinButton({ state, progress, onTogglePin, onLongPress }: Props) {
  const downTs = useRef<number | null>(null);
  const triggered = useRef(false);
  const timer = useRef<number | null>(null);

  const startPress = () => {
    triggered.current = false;
    downTs.current = Date.now();
    if (onLongPress) {
      timer.current = window.setTimeout(() => {
        triggered.current = true;
        onLongPress();
      }, LONG_PRESS_MS);
    }
  };
  const endPress = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    if (!triggered.current) onTogglePin();
    downTs.current = null;
  };
  const cancelPress = () => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    triggered.current = true; // suppress click
    downTs.current = null;
  };

  const filled = state !== "unpinned";
  const fillColor =
    state === "error" ? "#ff7a35" :
    state === "downloading" ? "#5be7ff" :
    state === "cached" ? "#9bf2c0" :
    "rgba(255,255,255,0.35)";

  return (
    <button
      type="button"
      aria-label={filled ? "Unpin" : "Pin for offline"}
      aria-pressed={filled}
      onPointerDown={startPress}
      onPointerUp={endPress}
      onPointerLeave={cancelPress}
      onPointerCancel={cancelPress}
      style={{
        width: 44, height: 44, minWidth: 44, minHeight: 44,
        display: "grid", placeItems: "center",
        background: "transparent",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 999,
        cursor: "pointer",
        position: "relative",
        flexShrink: 0,
        color: fillColor,
      }}
    >
      {/* Pin icon — filled when any non-unpinned state */}
      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M14 2 L18 6 L14 10 L13 9 L9 13 L11 15 L7 19 L5 17 L9 13 L7 11 L11 7 L10 6 Z"
          fill={filled ? "currentColor" : "none"}
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>

      {state === "downloading" && (
        <span style={{
          position: "absolute", inset: -2,
          borderRadius: 999,
          border: "2px solid rgba(91,231,255,0.25)",
          borderTopColor: "#5be7ff",
          animation: "boombox-pin-spin 0.9s linear infinite",
          pointerEvents: "none",
        }}>
          <span style={{
            position: "absolute", inset: 0, display: "grid", placeItems: "center",
            fontSize: 9, color: "#5be7ff", fontFamily: "'JetBrains Mono', monospace",
          }}>{progress != null ? `${Math.round(progress * 100)}` : ""}</span>
        </span>
      )}

      {state === "cached" && (
        <span style={{
          position: "absolute", right: 2, bottom: 2,
          width: 14, height: 14, borderRadius: 999,
          background: "#9bf2c0", color: "#0a0a0a",
          display: "grid", placeItems: "center",
          fontSize: 10, fontWeight: 700,
        }}>✓</span>
      )}

      {state === "error" && (
        <span style={{
          position: "absolute", right: 2, bottom: 2,
          width: 14, height: 14, borderRadius: 999,
          background: "#ff7a35", color: "#0a0a0a",
          display: "grid", placeItems: "center",
          fontSize: 10, fontWeight: 700,
        }}>⚠</span>
      )}
    </button>
  );
}
```

- [ ] **Step 4: Add the keyframes once globally**

Append to `ui/src/index.css` (create the file if it doesn't already contain a similar definition):

```css
@keyframes boombox-pin-spin {
  to { transform: rotate(360deg); }
}
```

(If `ui/src/index.css` doesn't exist, check `ui/src/main.tsx` for the CSS import — append to whatever stylesheet is imported there.)

- [ ] **Step 5: Run test to verify**

```bash
npx vitest run src/lib/__tests__/PinButton.test.tsx
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/PinButton.tsx ui/src/lib/__tests__/PinButton.test.tsx ui/src/index.css
git commit -m "feat(ui): PinButton with 4 visual states + long-press"
```

---

### Task 13: `SyncIndicator.tsx` + ChromeButtons integration

**Files:**
- Create: `ui/src/lib/SyncIndicator.tsx`
- Create: `ui/src/lib/__tests__/SyncIndicator.test.tsx`
- Modify: `ui/src/lib/ChromeButtons.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/SyncIndicator.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, act } from "@testing-library/react";
import { SyncIndicator } from "../SyncIndicator";
import { _resetForTests, applyHealth } from "../homeLibrary";

function setHealth(opts: Partial<{ reachable: boolean; syncing: boolean; lastSync: number; cachePresent: boolean }>) {
  applyHealth({
    service_version: "0.1",
    navidrome_reachable: opts.reachable ?? false,
    syncing: opts.syncing ?? false,
    last_sync_ts: opts.lastSync ?? 0,
    cache_present: opts.cachePresent ?? false,
    cache_mount: null,
  });
}

describe("SyncIndicator", () => {
  beforeEach(() => { _resetForTests(); });

  it("renders grey when source not configured (lastSync=0, unreachable)", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("offline");
  });

  it("renders green when reachable + recent sync", () => {
    const { getByLabelText, rerender } = render(<SyncIndicator />);
    act(() => setHealth({ reachable: true, lastSync: Date.now() / 1000 }));
    rerender(<SyncIndicator />);
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("online_idle");
  });

  it("renders amber when syncing", () => {
    const { getByLabelText, rerender } = render(<SyncIndicator />);
    act(() => setHealth({ reachable: true, syncing: true }));
    rerender(<SyncIndicator />);
    expect(getByLabelText(/sync/i).getAttribute("data-state")).toBe("syncing");
  });

  it("tapping dispatches boombox:open-settings-library", () => {
    const { getByLabelText } = render(<SyncIndicator />);
    let fired = false;
    window.addEventListener("boombox:open-settings-library", () => { fired = true; });
    getByLabelText(/sync/i).dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(fired).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/lib/__tests__/SyncIndicator.test.tsx
```

Expected: module not found.

- [ ] **Step 3: Implement `SyncIndicator.tsx`**

Create `ui/src/lib/SyncIndicator.tsx`:

```tsx
// SyncIndicator — 16 px dot in the chrome that reflects Home Library sync state.
//
//   green   = reachable AND fresh sync (< 2× sync.interval)
//   amber   = syncing (pulse)
//   blue    = reachable + cache present but no successful sync yet (initial)
//   grey    = unreachable OR no source configured (initial state)
//   red     = service down (handled by upstream poll failure → store stays empty)
//
// Tap → dispatches boombox:open-settings-library which the SettingsDrawer
// listens for to auto-open scrolled to the Library panel.

import { useSyncStatus } from "./homeLibrary";

const STATE_COLOR: Record<string, string> = {
  online_idle: "#9bf2c0",
  syncing:     "#ffb84d",
  online_due:  "#5be7ff",
  offline:     "rgba(255,255,255,0.35)",
  error:       "#ff7a35",
};

function computeState(s: ReturnType<typeof useSyncStatus>): keyof typeof STATE_COLOR {
  if (s.syncing) return "syncing";
  if (!s.reachable && s.lastSyncTs === 0) return "offline";
  if (s.reachable && s.lastSyncTs > 0) return "online_idle";
  if (s.reachable) return "online_due";
  return "offline";
}

export function SyncIndicator() {
  const status = useSyncStatus();
  const state = computeState(status);

  const open = () => {
    window.dispatchEvent(new CustomEvent("boombox:open-settings-library"));
  };

  return (
    <button
      onClick={open}
      aria-label={`Sync · ${state.replace("_", " ")}`}
      data-state={state}
      style={{
        width: 44, height: 44, minWidth: 44, minHeight: 44,
        border: "1.5px solid rgba(255,255,255,0.20)",
        borderRadius: 999,
        background: "rgba(255,255,255,0.06)",
        display: "grid", placeItems: "center",
        cursor: "pointer",
        flexShrink: 0,
      }}
    >
      <span style={{
        width: 12, height: 12, borderRadius: 999,
        background: STATE_COLOR[state],
        boxShadow: state === "syncing" ? "0 0 8px currentColor" : "none",
        color: STATE_COLOR[state],
        animation: state === "syncing" ? "boombox-sync-pulse 1.4s ease-in-out infinite" : "none",
      }}/>
    </button>
  );
}
```

Append to `ui/src/index.css`:

```css
@keyframes boombox-sync-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
```

- [ ] **Step 4: Mount in `ChromeButtons.tsx`**

Edit `ui/src/lib/ChromeButtons.tsx`. Add an import:

```tsx
import { SyncIndicator } from "./SyncIndicator";
```

Replace `ChromeButtons` (the default 3-button strip) to slot the indicator between Source and Queue/Skin:

```tsx
export function ChromeButtons({
  chrome, theme: t = {}, children, align = "spread",
}: {
  chrome: ChromeApi;
  theme?: ChromeTheme;
  children?: ReactNode;
  align?: "spread" | "left" | "right" | "center";
}) {
  const justify =
    align === "left" ? "flex-start"
    : align === "right" ? "flex-end"
    : align === "center" ? "center"
    : "space-between";
  return (
    <div style={{display: "flex", alignItems: "center", gap: 10, justifyContent: justify, width: "100%"}}>
      <ChromeSourceBtn chrome={chrome} theme={t}/>
      <SyncIndicator />
      {children}
      <div style={{display: "flex", gap: 10}}>
        <ChromeQueueBtn chrome={chrome} theme={t}/>
        <ChromeSkinBtn chrome={chrome} theme={t}/>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests + commit**

```bash
npx vitest run src/lib/__tests__/SyncIndicator.test.tsx
```

Expected: green.

```bash
git add ui/src/lib/SyncIndicator.tsx ui/src/lib/__tests__/SyncIndicator.test.tsx ui/src/lib/ChromeButtons.tsx ui/src/index.css
git commit -m "feat(ui): SyncIndicator chrome chip wired to homeLibrary"
```

---

### Task 14: `LibraryPanel.tsx`

**Files:**
- Create: `ui/src/lib/LibraryPanel.tsx`
- Create: `ui/src/lib/__tests__/LibraryPanel.test.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/LibraryPanel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { LibraryPanel } from "../LibraryPanel";
import * as api from "../libraryApi";
import { _resetForTests } from "../homeLibrary";

const realFetch = globalThis.fetch;
beforeEach(() => {
  _resetForTests();
  vi.spyOn(api, "getHealth").mockResolvedValue({
    service_version: "0.1", navidrome_reachable: true, cache_present: false,
    cache_mount: null, last_sync_ts: 0, syncing: false,
  });
  vi.spyOn(api, "getCacheStats").mockResolvedValue({
    present: false, mount_path: null, capacity: 0, free: 0,
    pinned_bytes: 0, streamed_bytes: 0, reserved: 0,
  });
  vi.spyOn(api, "getSource").mockResolvedValue({ url: "http://nav:4533", username: "u" });
  vi.spyOn(api, "putSource").mockResolvedValue({ ok: true });
  vi.spyOn(api, "testSource").mockResolvedValue({ ok: true });
  vi.spyOn(api, "runSync").mockResolvedValue();
});
afterEach(() => { vi.restoreAllMocks(); globalThis.fetch = realFetch; });

describe("LibraryPanel", () => {
  it("renders source form populated from GET /source (no password)", async () => {
    const { findByDisplayValue, queryByDisplayValue } = render(<LibraryPanel />);
    await findByDisplayValue("http://nav:4533");
    await findByDisplayValue("u");
    // Password field is empty (never echoed back)
    expect(queryByDisplayValue(/secret/i)).toBeNull();
  });

  it("Save calls putSource and triggers sync", async () => {
    const { findByText, container } = render(<LibraryPanel />);
    await findByText(/Save/i);
    const url = container.querySelector('input[type="url"]') as HTMLInputElement;
    const user = container.querySelector('input[name="username"]') as HTMLInputElement;
    const pw = container.querySelector('input[type="password"]') as HTMLInputElement;
    fireEvent.change(url, { target: { value: "http://nav:4533" } });
    fireEvent.change(user, { target: { value: "u" } });
    fireEvent.change(pw, { target: { value: "p" } });
    fireEvent.click(await findByText(/Save/i));
    await waitFor(() => expect(api.putSource).toHaveBeenCalledWith({
      url: "http://nav:4533", username: "u", password: "p",
    }));
  });

  it("Test button surfaces backend error", async () => {
    (api.testSource as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: false, error: "auth: wrong password" });
    const { findByText, getByText } = render(<LibraryPanel />);
    fireEvent.click(await findByText(/Test/i));
    await waitFor(() => getByText(/wrong password/i));
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/lib/__tests__/LibraryPanel.test.tsx
```

Expected: module not found.

- [ ] **Step 3: Implement `LibraryPanel.tsx`**

Create `ui/src/lib/LibraryPanel.tsx`:

```tsx
// LibraryPanel — SettingsDrawer section for Home Library source config.
// Mirrors UpdatesPanel.tsx in layout: 5 s health poll, inline errors,
// touch-friendly Test/Save/Sync buttons.

import { useEffect, useState } from "react";
import {
  getSource, putSource, testSource, runSync,
  type SourceConfig,
} from "./libraryApi";
import { useSyncStatus, refreshNow } from "./homeLibrary";

function fmtAgo(ts: number): string {
  if (!ts) return "never";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export function LibraryPanel() {
  const status = useSyncStatus();
  const [form, setForm] = useState<SourceConfig & { password: string }>(
    { url: "", username: "", password: "" }
  );
  const [busy, setBusy] = useState<"" | "test" | "save" | "sync">("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    getSource().then(s => setForm(f => ({ ...f, url: s.url, username: s.username })))
               .catch(() => { /* surface via status */ });
  }, []);

  const update = (patch: Partial<typeof form>) => setForm(f => ({ ...f, ...patch }));

  const doTest = async () => {
    setBusy("test"); setMsg(null);
    try {
      const r = await testSource(form);
      setMsg(r.ok ? { kind: "ok", text: "Connected" } : { kind: "err", text: r.error || "Failed" });
    } finally { setBusy(""); }
  };
  const doSave = async () => {
    setBusy("save"); setMsg(null);
    try {
      await putSource(form);
      setMsg({ kind: "ok", text: "Saved · syncing…" });
      await refreshNow();
    } catch (e) {
      setMsg({ kind: "err", text: String(e instanceof Error ? e.message : e) });
    } finally { setBusy(""); }
  };
  const doSync = async () => {
    setBusy("sync"); setMsg(null);
    try { await runSync(); await refreshNow(); }
    catch (e) { setMsg({ kind: "err", text: String(e) }); }
    finally { setBusy(""); }
  };

  const dotColor =
    status.syncing ? "#ffb84d" :
    status.reachable ? "#9bf2c0" :
    "rgba(255,255,255,0.35)";

  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>Home Library</div>

      <div style={{ display: "grid", gap: 8, marginBottom: 10 }}>
        <label style={labelStyle}>
          <span>Source URL</span>
          <input
            type="url"
            value={form.url}
            placeholder="http://192.168.1.223:4533"
            onChange={(e) => update({ url: e.target.value })}
            style={inputStyle}
          />
        </label>
        <label style={labelStyle}>
          <span>Username</span>
          <input
            name="username"
            value={form.username}
            onChange={(e) => update({ username: e.target.value })}
            style={inputStyle}
          />
        </label>
        <label style={labelStyle}>
          <span>Password</span>
          <input
            type="password"
            value={form.password}
            onChange={(e) => update({ password: e.target.value })}
            placeholder="••••••••"
            style={inputStyle}
          />
        </label>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          width: 10, height: 10, borderRadius: 999, background: dotColor,
        }}/>
        <span style={{ fontSize: 13, color: "rgba(255,255,255,0.78)" }}>
          {status.syncing
            ? "Syncing…"
            : status.reachable
              ? `Connected · last sync ${fmtAgo(status.lastSyncTs)}`
              : "Library unreachable"}
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button disabled={!!busy} onClick={doTest} style={btn("rgba(255,255,255,0.10)")}>
          {busy === "test" ? "Testing…" : "Test"}
        </button>
        <button disabled={!!busy} onClick={doSave} style={btn("#5be7ff")}>
          {busy === "save" ? "Saving…" : "Save"}
        </button>
        <button disabled={!!busy} onClick={doSync} style={btn("rgba(255,255,255,0.10)")}>
          {busy === "sync" ? "Syncing…" : "Sync now"}
        </button>
      </div>

      {msg && (
        <div style={{
          marginTop: 8, fontSize: 13,
          color: msg.kind === "ok" ? "#9bf2c0" : "#ff7a35",
        }}>{msg.kind === "ok" ? "✓ " : "✗ "}{msg.text}</div>
      )}
    </div>
  );
}

const labelStyle = {
  display: "grid", gridTemplateColumns: "110px 1fr", alignItems: "center", gap: 10,
  fontSize: 13, color: "rgba(255,255,255,0.78)",
} as const;
const inputStyle = {
  padding: "10px 12px", minHeight: 44,
  background: "rgba(255,255,255,0.06)",
  color: "#fff",
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: 8,
  fontSize: 14,
  fontFamily: "Inter, system-ui, sans-serif",
  outline: "none",
} as const;
function btn(bg: string) {
  return {
    padding: "10px 14px", minHeight: 44,
    background: bg, color: bg === "rgba(255,255,255,0.10)" ? "#fff" : "#000",
    border: "none", borderRadius: 999,
    fontWeight: 700, fontSize: 13, letterSpacing: "0.06em",
    cursor: "pointer",
  } as const;
}
```

- [ ] **Step 4: Run test to verify**

```bash
npx vitest run src/lib/__tests__/LibraryPanel.test.tsx
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/LibraryPanel.tsx ui/src/lib/__tests__/LibraryPanel.test.tsx
git commit -m "feat(ui): LibraryPanel — source form with Test/Save/Sync"
```

---

### Task 15: `CachePanel.tsx`

**Files:**
- Create: `ui/src/lib/CachePanel.tsx`
- Create: `ui/src/lib/__tests__/CachePanel.test.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/lib/__tests__/CachePanel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor, act } from "@testing-library/react";
import { CachePanel } from "../CachePanel";
import { _resetForTests, applyCacheStats } from "../homeLibrary";
import * as api from "../libraryApi";

beforeEach(() => {
  _resetForTests();
  vi.spyOn(api, "clearStreamedCache").mockResolvedValue({ cleared: 0 });
});
afterEach(() => vi.restoreAllMocks());

describe("CachePanel", () => {
  it("renders 'cache drive offline' when stats.present=false", () => {
    const { getByText } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: false, mount_path: null,
      capacity: 0, free: 0, pinned_bytes: 0, streamed_bytes: 0, reserved: 0,
    }));
    getByText(/Cache drive offline/i);
  });

  it("stacked bar widths sum to 100% (within rounding)", () => {
    const { container } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: true, mount_path: "/m",
      capacity: 100, free: 50, pinned_bytes: 30, streamed_bytes: 15, reserved: 5,
    }));
    const segs = Array.from(container.querySelectorAll('[data-cache-seg]')) as HTMLElement[];
    const total = segs.reduce((s, el) => s + parseFloat(el.style.width), 0);
    expect(Math.round(total)).toBe(100);
  });

  it("Clear streamed cache button calls API", async () => {
    const { getByText } = render(<CachePanel />);
    act(() => applyCacheStats({
      present: true, mount_path: "/m",
      capacity: 100, free: 50, pinned_bytes: 30, streamed_bytes: 15, reserved: 5,
    }));
    fireEvent.click(getByText(/Clear streamed/i));
    await waitFor(() => expect(api.clearStreamedCache).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/lib/__tests__/CachePanel.test.tsx
```

Expected: not found.

- [ ] **Step 3: Implement `CachePanel.tsx`**

Create `ui/src/lib/CachePanel.tsx`:

```tsx
// CachePanel — SettingsDrawer section for the USB cache drive.
// Stacked bar (reserved | pinned | streamed | free), drive label,
// Clear-streamed button. Updates from the homeLibrary poll.

import { useState } from "react";
import { clearStreamedCache } from "./libraryApi";
import { refreshNow, useCacheStats, useSyncStatus } from "./homeLibrary";

function fmtGB(bytes: number): string {
  if (!bytes) return "0 GB";
  const gb = bytes / 1024 / 1024 / 1024;
  return gb >= 10 ? `${gb.toFixed(0)} GB` : `${gb.toFixed(1)} GB`;
}

export function CachePanel() {
  const stats = useCacheStats();
  const sync = useSyncStatus();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const onClear = async () => {
    if (!window.confirm("Clear all streamed (non-pinned) cache?")) return;
    setBusy(true); setMsg(null);
    try {
      const r = await clearStreamedCache();
      setMsg(`Cleared ${r.cleared} entries`);
      await refreshNow();
    } catch (e) {
      setMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  const present = stats?.present ?? sync.cachePresent;

  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 10 }}>Offline Cache</div>

      {!present || !stats ? (
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", padding: "8px 0" }}>
          ● Cache drive offline — plug in a USB drive to enable downloads
        </div>
      ) : (
        <>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.55)",
                        fontFamily: "'JetBrains Mono', monospace", marginBottom: 8 }}>
            {stats.mount_path ?? "drive"}
          </div>

          <StackedBar stats={stats} />

          <div style={{ display: "flex", gap: 14, fontSize: 12, marginTop: 8,
                        color: "rgba(255,255,255,0.7)", flexWrap: "wrap" }}>
            <Legend color="rgba(255,255,255,0.18)" label={`reserved ${fmtGB(stats.reserved)}`} />
            <Legend color="#9bf2c0" label={`pinned ${fmtGB(stats.pinned_bytes)}`} />
            <Legend color="#5be7ff" label={`streamed ${fmtGB(stats.streamed_bytes)}`} />
            <Legend color="rgba(255,255,255,0.10)" label={`free ${fmtGB(stats.free)}`} />
          </div>

          <div style={{ display: "flex", gap: 14, fontSize: 12, marginTop: 6,
                        color: "rgba(255,255,255,0.55)" }}>
            <span>Total {fmtGB(stats.capacity)}</span>
            <span>· Used {fmtGB(stats.capacity - stats.free)}</span>
            <span>· Free {fmtGB(stats.free)}</span>
          </div>

          <div style={{ marginTop: 10 }}>
            <button
              disabled={busy}
              onClick={onClear}
              style={{
                padding: "10px 14px", minHeight: 44,
                background: "rgba(255,255,255,0.10)", color: "#fff",
                border: "1px solid rgba(255,255,255,0.18)", borderRadius: 999,
                fontWeight: 700, fontSize: 13, letterSpacing: "0.06em",
                cursor: "pointer",
                opacity: busy ? 0.6 : 1,
              }}
            >{busy ? "Clearing…" : "Clear streamed cache"}</button>
            {msg && <span style={{ marginLeft: 10, fontSize: 13, color: "#9bf2c0" }}>{msg}</span>}
          </div>
        </>
      )}
    </div>
  );
}

function StackedBar({ stats }: { stats: NonNullable<ReturnType<typeof useCacheStats>> }) {
  const cap = Math.max(1, stats.capacity);
  const reserved = (stats.reserved / cap) * 100;
  const pinned   = (stats.pinned_bytes / cap) * 100;
  const streamed = (stats.streamed_bytes / cap) * 100;
  const free     = Math.max(0, 100 - reserved - pinned - streamed);
  return (
    <div style={{
      display: "flex", width: "100%", height: 14, borderRadius: 7,
      overflow: "hidden", background: "rgba(255,255,255,0.06)",
      border: "1px solid rgba(255,255,255,0.10)",
    }}>
      <span data-cache-seg style={{ width: `${reserved}%`, background: "rgba(255,255,255,0.18)" }}/>
      <span data-cache-seg style={{ width: `${pinned}%`,   background: "#9bf2c0" }}/>
      <span data-cache-seg style={{ width: `${streamed}%`, background: "#5be7ff" }}/>
      <span data-cache-seg style={{ width: `${free}%`,     background: "rgba(255,255,255,0.10)" }}/>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 2, background: color, border: "1px solid rgba(0,0,0,0.2)" }}/>
      {label}
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify**

```bash
npx vitest run src/lib/__tests__/CachePanel.test.tsx
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/CachePanel.tsx ui/src/lib/__tests__/CachePanel.test.tsx
git commit -m "feat(ui): CachePanel — stacked-bar cache stats + clear streamed"
```

---

### Task 16: Mount both panels in `SettingsDrawer`

**Files:**
- Modify: `ui/src/lib/SettingsDrawer.tsx`

- [ ] **Step 1: Import the new panels**

Edit `ui/src/lib/SettingsDrawer.tsx` near the top (after the `UpdatesPanel` import):

```tsx
import { LibraryPanel } from "./LibraryPanel";
import { CachePanel } from "./CachePanel";
```

- [ ] **Step 2: Add a ref for the library section + event listener**

Inside the `SettingsDrawer` function body (alongside the existing `useState`/`useRef` declarations near line 67):

```tsx
const libraryAnchor = useRef<HTMLDivElement | null>(null);
useEffect(() => {
  const onOpen = () => {
    libraryAnchor.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  window.addEventListener("boombox:open-settings-library", onOpen);
  return () => window.removeEventListener("boombox:open-settings-library", onOpen);
}, []);
```

- [ ] **Step 3: Render the panels above `<UpdatesPanel />`**

Find the line `{/* Software updates — channel, window, install, rollback */}` in `SettingsDrawer.tsx` (~line 591) and insert immediately before it:

```tsx
{/* Home Library (Phase 2) */}
<div ref={libraryAnchor}>
  <LibraryPanel />
  <CachePanel />
</div>
```

- [ ] **Step 4: Build the UI to verify it compiles**

```bash
cd /Users/jwc/code/Boombox/ui
npx tsc -b --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/SettingsDrawer.tsx
git commit -m "feat(ui): mount Library + Cache panels in SettingsDrawer"
```

---

### Task 17: `LibraryDrawer` — add Home Library root + route `home:*` through `libraryApi`

**Files:**
- Modify: `ui/src/lib/library.ts`
- Modify: `ui/src/lib/LibraryDrawer.tsx`

- [ ] **Step 1: Add Home Library to `ROOTS`**

In `ui/src/lib/library.ts:111-118`, add the new root entry above the Mopidy ones:

```ts
export const ROOTS: Ref[] = [
  { uri: "boombox:favorites",           name: "Favorites",     type: "directory" },
  { uri: "boombox:recent",              name: "Recent",        type: "directory" },
  { uri: "home:root",                   name: "Home Library",  type: "directory" },
  { uri: "boombox:radio",               name: "Radio",         type: "directory" },
  { uri: "local:directory?type=album",  name: "Albums",        type: "directory" },
  { uri: "local:directory?type=artist", name: "Artists",       type: "directory" },
  { uri: "local:directory?type=track",  name: "Tracks",        type: "directory" },
];
```

- [ ] **Step 2: Add a `home:*` browse helper**

Append to `ui/src/lib/library.ts`:

```ts
import * as libraryApi from "./libraryApi";

/** Browse a home:* URI by translating to libraryApi calls. */
export async function browseHomeLibrary(uri: string): Promise<Ref[]> {
  if (uri === "home:root") {
    return [
      { uri: "home:artists",      name: "Artists",      type: "directory" },
      { uri: "home:albums",       name: "Albums",       type: "directory" },
      { uri: "home:playlists",    name: "Playlists",    type: "directory" },
      { uri: "home:cached-only",  name: "Cached only",  type: "directory" },
    ];
  }
  if (uri === "home:artists") {
    const items = await libraryApi.browse("artists");
    return items.map(a => ({ uri: `home:artist:${a.id}`, name: a.name, type: "artist" as const }));
  }
  if (uri === "home:albums") {
    const items = await libraryApi.browse("albums");
    return items.map(a => ({ uri: `home:album:${a.id}`, name: a.name, type: "album" as const }));
  }
  if (uri === "home:playlists") {
    const items = await libraryApi.browse("playlists");
    return items.map(p => ({ uri: `home:playlist:${p.id}`, name: p.name, type: "playlist" as const }));
  }
  if (uri === "home:cached-only") {
    // Reuse the albums browse but filter on cache presence client-side via cache stats poll.
    // v1: show all albums; status badges on rows surface which are actually cached.
    // A dedicated server-side filter is Phase 3.
    const items = await libraryApi.browse("albums");
    return items.map(a => ({ uri: `home:album:${a.id}`, name: a.name, type: "album" as const }));
  }
  // Deeper drilldowns (home:album:X / home:artist:X) are handled by the
  // LibraryDrawer itself via getAlbum/getArtist style calls; for v1 we
  // leave the drilldown to a follow-up subtask so this initial wiring
  // is verifiable on its own.
  return [];
}
```

- [ ] **Step 3: Route `home:*` in `LibraryDrawer.tsx`**

Edit `ui/src/lib/LibraryDrawer.tsx`. Near the top of the file, add to the imports:

```tsx
import { browseHomeLibrary } from "./library";
```

In the existing `useEffect` that loads directory contents (the one that starts around line 84), insert a branch BEFORE the existing `} else {` final clause that calls `browse(hereUri)`:

```tsx
} else if (hereUri.startsWith("home:")) {
  const refs = await browseHomeLibrary(hereUri);
  if (cancelled) return;
  setItems(refs);
  setHistory(null);
  setRadio(null);
  setTracks(null);
}
```

- [ ] **Step 4: Build to verify**

```bash
cd /Users/jwc/code/Boombox/ui
npx tsc -b --noEmit
```

Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/library.ts ui/src/lib/LibraryDrawer.tsx
git commit -m "feat(ui): Home Library root in LibraryDrawer via /api/library/browse"
```

---

### Task 18: NowPlayingBar source badge

**Files:**
- Modify: `ui/src/lib/NowPlayingBar.tsx`

- [ ] **Step 1: Add a small `<SourceBadge/>` helper inside NowPlayingBar**

In `ui/src/lib/NowPlayingBar.tsx`, near the bottom (after the existing `TransportBtn` component), add:

```tsx
function SourceBadge({ uri, externalLabel }: { uri: string | null; externalLabel: string | null }) {
  let glyph = "🎵"; let label = "USB";
  if (externalLabel) {
    if (/airplay/i.test(externalLabel))      { glyph = "📱"; label = "AirPlay"; }
    else if (/spotify/i.test(externalLabel)) { glyph = "🎵"; label = "Spotify"; }
    else if (/bluetooth/i.test(externalLabel)){ glyph = "🎙"; label = "BT"; }
    else                                      { glyph = "🎵"; label = externalLabel; }
  } else if (uri) {
    if (uri.startsWith("file://"))           { glyph = "⬇"; label = "Cache"; }
    else if (uri.startsWith("subsonic:"))    { glyph = "⚡"; label = "Stream"; }
    else if (uri.startsWith("spotify:"))     { glyph = "🎵"; label = "Spotify"; }
    else if (uri.startsWith("local:"))       { glyph = "🎵"; label = "USB"; }
  }
  return (
    <span
      title={`Source · ${label}`}
      style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px",
        background: "rgba(255,255,255,0.08)",
        border: "1px solid rgba(255,255,255,0.14)",
        borderRadius: 999,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: "0.08em",
        color: "rgba(255,255,255,0.78)",
        flexShrink: 0,
      }}
    >
      <span aria-hidden="true">{glyph}</span>
      <span>{label.toUpperCase()}</span>
    </span>
  );
}
```

- [ ] **Step 2: Mount the badge next to the title**

In the same file, inside the title/transport block, between the title button and the transport row, add:

```tsx
<SourceBadge
  uri={externalActive ? null : (m.track?.uri ?? null)}
  externalLabel={externalActive ? (ext.label ?? ext.source) : null}
/>
```

Place it just before the `<div style={{display: "flex", alignItems: "center", gap: 4}}>` transport-button row (around line 89).

- [ ] **Step 3: Build to verify**

```bash
cd /Users/jwc/code/Boombox/ui
npx tsc -b --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/lib/NowPlayingBar.tsx
git commit -m "feat(ui): NowPlayingBar source badge (cache/stream/spotify/usb/airplay/bt)"
```

---

### Task 19: `favorites.ts` — auto-pin coupling for Home Library URIs

**Files:**
- Modify: `ui/src/lib/favorites.ts`

- [ ] **Step 1: Add subsonic-id parsing helper + auto-pin coupling**

Replace the body of `ui/src/lib/favorites.ts` with:

```ts
// Track favorites — localStorage-backed set of "I liked this" track URIs.
//
// Lives entirely client-side; no Mopidy plugin required. Subscribers (the
// favorite button + the Favorites library view) react instantly to changes
// since toggling publishes to all hooks.
//
// Phase 2: when the toggled URI is a Home Library track (subsonic:track:<id>
// canonical form, or a file:// URI we can map back), we ALSO call the
// libraryApi pin/unpin endpoints with source='favorite' so the heart and
// the offline pin stay in sync.

import { useEffect, useState } from "react";
import * as libraryApi from "./libraryApi";

const KEY = "boombox.favorites";

let _set: Set<string> = readPersisted();
const _subs = new Set<(s: ReadonlySet<string>) => void>();

function readPersisted(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return new Set(arr.filter((x): x is string => typeof x === "string"));
    return new Set();
  } catch { return new Set(); }
}

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify([..._set])); } catch { /* ignore */ }
}

function publish() {
  for (const s of _subs) s(_set);
}

/** Extract a Subsonic track id from a Mopidy / Home Library URI, or null. */
export function subsonicIdFromUri(uri: string | null | undefined): string | null {
  if (!uri) return null;
  if (uri.startsWith("subsonic:track:")) return uri.slice("subsonic:track:".length);
  // file:///cache-mount/audio/<id>.<suffix> — Phase 1 downloader names files
  // <track_id>.<suffix>, so basename-minus-suffix recovers the id.
  if (uri.startsWith("file://")) {
    const path = decodeURIComponent(uri.slice("file://".length));
    const base = path.split("/").pop() ?? "";
    const dot = base.lastIndexOf(".");
    if (dot > 0) return base.slice(0, dot);
  }
  return null;
}

export function isFavorite(uri: string | null | undefined): boolean {
  return !!uri && _set.has(uri);
}

export function toggleFavorite(uri: string | null | undefined): void {
  if (!uri) return;
  const next = new Set(_set);
  const becomingFavorite = !next.has(uri);
  if (becomingFavorite) next.add(uri); else next.delete(uri);
  _set = next;
  persist();
  publish();

  const subsonicId = subsonicIdFromUri(uri);
  if (subsonicId) {
    // Auto-pin/unpin with source='favorite'. Errors are swallowed — the heart
    // already toggled visually; the worst case is the offline pin drifts and
    // the next sync reconciles.
    if (becomingFavorite) {
      libraryApi.pin("track", subsonicId, "favorite").catch(() => { /* ignore */ });
    } else {
      libraryApi.unpin("track", subsonicId, "favorite").catch(() => { /* ignore */ });
    }
  }
}

export function getFavorites(): string[] {
  return [..._set];
}

/** React hook returning the set of favorite URIs. Re-renders on toggle. */
export function useFavorites(): ReadonlySet<string> {
  const [state, setState] = useState<ReadonlySet<string>>(_set);
  useEffect(() => {
    const sub = (s: ReadonlySet<string>) => setState(s);
    _subs.add(sub);
    return () => { _subs.delete(sub); };
  }, []);
  return state;
}
```

- [ ] **Step 2: Build to verify**

```bash
cd /Users/jwc/code/Boombox/ui
npx tsc -b --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/lib/favorites.ts
git commit -m "feat(ui): favorites auto-pin coupling for Home Library URIs"
```

---

### Task 20: `CacheAdoptOverlay.tsx` + App polling

**Files:**
- Create: `ui/src/overlays/CacheAdoptOverlay.tsx`
- Create: `ui/src/overlays/__tests__/CacheAdoptOverlay.test.tsx`
- Modify: `ui/src/overlays/OverlayRoot.tsx`
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/overlays/__tests__/CacheAdoptOverlay.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { CacheAdoptOverlay } from "../CacheAdoptOverlay";
import * as api from "../../lib/libraryApi";

beforeEach(() => {
  vi.spyOn(api, "adoptCache").mockResolvedValue();
});
afterEach(() => vi.restoreAllMocks());

function fire(detail: { mount_path: string; label: string; free_bytes: number | null; total_bytes: number | null }) {
  window.dispatchEvent(new CustomEvent("boombox:cache-candidate", { detail }));
}

describe("CacheAdoptOverlay", () => {
  it("shows the prompt when a candidate is announced", async () => {
    const { findByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/DRIVE_B", label: "DRIVE_B", free_bytes: 230e9, total_bytes: 250e9 });
    await findByText(/DRIVE_B/);
  });

  it("Yes button calls adoptCache and closes", async () => {
    const { findByText, queryByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/X", label: "X", free_bytes: null, total_bytes: null });
    fireEvent.click(await findByText(/Yes/i));
    await waitFor(() => expect(api.adoptCache).toHaveBeenCalledWith("/media/X"));
    await waitFor(() => expect(queryByText(/X/)).toBeNull());
  });

  it("No button closes without calling API", async () => {
    const { findByText, queryByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/Y", label: "Y", free_bytes: null, total_bytes: null });
    fireEvent.click(await findByText(/No, browse/i));
    expect(api.adoptCache).not.toHaveBeenCalled();
    await waitFor(() => expect(queryByText(/Y/)).toBeNull());
  });

  it("does not re-trigger after user dismissed the same drive", async () => {
    const { findByText, queryByText } = render(<CacheAdoptOverlay />);
    fire({ mount_path: "/media/Z", label: "Z", free_bytes: null, total_bytes: null });
    fireEvent.click(await findByText(/No, browse/i));
    fire({ mount_path: "/media/Z", label: "Z", free_bytes: null, total_bytes: null });
    expect(queryByText(/Z/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
npx vitest run src/overlays/__tests__/CacheAdoptOverlay.test.tsx
```

Expected: not found.

- [ ] **Step 3: Implement `CacheAdoptOverlay.tsx`**

Create `ui/src/overlays/CacheAdoptOverlay.tsx`:

```tsx
// CacheAdoptOverlay — modal that prompts the user to bless a fresh USB
// drive as the boombox offline cache.
//
// Trigger model: App.tsx polls /api/library/cache/candidates every 5 s
// and dispatches `boombox:cache-candidate` when it sees the first
// unadopted drive AND no cache is currently adopted. The overlay
// listens for that event so the polling logic stays in one place.
//
// Dismissal is per-mount-path: a "No" on /media/X suppresses the prompt
// for /media/X until the user replugs (path goes away then reappears).

import { useEffect, useState } from "react";
import { adoptCache } from "../lib/libraryApi";
import { refreshNow } from "../lib/homeLibrary";

type Candidate = {
  mount_path: string;
  label: string;
  free_bytes: number | null;
  total_bytes: number | null;
};

function fmtGB(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 / 1024 / 1024;
  return gb >= 10 ? `${gb.toFixed(0)} GB` : `${gb.toFixed(1)} GB`;
}

export function CacheAdoptOverlay() {
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const handler = (e: Event) => {
      const c = (e as CustomEvent).detail as Candidate;
      if (dismissed.has(c.mount_path)) return;
      setCandidate(c);
    };
    window.addEventListener("boombox:cache-candidate", handler as EventListener);
    return () => window.removeEventListener("boombox:cache-candidate", handler as EventListener);
  }, [dismissed]);

  if (!candidate) return null;

  const onYes = async () => {
    setBusy(true);
    try {
      await adoptCache(candidate.mount_path);
      await refreshNow();
      setCandidate(null);
    } catch { setCandidate(null); }
    finally { setBusy(false); }
  };
  const onNo = () => {
    setDismissed(s => { const next = new Set(s); next.add(candidate.mount_path); return next; });
    setCandidate(null);
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9998, padding: 32,
    }}>
      <div style={{
        maxWidth: 560, background: "#0a0a0a",
        border: "1px solid rgba(255,255,255,0.14)", borderRadius: 14,
        padding: 24, textAlign: "left",
      }}>
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>New drive detected</div>
        <div style={{ fontSize: 14, color: "rgba(255,255,255,0.7)", marginBottom: 14,
                      fontFamily: "'JetBrains Mono', monospace" }}>
          {candidate.label} · Free: {fmtGB(candidate.free_bytes)}
        </div>
        <div style={{ fontSize: 15, marginBottom: 18 }}>
          Use this as the boombox offline cache? Existing files on the drive stay where they are.
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button
            disabled={busy}
            onClick={onYes}
            style={{
              padding: "12px 18px", minHeight: 44,
              background: "#5be7ff", color: "#000",
              border: "none", borderRadius: 999,
              fontWeight: 700, fontSize: 13, letterSpacing: "0.08em",
              cursor: "pointer", opacity: busy ? 0.6 : 1,
            }}
          >{busy ? "ADOPTING…" : "YES, USE FOR CACHE"}</button>
          <button
            disabled={busy}
            onClick={onNo}
            style={{
              padding: "12px 18px", minHeight: 44,
              background: "rgba(255,255,255,0.08)", color: "#fff",
              border: "1px solid rgba(255,255,255,0.18)", borderRadius: 999,
              fontWeight: 700, fontSize: 13, letterSpacing: "0.08em",
              cursor: "pointer",
            }}
          >NO, BROWSE AS MEDIA</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Mount in `OverlayRoot.tsx`**

Edit `ui/src/overlays/OverlayRoot.tsx`:

```tsx
import { QrOverlay } from "./QrOverlay";
import { SleepOsd } from "./SleepOsd";
import { RecordIndicator } from "./RecordIndicator";
import { SourceInstructionOverlay } from "./SourceInstructionOverlay";
import { ShutdownOverlay } from "./ShutdownOverlay";
import { CacheAdoptOverlay } from "./CacheAdoptOverlay";

export function OverlayRoot() {
  return (
    <>
      <QrOverlay />
      <SleepOsd />
      <RecordIndicator />
      <SourceInstructionOverlay />
      <ShutdownOverlay />
      <CacheAdoptOverlay />
    </>
  );
}
```

- [ ] **Step 5: Add candidate polling to `App.tsx`**

Edit `ui/src/App.tsx`. Add an import near the other lib imports:

```tsx
import { getCacheCandidates } from "./lib/libraryApi";
import { useSyncStatus } from "./lib/homeLibrary";
```

Inside the `App` function body (after the queue-count effect, around line 60), add:

```tsx
const syncStatus = useSyncStatus();
useEffect(() => {
  // Only prompt when no drive is currently adopted — otherwise plugging a
  // second drive would steal the cache role.
  if (syncStatus.cachePresent) return;
  let cancelled = false;
  const tick = async () => {
    try {
      const cands = await getCacheCandidates();
      if (cancelled || cands.length === 0) return;
      window.dispatchEvent(new CustomEvent("boombox:cache-candidate", { detail: cands[0] }));
    } catch { /* offline / 404 — quiet */ }
  };
  tick();
  const id = setInterval(tick, 5000);
  return () => { cancelled = true; clearInterval(id); };
}, [syncStatus.cachePresent]);
```

- [ ] **Step 6: Run tests + build + commit**

```bash
cd /Users/jwc/code/Boombox/ui
npx vitest run src/overlays/__tests__/CacheAdoptOverlay.test.tsx
npx tsc -b --noEmit
```

Expected: green, no type errors.

```bash
git add ui/src/overlays/CacheAdoptOverlay.tsx ui/src/overlays/__tests__/CacheAdoptOverlay.test.tsx ui/src/overlays/OverlayRoot.tsx ui/src/App.tsx
git commit -m "feat(ui): CacheAdoptOverlay + App candidate poll"
```

---

### Task 21: Final integration — full UI test pass + manual smoke

**Files:**
- (no new code; verify and commit)

- [ ] **Step 1: Run all UI tests**

```bash
cd /Users/jwc/code/Boombox/ui
npx vitest run
```

Expected: every test green.

- [ ] **Step 2: Run all Python tests**

```bash
cd /Users/jwc/code/Boombox
pytest services/tests/ --ignore=services/tests/test_library_integration.py -q
```

Expected: green.

- [ ] **Step 3: Type-check + production build**

```bash
cd /Users/jwc/code/Boombox/ui
npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Lint**

```bash
cd /Users/jwc/code/Boombox/ui
npm run lint
```

Expected: clean.

- [ ] **Step 5: Final commit (only if there are residual fixes)**

If anything was tweaked during the verification pass:

```bash
git add -u
git commit -m "chore(library): Phase 2 final verification fixes"
```

---

## Self-review checklist

- **Spec coverage** — every spec §Decisions row maps to a task: Home Library root (T17), pin/favorite coexist + auto-pin (T1+T19), no track-level pin (T12 only renders on album/artist/playlist detail), two SettingsDrawer panels (T14+T15), header chrome chip (T13), cache adoption overlay (T20), Now Playing source badge (T18), status badges (T11), "cached only" view (T17 root entry), homeLibrary state hub (T10).
- **Open questions resolved** — Q1 `/cache/candidates`: implemented as Option A (cache_drive scans `/media`, exposes negative results); Q2 resolver back-mapping: `subsonicIdFromUri` parses `file://` basename per the lean from spec; Q3 polling cadence: single shared poll in `homeLibrary.ts` ref-counted across subscribers; Q4 Vitest: accepted (T8); Q6 favorites parallel-key: `subsonicIdFromUri` handles both `subsonic:track:<id>` and `file://` forms.
- **Bite-sized steps** — every step is a single action with concrete code/commands. No "TBD" / "TODO" placeholders.
- **TDD discipline** — every backend + presentational + panel task starts with a failing test and verifies it fails before implementation.
- **Touch targets** — every actionable control sized ≥ 44 × 44 px (PinButton, SyncIndicator, panel buttons).
- **Backend ordering** — Tasks 1–7 land first so the UI never codes against missing endpoints.
- **Phase 1 backwards compat** — `_pin` defaults `source=USER` so existing Phase 1 integration tests continue to pass; `unpin(kind,id)` without source still force-deletes.

---

**Plan complete.** Execution starts after this header is committed; each task above produces one atomic commit.
