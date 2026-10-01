# Offline Music + Storage Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The boombox plays every "kept" album / artist / playlist (plus everything starred in Navidrome) with the homelab unreachable: originals download to the internal drive (`/opt/boombox/storage/music`) under a Pi-friendly scheduler, the LAN app gets a **Keep offline** toggle with progress, an **Offline** banner with dimmed un-kept music, and an admin **Storage** page (drive, kept items, downloads, uploads).

**Architecture:** `boombox-library` adopts `cache.internal_path` as an always-present cache drive (preferred over `/media`), reads the reserve from config (20 GiB default), and its `DownloadQueue` becomes a scheduler with gates (offline / low space / hot SoC / Mopidy streaming) that never retries failures by itself (the hourly sync does). A new `keep.py` holds user-pin keep/unkeep (with starred/RFID fall-back so overlapping pins never orphan files), the `keep` + `offline` facts for detail/search responses, the Storage overview and Remove/Retry. `boombox-remote` proxies them as pair-token routes (`/api/remote/home/keep|status|offline`); `boombox-setup` serves the admin tier `/api/accounts/storage*` (proxy to the library + the moved upload/delete handlers from `remote_files`). `boombox-rfid` asks the library whether Navidrome is reachable so a card plays only kept tracks offline. remote-ui: Music section gains status/keep/dimming; new `#/storage` admin section; the household Files tab becomes read-only with a pointer to Storage.

**Tech Stack:** Python 3.11+ (aiohttp, sqlite3, pytest + pytest-aiohttp, `asyncio_mode = "auto"`), nginx, React 19 + TypeScript + Vite + Vitest (`remote-ui`).

**Spec:** `docs/superpowers/specs/2026-09-30-offline-music-design.md`

## Global Constraints

- Branch `feat/offline-music` (already checked out); never switch branches.
- Internal storage path: `cache.internal_path`, default **`/opt/boombox/storage/music`**, created **0755, owned by the boombox user**, adopted automatically with the `.boombox-cache` marker and `audio/ meta/ tmp/`; **preferred over `/media` drives**. A `/media` drive is adopted only when `internal_path: ""` (or the internal path is unusable — see Task 1).
- Reserve: `cache.reserve_bytes` default **20 GiB** (`21474836480`); the downloader reads it from config. A download that would cross it is skipped with status **`no_space`**; **hard stop** (no new download starts, and a running transfer aborts) whenever `free < reserve`.
- Scheduler (`DownloadQueue`): **≤ `sync.max_concurrent_downloads` (2) at a time**; **pause while Mopidy is playing a stream-proxy URI (`/api/library/stream/`)** — in-flight finish; **thermal backoff**: before each start read **`/sys/class/thermal/thermal_zone0/temp`**, **≥ 70 °C → wait 60 s and re-check**, absent file → no backoff; **offline**: Navidrome unreachable → the queue **idles** (no retry storms) and resumes when the reachability check succeeds; **failed** downloads keep `status = 'error'` with a reason and are **retried on the hourly sync only** (plus the admin's explicit "Retry failed"), never in a tight loop.
- Routes and JSON shapes (household tier, pair token, `boombox-remote` → `boombox-library`):
  - `POST /api/remote/home/keep {kind: "album"|"artist"|"playlist", id}` → pin(source=user) + enqueue its tracks → `{"ok": true, "queued": <int>, "keep": <KeepState>}`
  - `DELETE /api/remote/home/keep {kind, id}` → unpin(source=user), cancel queued orphan downloads → `{"ok": true, "cancelled": <int>, "keep": <KeepState>}`
  - `KeepState = {"state": "none"|"kept"|"starred", "tracks_total": <int>, "tracks_present": <int>}`
  - `GET /api/remote/home/{album|artist|playlist}/{id}` gain `"keep": KeepState`; every track gains `"offline": <bool>` (artist albums gain `"offline": <bool>`)
  - `GET /api/remote/home/status` → `{"online": <bool>, "internal_storage": <bool>}`
  - `GET /api/remote/home/offline` → `{"album_ids": [...], "artist_ids": [...], "playlist_ids": [...]}` (items with ≥ 1 track on disk; for dimming browse tiles)
  - search results gain `"offline": <bool>`
- Admin tier (`boombox-setup`, admin session + non-loopback, same gate as Accounts): `GET /api/accounts/storage`, `POST /api/accounts/storage/remove {kind, id}`, `POST /api/accounts/storage/retry {}`, `GET /api/accounts/storage/files/browse?path=`, `POST /api/accounts/storage/files/upload` (multipart), `POST /api/accounts/storage/files/delete {path}`. Household `POST /api/remote/files/upload|delete` → **403** `{"error": "uploading and deleting moved to Admin → Storage"}`; browse/download stay household.
- Storage overview shape (`GET /api/library/storage`, passed through by `/api/accounts/storage`):
  `{"drive": {"present", "internal", "mount_path", "total_bytes", "free_bytes", "reserve_bytes", "music_bytes", "kept_tracks"}, "kept": [{"kind", "id", "name", "source": "user"|"starred", "tracks_total", "tracks_present", "bytes"}], "downloads": {"active", "queued", "in_flight": [{"id", "title"}], "paused": null|"offline"|"low_space"|"hot"|"streaming", "failed", "no_space"}}`
- Hardware-optional rule: no thermal file, Mopidy down, Navidrome down, no drive, library down → degrade to a message / "no reason to wait", never a crash or a 500. Upstream failures map to **502 JSON** `{"ok": false, "error": "..."}`; **never 500** (this plan also removes `remote_files.delete`'s 500 path).
- Keep / unkeep / remove are **idempotent**; removing a kept item while its downloads run **cancels the queued ones** (in-flight finish).
- Python: `.venv/bin/python -m pytest -q services/tests`, `~/.local/bin/ruff check services`, `~/.local/bin/mypy` **and** explicit mypy on touched `services/boombox_setup` files and new/edited single-file services: `~/.local/bin/mypy --follow-imports=silent services/boombox_setup/storage.py services/boombox_setup/accounts.py services/boombox_setup/api.py services/remote_home.py services/remote_files.py`.
- UI: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`. `ui/` and `setup-ui/` are not touched.
- Deploy: build UIs on the Mac only, never on the Pi; deploy to MarkII only when it is **< 65 °C** and **not within 2 minutes of `:38`** (hourly library sync).
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Drive nearly full** — a download that would cross the 20 GiB reserve (after evicting unpinned streamed cache) is `no_space`, never half-written; a transfer that drops below the reserve mid-way aborts and removes its `.part`; the queue then stops starting downloads (`paused: "low_space"`) and the Storage page says so; uploads that hit a full disk answer 507, not 500. (Task 2 `test_download_skips_with_no_space_when_it_would_cross_the_reserve`, `test_out_of_space_mid_transfer_is_no_space_and_leaves_no_partial`, `test_guarded_fetch_aborts_when_free_space_drops`, `test_low_space_is_a_hard_stop_until_room_appears`; Task 5 `test_storage_overview_reports_downloads_and_no_space`; Task 8 `test_upload_disk_full_is_507_and_leaves_no_partial`; Task 10 "no space" UI test.)
2. **Homelab drops mid-download** — the `.part` is deleted, the row goes back to `queued` (not `error`, never `present` with a truncated file), the queue idles 60 s instead of failing every remaining track, and resumes; leftover `.part` files and `downloading` rows from a power cut are swept at queue start. (Task 2 `test_link_drop_mid_transfer_requeues_and_leaves_no_partial`, `test_link_drop_idles_the_queue_instead_of_failing_every_track`, `test_queue_start_sweeps_partials_and_stale_rows`.)
3. **Unkeeping an album while it downloads** — queued downloads of tracks no other pin protects are cancelled (rows dropped), the in-flight one finishes, tracks shared with another kept item keep downloading. (Task 2 `test_cancel_drops_queued_and_in_flight_finishes`; Task 4 `test_unkeep_cancels_only_orphaned_queued_tracks`.)
4. **Starred item and user pin overlap on removal** — the `pins` table holds one row per target, so a user keep *replaces* a starred (or RFID) pin; unkeep / Storage Remove must restore the starred/RFID pin at once so nothing it protects is deleted or evicted, and Remove of a starred-only item is refused with "unstar in Navidrome to remove". (Task 4 `test_unkeep_starred_album_falls_back_to_starred_pin`, `test_unkeep_card_bound_album_falls_back_to_rfid_pin`; Task 5 `test_remove_kept_starred_overlap_deletes_nothing`, `test_remove_starred_only_is_refused`.)
5. **Kiosk / RFID playback of a kept track while offline** — the library resolver returns `file://` for kept tracks when Navidrome is down (kiosk path), and `boombox-rfid` (which used to resolve with `online=True` always) now asks the library and plays only kept tracks instead of queueing dead stream URLs; on MarkII Mopidy (system user `mopidy`) must be able to read the files. (Task 6 `test_resolve_batch_offline_returns_kept_file_and_drops_the_rest`, `test_library_online_*`, `test_resolve_uris_offline_plays_kept_file`; Task 12 Step 6/7.)

---

## File Structure

| File | Responsibility |
|---|---|
| `services/boombox_library/config.py` (modify) | `CacheConfig.internal_path`, 20 GiB reserve default, legacy-1-GiB upgrade, save/load. |
| `services/boombox_library/cache_drive.py` (modify) | `CacheDriveState.internal`, `ensure_internal_drive`, `select_cache_drive`. |
| `install/config/library.yml.template`, `install/install.sh` (modify) | New keys; create `/opt/boombox/storage/music` owned by the boombox user. |
| `services/boombox_library/download_gates.py` (create) | `read_soc_temp_c`, `free_bytes`, `MopidyStreamProbe`. |
| `services/boombox_library/downloader.py` (rewrite) | `download_track` with reserve/no_space/offline/cancel handling, `make_fetch` (mid-transfer space guard), `sweep_partials`, scheduler `DownloadQueue` + `Gates`. |
| `services/boombox_library/models.py` (modify) | `CacheStatus.NO_SPACE`. |
| `services/boombox-library.py` (modify) | Internal drive selection, queue wiring with gates + reserve, failed-retry cadence, `download_queue()`, candidates suppressed on internal storage, shutdown. |
| `services/boombox_library/keep.py` (create) | keep/unkeep with pin fall-back, `keep_state`, `offline_ids`, `offline_flags`, `kept_items`, `storage_overview`, `remove_kept`, `retry_failed`. |
| `services/boombox_library/api.py` (modify) | `/api/library/keep` (POST/DELETE), `/offline`, `/storage`, `/storage/remove`, `/storage/retry`; detail `keep`/`offline`; search `offline`; health `internal_storage`; `Context.download_queue()`. |
| `services/boombox_rfid/playback.py`, `services/boombox-rfid.py` (modify) | `library_online()`; taps resolve with the real reachability. |
| `services/remote_home.py` (modify) | `/api/remote/home/keep` (POST/DELETE), `/status`, `/offline`. |
| `services/boombox_setup/storage.py` (create) | `/api/accounts/storage*` admin routes. |
| `services/boombox_setup/accounts.py`, `api.py`, `services/boombox-setup.py` (modify) | Multipart allowed on the upload path only; `Context.library_call`; wiring. |
| `services/remote_files.py` (modify) | Household upload/delete → 403 "moved"; delete never 500; disk-full upload → 507. |
| `install/config/nginx-boombox-common.conf` (modify) | `location = /api/accounts/storage/files/upload` (4096M, unbuffered). |
| `services/tests/test_library_{config,cache_drive,downloader,download_gates,service,keep,api}.py`, `test_rfid_playback.py`, `test_remote_home.py`, `test_storage_admin_api.py` (create), `test_remote_files.py`, `test_nginx_lan_app.py` | Tests. |
| `remote-ui/src/lib/api.ts`, `lib/homeLibrary.ts`, `screens/HomeLibrary.tsx` (modify) | `del`, status/keep/offline client, banner, dimming, Keep offline toggle + progress, offline-only play. |
| `remote-ui/src/lib/route.ts`, `components/{AppShell,Sidebar}.tsx`, `screens/More.tsx`, `admin/LockScreen.tsx` (modify) | `#/storage` admin section. |
| `remote-ui/src/admin/storage/{types,api}.ts`, `admin/StorageSection.tsx` (create) | Storage page. |
| `remote-ui/src/screens/Files.tsx` (rewrite) | `FileBrowser` (shared) + read-only household `Files` with pointer to Storage. |
| `remote-ui/src/**/*.test.ts(x)` | UI tests. |
| `docs/SERVICES.md`, `docs/ACCESS.md`, `CHANGELOG.md` (modify) | Routes, upload move, changelog. |

---

### Task 1: Internal storage + reserve from config

**Files:**
- Modify: `services/boombox_library/config.py` (constants after `_KEY_SALT`; `CacheConfig` lines 47–51; `load_config` cache block lines 134–139; `save_config` cache dict lines 157–161)
- Modify: `services/boombox_library/cache_drive.py` (`CacheDriveState` lines 41–46; new functions after `adopt_drive`)
- Modify: `install/config/library.yml.template` (cache block), `install/install.sh` (after the state-dir lines 200–202)
- Test: `services/tests/test_library_config.py`, `services/tests/test_library_cache_drive.py`

**Interfaces:**
- Produces (`boombox_library.config`): `DEFAULT_INTERNAL_PATH = "/opt/boombox/storage/music"`, `DEFAULT_RESERVE_BYTES = 21474836480`, `LEGACY_RESERVE_BYTES = 1073741824`, `CacheConfig(marker_filename, search_paths, reserve_bytes=DEFAULT_RESERVE_BYTES, internal_path=DEFAULT_INTERNAL_PATH)`.
- Produces (`boombox_library.cache_drive`): `CacheDriveState(present, mount_path, free_bytes, total_bytes, internal: bool = False)`; `ensure_internal_drive(path: Path, marker: str = ".boombox-cache") -> CacheDriveState` (raises `OSError` when unusable); `select_cache_drive(internal_path: str, search_paths: Iterable[Path], marker: str = ".boombox-cache") -> CacheDriveState`.

- [ ] **Step 1: Write the failing tests**

In `services/tests/test_library_config.py` add `from dataclasses import replace` to the imports, change the last assert of `test_default_config_shape` and append:

```python
    assert c.cache.reserve_bytes == 20 * 1024 ** 3  # 20 GiB
    assert c.cache.internal_path == "/opt/boombox/storage/music"
```

```python
REPO = Path(__file__).resolve().parents[2]


def test_legacy_1gib_reserve_is_upgraded_to_20gib(tmp_path: Path):
    p = tmp_path / "library.yml"
    p.write_text("cache:\n  reserve_bytes: 1073741824\n")
    assert load_config(path=p).cache.reserve_bytes == 21474836480


def test_chosen_reserve_is_kept_and_junk_falls_back(tmp_path: Path):
    p = tmp_path / "library.yml"
    p.write_text("cache:\n  reserve_bytes: 5368709120\n")
    assert load_config(path=p).cache.reserve_bytes == 5368709120
    for junk in ("lots", "-1"):
        p.write_text(f"cache:\n  reserve_bytes: {junk}\n")
        assert load_config(path=p).cache.reserve_bytes == 21474836480


def test_internal_path_default_disable_and_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id", lambda: "deadbeef" * 4)
    p = tmp_path / "library.yml"
    p.write_text("cache:\n  search_paths: [/media]\n")
    assert load_config(path=p).cache.internal_path == "/opt/boombox/storage/music"
    p.write_text('cache:\n  internal_path: ""\n')
    assert load_config(path=p).cache.internal_path == ""
    p.write_text("cache:\n  internal_path:\n")
    assert load_config(path=p).cache.internal_path == ""
    cfg = replace(DEFAULT_CONFIG, cache=replace(DEFAULT_CONFIG.cache, internal_path="/srv/music"))
    save_config(cfg, path=p)
    assert load_config(path=p).cache.internal_path == "/srv/music"


def test_template_carries_the_new_defaults():
    cfg = load_config(path=REPO / "install" / "config" / "library.yml.template")
    assert cfg.cache.internal_path == "/opt/boombox/storage/music"
    assert cfg.cache.reserve_bytes == 21474836480


def test_install_creates_internal_storage_owned_by_the_service_user():
    sh = (REPO / "install" / "install.sh").read_text()
    assert ('sudo install -d -o "$BOOMBOX_USER" -g "$BOOMBOX_USER" -m 0755 '
            '/opt/boombox/storage /opt/boombox/storage/music') in sh
```

In `services/tests/test_library_cache_drive.py` extend the import to `from boombox_library.cache_drive import (..., ensure_internal_drive, select_cache_drive)` and append:

```python
def test_internal_storage_is_created_marked_and_adopted(tmp_path: Path):
    music = tmp_path / "storage" / "music"
    state = select_cache_drive(str(music), [tmp_path / "media"])
    assert state.present and state.internal and state.mount_path == music
    assert (music / ".boombox-cache").exists()
    for sub in ("audio", "meta", "tmp"):
        assert (music / sub).is_dir()
    assert music.stat().st_mode & 0o777 == 0o755
    assert state.total_bytes and state.free_bytes is not None


def test_internal_storage_preferred_over_media_drive(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    _make_drive(media, "usb0", has_marker=True)
    state = select_cache_drive(str(tmp_path / "music"), [media])
    assert state.internal and state.mount_path == tmp_path / "music"


def test_internal_disabled_falls_back_to_media_drive(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    usb = _make_drive(media, "usb0", has_marker=True)
    state = select_cache_drive("", [media])
    assert state.present and not state.internal and state.mount_path == usb


def test_unusable_internal_path_falls_back_to_media_drive(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    usb = _make_drive(media, "usb0", has_marker=True)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    state = select_cache_drive(str(blocker / "music"), [media])
    assert state.mount_path == usb and not state.internal


def test_internal_storage_adoption_is_idempotent(tmp_path: Path):
    music = tmp_path / "music"
    first = ensure_internal_drive(music)
    (music / "audio" / "t1.flac").write_bytes(b"x")
    marker_mtime = (music / ".boombox-cache").stat().st_mtime_ns
    second = ensure_internal_drive(music)
    assert first.mount_path == second.mount_path == music
    assert (music / "audio" / "t1.flac").read_bytes() == b"x"
    assert (music / ".boombox-cache").stat().st_mtime_ns == marker_mtime  # no write every poll
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_config.py services/tests/test_library_cache_drive.py`
Expected: FAIL — `ImportError: cannot import name 'ensure_internal_drive'` and the config asserts (`1073741824 != 21474836480`).

- [ ] **Step 3: Implement config**

In `services/boombox_library/config.py`, after `_KEY_SALT = b"boombox-library-v1"`:

```python
DEFAULT_INTERNAL_PATH = "/opt/boombox/storage/music"
DEFAULT_RESERVE_BYTES = 20 * 1024 ** 3  # 20 GiB
# The pre-2A default. A library.yml carrying exactly this value was written
# by the old template / a Settings save, not chosen by hand: upgrade it.
LEGACY_RESERVE_BYTES = 1_073_741_824
```

Replace `CacheConfig`:

```python
@dataclass(frozen=True)
class CacheConfig:
    marker_filename: str = ".boombox-cache"
    search_paths: tuple = ("/media",)
    # Downloads stop while free space is below this.
    reserve_bytes: int = DEFAULT_RESERVE_BYTES
    # Internal music storage, adopted as an always-present cache drive and
    # preferred over /media drives. "" disables it (a marker-carrying drive
    # under search_paths is then adopted, as before).
    internal_path: str = DEFAULT_INTERNAL_PATH
```

After `_non_negative_int`:

```python
def _reserve_bytes(value: Any) -> int:
    """Junk / negative → the default; the legacy 1 GiB default → 20 GiB."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RESERVE_BYTES
    if n < 0 or n == LEGACY_RESERVE_BYTES:
        return DEFAULT_RESERVE_BYTES
    return n


def _internal_path(value: Any) -> str:
    """None / "" (YAML `internal_path:` or `internal_path: ""`) disables it."""
    return str(value).strip() if value else ""
```

In `load_config` replace the cache block:

```python
    ca = raw.get("cache", {})
    cache = CacheConfig(
        marker_filename=ca.get("marker_filename", ".boombox-cache"),
        search_paths=tuple(ca.get("search_paths", ["/media"])),
        reserve_bytes=_reserve_bytes(ca.get("reserve_bytes", DEFAULT_RESERVE_BYTES)),
        internal_path=_internal_path(ca.get("internal_path", DEFAULT_INTERNAL_PATH)),
    )
```

In `save_config` the `"cache"` dict becomes:

```python
        "cache": {
            "internal_path": cfg.cache.internal_path,
            "marker_filename": cfg.cache.marker_filename,
            "search_paths": list(cfg.cache.search_paths),
            "reserve_bytes": cfg.cache.reserve_bytes,
        },
```

`install/config/library.yml.template` cache block becomes:

```yaml
cache:
  # Kept-offline music lives here on the boombox's own drive. Set to ""
  # to use a USB drive carrying the marker file under search_paths instead.
  internal_path: /opt/boombox/storage/music
  marker_filename: ".boombox-cache"
  search_paths:
    - /media
  # Downloads stop while free space is below this (20 GiB).
  reserve_bytes: 21474836480
```

In `install/install.sh`, directly after `sudo chown "$BOOMBOX_USER:$BOOMBOX_USER" /opt/boombox/state`:

```bash
# Internal music storage for "keep offline" downloads. boombox-library
# adopts it as its always-present cache drive; Mopidy (user mopidy) reads
# the files, so 0755.
sudo install -d -o "$BOOMBOX_USER" -g "$BOOMBOX_USER" -m 0755 /opt/boombox/storage /opt/boombox/storage/music
```

- [ ] **Step 4: Implement internal drive selection**

In `services/boombox_library/cache_drive.py` replace `CacheDriveState`:

```python
@dataclass(frozen=True)
class CacheDriveState:
    present: bool
    mount_path: Optional[Path]
    free_bytes: Optional[int]
    total_bytes: Optional[int]
    # True for the internal music storage (cache.internal_path).
    internal: bool = False
```

After `adopt_drive` add:

```python
def ensure_internal_drive(path: Path, marker: str = ".boombox-cache") -> CacheDriveState:
    """The internal music store as an always-present cache drive: create it
    (0755), write the marker and audio/meta/tmp when missing. Cheap when
    everything is there (cache_poll calls it every few seconds — no write).
    Raises OSError when the path can't be created or written."""
    created = not path.exists()
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    if created:
        path.chmod(0o755)  # mkdir's mode is filtered by the umask
    if not (path / marker).exists() or any(
            not (path / sub).is_dir() for sub in _REQUIRED_SUBDIRS):
        adopt_drive(path, marker=marker)
    free, total = _disk_usage(path)
    return CacheDriveState(present=True, mount_path=path, free_bytes=free,
                           total_bytes=total, internal=True)


_warned_internal: set[str] = set()


def select_cache_drive(
    internal_path: str,
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> CacheDriveState:
    """The cache drive for this poll: the internal storage when configured
    and usable (it always wins over /media), else the first marker-carrying
    drive under search_paths — the removable-drive fallback."""
    paths = [Path(p) for p in search_paths]
    if internal_path:
        try:
            state = ensure_internal_drive(Path(internal_path), marker)
            _warned_internal.discard(internal_path)
            return state
        except OSError as e:
            if internal_path not in _warned_internal:
                _warned_internal.add(internal_path)
                log.warning("internal music storage %s is unusable (%s); "
                            "falling back to a marked drive under %s",
                            internal_path, e, [str(p) for p in paths])
    return detect_cache_drive(paths, marker)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_config.py services/tests/test_library_cache_drive.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: all pass; ruff `All checks passed!`; mypy `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add services/boombox_library/config.py services/boombox_library/cache_drive.py install/config/library.yml.template install/install.sh services/tests/test_library_config.py services/tests/test_library_cache_drive.py
git commit -m "feat(library): internal music storage + 20 GiB reserve from config

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 2: Download scheduler — reserve, no_space, link drops, gates, cancel

**Files:**
- Create: `services/boombox_library/download_gates.py`
- Rewrite: `services/boombox_library/downloader.py`
- Modify: `services/boombox_library/models.py` (`CacheStatus`, lines 82–87)
- Test: `services/tests/test_library_download_gates.py` (create), `services/tests/test_library_downloader.py` (append)

**Interfaces:**
- Produces (`boombox_library.download_gates`): `THERMAL_PATH = Path("/sys/class/thermal/thermal_zone0/temp")`, `read_soc_temp_c(path: Path = THERMAL_PATH) -> float | None`, `free_bytes(path: Path) -> int | None`, `class MopidyStreamProbe(rpc_url: str = MOPIDY_RPC)` with `async is_streaming() -> bool`, `async close() -> None`.
- Produces (`boombox_library.downloader`): `THERMAL_LIMIT_C = 70.0`, `THERMAL_RECHECK_S = 60.0`, `OFFLINE_RECHECK_S = 60.0`, `PAUSE_RECHECK_S = 15.0`, `SPACE_CHECK_EVERY`; `DownloadResult` gains `OFFLINE`, `NO_SPACE`; `OutOfSpace`; `is_link_failure(e) -> bool`; `make_fetch(cache_root: Path, reserve_bytes: int) -> Fetcher`; `sweep_partials(cache_root: Path) -> int`; `download_track(conn, client, track_id, cache_root, fetch=default_fetch, *, reserve_bytes: int = 0) -> DownloadResult`; `@dataclass Gates(is_online, is_streaming, soc_temp_c, free_bytes)`; `DownloadQueue(conn, client, cache_root, max_concurrent=2, fetch=None, *, reserve_bytes=0, gates=None, sleep=asyncio.sleep, clock=time.monotonic)` with `enqueue(track_id) -> bool`, `cancel(track_ids) -> int`, `snapshot() -> {"queued": int, "in_flight": [str], "paused": str | None}`, `async pause_reason() -> str | None`, `async drain()`, `stop()`, attribute `reserve_bytes`.
- `cache_state.status` gains `'no_space'` (`CacheStatus.NO_SPACE`). `reserve_bytes` defaults to 0 only for direct callers/tests; the service always passes `cfg.cache.reserve_bytes` (Task 3).

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_library_download_gates.py`:

```python
"""download_gates: SoC temperature, free space, Mopidy stream-proxy probe."""
from __future__ import annotations

from aiohttp import web
from boombox_library.download_gates import MopidyStreamProbe, free_bytes, read_soc_temp_c


def test_soc_temp_reads_millidegrees_and_absent_means_none(tmp_path):
    assert read_soc_temp_c(tmp_path / "nope") is None
    (tmp_path / "junk").write_text("hot\n")
    assert read_soc_temp_c(tmp_path / "junk") is None
    (tmp_path / "temp").write_text("70000\n")
    assert read_soc_temp_c(tmp_path / "temp") == 70.0


def test_free_bytes(tmp_path):
    assert (free_bytes(tmp_path) or 0) > 0
    assert free_bytes(tmp_path / "missing") is None


class FakeMopidy:
    def __init__(self) -> None:
        self.state = "playing"
        self.uri: str | None = "http://127.0.0.1:6687/api/library/stream/t1"

    def app(self) -> web.Application:
        async def rpc(req: web.Request) -> web.Response:
            method = (await req.json())["method"]
            result: object = None
            if method == "core.playback.get_state":
                result = self.state
            elif method == "core.playback.get_current_track":
                result = {"uri": self.uri} if self.uri else None
            return web.json_response({"jsonrpc": "2.0", "id": 1, "result": result})
        app = web.Application()
        app.router.add_post("/mopidy/rpc", rpc)
        return app


async def test_probe_detects_stream_proxy_playback(aiohttp_server):
    fake = FakeMopidy()
    srv = await aiohttp_server(fake.app())
    probe = MopidyStreamProbe(str(srv.make_url("/mopidy/rpc")))
    try:
        assert await probe.is_streaming() is True
        fake.uri = "file:///opt/boombox/storage/music/audio/t1.flac"
        assert await probe.is_streaming() is False
        fake.uri = "http://127.0.0.1:6687/api/library/stream/t1"
        fake.state = "paused"
        assert await probe.is_streaming() is False
    finally:
        await probe.close()


async def test_probe_with_mopidy_down_is_not_streaming():
    probe = MopidyStreamProbe("http://127.0.0.1:1/mopidy/rpc")
    try:
        assert await probe.is_streaming() is False
    finally:
        await probe.close()
```

Append to `services/tests/test_library_downloader.py` (it already imports `asyncio`, `Path`, `pytest`, `connect`, `migrate`, `DownloadResult`, `download_track` and defines `FakeStreamingClient`); move the five new import lines into the file's top import block so ruff's isort check stays clean:

```python
# ---- spec 2A: reserve, link drops, scheduler gates ----

import aiohttp
import boombox_library.downloader as dl
from aiohttp import web
from boombox_library.download_gates import read_soc_temp_c
from boombox_library.downloader import DownloadQueue, Gates, OutOfSpace, make_fetch

GiB = 1024 ** 3


def _db(tmp_path: Path, n: int = 1, size: int = 100):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,"
                 "is_compilation,navidrome_starred,updated_at) VALUES('al','A','a','ar',?,30,0,0,0)", (n,))
    for i in range(n):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,"
                     "content_type,navidrome_starred,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"t{i}", "al", f"T{i}", 30, "mp3", size, "audio/mpeg", 0, 0))
    return conn


def _cache(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    (root / "audio").mkdir(parents=True)
    (root / "tmp").mkdir()
    return root


def _status(conn, tid):
    row = conn.execute("SELECT status FROM cache_state WHERE track_id=?", (tid,)).fetchone()
    return None if row is None else row["status"]


def _fake_free(monkeypatch, free):
    monkeypatch.setattr(dl, "free_bytes", lambda path: free)


class Sleeps:
    """Fake scheduler sleep: records durations, runs a hook, yields once."""
    def __init__(self, on_sleep=None):
        self.calls: list[float] = []
        self.on_sleep = on_sleep

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.on_sleep:
            self.on_sleep(len(self.calls))
        await asyncio.sleep(0)


def _ok_fetch(log: list):
    async def fetch(url, params, dest):
        log.append(url)
        dest.write_bytes(b"x")
    return fetch


async def test_download_skips_with_no_space_when_it_would_cross_the_reserve(tmp_path, monkeypatch):
    conn = _db(tmp_path, size=50 * 2**20)
    root = _cache(tmp_path)
    _fake_free(monkeypatch, 20 * GiB + 10 * 2**20)   # only 10 MiB above the reserve
    called: list = []
    r = await download_track(conn, FakeStreamingClient(b""), "t0", root, _ok_fetch(called),
                             reserve_bytes=20 * GiB)
    assert r is DownloadResult.NO_SPACE and called == []
    row = conn.execute("SELECT status, error_message FROM cache_state WHERE track_id='t0'").fetchone()
    assert row["status"] == "no_space" and "reserved" in row["error_message"]


async def test_download_proceeds_with_room_above_the_reserve(tmp_path, monkeypatch):
    conn = _db(tmp_path, size=5)
    root = _cache(tmp_path)
    _fake_free(monkeypatch, 30 * GiB)
    r = await download_track(conn, FakeStreamingClient(b""), "t0", root, _ok_fetch([]),
                             reserve_bytes=20 * GiB)
    assert r is DownloadResult.OK and _status(conn, "t0") == "present"


async def test_link_drop_mid_transfer_requeues_and_leaves_no_partial(tmp_path):
    conn = _db(tmp_path)
    root = _cache(tmp_path)

    async def fetch(url, params, dest):
        dest.write_bytes(b"half")
        raise aiohttp.ClientPayloadError("Response payload is not completed")

    r = await download_track(conn, FakeStreamingClient(b""), "t0", root, fetch)
    assert r is DownloadResult.OFFLINE
    assert _status(conn, "t0") == "queued"
    assert not (root / "tmp" / "t0.part").exists()
    assert not (root / "audio" / "t0.mp3").exists()


async def test_http_404_is_failed_with_its_reason(tmp_path):
    from yarl import URL
    conn = _db(tmp_path)
    root = _cache(tmp_path)

    async def fetch(url, params, dest):
        info = aiohttp.RequestInfo(url=URL("http://nav/rest/download.view"), method="GET",
                                   headers={},  # type: ignore[arg-type]
                                   real_url=URL("http://nav/rest/download.view"))
        raise aiohttp.ClientResponseError(request_info=info, history=(), status=404,
                                          message="Not Found")

    assert await download_track(conn, FakeStreamingClient(b""), "t0", root, fetch) is DownloadResult.ERROR
    row = conn.execute("SELECT status, error_message FROM cache_state WHERE track_id='t0'").fetchone()
    assert row["status"] == "error" and "404" in row["error_message"]


async def test_out_of_space_mid_transfer_is_no_space_and_leaves_no_partial(tmp_path):
    conn = _db(tmp_path)
    root = _cache(tmp_path)

    async def fetch(url, params, dest):
        dest.write_bytes(b"x" * 10)
        raise OutOfSpace("free 1 < reserve 2")

    assert await download_track(conn, FakeStreamingClient(b""), "t0", root, fetch) is DownloadResult.NO_SPACE
    assert _status(conn, "t0") == "no_space"
    assert not (root / "tmp" / "t0.part").exists()


async def test_guarded_fetch_aborts_when_free_space_drops(tmp_path, aiohttp_server, monkeypatch):
    async def body(req):
        return web.Response(body=b"\0" * (256 * 1024))
    app = web.Application()
    app.router.add_get("/dl", body)
    srv = await aiohttp_server(app)
    monkeypatch.setattr(dl, "SPACE_CHECK_EVERY", 64 * 1024)
    fetch = make_fetch(tmp_path, reserve_bytes=1000)
    _fake_free(monkeypatch, 100)
    with pytest.raises(OutOfSpace):
        await fetch(str(srv.make_url("/dl")), {}, tmp_path / "x.part")
    _fake_free(monkeypatch, 10**12)
    await fetch(str(srv.make_url("/dl")), {}, tmp_path / "y.part")
    assert (tmp_path / "y.part").stat().st_size == 256 * 1024


async def test_pause_reason_order_and_thresholds(tmp_path):
    conn = _db(tmp_path)
    g = Gates()
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), reserve_bytes=100, gates=g)
    assert await q.pause_reason() is None
    g.soc_temp_c = lambda: 69.9
    assert await q.pause_reason() is None
    g.soc_temp_c = lambda: 70.0
    assert await q.pause_reason() == "hot"

    async def streaming():
        return True
    g.soc_temp_c = lambda: None
    g.is_streaming = streaming
    assert await q.pause_reason() == "streaming"
    g.free_bytes = lambda: 99
    assert await q.pause_reason() == "low_space"
    g.is_online = lambda: False
    assert await q.pause_reason() == "offline"


async def test_queue_pauses_while_streaming_then_runs(tmp_path):
    conn = _db(tmp_path, n=2)
    state = {"streaming": True}
    fetched: list = []

    async def streaming():
        return state["streaming"]

    def on_sleep(n):
        assert fetched == []          # nothing started while a stream played
        state["streaming"] = False

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      gates=Gates(is_streaming=streaming), sleep=sleeps)
    q.enqueue("t0"); q.enqueue("t1")
    await q.drain()
    assert sleeps.calls == [15.0] and len(fetched) == 2


async def test_thermal_backoff_reads_the_sysfs_file_and_rechecks_every_minute(tmp_path):
    conn = _db(tmp_path)
    temp = tmp_path / "temp"
    temp.write_text("71500\n")
    fetched: list = []

    def on_sleep(n):
        assert fetched == []
        if n == 2:
            temp.write_text("55000\n")

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      gates=Gates(soc_temp_c=lambda: read_soc_temp_c(temp)), sleep=sleeps)
    q.enqueue("t0")
    await q.drain()
    assert sleeps.calls == [60.0, 60.0] and len(fetched) == 1


async def test_queue_idles_while_offline_and_resumes(tmp_path):
    conn = _db(tmp_path)
    state = {"online": False}
    fetched: list = []

    def on_sleep(n):
        assert fetched == []
        if n == 3:
            state["online"] = True

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      gates=Gates(is_online=lambda: state["online"]), sleep=sleeps)
    q.enqueue("t0")
    await q.drain()
    assert sleeps.calls == [60.0, 60.0, 60.0] and len(fetched) == 1


async def test_link_drop_idles_the_queue_instead_of_failing_every_track(tmp_path):
    conn = _db(tmp_path, n=5)
    now = {"t": 1000.0}
    calls: list = []

    async def fetch(url, params, dest):
        calls.append(url)
        if len(calls) == 1:
            raise aiohttp.ClientConnectionError("connection refused")
        dest.write_bytes(b"x")

    def on_sleep(n):
        now["t"] += 60.0

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 1, fetch,
                      sleep=sleeps, clock=lambda: now["t"])
    for i in range(5):
        q.enqueue(f"t{i}")
    await q.drain()
    assert len(calls) == 6 and sleeps.calls == [60.0]
    assert [_status(conn, f"t{i}") for i in range(5)] == ["present"] * 5


async def test_low_space_is_a_hard_stop_until_room_appears(tmp_path):
    conn = _db(tmp_path)
    state = {"free": 10}
    fetched: list = []

    def on_sleep(n):
        assert fetched == []
        state["free"] = 10**12

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      reserve_bytes=1000, gates=Gates(free_bytes=lambda: state["free"]), sleep=sleeps)
    q.enqueue("t0")
    await q.drain()
    assert sleeps.calls == [15.0] and len(fetched) == 1
    assert q.snapshot()["paused"] is None


async def test_cancel_drops_queued_and_in_flight_finishes(tmp_path):
    conn = _db(tmp_path, n=3)
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch(url, params, dest):
        started.set()
        await release.wait()
        dest.write_bytes(b"x")

    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 1, fetch)
    for i in range(3):
        q.enqueue(f"t{i}")
    await asyncio.wait_for(started.wait(), 1)
    assert q.snapshot() == {"queued": 2, "in_flight": ["t0"], "paused": None}
    assert q.cancel(["t0", "t1", "t2"]) == 2
    release.set()
    await q.drain()
    assert _status(conn, "t0") == "present"
    assert _status(conn, "t1") is None and _status(conn, "t2") is None


async def test_enqueue_is_idempotent_and_skips_present(tmp_path):
    conn = _db(tmp_path, n=2)
    conn.execute("INSERT INTO cache_state(track_id,status,local_path) VALUES('t1','present','/x')")
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch([]))
    assert q.enqueue("t0") is True
    assert q.enqueue("t0") is False
    assert q.enqueue("t1") is False
    await q.drain()


async def test_failed_download_is_not_retried_by_the_queue(tmp_path):
    conn = _db(tmp_path)
    calls: list = []

    async def fetch(url, params, dest):
        calls.append(url)
        raise OSError("disk says no")

    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, fetch)
    q.enqueue("t0")
    await q.drain()
    await asyncio.sleep(0.05)
    assert calls == ["http://nav/t0"] and _status(conn, "t0") == "error"


async def test_queue_start_sweeps_partials_and_stale_rows(tmp_path):
    conn = _db(tmp_path, n=2)
    root = _cache(tmp_path)
    (root / "tmp" / "t0.part").write_bytes(b"half")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t0','downloading')")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t1','queued')")
    DownloadQueue(conn, FakeStreamingClient(b""), root)
    assert not (root / "tmp" / "t0.part").exists()
    assert _status(conn, "t0") == "absent" and _status(conn, "t1") == "absent"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_download_gates.py services/tests/test_library_downloader.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'boombox_library.download_gates'`.

- [ ] **Step 3: Implement the gates module**

Create `services/boombox_library/download_gates.py`:

```python
"""What the download scheduler checks before each start (spec 2A): SoC
temperature, free space, and whether Mopidy is playing a boombox-library
stream-proxy URI. Every probe degrades to "no reason to wait" when its
source is absent — no thermal zone on a dev box, Mopidy down — per the
hardware-optional rule."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("boombox-library.gates")

THERMAL_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
MOPIDY_RPC = os.environ.get("BOOMBOX_MOPIDY_RPC", "http://127.0.0.1:6680/mopidy/rpc")
STREAM_MARKER = "/api/library/stream/"
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=2)


def read_soc_temp_c(path: Path = THERMAL_PATH) -> Optional[float]:
    """SoC temperature in °C from a sysfs thermal zone (millidegrees), or
    None when the file is absent or unreadable."""
    try:
        return int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def free_bytes(path: Path) -> Optional[int]:
    """Bytes available to us on path's filesystem, or None if unknown."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return st.f_bavail * st.f_frsize


class MopidyStreamProbe:
    """is_streaming(): Mopidy is playing a stream-proxy URI right now."""

    def __init__(self, rpc_url: str = MOPIDY_RPC) -> None:
        self._rpc = rpc_url
        self._session: aiohttp.ClientSession | None = None

    async def _call(self, method: str) -> object:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_PROBE_TIMEOUT)
        async with self._session.post(
                self._rpc, json={"jsonrpc": "2.0", "id": 1, "method": method}) as r:
            body = await r.json(content_type=None)
        return body.get("result") if isinstance(body, dict) else None

    async def is_streaming(self) -> bool:
        try:
            if await self._call("core.playback.get_state") != "playing":
                return False
            track = await self._call("core.playback.get_current_track")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.debug("mopidy probe failed: %s", type(e).__name__)
            return False
        uri = track.get("uri") if isinstance(track, dict) else None
        return isinstance(uri, str) and STREAM_MARKER in uri

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
```

- [ ] **Step 4: Rewrite the downloader**

In `services/boombox_library/models.py`, `CacheStatus` gains `NO_SPACE = "no_space"` after `ERROR = "error"`.

Replace `services/boombox_library/downloader.py` with:

```python
"""Audio file downloader + download scheduler for boombox-library.

download_track() handles one track end-to-end: stream from Subsonic to a
.part tmp file, atomically rename to final, update cache_state. The fetch
coroutine is injected to keep network out of unit tests; the real one
(make_fetch) streams with aiohttp and aborts if free space falls below the
reserve mid-transfer.

DownloadQueue schedules downloads (spec 2A, "never starve the Pi"): at most
`max_concurrent` at a time, and before EACH start it checks, in order —
  offline    Navidrome unreachable, or a download just lost the link: idle,
             re-check every OFFLINE_RECHECK_S (no retry storm);
  low_space  free space below the reserve: hard stop until there is room;
  hot        SoC >= THERMAL_LIMIT_C: wait THERMAL_RECHECK_S, re-check;
  streaming  Mopidy is playing a stream-proxy URI: leave it the link.
In-flight downloads always finish. A failed download keeps status 'error'
with its reason and is NOT retried by the queue — the hourly sync
re-enqueues it (ServiceContext._enqueue_pinned_downloads). The queue is
in memory: the sync re-derives what to download from the pins.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import Awaitable, Callable, Iterable, Optional, Protocol

import aiohttp

from .download_gates import free_bytes

log = logging.getLogger("boombox-library.downloader")

THERMAL_LIMIT_C = 70.0
THERMAL_RECHECK_S = 60.0
OFFLINE_RECHECK_S = 60.0
PAUSE_RECHECK_S = 15.0
SPACE_CHECK_EVERY = 16 * 1024 * 1024
_RECHECK_S = {"offline": OFFLINE_RECHECK_S, "low_space": PAUSE_RECHECK_S,
              "hot": THERMAL_RECHECK_S, "streaming": PAUSE_RECHECK_S}
# What a CDN / tunnel answers when the homelab behind it is down: the link
# failed, not the track. (503 stays a track error: Navidrome itself sends it.)
_LINK_DOWN_STATUSES = frozenset({502, 504, 520, 521, 522, 523, 524, 530})


class DownloadResult(str, enum.Enum):
    OK = "ok"
    SKIPPED = "skipped"    # already present
    ERROR = "error"        # this track failed: status 'error', reason kept
    OFFLINE = "offline"    # the link dropped: requeued, not failed
    NO_SPACE = "no_space"  # would cross the reserve: status 'no_space'


class OutOfSpace(Exception):
    """Free space fell below the reserve during a transfer."""


class StreamingClient(Protocol):
    def download_url(self, track_id: str) -> tuple[str, dict]: ...


Fetcher = Callable[[str, dict, Path], Awaitable[None]]
"""(url, params, dest_path) → writes bytes to dest_path."""


def _safe_error_message(e: Exception) -> str:
    """Format an exception for cache_state.error_message without leaking
    auth params from the request URL.

    aiohttp.ClientResponseError.__str__ includes the merged URL with
    `?u=USERNAME&t=TOKEN&s=SALT&id=...`. We strip the URL by formatting
    only type + status + message for that exception type.
    """
    if isinstance(e, aiohttp.ClientResponseError):
        return f"{type(e).__name__}: {e.status} {e.message}"
    if isinstance(e, aiohttp.ClientError):
        msg = str(e)
        return msg.split('?', 1)[0] if 'http' in msg else msg
    return f"{type(e).__name__}: {e}"


def is_link_failure(e: BaseException) -> bool:
    """The connection to the music server failed (vs. this track failing)."""
    if isinstance(e, aiohttp.ClientResponseError):
        return e.status in _LINK_DOWN_STATUSES
    return isinstance(e, (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError,
                          asyncio.TimeoutError, ConnectionError))


async def default_fetch(url: str, params: dict, dest: Path) -> None:
    """Plain aiohttp streaming fetch (no space guard). Raises on non-2xx."""
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)


def make_fetch(cache_root: Path, reserve_bytes: int) -> Fetcher:
    """The queue's fetch: default_fetch plus the disk-full hard stop —
    every SPACE_CHECK_EVERY bytes, abort with OutOfSpace when free space on
    cache_root has fallen below the reserve."""
    async def fetch(url: str, params: dict, dest: Path) -> None:
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                since_check = 0
                with dest.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        since_check += len(chunk)
                        if since_check >= SPACE_CHECK_EVERY:
                            since_check = 0
                            free = free_bytes(cache_root)
                            if free is not None and free < reserve_bytes:
                                raise OutOfSpace(f"{free} B free < {reserve_bytes} B reserve")
    return fetch


def _mark(conn: Connection, track_id: str, status: str,
          message: Optional[str] = None) -> None:
    conn.execute(
        """INSERT INTO cache_state(track_id, status, error_message) VALUES (?, ?, ?)
           ON CONFLICT(track_id) DO UPDATE SET status=excluded.status,
                                               error_message=excluded.error_message""",
        (track_id, status, message),
    )


def _drop_partial(tmp_path: Path) -> None:
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass


def sweep_partials(cache_root: Path) -> int:
    """Delete leftover tmp/*.part files (crash / power cut mid-download).
    Only call while no download runs on this cache_root."""
    try:
        parts = list((cache_root / "tmp").glob("*.part"))
    except OSError:
        return 0
    n = 0
    for p in parts:
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


async def download_track(
    conn: Connection,
    client: StreamingClient,
    track_id: str,
    cache_root: Path,
    fetch: Fetcher = default_fetch,
    *,
    reserve_bytes: int = 0,
) -> DownloadResult:
    """Download one track into cache_root/audio/<id>.<suffix> atomically.

    cache_root must contain audio/ and tmp/ (adopt_drive creates them).
    reserve_bytes: keep at least this much free (the service passes
    cache.reserve_bytes; 0 = none, for direct callers and tests). A track
    that would cross it — after evicting unpinned streamed cache — is
    skipped with status 'no_space'. A dropped link requeues the track
    (status 'queued', DownloadResult.OFFLINE) instead of failing it.
    """
    row = conn.execute(
        "SELECT status FROM cache_state WHERE track_id=?", (track_id,)
    ).fetchone()
    if row and row["status"] == "present":
        return DownloadResult.SKIPPED

    trow = conn.execute(
        "SELECT suffix, size_bytes FROM tracks WHERE id=?", (track_id,)
    ).fetchone()
    if trow is None:
        log.error("track %s not in catalog; skipping", track_id)
        return DownloadResult.ERROR
    suffix = trow["suffix"] or "bin"

    expected_size = int(trow["size_bytes"] or 0)
    free = free_bytes(cache_root)
    if free is not None:
        need = expected_size + reserve_bytes - free
        if need > 0:
            from .eviction import evict_until_fits
            freed, _left = evict_until_fits(
                conn, need, lambda p: os.unlink(p) if p else None)
            free += freed
        if expected_size + reserve_bytes > free:
            _mark(conn, track_id, "no_space",
                  f"no space: {expected_size} B needed, {free} B free, "
                  f"{reserve_bytes} B reserved")
            log.warning("skipping %s: it would cross the %d B reserve",
                        track_id, reserve_bytes)
            return DownloadResult.NO_SPACE

    tmp_path = cache_root / "tmp" / f"{track_id}.part"
    final_path = cache_root / "audio" / f"{track_id}.{suffix}"

    conn.execute(
        """INSERT INTO cache_state(track_id, status, downloaded_at)
           VALUES (?, 'downloading', ?)
           ON CONFLICT(track_id) DO UPDATE SET status='downloading',
                                                error_message=NULL""",
        (track_id, time.time()),
    )

    url, params = client.download_url(track_id)
    try:
        _drop_partial(tmp_path)
        await fetch(url, params, tmp_path)
        os.replace(tmp_path, final_path)
        size = final_path.stat().st_size
        conn.execute(
            """INSERT INTO cache_state(track_id, status, local_path,
                                       size_bytes, downloaded_at)
               VALUES (?, 'present', ?, ?, ?)
               ON CONFLICT(track_id) DO UPDATE SET
                  status='present',
                  local_path=excluded.local_path,
                  size_bytes=excluded.size_bytes,
                  downloaded_at=excluded.downloaded_at,
                  error_message=NULL""",
            (track_id, str(final_path), size, time.time()),
        )
        return DownloadResult.OK
    except asyncio.CancelledError:
        _drop_partial(tmp_path)
        _mark(conn, track_id, "absent")
        raise
    except OutOfSpace as e:
        _drop_partial(tmp_path)
        _mark(conn, track_id, "no_space", f"no space: {e}")
        log.warning("download of %s stopped: %s", track_id, e)
        return DownloadResult.NO_SPACE
    except Exception as e:
        _drop_partial(tmp_path)
        if is_link_failure(e):
            _mark(conn, track_id, "queued")
            log.info("download of %s interrupted, music server unreachable: %s",
                     track_id, _safe_error_message(e))
            return DownloadResult.OFFLINE
        _mark(conn, track_id, "error", _safe_error_message(e))
        log.warning("download of %s failed: %s", track_id, _safe_error_message(e))
        return DownloadResult.ERROR


async def _never_streaming() -> bool:
    return False


def _always_online() -> bool:
    return True


def _unknown() -> Optional[float]:
    return None


def _unknown_free() -> Optional[int]:
    return None


@dataclass
class Gates:
    """Inputs the scheduler checks before each start (defaults: all clear)."""
    is_online: Callable[[], bool] = _always_online
    is_streaming: Callable[[], Awaitable[bool]] = _never_streaming
    soc_temp_c: Callable[[], Optional[float]] = _unknown
    free_bytes: Callable[[], Optional[int]] = _unknown_free


class DownloadQueue:
    """In-memory download scheduler with bounded concurrency and gates."""

    def __init__(
        self,
        conn: Connection,
        client: StreamingClient,
        cache_root: Path,
        max_concurrent: int = 2,
        fetch: Optional[Fetcher] = None,
        *,
        reserve_bytes: int = 0,
        gates: Optional[Gates] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.conn = conn
        self.client = client
        self.cache_root = cache_root
        self.max_concurrent = max(1, max_concurrent)
        self.reserve_bytes = reserve_bytes
        self._fetch = fetch or make_fetch(cache_root, reserve_bytes)
        self._gates = gates or Gates()
        self._sleep = sleep
        self._clock = clock
        self._pending: dict[str, None] = {}          # insertion-ordered set
        self._in_flight: dict[str, asyncio.Task] = {}
        self._wake = asyncio.Event()
        self._runner: Optional[asyncio.Task] = None
        self._offline_until = 0.0
        self.paused: Optional[str] = None
        # A new queue owns this drive: whatever an earlier run left half
        # done (power cut) is not downloading any more.
        sweep_partials(cache_root)
        conn.execute("UPDATE cache_state SET status='absent' "
                     "WHERE status IN ('downloading', 'queued')")

    def enqueue(self, track_id: str) -> bool:
        """Schedule a download. False when it is already queued, in flight
        or present."""
        if track_id in self._pending or track_id in self._in_flight:
            return False
        row = self.conn.execute(
            "SELECT status FROM cache_state WHERE track_id=?", (track_id,)).fetchone()
        if row is not None and row["status"] == "present":
            return False
        self.conn.execute(
            """INSERT INTO cache_state(track_id, status) VALUES (?, 'queued')
               ON CONFLICT(track_id) DO UPDATE SET status='queued', error_message=NULL""",
            (track_id,),
        )
        self._pending[track_id] = None
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run())
        self._wake.set()
        return True

    def cancel(self, track_ids: Iterable[str]) -> int:
        """Drop queued (not yet started) downloads; in-flight ones finish.
        Returns how many were dropped."""
        n = 0
        for tid in track_ids:
            if tid in self._pending:
                del self._pending[tid]
                self.conn.execute(
                    "DELETE FROM cache_state WHERE track_id=? AND status='queued'", (tid,))
                n += 1
        return n

    def snapshot(self) -> dict:
        return {"queued": len(self._pending), "in_flight": list(self._in_flight),
                "paused": self.paused}

    async def pause_reason(self) -> Optional[str]:
        if not self._gates.is_online() or self._clock() < self._offline_until:
            return "offline"
        free = self._gates.free_bytes()
        if free is not None and free < self.reserve_bytes:
            return "low_space"
        temp = self._gates.soc_temp_c()
        if temp is not None and temp >= THERMAL_LIMIT_C:
            return "hot"
        try:
            if await self._gates.is_streaming():
                return "streaming"
        except Exception as e:  # a broken probe never blocks downloads
            log.debug("streaming probe failed: %s", e)
        return None

    async def _run(self) -> None:
        while True:
            if not self._pending or len(self._in_flight) >= self.max_concurrent:
                if not self._pending:
                    self.paused = None
                self._wake.clear()
                await self._wake.wait()
                continue
            reason = await self.pause_reason()
            if reason != self.paused:
                log.info("downloads %s", f"paused: {reason}" if reason else "resumed")
            self.paused = reason
            if reason is not None:
                await self._sleep(_RECHECK_S[reason])
                continue
            tid = next(iter(self._pending))
            del self._pending[tid]
            self._in_flight[tid] = asyncio.create_task(self._download(tid))

    async def _download(self, track_id: str) -> None:
        try:
            result = await download_track(
                self.conn, self.client, track_id, self.cache_root, self._fetch,
                reserve_bytes=self.reserve_bytes)
            if result is DownloadResult.OFFLINE:
                # Back at the head of the line; idle before the next try.
                self._pending = {track_id: None, **self._pending}
                self._offline_until = self._clock() + OFFLINE_RECHECK_S
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("download of %s crashed", track_id)
        finally:
            self._in_flight.pop(track_id, None)
            self._wake.set()

    async def drain(self) -> None:
        """Wait until nothing is queued or in flight (tests)."""
        while self._pending or self._in_flight:
            await asyncio.sleep(0.005)

    def stop(self) -> None:
        """Cancel the scheduler and every in-flight download (drive lost,
        shutdown). Their .part files are removed by download_track."""
        if self._runner is not None:
            self._runner.cancel()
        for task in self._in_flight.values():
            task.cancel()
        self._pending.clear()
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_download_gates.py services/tests/test_library_downloader.py services/tests/test_library_eviction.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: all pass (the pre-existing downloader tests are unchanged: `reserve_bytes` defaults to 0, and the 503 in `test_error_message_does_not_leak_auth_params` is still a track ERROR); ruff and mypy clean.

- [ ] **Step 6: Commit**

```bash
git add services/boombox_library/download_gates.py services/boombox_library/downloader.py services/boombox_library/models.py services/tests/test_library_download_gates.py services/tests/test_library_downloader.py
git commit -m "feat(library): download scheduler — reserve, link drops, thermal/stream/offline gates, cancel

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 3: Wire the scheduler into boombox-library (internal drive, gates, hourly failed-retry)

**Files:**
- Modify: `services/boombox-library.py` (imports lines 25–48; `ServiceContext.__init__` ~line 111; `cache_candidates` lines 210–215; `cache_poll` lines 336–371; `_init_download_queue` / `_enqueue_pinned_downloads` lines 396–422; `amain` lines 459–462)
- Test: `services/tests/test_library_service.py` (fixture line 60–63; append tests)

**Interfaces:**
- Consumes: `select_cache_drive` (Task 1), `DownloadQueue`, `Gates`, `MopidyStreamProbe`, `read_soc_temp_c`, `free_bytes` (Task 2).
- Produces (`ServiceContext`): `download_queue() -> DownloadQueue | None` (builds the queue lazily once a drive and a source exist; rebuilds it when the drive or the source credentials change), `_ensure_download_queue()`, `_stop_download_queue()`, `_enqueue_pinned_downloads(now: float | None = None)`, `async close()`; `cache_candidates()` returns `[]` while the internal storage is the drive.

- [ ] **Step 1: Write the failing tests**

In `services/tests/test_library_service.py`: add `from dataclasses import replace` and `CacheConfig` to the config import; in the `ctx` fixture replace the `cache=` line with

```python
        cache=CacheConfig(search_paths=(str(tmp_path / "media"),), internal_path=""),
```

(the default internal path `/opt/boombox/storage/music` must never be touched by tests). Append:

```python
class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.stopped = False

    def enqueue(self, tid):
        self.enqueued.append(tid)
        return True

    def cancel(self, ids):
        return 0

    def snapshot(self):
        return {"queued": 0, "in_flight": [], "paused": None}

    def stop(self):
        self.stopped = True


def _seed_pinned_album(conn):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,"
                 "is_compilation,navidrome_starred,updated_at) VALUES('al1','A','a','ar',2,60,0,0,0)")
    for tid in ("t1", "t2"):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,content_type,"
                     "navidrome_starred,updated_at) VALUES(?,'al1','T',30,'mp3',10,'audio/mpeg',0,0)", (tid,))
    conn.execute("INSERT INTO pins(target_kind,target_id,source,added_at) VALUES('album','al1','user',0)")


@pytest.mark.asyncio
async def test_internal_storage_is_adopted_with_a_gated_queue(ctx, tmp_path, monkeypatch):
    music = tmp_path / "storage" / "music"
    ctx.cfg = replace(ctx.cfg, cache=replace(ctx.cfg.cache, internal_path=str(music)))
    (tmp_path / "media" / "usb0").mkdir()          # unmarked, writable: would be a candidate
    await _poll_once(ctx, monkeypatch)
    assert ctx.cache_state.internal and ctx.cache_state.mount_path == music
    assert (tmp_path / "cache-mount").resolve() == music.resolve()
    q = ctx.download_queue()
    assert q is not None
    assert q.reserve_bytes == ctx.cfg.cache.reserve_bytes == 21474836480
    assert q.max_concurrent == ctx.cfg.sync.max_concurrent_downloads == 2
    assert ctx.cache_candidates() == []


@pytest.mark.asyncio
async def test_queue_appears_once_a_source_is_configured(ctx, tmp_path, monkeypatch):
    ctx.cfg = replace(ctx.cfg, source=SourceConfig(),
                      cache=replace(ctx.cfg.cache, internal_path=str(tmp_path / "music")))
    await _poll_once(ctx, monkeypatch)
    assert ctx.download_queue() is None
    ctx.cfg = replace(ctx.cfg, source=SourceConfig(url="https://music.example", username="u", password="p"))
    assert ctx.download_queue() is not None


@pytest.mark.asyncio
async def test_losing_the_drive_stops_its_queue(ctx, tmp_path, monkeypatch):
    drive = tmp_path / "media" / "usb0"
    drive.mkdir()
    (drive / ".boombox-cache").touch()
    await _poll_once(ctx, monkeypatch)
    fake = FakeQueue()
    ctx._download_queue = fake
    (drive / ".boombox-cache").unlink()
    await _poll_once(ctx, monkeypatch)
    assert fake.stopped and ctx._download_queue is None


def test_failed_downloads_are_retried_on_the_hourly_cadence_only(ctx):
    _seed_pinned_album(ctx.conn)
    ctx.conn.execute("INSERT INTO cache_state(track_id,status,error_message) VALUES('t1','error','boom')")
    fake = FakeQueue()
    ctx._ensure_download_queue = lambda: fake
    ctx._enqueue_pinned_downloads(now=10_000.0)              # first sync: retry failed
    assert sorted(fake.enqueued) == ["t1", "t2"]
    fake.enqueued.clear()
    ctx._enqueue_pinned_downloads(now=10_000.0 + 120)        # backoff retry / "Sync now"
    assert fake.enqueued == ["t2"]
    fake.enqueued.clear()
    ctx._enqueue_pinned_downloads(now=10_000.0 + 3600)       # an hour later
    assert sorted(fake.enqueued) == ["t1", "t2"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_service.py`
Expected: FAIL — `AttributeError: 'ServiceContext' object has no attribute 'download_queue'` (and the internal-storage test: `cache_state` has no `internal` drive).

- [ ] **Step 3: Implement**

In `services/boombox-library.py` imports: replace `detect_cache_drive,` with `select_cache_drive,` in the `cache_drive` import list, and replace `from boombox_library.downloader import DownloadQueue` with:

```python
from boombox_library.download_gates import MopidyStreamProbe, free_bytes, read_soc_temp_c
from boombox_library.downloader import DownloadQueue, Gates
```

In `ServiceContext.__init__`, after `self._download_queue: DownloadQueue | None = None`:

```python
        # (drive, source) the current queue was built for; see _ensure_download_queue
        self._queue_key: tuple[str, str, str, str] | None = None
        # Mopidy "is a stream-proxy URI playing?" — a download gate.
        self._stream_probe = MopidyStreamProbe()
        # Last time pinned tracks in 'error' / 'no_space' were re-enqueued:
        # failed downloads are retried on the hourly cadence only.
        self._last_failed_retry = 0.0
```

Replace `cache_candidates`:

```python
    def cache_candidates(self) -> list[dict]:
        """List drives that could be adopted as the cache (marker absent).
        Empty while the internal storage is the cache: a USB stick plugged
        in then must not raise the kiosk's adopt prompt."""
        if self.cache_state.internal:
            return []
        return list_candidate_drives(
            [Path(p) for p in self.cfg.cache.search_paths],
            marker=self.cfg.cache.marker_filename,
        )

    def download_queue(self) -> DownloadQueue | None:
        """The live download queue (api.py keep / storage routes), or None
        when there is no drive or no music server configured."""
        return self._ensure_download_queue()

    async def close(self) -> None:
        self._stop_download_queue()
        await self._stream_probe.close()
```

In `cache_poll`, replace the `new_state = detect_cache_drive(...)` call with:

```python
                new_state = select_cache_drive(
                    self.cfg.cache.internal_path,
                    [Path(p) for p in self.cfg.cache.search_paths],
                    marker=self.cfg.cache.marker_filename,
                )
```

and in its "lost" branch replace `self._download_queue = None` with `self._stop_download_queue()`.

Replace `_init_download_queue` and `_enqueue_pinned_downloads` with:

```python
    def _init_download_queue(self, mount: Path) -> None:
        self._stop_download_queue()
        src = self.cfg.source
        if not src.url:
            return
        # Note: client lifetime is per-download in the fetch — this client
        # is only used for download_url() construction.
        client = SubsonicClient(src.url, src.username, src.password)
        self._download_queue = DownloadQueue(
            conn=self.conn, client=client, cache_root=mount,
            max_concurrent=self.cfg.sync.max_concurrent_downloads,
            reserve_bytes=self.cfg.cache.reserve_bytes,
            gates=Gates(
                is_online=lambda: self._online,
                is_streaming=self._stream_probe.is_streaming,
                soc_temp_c=read_soc_temp_c,
                free_bytes=lambda: free_bytes(mount),
            ),
        )
        self._queue_key = (str(mount), src.url, src.username, src.password)

    def _stop_download_queue(self) -> None:
        if self._download_queue is not None:
            self._download_queue.stop()
        self._download_queue = None
        self._queue_key = None

    def _ensure_download_queue(self) -> DownloadQueue | None:
        """The queue for the current drive + source: built on first need
        (a source saved after the drive was adopted — the internal drive
        never "changes"), rebuilt when the drive or the credentials change."""
        mount = self.cache_state.mount_path if self.cache_state.present else None
        src = self.cfg.source
        if mount is None or not src.url:
            self._stop_download_queue()
            return None
        if self._download_queue is None or self._queue_key != (
                str(mount), src.url, src.username, src.password):
            self._init_download_queue(mount)
        return self._download_queue

    def _enqueue_pinned_downloads(self, now: float | None = None) -> None:
        queue = self._ensure_download_queue()
        if queue is None:
            log.info("no music storage or no source; pinned downloads deferred")
            return
        pinned = all_pinned_track_ids(self.conn)
        if not pinned:
            return
        now = time.time() if now is None else now
        retry_failed = now - self._last_failed_retry >= self.cfg.sync.interval_seconds
        skip = ("present",) if retry_failed else ("present", "error", "no_space")
        marks = ",".join("?" * len(skip))
        have = {r[0] for r in self.conn.execute(
            f"SELECT track_id FROM cache_state WHERE status IN ({marks})", skip)}
        if retry_failed:
            self._last_failed_retry = now
        for tid in pinned - have:
            queue.enqueue(tid)
```

In `amain`, after `cache_task.cancel()`, add `await ctx.close()`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_service.py services/tests/test_library_integration.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy --follow-imports=silent services/boombox-library.py && ~/.local/bin/mypy`
Expected: all pass; ruff and both mypy runs clean.

- [ ] **Step 5: Commit**

```bash
git add services/boombox-library.py services/tests/test_library_service.py
git commit -m "feat(library): adopt internal storage, gated queue, failed downloads retried hourly

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 4: Keep / unkeep + `keep` and `offline` facts (boombox-library API)

**Files:**
- Create: `services/boombox_library/keep.py`
- Modify: `services/boombox_library/api.py` (imports; `Context` protocol lines 36–58; `build_app` lines 61–85; `_health` lines 88–100; `_search` lines 249–265; `_artist_detail` / `_album_detail` / `_playlist_detail` lines 415–475; new handlers after `_playlist_detail`)
- Test: `services/tests/test_library_keep.py` (create), `services/tests/test_library_api.py` (`FakeContext` + appended tests)

**Interfaces:**
- Produces (`boombox_library.keep`): `KEEP_KINDS`, `class QueueLike(Protocol)` (`enqueue(tid) -> bool`, `cancel(ids) -> int`, `snapshot() -> dict`), `target_exists(conn, kind, id) -> bool`, `track_ids(conn, kind, id) -> list[str]`, `present_sizes(conn, ids) -> dict[str, int]`, `keep_state(conn, kind, id) -> KeepState`, `keep(conn, queue, kind, id) -> {"ok", "queued", "keep"}`, `unkeep(conn, queue, kind, id, *, starred_auto_pin) -> {"ok", "cancelled", "keep"}`, `offline_ids(conn) -> {"album_ids", "artist_ids", "playlist_ids"}`, `offline_flags(conn, results) -> results + "offline"`.
- `KeepState.state`: `"kept"` = a user pin on that target; `"starred"` = its pin is the starred one; `"none"` otherwise (including card-bound / favorite pins — their tracks still count in `tracks_present`, and keeping upgrades them to a user pin).
- Produces (HTTP, loopback `:6687`): `POST /api/library/keep {kind, id}` → 200 keep() | 400 `{"ok": false, "error": "kind must be album, artist or playlist"}` / `"missing id"` / `"expected a JSON object"` | 404 `{"ok": false, "error": "album not found"}`; `DELETE /api/library/keep {kind, id}` → 200 unkeep() | 400; `GET /api/library/offline` → offline_ids(); detail responses gain `keep` and per-track `offline` (artist: per-album `offline`); search results gain `offline`; health gains `"internal_storage": bool`.
- Consumes: `Context.download_queue()` (Task 3; `FakeContext.queue` in tests).

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_library_keep.py`:

```python
"""keep.py — keep/unkeep with pin fall-back, keep state, offline facts."""
from __future__ import annotations

from boombox_library import keep as k
from boombox_library.db import connect, migrate
from boombox_library.models import PinKind
from boombox_library.pins import all_pinned_track_ids, reconcile_starred


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.cancelled: list[str] = []
        self.snap = {"queued": 0, "in_flight": [], "paused": None}

    def enqueue(self, tid):
        if tid in self.enqueued:
            return False
        self.enqueued.append(tid)
        return True

    def cancel(self, ids):
        hit = [i for i in ids if i in self.enqueued and i not in self.cancelled]
        self.cancelled += hit
        return len(hit)

    def snapshot(self):
        return dict(self.snap)


def _db(tmp_path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) VALUES('ar1','Joni','joni',2,0)")
    for al, name, starred in (("al1", "Blue", 0), ("al2", "Court and Spark", 1)):
        conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,is_compilation,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,'ar1',2,60,0,?,0)", (al, name, name.lower(), starred))
    for tid, al in (("t1", "al1"), ("t2", "al1"), ("t3", "al1"), ("t4", "al2"), ("t5", "al2")):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,content_type,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,30,'mp3',1000,'audio/mpeg',0,0)",
                     (tid, al, tid.upper()))
    conn.execute("INSERT INTO playlists(id,name,song_count,owner,public,updated_at) VALUES('pl1','Mix',1,'u',0,0)")
    conn.execute("INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES('pl1','t2',0)")
    return conn


def _present(conn, tid, path="/m/x.mp3", size=1000):
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,downloaded_at) "
                 "VALUES(?,'present',?,?,0) ON CONFLICT(track_id) DO UPDATE SET status='present', "
                 "local_path=excluded.local_path, size_bytes=excluded.size_bytes", (tid, path, size))


def _source(conn, kind, tid):
    row = conn.execute("SELECT source FROM pins WHERE target_kind=? AND target_id=?", (kind, tid)).fetchone()
    return None if row is None else row["source"]


def test_keep_pins_user_and_enqueues_its_tracks(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    _present(conn, "t1")
    r = k.keep(conn, q, PinKind.ALBUM, "al1")
    assert r == {"ok": True, "queued": 3,
                 "keep": {"state": "kept", "tracks_total": 3, "tracks_present": 1}}
    assert q.enqueued == ["t1", "t2", "t3"] and _source(conn, "album", "al1") == "user"


def test_keep_is_idempotent_and_works_without_a_queue(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, q, PinKind.ALBUM, "al1")
    assert k.keep(conn, q, PinKind.ALBUM, "al1")["queued"] == 0
    assert k.keep(conn, None, PinKind.PLAYLIST, "pl1")["keep"]["state"] == "kept"


def test_unkeep_cancels_only_orphaned_queued_tracks(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, q, PinKind.ALBUM, "al1")
    k.keep(conn, q, PinKind.PLAYLIST, "pl1")
    r = k.unkeep(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True)
    assert q.cancelled == ["t1", "t3"]          # t2 is still in the kept playlist
    assert r["cancelled"] == 2 and r["keep"]["state"] == "none"
    assert _source(conn, "album", "al1") is None
    assert k.unkeep(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True)["ok"] is True


def test_unkeep_starred_album_falls_back_to_starred_pin(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    reconcile_starred(conn)
    assert _source(conn, "album", "al2") == "starred"
    k.keep(conn, q, PinKind.ALBUM, "al2")
    assert _source(conn, "album", "al2") == "user"      # one row per target: replaced
    r = k.unkeep(conn, q, PinKind.ALBUM, "al2", starred_auto_pin=True)
    assert _source(conn, "album", "al2") == "starred"
    assert {"t4", "t5"} <= all_pinned_track_ids(conn)
    assert r["cancelled"] == 0 and r["keep"]["state"] == "starred"


def test_unkeep_with_starred_auto_pin_off_drops_the_pin(tmp_path):
    conn = _db(tmp_path)
    k.keep(conn, None, PinKind.ALBUM, "al2")
    k.unkeep(conn, None, PinKind.ALBUM, "al2", starred_auto_pin=False)
    assert _source(conn, "album", "al2") is None


def test_unkeep_card_bound_album_falls_back_to_rfid_pin(tmp_path):
    from boombox_rfid.bindings import bind
    from boombox_rfid.db import migrate as rfid_migrate
    from boombox_rfid.models import BindingKind
    conn = _db(tmp_path)
    rfid_migrate(conn)
    bind(conn, "04aa", BindingKind.ALBUM, "al1", "Blue")
    assert _source(conn, "album", "al1") == "rfid"
    k.keep(conn, None, PinKind.ALBUM, "al1")
    k.unkeep(conn, None, PinKind.ALBUM, "al1", starred_auto_pin=True)
    assert _source(conn, "album", "al1") == "rfid"
    assert k.keep_state(conn, PinKind.ALBUM, "al1")["state"] == "none"


def test_keep_state_for_artist_and_playlist(tmp_path):
    conn = _db(tmp_path)
    _present(conn, "t2")
    _present(conn, "t4")
    assert k.keep_state(conn, PinKind.ARTIST, "ar1") == {"state": "none", "tracks_total": 5, "tracks_present": 2}
    assert k.keep_state(conn, PinKind.PLAYLIST, "pl1") == {"state": "none", "tracks_total": 1, "tracks_present": 1}


def test_offline_ids_and_flags(tmp_path):
    conn = _db(tmp_path)
    _present(conn, "t2")
    assert k.offline_ids(conn) == {"album_ids": ["al1"], "artist_ids": ["ar1"], "playlist_ids": ["pl1"]}
    flags = k.offline_flags(conn, [
        {"content_type": "track", "id": "t2", "title": "T2"},
        {"content_type": "track", "id": "t4", "title": "T4"},
        {"content_type": "album", "id": "al1", "title": "Blue"},
        {"content_type": "album", "id": "al2", "title": "Court and Spark"},
        {"content_type": "artist", "id": "ar1", "title": "Joni"},
    ])
    assert [f["offline"] for f in flags] == [True, False, True, False, True]
    assert flags[0]["title"] == "T2"
```

In `services/tests/test_library_api.py`: add `from boombox_library.cache_drive import CacheDriveState` to the imports; in `FakeContext.__init__` add `self.queue = None`; add the method `def download_queue(self): return self.queue`. Append:

```python
class KeepQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.snap = {"queued": 0, "in_flight": [], "paused": None}

    def enqueue(self, tid):
        if tid in self.enqueued:
            return False
        self.enqueued.append(tid)
        return True

    def cancel(self, ids):
        return 0

    def snapshot(self):
        return dict(self.snap)


def _seed_keep(conn):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) VALUES('ar1','Joni','joni',2,0)")
    for al, name, starred in (("al1", "Blue", 0), ("al2", "Court and Spark", 1)):
        conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,is_compilation,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,'ar1',2,60,0,?,0)", (al, name, name.lower(), starred))
    for tid, al in (("t1", "al1"), ("t2", "al1"), ("t3", "al1"), ("t4", "al2"), ("t5", "al2")):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,content_type,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,30,'mp3',1000,'audio/mpeg',0,0)",
                     (tid, al, tid.upper()))
    conn.execute("INSERT INTO playlists(id,name,song_count,owner,public,updated_at) VALUES('pl1','Mix',1,'u',0,0)")
    conn.execute("INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES('pl1','t2',0)")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,downloaded_at) "
                 "VALUES('t2','present','/m/t2.mp3',1000,0)")


async def test_keep_route_pins_enqueues_and_unkeeps(client):
    c, ctx, conn = client
    _seed_keep(conn)
    ctx.queue = KeepQueue()
    r = await c.post("/api/library/keep", json={"kind": "album", "id": "al1"})
    assert r.status == 200
    body = await r.json()
    assert body["queued"] == 3
    assert body["keep"] == {"state": "kept", "tracks_total": 3, "tracks_present": 1}
    r = await c.delete("/api/library/keep", json={"kind": "album", "id": "al1"})
    assert r.status == 200 and (await r.json())["keep"]["state"] == "none"


async def test_keep_route_validates(client):
    c, ctx, conn = client
    _seed_keep(conn)
    assert (await c.post("/api/library/keep", json={"kind": "track", "id": "t1"})).status == 400
    assert (await c.post("/api/library/keep", json={"kind": "album"})).status == 400
    assert (await c.post("/api/library/keep", data="nope")).status == 400
    r = await c.post("/api/library/keep", json={"kind": "album", "id": "zzz"})
    assert r.status == 404 and (await r.json()) == {"ok": False, "error": "album not found"}


async def test_keep_without_music_storage_still_pins(client):
    c, ctx, conn = client
    _seed_keep(conn)
    r = await c.post("/api/library/keep", json={"kind": "playlist", "id": "pl1"})
    assert (await r.json()) == {"ok": True, "queued": 0,
                                "keep": {"state": "kept", "tracks_total": 1, "tracks_present": 1}}


async def test_album_and_playlist_detail_carry_keep_and_offline(client):
    c, ctx, conn = client
    _seed_keep(conn)
    d = await (await c.get("/api/library/album/al1")).json()
    assert d["keep"] == {"state": "none", "tracks_total": 3, "tracks_present": 1}
    assert [(t["id"], t["offline"]) for t in d["tracks"]] == [("t1", False), ("t2", True), ("t3", False)]
    d = await (await c.get("/api/library/playlist/pl1")).json()
    assert d["keep"]["tracks_present"] == 1 and d["tracks"][0]["offline"] is True


async def test_artist_detail_albums_carry_offline(client):
    c, ctx, conn = client
    _seed_keep(conn)
    d = await (await c.get("/api/library/artist/ar1")).json()
    assert {a["id"]: a["offline"] for a in d["albums"]} == {"al1": True, "al2": False}
    assert d["keep"] == {"state": "none", "tracks_total": 5, "tracks_present": 1}


async def test_search_results_carry_offline(client):
    c, ctx, conn = client
    _seed_keep(conn)
    conn.execute("INSERT INTO search_index(content_type,id,title,body) VALUES('album','al1','Blue','Blue')")
    conn.execute("INSERT INTO search_index(content_type,id,title,body) VALUES('album','al2','Court','Court')")
    blue = (await (await c.get("/api/library/search?q=blue")).json())["results"]
    court = (await (await c.get("/api/library/search?q=court")).json())["results"]
    assert blue[0]["offline"] is True and court[0]["offline"] is False


async def test_offline_ids_route(client):
    c, ctx, conn = client
    _seed_keep(conn)
    assert (await (await c.get("/api/library/offline")).json()) == {
        "album_ids": ["al1"], "artist_ids": ["ar1"], "playlist_ids": ["pl1"]}


async def test_health_reports_internal_storage(client):
    c, ctx, _ = client
    assert (await (await c.get("/api/library/health")).json())["internal_storage"] is False
    ctx.cache_state = CacheDriveState(present=True, mount_path=Path("/opt/boombox/storage/music"),
                                      free_bytes=1, total_bytes=2, internal=True)
    assert (await (await c.get("/api/library/health")).json())["internal_storage"] is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_keep.py services/tests/test_library_api.py`
Expected: FAIL — `ImportError: cannot import name 'keep' from 'boombox_library'` and 404s for `/api/library/keep`.

- [ ] **Step 3: Implement `keep.py`**

Create `services/boombox_library/keep.py`:

```python
"""'Keep offline' (spec 2A): user pins on albums / artists / playlists,
their download progress, and the offline facts the LAN app dims rows with.

Pure functions over the catalog connection plus a queue-like object (the
service's DownloadQueue, or None when there is no music storage / source).

The pins table holds ONE row per target (pins.py ranks sources user >
favorite > rfid > starred), so keeping a starred or card-bound album
*replaces* its pin. Unkeeping therefore restores the weaker pin at once —
otherwise the album's files would be unprotected (evictable, removable)
until the next hourly reconcile.
"""
from __future__ import annotations

import logging
from sqlite3 import Connection
from typing import Iterable, Iterator, Optional, Protocol

from .models import PinKind, PinSource
from .pins import all_pinned_track_ids, expand_pin_to_tracks, pin, unpin

log = logging.getLogger("boombox-library.keep")

KEEP_KINDS = frozenset({PinKind.ALBUM, PinKind.ARTIST, PinKind.PLAYLIST})
_TABLE = {PinKind.ALBUM: "albums", PinKind.ARTIST: "artists",
          PinKind.PLAYLIST: "playlists", PinKind.TRACK: "tracks"}


class QueueLike(Protocol):
    def enqueue(self, track_id: str) -> bool: ...
    def cancel(self, track_ids: Iterable[str]) -> int: ...
    def snapshot(self) -> dict: ...


def _chunks(ids: list[str], n: int = 500) -> Iterator[list[str]]:
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def target_exists(conn: Connection, kind: PinKind, target_id: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {_TABLE[kind]} WHERE id=?",
                        (target_id,)).fetchone() is not None


def track_ids(conn: Connection, kind: PinKind, target_id: str) -> list[str]:
    """The target's tracks, de-duplicated (a playlist can repeat one)."""
    return list(dict.fromkeys(expand_pin_to_tracks(conn, kind, target_id)))


def present_sizes(conn: Connection, ids: list[str]) -> dict[str, int]:
    """track_id → size of every id that is on disk ('present')."""
    out: dict[str, int] = {}
    for chunk in _chunks(ids):
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT track_id, size_bytes FROM cache_state "
                f"WHERE status='present' AND track_id IN ({marks})", chunk):
            out[r[0]] = int(r[1] or 0)
    return out


def _pin_source(conn: Connection, kind: PinKind, target_id: str) -> Optional[str]:
    row = conn.execute("SELECT source FROM pins WHERE target_kind=? AND target_id=?",
                       (kind.value, target_id)).fetchone()
    return None if row is None else str(row["source"])


def keep_state(conn: Connection, kind: PinKind, target_id: str) -> dict:
    source = _pin_source(conn, kind, target_id)
    state = ("kept" if source == PinSource.USER.value
             else "starred" if source == PinSource.STARRED.value else "none")
    ids = track_ids(conn, kind, target_id)
    return {"state": state, "tracks_total": len(ids),
            "tracks_present": len(present_sizes(conn, ids))}


def keep(conn: Connection, queue: Optional[QueueLike], kind: PinKind,
         target_id: str) -> dict:
    """pin(source=user) + enqueue the target's tracks. Idempotent."""
    pin(conn, kind, target_id, PinSource.USER)
    queued = 0
    if queue is not None:
        queued = sum(1 for tid in track_ids(conn, kind, target_id) if queue.enqueue(tid))
    return {"ok": True, "queued": queued, "keep": keep_state(conn, kind, target_id)}


def _card_bound(conn: Connection, kind: PinKind, target_id: str) -> bool:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='rfid_bindings'").fetchone() is None:
        return False
    return conn.execute("SELECT 1 FROM rfid_bindings WHERE kind=? AND target_id=?",
                        (kind.value, target_id)).fetchone() is not None


def _starred(conn: Connection, kind: PinKind, target_id: str) -> bool:
    if kind not in (PinKind.ALBUM, PinKind.TRACK):
        return False  # reconcile_starred pins albums and tracks only
    row = conn.execute(f"SELECT navidrome_starred FROM {_TABLE[kind]} WHERE id=?",
                       (target_id,)).fetchone()
    return bool(row and row[0])


def unkeep(conn: Connection, queue: Optional[QueueLike], kind: PinKind,
           target_id: str, *, starred_auto_pin: bool) -> dict:
    """Drop the user pin; restore the card's or the star's pin it replaced;
    cancel queued downloads of tracks no pin protects any more (in-flight
    ones finish). Idempotent."""
    unpin(conn, kind, target_id, source=PinSource.USER)
    if _pin_source(conn, kind, target_id) is None:
        if _card_bound(conn, kind, target_id):
            pin(conn, kind, target_id, PinSource.RFID)
        elif starred_auto_pin and _starred(conn, kind, target_id):
            pin(conn, kind, target_id, PinSource.STARRED)
    cancelled = 0
    if queue is not None:
        protected = all_pinned_track_ids(conn)
        cancelled = queue.cancel(
            [t for t in track_ids(conn, kind, target_id) if t not in protected])
    return {"ok": True, "cancelled": cancelled, "keep": keep_state(conn, kind, target_id)}


_OFFLINE_IDS = {
    "album_ids": "SELECT DISTINCT t.album_id FROM tracks t "
                 "JOIN cache_state cs ON cs.track_id = t.id WHERE cs.status='present'",
    "artist_ids": "SELECT DISTINCT al.artist_id FROM albums al "
                  "JOIN tracks t ON t.album_id = al.id "
                  "JOIN cache_state cs ON cs.track_id = t.id WHERE cs.status='present'",
    "playlist_ids": "SELECT DISTINCT pt.playlist_id FROM playlist_tracks pt "
                    "JOIN cache_state cs ON cs.track_id = pt.track_id WHERE cs.status='present'",
}

_OFFLINE_FLAG_SQL = {
    "track": "SELECT track_id FROM cache_state WHERE status='present' AND track_id IN ({})",
    "album": "SELECT DISTINCT t.album_id FROM tracks t JOIN cache_state cs ON cs.track_id = t.id "
             "WHERE cs.status='present' AND t.album_id IN ({})",
    "artist": "SELECT DISTINCT al.artist_id FROM albums al JOIN tracks t ON t.album_id = al.id "
              "JOIN cache_state cs ON cs.track_id = t.id "
              "WHERE cs.status='present' AND al.artist_id IN ({})",
}


def offline_ids(conn: Connection) -> dict[str, list[str]]:
    """Albums / artists / playlists with at least one track on disk."""
    return {key: sorted(r[0] for r in conn.execute(sql)) for key, sql in _OFFLINE_IDS.items()}


def offline_flags(conn: Connection, results: list[dict]) -> list[dict]:
    """Search results (content_type, id, ...) + "offline": on disk (a track)
    or with at least one track on disk (an album / artist)."""
    by_type: dict[str, list[str]] = {}
    for r in results:
        by_type.setdefault(str(r.get("content_type", "")), []).append(str(r["id"]))
    have: set[tuple[str, str]] = set()
    for ctype, ids in by_type.items():
        sql = _OFFLINE_FLAG_SQL.get(ctype)
        if sql is None:
            continue
        for chunk in _chunks(list(dict.fromkeys(ids))):
            for row in conn.execute(sql.format(",".join("?" * len(chunk))), chunk):
                have.add((ctype, row[0]))
    return [{**r, "offline": (str(r.get("content_type", "")), str(r["id"])) in have}
            for r in results]
```

(Task 5 adds `os`, `Callable` and `CacheDriveState` imports together with the code that uses them.)

- [ ] **Step 4: Wire the API**

In `services/boombox_library/api.py` imports add `from . import keep as keep_mod`. In `Context` add:

```python
    # The live DownloadQueue (keep / storage routes), None without storage or source.
    def download_queue(self): ...
```

In `build_app`, before `stream_proxy.setup(app)`:

```python
    app.router.add_post("/api/library/keep", _keep_post)
    app.router.add_delete("/api/library/keep", _keep_delete)
    app.router.add_get("/api/library/offline", _offline)
```

In `_health`'s dict add `"internal_storage": bool(drive and getattr(drive, "internal", False)),` after `"cache_mount"`.

In `_search` replace the last line with:

```python
    return web.json_response(
        {"results": keep_mod.offline_flags(ctx.conn, [dict(r) for r in rows])})
```

`_artist_detail` return becomes:

```python
    album_rows = [dict(a) for a in albums]
    flags = keep_mod.offline_flags(
        ctx.conn, [{"content_type": "album", "id": a["id"]} for a in album_rows])
    for a, f in zip(album_rows, flags):
        a["offline"] = f["offline"]
    return web.json_response({
        "artist": dict(row),
        "albums": album_rows,
        "keep": keep_mod.keep_state(ctx.conn, PinKind.ARTIST, artist_id),
    })
```

`_album_detail` return becomes (and `_playlist_detail` the same with `"playlist": dict(row)` and `PinKind.PLAYLIST, playlist_id`):

```python
    track_rows = _with_offline(tracks)
    return web.json_response({
        "album": dict(row),
        "tracks": track_rows,
        "keep": keep_mod.keep_state(ctx.conn, PinKind.ALBUM, album_id),
    })
```

Add after `_not_found`:

```python
def _with_offline(rows) -> list[dict]:
    """Track rows + "offline": the file is on the boombox."""
    out = [dict(t) for t in rows]
    for t in out:
        t["offline"] = t.get("cache_status") == "present"
    return out
```

Add after `_playlist_detail`:

```python
def _bad(error: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": error}, status=status)


async def _keep_target(req: web.Request) -> tuple[PinKind, str] | web.Response:
    """(kind, id) from a {kind, id} JSON body, or the 400 to answer."""
    try:
        body = await req.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _bad("expected a JSON object")
    try:
        kind = PinKind(body.get("kind"))
    except ValueError:
        return _bad("kind must be album, artist or playlist")
    if kind not in keep_mod.KEEP_KINDS:
        return _bad("kind must be album, artist or playlist")
    target_id = body.get("id")
    if not isinstance(target_id, str) or not target_id:
        return _bad("missing id")
    return kind, target_id


async def _keep_post(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    t = await _keep_target(req)
    if isinstance(t, web.Response):
        return t
    kind, target_id = t
    if not keep_mod.target_exists(ctx.conn, kind, target_id):
        return _bad(f"{kind.value} not found", 404)
    return web.json_response(keep_mod.keep(ctx.conn, ctx.download_queue(), kind, target_id))


async def _keep_delete(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    t = await _keep_target(req)
    if isinstance(t, web.Response):
        return t
    kind, target_id = t
    return web.json_response(keep_mod.unkeep(
        ctx.conn, ctx.download_queue(), kind, target_id,
        starred_auto_pin=ctx.cfg.sync.starred_auto_pin))


async def _offline(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(keep_mod.offline_ids(ctx.conn))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_keep.py services/tests/test_library_api.py services/tests/test_library_pins.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 6: Commit**

```bash
git add services/boombox_library/keep.py services/boombox_library/api.py services/tests/test_library_keep.py services/tests/test_library_api.py
git commit -m "feat(library): keep/unkeep with starred/card pin fall-back; keep + offline in details and search

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Storage overview, Remove and Retry (boombox-library API)

**Files:**
- Modify: `services/boombox_library/keep.py` (append), `services/boombox_library/api.py` (routes + handlers)
- Modify: `docs/SERVICES.md` (boombox-library endpoint table, after the `/api/library/art/{art_id}` row)
- Test: `services/tests/test_library_keep.py`, `services/tests/test_library_api.py` (append)

**Interfaces:**
- Produces (`boombox_library.keep`): `STARRED_ONLY = "unstar in Navidrome to remove"`, `kept_items(conn) -> list[dict]`, `storage_overview(conn, drive: CacheDriveState | None, reserve_bytes: int, queue: QueueLike | None) -> dict` (shape in Global Constraints), `remove_kept(conn, queue, kind, id, *, starred_auto_pin, delete_file=os.unlink) -> tuple[int, dict]` (200 `{"ok": true, "removed_tracks", "freed_bytes", "keep"}` | 409 `{"ok": false, "error": STARRED_ONLY}`), `retry_failed(conn, queue) -> int`.
- `kept` lists user and starred pins on albums / artists / playlists (oldest first) plus one `{"kind": "starred_tracks", "id": "", "name": "Starred songs", "source": "starred", ...}` row when starred single tracks exist.
- Produces (HTTP): `GET /api/library/storage`; `POST /api/library/storage/remove {kind: album|artist|playlist|starred_tracks, id}` → 200 | 400 | 409; `POST /api/library/storage/retry` → 200 `{"ok": true, "retried": n}` | 409 `{"ok": false, "error": "downloads aren't running — no music storage or no music server set up"}`.

- [ ] **Step 1: Write the failing tests**

In `services/tests/test_library_keep.py` add `from pathlib import Path` and `from boombox_library.cache_drive import CacheDriveState` to the top import block, then append:

```python
def test_storage_overview_reports_downloads_and_no_space(tmp_path):
    conn = _db(tmp_path)
    reconcile_starred(conn)
    k.keep(conn, None, PinKind.ALBUM, "al1")
    _present(conn, "t1", size=1500)
    conn.execute("INSERT INTO cache_state(track_id,status,error_message) VALUES('t2','error','boom')")
    conn.execute("INSERT INTO cache_state(track_id,status,error_message) VALUES('t3','no_space','no space')")
    q = FakeQueue()
    q.snap = {"queued": 4, "in_flight": ["t4"], "paused": "low_space"}
    drive = CacheDriveState(present=True, mount_path=Path("/opt/boombox/storage/music"),
                            free_bytes=10, total_bytes=100, internal=True)
    o = k.storage_overview(conn, drive, 20, q)
    assert o["drive"] == {"present": True, "internal": True, "mount_path": "/opt/boombox/storage/music",
                          "total_bytes": 100, "free_bytes": 10, "reserve_bytes": 20,
                          "music_bytes": 1500, "kept_tracks": 1}
    assert o["downloads"] == {"active": True, "queued": 4, "in_flight": [{"id": "t4", "title": "T4"}],
                              "paused": "low_space", "failed": 1, "no_space": 1}
    assert sorted(o["kept"], key=lambda i: i["id"]) == [
        {"kind": "album", "id": "al1", "name": "Blue", "source": "user",
         "tracks_total": 3, "tracks_present": 1, "bytes": 1500},
        {"kind": "album", "id": "al2", "name": "Court and Spark", "source": "starred",
         "tracks_total": 2, "tracks_present": 0, "bytes": 0},
    ]


def test_storage_overview_without_drive_or_queue(tmp_path):
    conn = _db(tmp_path)
    conn.execute("UPDATE tracks SET navidrome_starred=1 WHERE id='t5'")
    reconcile_starred(conn)
    o = k.storage_overview(conn, None, 20, None)
    assert o["drive"]["present"] is False and o["drive"]["free_bytes"] is None
    assert o["downloads"]["active"] is False and o["downloads"]["paused"] is None
    assert o["kept"][-1] == {"kind": "starred_tracks", "id": "", "name": "Starred songs", "source": "starred",
                             "tracks_total": 1, "tracks_present": 0, "bytes": 0}


def test_remove_kept_deletes_orphaned_files_now(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    f1, f2 = tmp_path / "t1.mp3", tmp_path / "t2.mp3"
    f1.write_bytes(b"x" * 10)
    f2.write_bytes(b"y")
    k.keep(conn, q, PinKind.ALBUM, "al1")
    k.keep(conn, q, PinKind.PLAYLIST, "pl1")
    _present(conn, "t1", str(f1), 10)
    _present(conn, "t2", str(f2), 1)
    status, r = k.remove_kept(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True)
    assert status == 200 and r["removed_tracks"] == 1 and r["freed_bytes"] == 10
    assert not f1.exists() and f2.exists()        # t2 is still kept via the playlist
    assert r["keep"]["state"] == "none"
    assert k.remove_kept(conn, q, PinKind.ALBUM, "al1", starred_auto_pin=True)[1]["removed_tracks"] == 0


def test_remove_kept_starred_overlap_deletes_nothing(tmp_path):
    conn = _db(tmp_path)
    reconcile_starred(conn)
    f4 = tmp_path / "t4.mp3"
    f4.write_bytes(b"x")
    _present(conn, "t4", str(f4), 1)
    k.keep(conn, None, PinKind.ALBUM, "al2")
    status, r = k.remove_kept(conn, None, PinKind.ALBUM, "al2", starred_auto_pin=True)
    assert status == 200 and r["removed_tracks"] == 0 and f4.exists()
    assert r["keep"]["state"] == "starred"


def test_remove_starred_only_is_refused(tmp_path):
    conn = _db(tmp_path)
    reconcile_starred(conn)
    status, r = k.remove_kept(conn, None, PinKind.ALBUM, "al2", starred_auto_pin=True)
    assert status == 409 and r == {"ok": False, "error": "unstar in Navidrome to remove"}


def test_retry_failed_requeues_pinned_failures_only(tmp_path):
    conn = _db(tmp_path)
    q = FakeQueue()
    k.keep(conn, None, PinKind.ALBUM, "al1")
    for tid, status in (("t1", "error"), ("t2", "no_space"), ("t4", "error")):
        conn.execute("INSERT INTO cache_state(track_id,status) VALUES(?,?)", (tid, status))
    assert k.retry_failed(conn, q) == 2 and q.enqueued == ["t1", "t2"]
```

Append to `services/tests/test_library_api.py`:

```python
async def test_storage_route_overview(client):
    c, ctx, conn = client
    _seed_keep(conn)
    ctx.queue = KeepQueue()
    ctx.cache_state = CacheDriveState(present=True, mount_path=Path("/opt/boombox/storage/music"),
                                      free_bytes=5, total_bytes=9, internal=True)
    o = await (await c.get("/api/library/storage")).json()
    assert o["drive"]["internal"] is True and o["drive"]["reserve_bytes"] == ctx.cfg.cache.reserve_bytes
    assert o["drive"]["kept_tracks"] == 1 and o["downloads"]["active"] is True


async def test_storage_remove_route(client):
    c, ctx, conn = client
    _seed_keep(conn)
    await c.post("/api/library/keep", json={"kind": "album", "id": "al1"})
    r = await c.post("/api/library/storage/remove", json={"kind": "album", "id": "al1"})
    assert r.status == 200 and (await r.json())["ok"] is True
    r = await c.post("/api/library/storage/remove", json={"kind": "starred_tracks", "id": ""})
    assert r.status == 409 and (await r.json())["error"] == "unstar in Navidrome to remove"
    assert (await c.post("/api/library/storage/remove", json={"kind": "track", "id": "t1"})).status == 400


async def test_storage_retry_route(client):
    c, ctx, conn = client
    r = await c.post("/api/library/storage/retry", json={})
    assert r.status == 409 and (await r.json())["ok"] is False
    ctx.queue = KeepQueue()
    r = await c.post("/api/library/storage/retry", json={})
    assert (await r.json()) == {"ok": True, "retried": 0}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_keep.py services/tests/test_library_api.py`
Expected: FAIL — `AttributeError: module 'boombox_library.keep' has no attribute 'storage_overview'`; 404 on `/api/library/storage`.

- [ ] **Step 3: Implement**

In `services/boombox_library/keep.py` add `import os` to the stdlib imports, `Callable` to the `typing` import and `from .cache_drive import CacheDriveState` before `from .models import …`, then append:

```python
STARRED_ONLY = "unstar in Navidrome to remove"


def _name(conn: Connection, kind: PinKind, target_id: str) -> str:
    row = conn.execute(f"SELECT name FROM {_TABLE[kind]} WHERE id=?", (target_id,)).fetchone()
    return str(row[0]) if row else target_id


def _item(conn: Connection, kind: str, target_id: str, name: str, source: str,
          ids: list[str]) -> dict:
    sizes = present_sizes(conn, ids)
    return {"kind": kind, "id": target_id, "name": name, "source": source,
            "tracks_total": len(ids), "tracks_present": len(sizes),
            "bytes": sum(sizes.values())}


def kept_items(conn: Connection) -> list[dict]:
    """User + starred keeps (albums / artists / playlists), oldest first,
    then one aggregate row for starred single tracks."""
    rows = list(conn.execute(
        "SELECT target_kind, target_id, source FROM pins "
        "WHERE source IN ('user', 'starred') "
        "AND target_kind IN ('album', 'artist', 'playlist') ORDER BY added_at"))
    items = []
    for r in rows:
        kind = PinKind(r["target_kind"])
        items.append(_item(conn, kind.value, r["target_id"], _name(conn, kind, r["target_id"]),
                           r["source"], track_ids(conn, kind, r["target_id"])))
    starred = [r[0] for r in conn.execute(
        "SELECT target_id FROM pins WHERE target_kind='track' AND source='starred'")]
    if starred:
        items.append(_item(conn, "starred_tracks", "", "Starred songs", "starred", starred))
    return items


def storage_overview(conn: Connection, drive: Optional[CacheDriveState],
                     reserve_bytes: int, queue: Optional[QueueLike]) -> dict:
    count, total = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM cache_state "
        "WHERE status='present'").fetchone()
    failed = {r[0]: int(r[1]) for r in conn.execute(
        "SELECT status, COUNT(*) FROM cache_state "
        "WHERE status IN ('error', 'no_space') GROUP BY status")}
    snap = queue.snapshot() if queue is not None else {
        "queued": 0, "in_flight": [], "paused": None}
    in_flight = [str(t) for t in snap["in_flight"]]
    titles: dict[str, str] = {}
    for chunk in _chunks(in_flight):
        marks = ",".join("?" * len(chunk))
        titles.update((r[0], r[1]) for r in conn.execute(
            f"SELECT id, title FROM tracks WHERE id IN ({marks})", chunk))
    present = drive is not None and drive.present
    return {
        "drive": {
            "present": present,
            "internal": bool(drive is not None and drive.internal),
            "mount_path": str(drive.mount_path) if drive is not None and present and drive.mount_path else None,
            "total_bytes": drive.total_bytes if drive is not None and present else None,
            "free_bytes": drive.free_bytes if drive is not None and present else None,
            "reserve_bytes": reserve_bytes,
            "music_bytes": int(total),
            "kept_tracks": int(count),
        },
        "kept": kept_items(conn),
        "downloads": {
            "active": queue is not None,
            "queued": int(snap["queued"]),
            "in_flight": [{"id": t, "title": titles.get(t, t)} for t in in_flight],
            "paused": snap["paused"],
            "failed": failed.get("error", 0),
            "no_space": failed.get("no_space", 0),
        },
    }


def remove_kept(conn: Connection, queue: Optional[QueueLike], kind: PinKind,
                target_id: str, *, starred_auto_pin: bool,
                delete_file: Callable[[str], None] = os.unlink) -> tuple[int, dict]:
    """Storage → Remove: unkeep, then delete at once the files of tracks no
    pin protects any more (the plain unkeep leaves them to eviction).
    Starred-only items can't be removed here. Idempotent."""
    if _pin_source(conn, kind, target_id) == PinSource.STARRED.value:
        return 409, {"ok": False, "error": STARRED_ONLY}
    unkeep(conn, queue, kind, target_id, starred_auto_pin=starred_auto_pin)
    protected = all_pinned_track_ids(conn)
    orphans = [t for t in track_ids(conn, kind, target_id) if t not in protected]
    removed = freed = 0
    for chunk in _chunks(orphans):
        marks = ",".join("?" * len(chunk))
        rows = list(conn.execute(
            f"SELECT track_id, local_path, size_bytes FROM cache_state "
            f"WHERE status='present' AND track_id IN ({marks})", chunk))
        for r in rows:
            if r["local_path"]:
                try:
                    delete_file(r["local_path"])
                except FileNotFoundError:
                    pass
                except OSError as e:
                    log.warning("could not delete %s: %s", r["local_path"], e)
                    continue
            conn.execute(
                "UPDATE cache_state SET status='absent', local_path=NULL, size_bytes=NULL, "
                "downloaded_at=NULL, error_message=NULL WHERE track_id=?", (r["track_id"],))
            removed += 1
            freed += int(r["size_bytes"] or 0)
    return 200, {"ok": True, "removed_tracks": removed, "freed_bytes": freed,
                 "keep": keep_state(conn, kind, target_id)}


def retry_failed(conn: Connection, queue: QueueLike) -> int:
    """Re-enqueue pinned tracks in 'error' / 'no_space' (Storage → Retry failed)."""
    protected = all_pinned_track_ids(conn)
    ids = [r[0] for r in conn.execute(
        "SELECT track_id FROM cache_state WHERE status IN ('error', 'no_space') "
        "ORDER BY track_id") if r[0] in protected]
    return sum(1 for t in ids if queue.enqueue(t))
```

In `services/boombox_library/api.py` `build_app` add:

```python
    app.router.add_get("/api/library/storage", _storage)
    app.router.add_post("/api/library/storage/remove", _storage_remove)
    app.router.add_post("/api/library/storage/retry", _storage_retry)
```

and after `_offline`:

```python
async def _storage(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(keep_mod.storage_overview(
        ctx.conn, ctx.cache_drive_state(), ctx.cfg.cache.reserve_bytes, ctx.download_queue()))


async def _storage_remove(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    try:
        body = await req.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("kind") == "starred_tracks":
        return _bad(keep_mod.STARRED_ONLY, 409)
    t = await _keep_target(req)
    if isinstance(t, web.Response):
        return t
    kind, target_id = t
    status, out = keep_mod.remove_kept(
        ctx.conn, ctx.download_queue(), kind, target_id,
        starred_auto_pin=ctx.cfg.sync.starred_auto_pin)
    return web.json_response(out, status=status)


async def _storage_retry(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    queue = ctx.download_queue()
    if queue is None:
        return _bad("downloads aren't running — no music storage or no music server set up", 409)
    return web.json_response({"ok": True, "retried": keep_mod.retry_failed(ctx.conn, queue)})
```

(aiohttp caches the request body, so `_keep_target` re-reading `req.json()` after the first read is safe.)

In `docs/SERVICES.md`, change the health row's field list to include `internal_storage`, and add after the `/api/library/art/{art_id}` row:

```markdown
| `POST` / `DELETE /api/library/keep` | LAN app "Keep offline": `{kind: album\|artist\|playlist, id}` → user pin + enqueue / unpin (a starred or card-bound target falls back to that pin) + cancel queued orphans → `{ok, queued\|cancelled, keep: {state, tracks_total, tracks_present}}` |
| `GET  /api/library/offline` | `{album_ids, artist_ids, playlist_ids}` with ≥ 1 track on disk (LAN app dims the rest while offline) |
| `GET  /api/library/storage` | Admin → Storage: `{drive, kept, downloads}` (reserve, music bytes, kept items with progress, queue / in-flight / paused reason / failed / no_space) |
| `POST /api/library/storage/remove` | `{kind, id}` → unkeep + delete the now-unprotected files at once; starred-only → 409 "unstar in Navidrome to remove" |
| `POST /api/library/storage/retry` | Re-enqueue pinned `error` / `no_space` tracks (otherwise retried by the hourly sync only) |
```

and under the boombox-library heading add the paragraph:

```markdown
Kept-offline music lives on the internal drive at `cache.internal_path`
(default `/opt/boombox/storage/music`, adopted automatically and preferred
over `/media` drives; `""` restores the USB-drive behaviour). Downloads keep
`cache.reserve_bytes` (default 20 GiB) free, run ≤ `sync.max_concurrent_downloads`
at a time, and pause while Mopidy streams from the proxy, while the SoC is
≥ 70 °C (re-checked every 60 s) and while Navidrome is unreachable.
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/keep.py services/boombox_library/api.py services/tests/test_library_keep.py services/tests/test_library_api.py docs/SERVICES.md
git commit -m "feat(library): storage overview, remove kept items, retry failed downloads

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 6: Kept tracks play offline from RFID cards and the kiosk

`boombox-rfid` resolves every tap with `online=True`, so with the homelab down a card for a half-kept album queues dead stream-proxy URLs (Mopidy then fails track by track, and the queue's "pause while streaming" gate sees a stream that never plays). It now asks boombox-library whether Navidrome is reachable. The kiosk already resolves through `/api/library/resolve` (which uses the library's own reachability); this task pins that path with a test.

**Files:**
- Modify: `services/boombox_rfid/playback.py` (imports; new `library_online` after `resolve_uris`)
- Modify: `services/boombox-rfid.py` (imports lines 26–31; the `resolve_uris(... online=True ...)` call ~line 119)
- Test: `services/tests/test_rfid_playback.py`, `services/tests/test_library_api.py` (append)

**Interfaces:**
- Produces (`boombox_rfid.playback`): `async library_online(url: str | None = None, timeout: float = 2.0) -> bool` — GET `${BOOMBOX_LIBRARY_BASE:-http://127.0.0.1:6687}/api/library/health`; returns False only when the library answers 200 with `"navidrome_reachable": false`; library down / non-200 / bad JSON → True (keeps `wait_for_stream_proxy`'s restart ride-out).

- [ ] **Step 1: Write the failing tests**

In `services/tests/test_rfid_playback.py` change the playback import to `from boombox_rfid.playback import expand_to_track_ids, library_online, resolve_uris` and append:

```python
def test_resolve_uris_offline_plays_kept_file(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    kept = tmp_path / "storage" / "music" / "audio" / "t1.mp3"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"ID3")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,downloaded_at) "
                 "VALUES('t1','present',?,3,0)", (str(kept),))
    uris = resolve_uris(conn, ["t1", "t2"], online=False,
                        source_url="http://nav:4533", source_username="u", source_password="p")
    assert uris == [f"file://{kept}"]          # t2 isn't kept: dropped, not a dead stream URL


async def test_library_online_follows_the_library_health(aiohttp_server):
    from aiohttp import web
    state: dict = {"status": 200, "body": {"navidrome_reachable": False}}

    async def health(req):
        return web.json_response(state["body"], status=state["status"])
    app = web.Application()
    app.router.add_get("/api/library/health", health)
    srv = await aiohttp_server(app)
    url = str(srv.make_url("/api/library/health"))
    assert await library_online(url) is False
    state["body"] = {"navidrome_reachable": True}
    assert await library_online(url) is True
    state["status"] = 500
    assert await library_online(url) is True


async def test_library_online_when_the_library_is_down_keeps_the_stream_path():
    assert await library_online("http://127.0.0.1:1/api/library/health", timeout=0.5) is True
```

Append to `services/tests/test_library_api.py`:

```python
async def test_resolve_batch_offline_returns_kept_file_and_drops_the_rest(client, tmp_path):
    c, ctx, conn = client
    _seed_keep(conn)
    f = tmp_path / "t2.mp3"
    f.write_bytes(b"x")
    conn.execute("UPDATE cache_state SET local_path=? WHERE track_id='t2'", (str(f),))
    ctx._ping_ok = False                       # Navidrome unreachable
    ctx.cfg = replace(ctx.cfg, source=SourceConfig(url="https://m.example", username="u", password="p"))
    items = (await (await c.post("/api/library/resolve", json={"ids": ["t1", "t2"]})).json())["items"]
    assert [(i["id"], i["source"]) for i in items] == [("t1", "offline_miss"), ("t2", "cache")]
    assert items[1]["uri"] == f"file://{f}"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_rfid_playback.py services/tests/test_library_api.py`
Expected: FAIL — `ImportError: cannot import name 'library_online'` (the resolve-batch and resolve_uris offline tests already pass: they pin existing behaviour).

- [ ] **Step 3: Implement**

In `services/boombox_rfid/playback.py` add `import os` to the imports and, after `resolve_uris`:

```python
def _library_health_url() -> str:
    base = os.environ.get("BOOMBOX_LIBRARY_BASE") or "http://127.0.0.1:6687"
    return base.rstrip("/") + "/api/library/health"


async def library_online(url: str | None = None, timeout: float = 2.0) -> bool:
    """Is the Home Library server reachable, per boombox-library's own check?

    Only a definite "unreachable" answer returns False — the tap then plays
    the kept (cached) tracks and skips the rest instead of queueing stream
    URLs that can't play. boombox-library itself not answering returns True,
    so wait_for_stream_proxy still rides out its restart."""
    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get(url or _library_health_url()) as r:
                if r.status != 200:
                    return True
                body = await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return True
    return not (isinstance(body, dict) and body.get("navidrome_reachable") is False)
```

In `services/boombox-rfid.py` add `library_online,` to the `boombox_rfid.playback` import list and replace the resolve block:

```python
        # Re-read library config every tap so freshly-saved creds take
        # effect without restarting boombox-rfid.
        lib_cfg = load_library_config()
        online = await library_online()
        if not online:
            log.info("uid %s: Home Library unreachable — playing kept tracks only", uid)
        try:
            uris = resolve_uris(
                self.conn, track_ids, online=online,
                source_url=lib_cfg.source.url,
                source_username=lib_cfg.source.username,
                source_password=lib_cfg.source.password,
            )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_rfid_playback.py services/tests/test_library_api.py services/tests/test_rfid_queueing.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy && ~/.local/bin/mypy --follow-imports=silent services/boombox-rfid.py`
Expected: all pass; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_rfid/playback.py services/boombox-rfid.py services/tests/test_rfid_playback.py services/tests/test_library_api.py
git commit -m "fix(rfid): taps play only kept tracks while the Home Library is unreachable

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Household routes — keep / unkeep / status / offline (boombox-remote)

**Files:**
- Modify: `services/remote_home.py` (constants; new `_proxy_json`; `_make_handlers` returns a dict; `add_routes`)
- Modify: `docs/SERVICES.md` (boombox-remote table, after the `POST /api/remote/home/play` row)
- Test: `services/tests/test_remote_home.py` (`FakeLibrary` + appended tests)

**Interfaces:**
- Consumes: `POST`/`DELETE /api/library/keep`, `GET /api/library/health` (`navidrome_reachable`, `internal_storage`), `GET /api/library/offline` (Tasks 4–5).
- Produces (pair token + remote enabled, via the existing middlewares): `POST`/`DELETE /api/remote/home/keep {kind, id}` → the library's JSON and status (400 `{"ok": false, "error": "kind must be album, artist or playlist"}` / `"bad id"` / `"expected a JSON object"` before any upstream call; upstream ≥ 500 / unreachable → 502 `{"ok": false, "error": "library service not answering"}`; a library 4xx without `ok` gets `{"ok": false, "error": <its error>}`); `GET /api/remote/home/status` → `{"online": bool, "internal_storage": bool}` | 502; `GET /api/remote/home/offline` → pass-through | 502.

- [ ] **Step 1: Write the failing tests**

In `services/tests/test_remote_home.py` `FakeLibrary.__init__` add:

```python
        self.health: dict = {"navidrome_reachable": True, "internal_storage": True}
        self.keep_calls: list[tuple[str, dict]] = []
```

and in `handle`, before the final `return web.json_response({"error": "not found"}, status=404)`:

```python
            if p == "/api/library/health":
                return web.json_response(self.health)
            if p == "/api/library/offline":
                return web.json_response({"album_ids": ["al1"], "artist_ids": [], "playlist_ids": []})
            if p == "/api/library/keep":
                body = await req.json()
                self.keep_calls.append((req.method, body))
                if body.get("id") == "missing":
                    return web.json_response({"ok": False, "error": "album not found"}, status=404)
                state = "kept" if req.method == "POST" else "none"
                return web.json_response({"ok": True, "queued": 3, "keep": {
                    "state": state, "tracks_total": 3, "tracks_present": 0}})
```

Append:

```python
async def test_keep_status_offline_require_pair_token(home):
    client, _lib, _ = home
    body = {"kind": "album", "id": "al1"}
    assert (await client.post("/api/remote/home/keep", json=body)).status == 401
    assert (await client.delete("/api/remote/home/keep", json=body)).status == 401
    for path in ("/api/remote/home/status", "/api/remote/home/offline"):
        assert (await client.get(path)).status == 401, path


async def test_keep_and_unkeep_proxy_to_the_library(home):
    client, lib, _ = home
    body = {"kind": "album", "id": "al1"}
    r = await client.post("/api/remote/home/keep", json=body, headers=AUTH)
    assert r.status == 200 and (await r.json())["keep"]["state"] == "kept"
    r = await client.delete("/api/remote/home/keep", json=body, headers=AUTH)
    assert r.status == 200 and (await r.json())["keep"]["state"] == "none"
    assert lib.keep_calls == [("POST", body), ("DELETE", body)]


@pytest.mark.parametrize("body", [{"kind": "track", "id": "t1"}, {"kind": "album", "id": "a b"},
                                  {"kind": "album"}, ["al1"]])
async def test_keep_validates_before_calling_the_library(home, body):
    client, lib, _ = home
    assert (await client.post("/api/remote/home/keep", json=body, headers=AUTH)).status == 400
    assert lib.keep_calls == []


async def test_keep_passes_a_library_404_through(home):
    client, _lib, _ = home
    r = await client.post("/api/remote/home/keep", json={"kind": "album", "id": "missing"}, headers=AUTH)
    assert r.status == 404 and (await r.json()) == {"ok": False, "error": "album not found"}


async def test_keep_and_status_library_failure_is_502(home):
    client, lib, _ = home
    lib.force_status = 500
    r = await client.post("/api/remote/home/keep", json={"kind": "album", "id": "al1"}, headers=AUTH)
    assert r.status == 502 and (await r.json()) == {"ok": False, "error": "library service not answering"}
    assert (await client.get("/api/remote/home/status", headers=AUTH)).status == 502
    assert (await client.get("/api/remote/home/offline", headers=AUTH)).status == 502


async def test_status_maps_the_library_health(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/status", headers=AUTH)
    assert (await r.json()) == {"online": True, "internal_storage": True}
    lib.health = {"navidrome_reachable": False, "internal_storage": True}
    r = await client.get("/api/remote/home/status", headers=AUTH)
    assert (await r.json()) == {"online": False, "internal_storage": True}


async def test_offline_ids_pass_through(home):
    client, _lib, _ = home
    r = await client.get("/api/remote/home/offline", headers=AUTH)
    assert (await r.json()) == {"album_ids": ["al1"], "artist_ids": [], "playlist_ids": []}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_home.py`
Expected: FAIL — 404/405 for `/api/remote/home/keep`, `/status`, `/offline`.

- [ ] **Step 3: Implement**

In `services/remote_home.py` after `_PASS_HEADERS`:

```python
KEEP_KINDS = frozenset({"album", "artist", "playlist"})
```

After `_proxy_get`:

```python
async def _proxy_json(session: aiohttp.ClientSession, method: str, url: str,
                      body: dict | None = None) -> web.Response:
    """JSON call to boombox-library; its status and body pass through, its
    failures become 502."""
    try:
        async with session.request(method, url, json=body, timeout=TIMEOUT) as r:
            status = r.status
            try:
                data = await r.json(content_type=None)
            except ValueError:
                data = None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.warning("home library %s %s failed: %s", method, url, type(e).__name__)
        return _fail(502, LIBRARY_DOWN)
    if status >= 500 or not isinstance(data, dict):
        log.warning("home library %s %s → HTTP %s", method, url, status)
        return _fail(502, LIBRARY_DOWN)
    if status >= 400 and "ok" not in data:
        data = {"ok": False, "error": str(data.get("error") or "request refused")}
    return web.json_response(data, status=status)
```

At the end of `_make_handlers`, replace `return browse, search, detail, art, play` with:

```python
    async def keep(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return _fail(400, "invalid_json")
        if not isinstance(body, dict):
            return _fail(400, "expected a JSON object")
        kind, item_id = body.get("kind"), body.get("id")
        if kind not in KEEP_KINDS:
            return _fail(400, "kind must be album, artist or playlist")
        if not isinstance(item_id, str) or not _ID_RE.match(item_id):
            return _fail(400, "bad id")
        return await _proxy_json(session, req.method, f"{base}/api/library/keep",
                                 {"kind": kind, "id": item_id})

    async def status(req: web.Request) -> web.Response:
        try:
            async with session.get(f"{base}/api/library/health", timeout=TIMEOUT) as r:
                health = await r.json(content_type=None) if r.status == 200 else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.warning("home library health failed: %s", type(e).__name__)
            health = None
        if not isinstance(health, dict):
            return _fail(502, LIBRARY_DOWN)
        return web.json_response({"online": bool(health.get("navidrome_reachable")),
                                  "internal_storage": bool(health.get("internal_storage"))})

    async def offline(req: web.Request) -> web.Response:
        return await _proxy_get(session, f"{base}/api/library/offline", req)

    return {"browse": browse, "search": search, "detail": detail, "art": art,
            "play": play, "keep": keep, "status": status, "offline": offline}
```

Replace `add_routes`' body:

```python
    h = _make_handlers(session, base.rstrip("/"), player)
    app.router.add_get("/api/remote/home/browse", h["browse"])
    app.router.add_get("/api/remote/home/search", h["search"])
    app.router.add_get("/api/remote/home/status", h["status"])
    app.router.add_get("/api/remote/home/offline", h["offline"])
    app.router.add_get("/api/remote/home/art/{art_id}", h["art"])
    app.router.add_get("/api/remote/home/{kind:artist|album|playlist}/{item_id}", h["detail"])
    app.router.add_post("/api/remote/home/play", h["play"])
    app.router.add_post("/api/remote/home/keep", h["keep"])
    app.router.add_delete("/api/remote/home/keep", h["keep"])
```

`docs/SERVICES.md`, after the `POST /api/remote/home/play` row:

```markdown
| `POST` / `DELETE /api/remote/home/keep` | Bearer: `{kind: album\|artist\|playlist, id}` → keep offline / stop keeping (boombox-library `/api/library/keep`) |
| `GET  /api/remote/home/status` | Bearer: `{online, internal_storage}` — the app's Offline banner |
| `GET  /api/remote/home/offline` | Bearer: `{album_ids, artist_ids, playlist_ids}` with music on the boombox (dimming while offline) |
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_home.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy --follow-imports=silent services/remote_home.py`
Expected: all pass; clean.

- [ ] **Step 5: Commit**

```bash
git add services/remote_home.py services/tests/test_remote_home.py docs/SERVICES.md
git commit -m "feat(remote): keep offline, home status and offline ids for the LAN app

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Admin Storage API in boombox-setup; uploads move to the admin tier

**Decision (vs. the spec's "Uploads: the existing Files browser/uploader moves here … household users keep read-only browse"):** the upload and delete **routes** move to the admin tier, not just the UI. Every paired household phone shares the pair-token tier, so hiding the buttons alone would leave a plain `curl` able to upload/delete; "read-only browse" is only true if the server enforces it. boombox-setup reuses `remote_files`' security-reviewed handlers (`safe_compose` / `under_root` / size cap); browse and download stay on the household tier. nginx gets a dedicated exact location so 4 GB uploads stream through unbuffered to boombox-setup.

**Files:**
- Create: `services/boombox_setup/storage.py`
- Modify: `services/boombox_setup/accounts.py` (constants after `_MUTATING`; `check_auth` mutating branch)
- Modify: `services/boombox_setup/api.py` (import; `Context`; `build_app`)
- Modify: `services/boombox-setup.py` (`ServiceContext.library_call`, after `library_health`)
- Modify: `services/remote_files.py` (docstring; `upload` disk-full; `delete` never 500; `moved`; `add_routes`)
- Modify: `install/config/nginx-boombox-common.conf` (new location before `location /api/accounts/`)
- Modify: `docs/ACCESS.md` ("Uploading files" section and both route tables)
- Test: `services/tests/test_storage_admin_api.py` (create), `services/tests/test_remote_files.py` (replace the upload/delete tests), `services/tests/test_nginx_lan_app.py` (append)

**Interfaces:**
- Produces (`boombox_setup.accounts`): `STORAGE_UPLOAD_PATH = "/api/accounts/storage/files/upload"`, `MULTIPART_PATHS = frozenset({STORAGE_UPLOAD_PATH})` — multipart accepted there only (still admin token + non-loopback + Origin check).
- Produces (`boombox_setup.api.Context`): `async library_call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]` — `(0, None)` when boombox-library doesn't answer (15 s timeout).
- Produces (HTTP via nginx `/api/accounts/`): `GET /api/accounts/storage` → library overview | 502; `POST /api/accounts/storage/remove {kind: album|artist|playlist|starred_tracks, id}` → library status/body | 400 | 502; `POST /api/accounts/storage/retry {}` → library | 502; `GET /api/accounts/storage/files/browse?path=` → `{path, parent, entries}` | 404; `POST /api/accounts/storage/files/upload` (multipart, field `file`) → `{"saved": [...]}` | 400 | 413 | 507 `{"error": "the boombox's disk is full or not writable"}`; `POST /api/accounts/storage/files/delete {path}` → `{"deleted": path}` | 403 | 404 | 409.
- Produces (household): `POST /api/remote/files/upload|delete` → 403 `{"error": "uploading and deleting moved to Admin → Storage"}`.

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_storage_admin_api.py`:

```python
"""/api/accounts/storage* — Admin → Storage (boombox-setup)."""
from __future__ import annotations

import builtins

import aiohttp
import pytest
import remote_files
from aiohttp.test_utils import TestClient, TestServer
from boombox_setup.accounts import ADMIN_KEY
from boombox_setup.api import build_app

from .test_accounts_api import FakeAccountsContext

LAN = {"X-Real-IP": "192.168.1.50", "X-Boombox-Host": "192.168.1.81:8090"}


class FakeStorageContext(FakeAccountsContext):
    def __init__(self) -> None:
        super().__init__()
        self.library_calls: list[tuple] = []
        self.library_reply: tuple[int, dict | None] = (
            200, {"drive": {"present": True}, "kept": [], "downloads": {}})

    async def library_call(self, method, path, body=None):
        self.library_calls.append((method, path, body))
        return self.library_reply


async def _noop() -> None:
    return None


@pytest.fixture
async def storage(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    (music / "Album").mkdir(parents=True)
    (music / "Album" / "track.mp3").write_bytes(b"id3data")
    monkeypatch.setenv("BOOMBOX_MUSIC_DIR", str(music))
    monkeypatch.setenv("BOOMBOX_VIDEO_DIR", str(tmp_path / "Videos"))
    monkeypatch.setattr(remote_files, "_trigger_scan", _noop)
    monkeypatch.setattr(remote_files, "_trigger_jellyfin_scan", _noop)
    ctx = FakeStorageContext()
    app = build_app(ctx)
    token, _ = app[ADMIN_KEY].issue()
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c, ctx, {**LAN, "Authorization": f"Bearer {token}"}, music
    await c.close()


def _song(name: str = "song.mp3", data: bytes = b"fake-audio-bytes") -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field("file", data, filename=name, content_type="audio/mpeg")
    return form


async def test_storage_needs_an_admin_session(storage):
    c, _ctx, auth, _ = storage
    assert (await c.get("/api/accounts/storage", headers=LAN)).status == 401
    assert (await c.get("/api/accounts/storage", headers={**auth, "X-Real-IP": "127.0.0.1"})).status == 403
    assert (await c.post("/api/accounts/storage/files/upload", data=_song(), headers=LAN)).status == 401


async def test_overview_proxies_the_library(storage):
    c, ctx, auth, _ = storage
    r = await c.get("/api/accounts/storage", headers=auth)
    assert r.status == 200 and (await r.json())["drive"]["present"] is True
    assert ctx.library_calls == [("GET", "/api/library/storage", None)]


@pytest.mark.parametrize("reply", [(0, None), (500, {"error": "x"}), (200, None)])
async def test_library_failure_is_502(storage, reply):
    c, ctx, auth, _ = storage
    ctx.library_reply = reply
    r = await c.get("/api/accounts/storage", headers=auth)
    assert r.status == 502 and (await r.json()) == {"ok": False, "error": "library service not answering"}


async def test_remove_and_retry_proxy(storage):
    c, ctx, auth, _ = storage
    ctx.library_reply = (409, {"ok": False, "error": "unstar in Navidrome to remove"})
    r = await c.post("/api/accounts/storage/remove", json={"kind": "album", "id": "al1"}, headers=auth)
    assert r.status == 409 and (await r.json())["error"] == "unstar in Navidrome to remove"
    assert ctx.library_calls[-1] == ("POST", "/api/library/storage/remove", {"kind": "album", "id": "al1"})
    ctx.library_reply = (200, {"ok": True, "retried": 2})
    r = await c.post("/api/accounts/storage/retry", json={}, headers=auth)
    assert (await r.json()) == {"ok": True, "retried": 2}
    assert ctx.library_calls[-1] == ("POST", "/api/library/storage/retry", {})
    for bad in ({"kind": "track", "id": "t1"}, {"kind": "album"}, ["al1"]):
        assert (await c.post("/api/accounts/storage/remove", json=bad, headers=auth)).status == 400


async def test_upload_is_admin_multipart_only_on_its_path(storage):
    c, _ctx, auth, music = storage
    r = await c.post("/api/accounts/storage/files/upload", data=_song(), headers=auth)
    assert r.status == 200 and (await r.json())["saved"] == ["uploads/song.mp3"]
    assert (music / "uploads" / "song.mp3").read_bytes() == b"fake-audio-bytes"
    r = await c.post("/api/accounts/storage/remove", data=_song(), headers=auth)
    assert r.status == 415


async def test_upload_cross_origin_is_refused(storage):
    c, _ctx, auth, _ = storage
    r = await c.post("/api/accounts/storage/files/upload", data=_song(),
                     headers={**auth, "Origin": "http://evil.example"})
    assert r.status == 403


async def test_upload_rejects_unsupported_type_and_over_cap(storage, monkeypatch):
    c, _ctx, auth, music = storage
    form = aiohttp.FormData()
    form.add_field("file", b"not media", filename="notes.txt", content_type="text/plain")
    assert (await c.post("/api/accounts/storage/files/upload", data=form, headers=auth)).status == 400
    monkeypatch.setattr(remote_files, "MAX_FILE_BYTES", 1024)
    r = await c.post("/api/accounts/storage/files/upload", data=_song("toobig.mp3", b"\0" * 4096), headers=auth)
    assert r.status == 413 and not (music / "uploads" / "toobig.mp3").exists()


async def test_upload_disk_full_is_507_and_leaves_no_partial(storage, monkeypatch):
    c, _ctx, auth, music = storage

    def full_open(path, mode="r", *a, **k):
        real = builtins.open(path, mode, *a, **k)

        class Full:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                real.close()
                return False

            def write(self, data):
                raise OSError(28, "No space left on device")

            def close(self):
                real.close()
        return Full()

    monkeypatch.setattr(remote_files, "open", full_open, raising=False)
    r = await c.post("/api/accounts/storage/files/upload", data=_song(), headers=auth)
    assert r.status == 507 and (await r.json())["error"] == "the boombox's disk is full or not writable"
    assert not (music / "uploads" / "song.mp3").exists()


async def test_admin_browse_and_delete(storage):
    c, _ctx, auth, music = storage
    r = await c.get("/api/accounts/storage/files/browse?path=", headers=auth)
    assert "Album" in [e["name"] for e in (await r.json())["entries"]]
    r = await c.post("/api/accounts/storage/files/delete", json={"path": "Album/track.mp3"}, headers=auth)
    assert r.status == 200 and not (music / "Album" / "track.mp3").exists()


async def test_delete_failure_is_409_not_500(storage, monkeypatch):
    import pathlib
    c, _ctx, auth, _ = storage

    def refuse(self, missing_ok=False):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(pathlib.Path, "unlink", refuse)
    r = await c.post("/api/accounts/storage/files/delete", json={"path": "Album/track.mp3"}, headers=auth)
    assert r.status == 409
```

In `services/tests/test_remote_files.py` delete `test_delete_removes_file`, `test_upload_audio_file`, `test_upload_rejects_unsupported_type` and `test_upload_rejects_file_over_cap` (now covered on the admin tier above) and append:

```python
@pytest.mark.asyncio
async def test_household_upload_and_delete_moved_to_admin_storage(files_app, aiohttp_client):
    app, music = files_app
    client = await aiohttp_client(app)
    data = aiohttp.FormData()
    data.add_field("file", b"x", filename="song.mp3", content_type="audio/mpeg")
    r = await client.post("/api/remote/files/upload", data=data, headers={"Authorization": "Bearer t"})
    assert r.status == 403 and "Admin → Storage" in (await r.json())["error"]
    r = await client.post("/api/remote/files/delete", json={"path": "Album/track.mp3"},
                          headers={"Authorization": "Bearer t"})
    assert r.status == 403 and (music / "Album" / "track.mp3").exists()
    assert not (music / "uploads").exists()
```

Append to `services/tests/test_nginx_lan_app.py`:

```python
def test_admin_upload_streams_large_bodies_to_boombox_setup():
    loc = _location(SNIPPET, "location = /api/accounts/storage/files/upload {")
    for line in ("auth_basic off;",
                 "proxy_pass http://127.0.0.1:6689/api/accounts/storage/files/upload;",
                 "proxy_set_header X-Real-IP $remote_addr;",
                 "proxy_set_header X-Boombox-Host $http_host;",
                 "client_max_body_size 4096M;",
                 "proxy_request_buffering off;",
                 "proxy_read_timeout 1h;"):
        assert line in loc, line
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_storage_admin_api.py services/tests/test_remote_files.py services/tests/test_nginx_lan_app.py`
Expected: FAIL — 404 for `/api/accounts/storage`, household upload still 200, nginx location missing.

- [ ] **Step 3: Implement remote_files changes**

In `services/remote_files.py` replace the module docstring's last sentence with "Upload and delete are served on the admin tier (boombox_setup/storage.py, `/api/accounts/storage/files/*`); the household tier keeps browse + download and answers 403 for the old upload/delete routes." Add after `SCAN_TRIGGER_URL`:

```python
MOVED = "uploading and deleting moved to Admin → Storage"
DISK_FULL = "the boombox's disk is full or not writable"
```

In `upload`, wrap the write loop:

```python
        size = 0
        try:
            with open(target, "wb") as f:
                while True:
                    chunk = await part.read_chunk(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        f.close()
                        target.unlink(missing_ok=True)
                        return web.json_response(
                            {"error": "file too large"}, status=413)
                    f.write(chunk)
        except OSError as e:
            log.warning("upload of %s failed: %s", target, e)
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            return web.json_response({"error": DISK_FULL}, status=507)
```

In `delete`, the unlink failure becomes:

```python
    try:
        target.unlink()
    except OSError as e:
        return web.json_response(
            {"error": f"could not delete: {e.strerror or type(e).__name__}"}, status=409)
```

Add before `add_routes` and replace `add_routes`:

```python
async def moved(request: web.Request) -> web.Response:
    return web.json_response({"error": MOVED}, status=403)


def add_routes(app: web.Application) -> None:
    """Household /api/remote/files/*: browse + download. Upload and delete
    moved to the admin tier (boombox_setup/storage.py)."""
    app.router.add_get("/api/remote/files/browse", browse)
    app.router.add_get("/api/remote/files/download/{path:.+}", download)
    app.router.add_post("/api/remote/files/upload", moved)
    app.router.add_post("/api/remote/files/delete", moved)
```

- [ ] **Step 4: Implement the admin storage routes**

In `services/boombox_setup/accounts.py` after `_MUTATING`:

```python
STORAGE_UPLOAD_PATH = "/api/accounts/storage/files/upload"
# Multipart bodies are accepted on these paths only. They still need the
# admin bearer token (a cross-site form can't send one) and pass the
# Origin check below.
MULTIPART_PATHS = frozenset({STORAGE_UPLOAD_PATH})
```

and in `check_auth` replace the JSON check:

```python
    if req.method in _MUTATING:
        multipart_ok = (req.path in MULTIPART_PATHS
                        and req.content_type == "multipart/form-data")
        if req.content_type != "application/json" and not multipart_ok:
            return web.json_response(
                {"error": "Content-Type must be application/json"}, status=415)
```

Create `services/boombox_setup/storage.py`:

```python
"""/api/accounts/storage* — Admin → Storage in the LAN app (spec 2A).

Behind the same admin-session gate as the Accounts cards (api._auth_mw runs
accounts.check_auth for every /api/accounts/ path). Drive / kept items /
downloads and their actions proxy boombox-library over loopback. The file
browser reuses remote_files' security-reviewed handlers, moved here from
the household tier so a paired phone can browse but not change files."""
from __future__ import annotations

import logging
from typing import Any

import remote_files
from aiohttp import web

from .accounts import STORAGE_UPLOAD_PATH

log = logging.getLogger("boombox-setup.storage")

LIBRARY_DOWN = "library service not answering"
_REMOVE_KINDS = frozenset({"album", "artist", "playlist", "starred_tracks"})


async def _proxy(req: web.Request, method: str, path: str,
                 body: dict | None = None) -> web.Response:
    ctx: Any = req.app["ctx"]
    status, data = await ctx.library_call(method, path, body)
    if status == 0 or status >= 500 or not isinstance(data, dict):
        return web.json_response({"ok": False, "error": LIBRARY_DOWN}, status=502)
    return web.json_response(data, status=status)


async def _overview(req: web.Request) -> web.Response:
    return await _proxy(req, "GET", "/api/library/storage")


async def _remove(req: web.Request) -> web.Response:
    try:
        b = await req.json()
    except ValueError:
        b = None
    if not isinstance(b, dict):
        return web.json_response({"ok": False, "error": "expected a JSON object"}, status=400)
    kind, item_id = b.get("kind"), b.get("id")
    if kind not in _REMOVE_KINDS or not isinstance(item_id, str) or len(item_id) > 128:
        return web.json_response({"ok": False, "error": "kind and id are required"}, status=400)
    return await _proxy(req, "POST", "/api/library/storage/remove", {"kind": kind, "id": item_id})


async def _retry(req: web.Request) -> web.Response:
    return await _proxy(req, "POST", "/api/library/storage/retry", {})


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/accounts/storage", _overview)
    r.add_post("/api/accounts/storage/remove", _remove)
    r.add_post("/api/accounts/storage/retry", _retry)
    r.add_get("/api/accounts/storage/files/browse", remote_files.browse)
    r.add_post(STORAGE_UPLOAD_PATH, remote_files.upload)
    r.add_post("/api/accounts/storage/files/delete", remote_files.delete)
```

In `services/boombox_setup/api.py`: `from . import __version__, accounts, storage`; in `Context` after `remote_pair_start`:

```python
    # one JSON call to boombox-library: (status, body); (0, None) = no answer
    async def library_call(self, method: str, path: str,
                           body: dict | None = None) -> tuple[int, dict | None]: ...
```

and in `build_app` after `accounts.add_routes(app)`: `storage.add_routes(app)`.

In `services/boombox-setup.py` `ServiceContext`, after `library_health`:

```python
    _STORAGE_TIMEOUT = aiohttp.ClientTimeout(total=15)

    async def library_call(self, method: str, path: str,
                           body: dict | None = None) -> tuple[int, dict | None]:
        """One JSON call to boombox-library (Admin → Storage); (0, None)
        when it doesn't answer — the route turns that into a 502."""
        try:
            s = await self._http()
            async with s.request(method, f"{LIBRARY_BASE}{path}", json=body,
                                 timeout=self._STORAGE_TIMEOUT) as r:
                return r.status, await self._json_or_none(r)
        except Exception as e:
            log.warning("library %s %s failed: %s", method, path, type(e).__name__)
            return 0, None
```

In `install/config/nginx-boombox-common.conf`, directly before the `location /api/accounts/ {` block:

```nginx
# Admin → Storage uploads (boombox-setup, admin session): 4 GB files stream
# straight through like the old household upload did. Exact match wins over
# the /api/accounts/ prefix below.
location = /api/accounts/storage/files/upload {
    auth_basic off;
    proxy_pass http://127.0.0.1:6689/api/accounts/storage/files/upload;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Boombox-Host $http_host;
    # matches remote_files.MAX_FILE_BYTES
    client_max_body_size 4096M;
    proxy_request_buffering off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
}
```

In `docs/ACCESS.md`: in "Uploading files" replace `` `POST /api/remote/files/upload` takes a multipart form. `` with `` `POST /api/accounts/storage/files/upload` (Admin → Storage in the LAN app: admin session, not the pair token) takes a multipart form. `` and add the sentence "The household `POST /api/remote/files/upload` / `delete` routes now answer 403 — paired phones browse and download only."; in "What the remote API can do" replace the Upload and Delete rows with `| Upload / delete | Admin → Storage: `POST /api/accounts/storage/files/upload` / `delete` (admin session). The pair token can only browse and download. |`; in the endpoint table replace the two `/api/remote/files/upload` and `/delete` rows with `| `/api/remote/files/upload`, `/delete` | POST | Bearer | 403 — moved to `/api/accounts/storage/files/*` (admin) |` and add `| `/api/accounts/storage`, `/storage/remove`, `/storage/retry`, `/storage/files/{browse,upload,delete}` | GET / POST | Admin session | Admin → Storage |`.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy && ~/.local/bin/mypy --follow-imports=silent services/boombox_setup/storage.py services/boombox_setup/accounts.py services/boombox_setup/api.py services/remote_files.py services/boombox-setup.py`
Expected: all pass (the existing `test_accounts_api.py` JSON/Origin tests are unchanged); ruff and mypy clean.

- [ ] **Step 6: Commit**

```bash
git add services/boombox_setup/storage.py services/boombox_setup/accounts.py services/boombox_setup/api.py services/boombox-setup.py services/remote_files.py install/config/nginx-boombox-common.conf docs/ACCESS.md services/tests/test_storage_admin_api.py services/tests/test_remote_files.py services/tests/test_nginx_lan_app.py
git commit -m "feat(setup): admin Storage API; uploads and deletes move to the admin tier

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 9: Music section — Offline banner, dimmed un-kept music, Keep offline toggle + progress

**Files:**
- Modify: `remote-ui/src/lib/api.ts` (`RemoteApi.del`, `HttpApi.del`)
- Modify: `remote-ui/src/lib/homeLibrary.ts` (types, status / offline / keep clients, `artistTrackIds` offline filter)
- Rewrite: `remote-ui/src/screens/HomeLibrary.tsx`
- Test: `remote-ui/src/lib/api.test.ts`, `remote-ui/src/screens/HomeLibrary.test.tsx` (append)

**Interfaces:**
- Consumes: `GET api/remote/home/status`, `GET api/remote/home/offline`, `POST`/`DELETE api/remote/home/keep`, detail `keep` + track `offline`, search `offline` (Tasks 4, 7).
- Produces (TS, `lib/homeLibrary.ts`): `KeepState`, `HomeStatus`, `OfflineIds`, `KeepResult`; `STATUS_POLL_MS = 30000`, `KEEP_POLL_MS = 5000`; `homeStatus(api)`, `offlineIds(api)`, `keepHome(api, kind, id)`, `unkeepHome(api, kind, id)`, `artistTrackIds(api, artistId, onlyOffline = false)`; `RemoteApi.del?<T>(path, body?)`.
- UI contract: status unknown (route failed / old server) = treat as online (no banner, no dimming). Offline = banner text **"Offline — showing kept music"**; un-kept tiles / rows / search results at reduced opacity with a "not offline" tag and disabled play buttons; Play all / play-from / artist play send only `offline: true` tracks, and with none: toast **"None of these tracks are on the boombox."** without calling play. Detail pages show a `role="switch"` named **"Keep offline"** (`aria-checked` = kept) with progress **"N / M on the boombox"** (or "All M on the boombox"), polled every 5 s while a kept item is incomplete; starred items show "★ Starred in Navidrome — kept offline automatically" and no switch.

- [ ] **Step 1: Write the failing tests**

Append to `remote-ui/src/lib/api.test.ts`:

```ts
describe("del", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("sends DELETE with a JSON body and the token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const api = makeApi("http://pi", "tok");
    expect(await api.del!("api/remote/home/keep", { kind: "album", id: "al1" })).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith("http://pi/api/remote/home/keep", expect.objectContaining({
      method: "DELETE", body: JSON.stringify({ kind: "album", id: "al1" }),
      headers: expect.objectContaining({ Authorization: "Bearer tok", "Content-Type": "application/json" }),
    }));
  });
});
```

In `remote-ui/src/screens/HomeLibrary.test.tsx` change the testing-library import to `import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";` and append:

```tsx
const ALBUM_OFFLINE = { ...ALBUM, keep: { state: "kept", tracks_total: 3, tracks_present: 2 },
  tracks: [{ ...ALBUM.tracks[0], offline: true }, { ...ALBUM.tracks[1], offline: false },
           { ...ALBUM.tracks[2], offline: true }] };

function offlineApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return mockApi({
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/status") return { online: false, internal_storage: true };
      if (p === "api/remote/home/offline") return { album_ids: ["al1"], artist_ids: ["ar1"], playlist_ids: [] };
      if (p === "api/remote/home/browse?type=albums") return ALBUMS;
      if (p === "api/remote/home/album/al1") return ALBUM_OFFLINE;
      if (p === "api/remote/home/album/al2") return { ...ALBUM2, tracks: [{ id: "t9", title: "Help Me", offline: false }] };
      throw new Error(`unmocked ${p}`);
    }),
    ...overrides,
  });
}

function albumApi(keep: object, extra: Partial<RemoteApi> = {}): RemoteApi {
  return mockApi({
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/album/al1") return { ...ALBUM, keep };
      throw new Error(`unmocked ${p}`);
    }),
    ...extra,
  });
}

describe("HomeLibrary offline + keep", () => {
  it("offline: banner, dimmed un-kept rows, Play all sends only kept tracks", async () => {
    const api = offlineApi();
    wrap(api, ["album", "al1"]);
    expect(await screen.findByText("Offline — showing kept music")).toBeTruthy();
    const row = (await screen.findByText("My Old Man")).closest("li")!;
    expect(row.textContent).toContain("not offline");
    expect((within(row).getByRole("button", { name: "Play from My Old Man" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Play all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t1", "t3"], mode: "play" }));
  });

  it("offline: album tiles that aren't kept are dimmed", async () => {
    wrap(offlineApi(), []);
    await screen.findByText("Offline — showing kept music");
    await waitFor(() => expect(screen.getByRole("button", { name: /Court and Spark/ }).textContent)
      .toContain("not offline"));
    expect(screen.getByRole("button", { name: /^Blue/ }).textContent).not.toContain("not offline");
  });

  it("offline with nothing kept: says so without calling play", async () => {
    const api = offlineApi();
    wrap(api, ["album", "al2"]);
    await screen.findByText("Offline — showing kept music");
    await screen.findByText("Help Me");
    fireEvent.click(screen.getByRole("button", { name: "Play all" }));
    expect(await screen.findByText("None of these tracks are on the boombox.")).toBeTruthy();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("Keep offline pins the album and shows progress", async () => {
    const api = albumApi({ state: "none", tracks_total: 3, tracks_present: 0 }, {
      post: vi.fn().mockImplementation(async (p: string) => p === "api/remote/home/keep"
        ? { ok: true, queued: 3, keep: { state: "kept", tracks_total: 3, tracks_present: 0 } }
        : { ok: true, count: 3, skipped: 0 }),
    });
    wrap(api, ["album", "al1"]);
    const sw = await screen.findByRole("switch", { name: "Keep offline" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(sw);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("api/remote/home/keep", { kind: "album", id: "al1" }));
    expect(await screen.findByText("0 / 3 on the boombox")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Keep offline" }).getAttribute("aria-checked")).toBe("true");
  });

  it("a kept album can be removed with DELETE", async () => {
    const del = vi.fn().mockResolvedValue({ ok: true, cancelled: 0,
      keep: { state: "none", tracks_total: 3, tracks_present: 3 } });
    const api = albumApi({ state: "kept", tracks_total: 3, tracks_present: 3 }, { del });
    wrap(api, ["album", "al1"]);
    expect(await screen.findByText("All 3 on the boombox")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Keep offline" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("api/remote/home/keep", { kind: "album", id: "al1" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Keep offline" })
      .getAttribute("aria-checked")).toBe("false"));
  });

  it("a starred album says so and has no switch", async () => {
    wrap(albumApi({ state: "starred", tracks_total: 3, tracks_present: 2 }), ["album", "al1"]);
    expect(await screen.findByText(/Starred in Navidrome/)).toBeTruthy();
    expect(screen.getByText("2 / 3 on the boombox")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("progress refreshes while a kept album downloads", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    const api = mockApi({
      get: vi.fn().mockImplementation(async (p: string) => {
        if (p === "api/remote/home/album/al1") {
          calls += 1;
          return { ...ALBUM, keep: { state: "kept", tracks_total: 3, tracks_present: calls === 1 ? 1 : 3 } };
        }
        throw new Error(`unmocked ${p}`);
      }),
    });
    wrap(api, ["album", "al1"]);
    expect(await screen.findByText("1 / 3 on the boombox")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(await screen.findByText("All 3 on the boombox")).toBeTruthy();
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd remote-ui && npx vitest run src/lib/api.test.ts src/screens/HomeLibrary.test.tsx`
Expected: FAIL — `api.del is not a function`; no "Offline — showing kept music" / no switch.

- [ ] **Step 3: Implement the API client pieces**

In `remote-ui/src/lib/api.ts`, `RemoteApi` gains (after `post`):

```ts
  /** DELETE <base><path> with a JSON body + bearer token. JSON response.
   *  Optional so test doubles needn't implement it. */
  del?<T = unknown>(path: string, body?: unknown): Promise<T>;
```

and `HttpApi` gains (after `post`):

```ts
  async del<T>(path: string, body?: unknown): Promise<T> {
    const r = await this.check(await fetch(this.url(path), {
      method: "DELETE",
      headers: { ...this.authHeader(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }));
    return r.json() as Promise<T>;
  }
```

In `remote-ui/src/lib/homeLibrary.ts`: `HomeTrack` gains `offline?: boolean;`; `HomeAlbumDetail`, `HomeArtistDetail` and `HomePlaylistDetail` gain `keep?: KeepState;`; `HomeArtistDetail.albums` items gain `offline?: boolean`; `HomeSearchResult` gains `offline?: boolean`. Add:

```ts
export interface KeepState { state: "none" | "kept" | "starred"; tracks_total: number; tracks_present: number }
export interface HomeStatus { online: boolean; internal_storage: boolean }
export interface OfflineIds { album_ids: string[]; artist_ids: string[]; playlist_ids: string[] }
export interface KeepResult { ok: boolean; keep: KeepState; queued?: number; cancelled?: number }

/** How often the Music section re-checks Home Library reachability. */
export const STATUS_POLL_MS = 30_000;
/** How often a kept-but-incomplete detail page refreshes its progress. */
export const KEEP_POLL_MS = 5_000;

export function homeStatus(api: RemoteApi): Promise<HomeStatus> {
  return api.get<HomeStatus>("api/remote/home/status");
}

export function offlineIds(api: RemoteApi): Promise<OfflineIds> {
  return api.get<OfflineIds>("api/remote/home/offline");
}

export function keepHome(api: RemoteApi, kind: HomeKind, id: string): Promise<KeepResult> {
  return api.post<KeepResult>("api/remote/home/keep", { kind, id });
}

export async function unkeepHome(api: RemoteApi, kind: HomeKind, id: string): Promise<KeepResult> {
  if (!api.del) throw new Error("This app can't remove kept music.");
  return api.del<KeepResult>("api/remote/home/keep", { kind, id });
}
```

and `artistTrackIds` becomes:

```ts
export async function artistTrackIds(api: RemoteApi, artistId: string,
                                     onlyOffline = false): Promise<string[]> {
  const a = await homeDetail<HomeArtistDetail>(api, "artist", artistId);
  const ids: string[] = [];
  for (const al of a.albums) {
    if (ids.length >= MAX_EXPANDED_TRACKS) break;
    if (onlyOffline && al.offline === false) continue;
    const d = await homeDetail<HomeAlbumDetail>(api, "album", al.id);
    ids.push(...d.tracks.filter((t) => !onlyOffline || t.offline === true).map((t) => t.id));
  }
  return ids;
}
```

- [ ] **Step 4: Rewrite `HomeLibrary.tsx`**

Replace `remote-ui/src/screens/HomeLibrary.tsx` with:

```tsx
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { AuthedImg } from "../components/AuthedImg";
import { SectionMessage } from "../components/SectionMessage";
import { SkeletonRows } from "../components/Skeleton";
import { TILE_GRID } from "../components/grid";
import {
  KEEP_POLL_MS, MAX_EXPANDED_TRACKS, STATUS_POLL_MS, artPath, artistTrackIds, browseHome,
  homeDetail, homeStatus, keepHome, offlineIds, playHome, searchHome, unkeepHome,
  type HomeAlbumDetail, type HomeArtistDetail, type HomeItem, type HomeKind,
  type HomeList, type HomePlaylistDetail, type HomeSearchResult, type HomeStatus,
  type HomeTrack, type KeepState,
} from "../lib/homeLibrary";

const PAGE = 120;
const LIBRARY_DOWN = "The Home Library isn't answering";
export const OFFLINE_BANNER = "Offline — showing kept music";
export const NOTHING_KEPT = "None of these tracks are on the boombox.";
const LISTS: { id: HomeList; label: string }[] = [
  { id: "albums", label: "Albums" }, { id: "artists", label: "Artists" },
  { id: "playlists", label: "Playlists" },
];

type Detail = HomeAlbumDetail | HomeArtistDetail | HomePlaylistDetail;
type PlayFn = (ids: string[] | (() => Promise<string[]>), mode: "play" | "queue",
               label: string) => Promise<void>;

function usePlay(offline: boolean): { toast: string | null; play: PlayFn } {
  const api = useApi();
  const [toast, setToast] = useState<string | null>(null);
  const play = useCallback<PlayFn>(async (ids, mode, label) => {
    setToast(mode === "play" ? `Starting ${label}…` : `Queueing ${label}…`);
    try {
      const all = typeof ids === "function" ? await ids() : ids;
      if (all.length === 0) { setToast(offline ? NOTHING_KEPT : `${label}: nothing to play.`); return; }
      // The play route takes at most 1000 ids; cap every play/queue (album,
      // playlist, play-from, artist) at the kiosk's 500 and say so.
      const capped = all.length > MAX_EXPANDED_TRACKS;
      const list = capped ? all.slice(0, MAX_EXPANDED_TRACKS) : all;
      const r = await playHome(api, list, mode);
      const n = `${r.count} track${r.count === 1 ? "" : "s"}`;
      const skipped = r.skipped ? ` (${r.skipped} not available offline)` : "";
      const verb = mode === "play" ? "Playing" : "Queued";
      const what = capped ? `the first ${MAX_EXPANDED_TRACKS} tracks of ${label}` : label;
      setToast(`${verb} ${what} — ${n}${skipped}.`);
    } catch (e) {
      setToast(apiErrorMessage(e, "Couldn't play that"));
    }
  }, [api, offline]);
  return { toast, play };
}

/** Home Library reachability. null = unknown (route failed / older server):
 *  treated as online — no banner, nothing dimmed. */
function useHomeStatus(): HomeStatus | null {
  const api = useApi();
  const [status, setStatus] = useState<HomeStatus | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => {
      homeStatus(api)
        .then((s) => { if (live) setStatus(s); })
        .catch(() => { if (live) setStatus(null); });
    };
    load();
    const t = window.setInterval(load, STATUS_POLL_MS);
    return () => { live = false; window.clearInterval(t); };
  }, [api]);
  return status;
}

function mmss(sec: number | null | undefined): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function NotOffline() {
  return <span style={notOfflineTag}>not offline</span>;
}

/** Home Library browser. Lists (albums / artists / playlists) and details
 *  (album / artist / playlist) are hash routes: #/music/home/<list> and
 *  #/music/home/<kind>/<id>, so the phone's back button walks back out.
 *  While the Home Library server is unreachable an Offline banner shows and
 *  music that isn't on the boombox is dimmed and can't be played. */
export function HomeLibrary({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const status = useHomeStatus();
  const offline = status !== null && !status.online;
  const [a, b] = params;
  const isDetail = (a === "artist" || a === "album" || a === "playlist") && b;
  const list: HomeList = a === "artists" || a === "playlists" ? a : "albums";
  return (
    <>
      {offline && <div role="status" aria-label="Offline" style={offlineBanner}>{OFFLINE_BANNER}</div>}
      {isDetail
        ? <HomeDetail key={`${a}/${b}`} kind={a as HomeKind} id={b} navigate={navigate} offline={offline} />
        : <HomeBrowse key={list} list={list} navigate={navigate} offline={offline} />}
    </>
  );
}

function HomeBrowse({ list, navigate, offline }: { list: HomeList; navigate: Navigate; offline: boolean }) {
  const api = useApi();
  const [items, setItems] = useState<HomeItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState("");
  const [results, setResults] = useState<HomeSearchResult[] | null>(null);
  const [shown, setShown] = useState(PAGE);
  const [kept, setKept] = useState<Set<string> | null>(null);
  const { toast, play } = usePlay(offline);

  useEffect(() => {
    let live = true;
    setError(null);
    browseHome(api, list)
      .then((r) => { if (live) setItems(r); })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, list, attempt]);

  useEffect(() => {
    if (!offline) { setKept(null); return; }
    let live = true;
    offlineIds(api)
      .then((r) => {
        if (!live) return;
        setKept(new Set(list === "albums" ? r.album_ids : list === "artists" ? r.artist_ids : r.playlist_ids));
      })
      .catch(() => { if (live) setKept(null); });
    return () => { live = false; };
  }, [api, list, offline]);

  useEffect(() => {
    const q = filter.trim();
    if (q.length < 2) { setResults(null); return; }
    let live = true;
    const t = window.setTimeout(() => {
      searchHome(api, q)
        .then((r) => { if (live) setResults(r); })
        .catch(() => { if (live) setResults([]); });
    }, 300);
    return () => { live = false; window.clearTimeout(t); };
  }, [api, filter]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!items) return [];
    return q ? items.filter((i) => i.name.toLowerCase().includes(q)) : items;
  }, [items, filter]);

  const dim = (id: string) => kept !== null && !kept.has(id);
  const openKind: HomeKind = list === "artists" ? "artist" : list === "albums" ? "album" : "playlist";

  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      <div role="tablist" aria-label="Home Library lists" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {LISTS.map((l) => (
          <button key={l.id} type="button" role="tab" aria-selected={l.id === list}
                  onClick={() => navigate("music", ["home", l.id])} style={pill(l.id === list)}>
            {l.label}
          </button>
        ))}
      </div>
      <input type="search" aria-label="Search the Home Library" value={filter}
             onChange={(e) => { setFilter(e.target.value); setShown(PAGE); }}
             placeholder="Search artists, albums, tracks…" style={searchInput} />
      {toast && <div role="status" style={banner}>{toast}</div>}
      {results && results.length > 0 && (
        <section aria-label="Search results">
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {results.slice(0, 30).map((r) => {
              const dimmed = offline && r.offline === false;
              return (
                <li key={`${r.content_type}:${r.id}`} style={{ ...row, opacity: dimmed ? 0.45 : 1 }}>
                  <span aria-hidden="true" style={{ width: 20 }}>
                    {r.content_type === "track" ? "🎵" : r.content_type === "album" ? "💿" : "👤"}
                  </span>
                  <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{r.title}</span>
                  {dimmed && <NotOffline />}
                  {r.content_type === "track" ? (
                    <button type="button" aria-label={`Play ${r.title}`} style={smallBtn} disabled={dimmed}
                            onClick={() => void play([r.id], "play", r.title)}>▶</button>
                  ) : (
                    <button type="button" aria-label={`Open ${r.title}`} style={smallBtn}
                            onClick={() => navigate("music", ["home",
                              r.content_type === "artist" ? "artist" : "album", r.id])}>›</button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {error ? (
        <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : !items ? (
        <SkeletonRows count={8} />
      ) : list === "playlists" ? (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {filtered.slice(0, shown).map((p) => (
            <li key={p.id} style={{ ...row, opacity: dim(p.id) ? 0.45 : 1 }}>
              <button type="button" onClick={() => navigate("music", ["home", "playlist", p.id])}
                      style={{ ...rowBtn, flex: 1, minWidth: 0 }}>
                <span style={ellipsis}>{p.name}</span>
                {p.song_count != null && (
                  <span style={{ color: "var(--ink2)", fontSize: 12, flexShrink: 0 }}>
                    {p.song_count} tracks</span>
                )}
                {dim(p.id) && <NotOffline />}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div style={TILE_GRID}>
          {filtered.slice(0, shown).map((i) => (
            <button key={i.id} type="button" onClick={() => navigate("music", ["home", openKind, i.id])}
                    style={{ ...tileBtn, opacity: dim(i.id) ? 0.4 : 1 }}>
              <AuthedImg path={artPath(i.art_id)} alt=""
                         style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
              <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{i.name}</span>
              {list === "albums" && i.year != null && (
                <span style={{ fontSize: 12, color: "var(--ink2)" }}>{i.year}</span>
              )}
              {dim(i.id) && <NotOffline />}
            </button>
          ))}
        </div>
      )}
      {items && filtered.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + PAGE)} style={moreBtn}>
          Show more ({filtered.length - shown} left)
        </button>
      )}
    </div>
  );
}

function progressText(k: KeepState): string {
  return k.tracks_total > 0 && k.tracks_present >= k.tracks_total
    ? `All ${k.tracks_total} on the boombox`
    : `${k.tracks_present} / ${k.tracks_total} on the boombox`;
}

function KeepToggle({ kind, id, keep, onChange }: {
  kind: HomeKind; id: string; keep: KeepState; onChange: (k: KeepState) => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (keep.state === "starred") {
    return (
      <div style={keepRow}>
        <span>★ Starred in Navidrome — kept offline automatically</span>
        <span style={keepProgress}>{progressText(keep)}</span>
      </div>
    );
  }
  const kept = keep.state === "kept";
  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = kept ? await unkeepHome(api, kind, id) : await keepHome(api, kind, id);
      onChange(r.keep);
    } catch (e) {
      setError(apiErrorMessage(e, kept ? "Couldn't stop keeping it" : "Couldn't keep it offline"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={keepRow}>
      <button type="button" role="switch" aria-checked={kept} aria-label="Keep offline"
              disabled={busy} onClick={() => void toggle()} style={kept ? keptBtn : moreBtn}>
        {kept ? "✓ Kept offline" : "Keep offline"}
      </button>
      {kept && <span style={keepProgress}>{progressText(keep)}</span>}
      {error && <span role="alert" style={{ color: "var(--accent2)", fontSize: 13 }}>{error}</span>}
    </div>
  );
}

function HomeDetail({ kind, id, navigate, offline }: {
  kind: HomeKind; id: string; navigate: Navigate; offline: boolean;
}) {
  const api = useApi();
  const [data, setData] = useState<Detail | null>(null);
  const [keep, setKeep] = useState<KeepState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const { toast, play } = usePlay(offline);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    homeDetail<Detail>(api, kind, id)
      .then((d) => { if (live) { setData(d); setKeep(d.keep ?? null); } })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, kind, id, attempt]);

  // A kept item still downloading: refresh its progress (and track marks).
  const downloading = keep !== null && keep.state === "kept" && keep.tracks_present < keep.tracks_total;
  useEffect(() => {
    if (!downloading) return;
    let live = true;
    const t = window.setInterval(() => {
      homeDetail<Detail>(api, kind, id)
        .then((d) => { if (live) { setData(d); setKeep(d.keep ?? null); } })
        .catch(() => { /* keep showing the last progress */ });
    }, KEEP_POLL_MS);
    return () => { live = false; window.clearInterval(t); };
  }, [api, kind, id, downloading]);

  const backList: HomeList = kind === "artist" ? "artists" : kind === "album" ? "albums" : "playlists";
  const back = (
    <button type="button" onClick={() => navigate("music", ["home", backList])} style={backBtn}>
      ‹ Home Library
    </button>
  );
  if (error) {
    return <div style={{ padding: 16 }}>{back}
      <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} /></div>;
  }
  if (!data) return <div style={{ padding: 16 }}>{back}<SkeletonRows count={8} /></div>;
  const toggle = keep && <KeepToggle kind={kind} id={id} keep={keep} onChange={setKeep} />;

  if (kind === "artist") {
    const d = data as HomeArtistDetail;
    return (
      <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
        {back}
        <h1 style={{ margin: 0, fontSize: 24 }}>{d.artist.name}</h1>
        <Actions onPlay={() => void play(() => artistTrackIds(api, id, offline), "play", d.artist.name)}
                 onQueue={() => void play(() => artistTrackIds(api, id, offline), "queue", d.artist.name)} />
        {toggle}
        {toast && <div role="status" style={banner}>{toast}</div>}
        <div style={TILE_GRID}>
          {d.albums.map((al) => {
            const dimmed = offline && al.offline === false;
            return (
              <button key={al.id} type="button" onClick={() => navigate("music", ["home", "album", al.id])}
                      style={{ ...tileBtn, opacity: dimmed ? 0.4 : 1 }}>
                <AuthedImg path={artPath(al.art_id)} alt=""
                           style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
                <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{al.name}</span>
                {al.year != null && <span style={{ fontSize: 12, color: "var(--ink2)" }}>{al.year}</span>}
                {dimmed && <NotOffline />}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  const album = kind === "album" ? (data as HomeAlbumDetail).album : null;
  const title = album ? album.name : (data as HomePlaylistDetail).playlist.name;
  const tracks: HomeTrack[] = (data as HomeAlbumDetail | HomePlaylistDetail).tracks;
  const playable = (t: HomeTrack) => !offline || t.offline === true;
  const ids = tracks.filter(playable).map((t) => t.id);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      {back}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
        {album && <AuthedImg path={artPath(album.art_id, 480)} alt=""
                             style={{ width: 160, height: 160, borderRadius: 12, flexShrink: 0 }} />}
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 24 }}>{title}</h1>
          {album && (album.artist || album.year) && (
            <div style={{ color: "var(--ink2)" }}>
              {[album.artist, album.year].filter(Boolean).join(" · ")}</div>
          )}
        </div>
      </div>
      <Actions onPlay={() => void play(ids, "play", title)} onQueue={() => void play(ids, "queue", title)} />
      {toggle}
      {toast && <div role="status" style={banner}>{toast}</div>}
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {tracks.map((t, i) => {
          const dimmed = !playable(t);
          return (
            <li key={`${t.id}:${i}`} style={{ ...row, opacity: dimmed ? 0.45 : 1 }}>
              <span style={{ width: 24, color: "var(--ink2)", fontSize: 12 }}>{i + 1}</span>
              <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{t.title}</span>
              {dimmed && <NotOffline />}
              {t.duration ? <span style={{ color: "var(--ink2)", fontSize: 12 }}>{mmss(t.duration)}</span> : null}
              <button type="button" aria-label={`Play from ${t.title}`} style={smallBtn} disabled={dimmed}
                      onClick={() => void play(tracks.slice(i).filter(playable).map((x) => x.id), "play", title)}>▶</button>
              <button type="button" aria-label={`Queue ${t.title}`} style={smallBtn} disabled={dimmed}
                      onClick={() => void play([t.id], "queue", t.title)}>+Q</button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Actions({ onPlay, onQueue }: { onPlay: () => void; onQueue: () => void }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button type="button" onClick={onPlay} style={primaryBtn}>Play all</button>
      <button type="button" onClick={onQueue} style={moreBtn}>Queue all</button>
    </div>
  );
}

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const pill = (active: boolean): CSSProperties => ({
  padding: "6px 14px", borderRadius: 999, fontSize: 13, border: "1px solid var(--rule)",
  background: active ? "var(--accent)" : "var(--panel)",
  color: active ? "var(--bg)" : "var(--ink)", cursor: "pointer",
});
const searchInput: CSSProperties = {
  padding: "10px 12px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, width: "100%",
};
const banner: CSSProperties = {
  padding: "8px 12px", borderRadius: 8, background: "var(--panel)",
  color: "var(--ink2)", fontSize: 13,
};
const offlineBanner: CSSProperties = {
  margin: "12px 16px 0", padding: "8px 12px", borderRadius: 8, fontSize: 14, fontWeight: 600,
  background: "var(--panel)", color: "var(--ink)", border: "1px solid var(--accent)",
};
const notOfflineTag: CSSProperties = {
  fontSize: 11, color: "var(--ink2)", border: "1px solid var(--rule)", borderRadius: 999,
  padding: "1px 6px", flexShrink: 0, alignSelf: "flex-start",
};
const keepRow: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", fontSize: 14, color: "var(--ink2)",
};
const keepProgress: CSSProperties = { fontSize: 13, color: "var(--ink2)" };
const row: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "10px 4px",
  borderBottom: "1px solid var(--rule)", minWidth: 0,
};
const rowBtn: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, background: "transparent", border: 0,
  color: "var(--ink)", fontSize: 15, padding: "4px 0", cursor: "pointer", textAlign: "left",
};
const tileBtn: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 6, minWidth: 0, padding: 0,
  background: "transparent", border: 0, color: "var(--ink)", textAlign: "left", cursor: "pointer",
};
const smallBtn: CSSProperties = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 13, cursor: "pointer", flexShrink: 0,
};
const primaryBtn: CSSProperties = {
  padding: "10px 18px", borderRadius: 10, border: 0, background: "var(--accent)",
  color: "var(--bg)", fontWeight: 700, fontSize: 15, cursor: "pointer",
};
const moreBtn: CSSProperties = {
  padding: "10px 18px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
const keptBtn: CSSProperties = { ...moreBtn, borderColor: "var(--accent)", color: "var(--accent)" };
const backBtn: CSSProperties = {
  alignSelf: "flex-start", background: "transparent", border: 0, color: "var(--ink2)",
  fontSize: 14, cursor: "pointer", padding: "4px 0",
};
```

- [ ] **Step 5: Run the tests**

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`
Expected: tsc clean; every test passes (the earlier HomeLibrary tests are unchanged: their mock rejects `api/remote/home/status`, which the hook treats as online); build succeeds.

- [ ] **Step 6: Commit**

```bash
git add remote-ui/src/lib/api.ts remote-ui/src/lib/api.test.ts remote-ui/src/lib/homeLibrary.ts remote-ui/src/screens/HomeLibrary.tsx remote-ui/src/screens/HomeLibrary.test.tsx
git commit -m "feat(remote-ui): offline banner, dimmed un-kept music, Keep offline toggle with progress

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 10: Admin → Storage section (drive, downloads, kept items)

**Files:**
- Modify: `remote-ui/src/lib/route.ts` (`Route`, `ROUTES`)
- Modify: `remote-ui/src/components/Sidebar.tsx` (Admin group), `remote-ui/src/screens/More.tsx` (rows), `remote-ui/src/components/AppShell.tsx` (`renderSection`), `remote-ui/src/admin/LockScreen.tsx` (`purpose` prop)
- Create: `remote-ui/src/admin/storage/types.ts`, `remote-ui/src/admin/storage/api.ts`, `remote-ui/src/admin/StorageSection.tsx`
- Test: `remote-ui/src/admin/StorageSection.test.tsx` (create), `remote-ui/src/lib/route.test.ts`, `remote-ui/src/components/TabBar.test.tsx`, `remote-ui/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: `GET /api/accounts/storage`, `POST /api/accounts/storage/remove {kind, id}`, `POST /api/accounts/storage/retry {}` via `accountsApi` (admin token; a 401 clears the session → lock screen) (Task 8).
- Produces: route `"storage"` (`#/storage`), `StorageSection({ desktop })`, `STORAGE_POLL_MS = 5000`, `PAUSED_TEXT: Record<PauseReason, string>`, `fmtBytes(n)`, `storageApi.{overview, remove, retry}`; `LockScreen({ expired, purpose = "manage accounts" })`.
- UI text contract: drive "Internal drive" / "USB drive at <path>" / "No music storage — downloads are off."; "N downloading · M queued"; paused texts below; "Low space — downloads stop until more than X is free."; "N skipped — not enough space"; "N failed" + **Retry failed**; kept rows "Album · you · 4 / 10 · 300 MB" with **Remove** (`aria-label="Remove <name>"`) for `source: "user"`, "Unstar in Navidrome to remove" for starred; notices "Removed <name> — <size> freed." / "Retrying N downloads."; library down → message + **Retry**.

- [ ] **Step 1: Write the failing tests**

Create `remote-ui/src/admin/StorageSection.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { StorageSection, PAUSED_TEXT } from "./StorageSection";
import { adminSession } from "./session";
import type { PauseReason } from "./storage/types";

const GiB = 1024 ** 3;
const OVERVIEW = {
  drive: { present: true, internal: true, mount_path: "/opt/boombox/storage/music", total_bytes: 900 * GiB,
           free_bytes: 800 * GiB, reserve_bytes: 20 * GiB, music_bytes: 3 * GiB, kept_tracks: 412 },
  kept: [
    { kind: "album", id: "al1", name: "Blue", source: "user", tracks_total: 10, tracks_present: 4, bytes: 300 * 1024 ** 2 },
    { kind: "album", id: "al2", name: "Court and Spark", source: "starred", tracks_total: 11, tracks_present: 11, bytes: 400 * 1024 ** 2 },
  ],
  downloads: { active: true, queued: 12, in_flight: [{ id: "t5", title: "California" }, { id: "t6", title: "River" }],
               paused: null, failed: 2, no_space: 0 },
};

function mockFetch(routes: Record<string, unknown>, status = 200) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const body = key in routes ? routes[key] : { ok: false, error: `unmocked ${key}` };
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  adminSession.set("tok");
  (globalThis as { confirm?: () => boolean }).confirm = () => true;
});
afterEach(() => {
  vi.unstubAllGlobals();
  adminSession.clear("logout");
  delete (globalThis as { confirm?: () => boolean }).confirm;
});

describe("StorageSection", () => {
  it("is locked until the web password is entered", async () => {
    adminSession.clear("logout");
    render(<StorageSection desktop={false} />);
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
  });

  it("shows the drive, the downloads and the kept items", async () => {
    mockFetch({ "GET /api/accounts/storage": OVERVIEW });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText("Internal drive")).toBeTruthy();
    expect(screen.getByText("2 downloading · 12 queued")).toBeTruthy();
    expect(screen.getByText(/California/)).toBeTruthy();
    expect(screen.getByText("2 failed")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Blue" })).toBeTruthy();
    const starred = screen.getByText("Court and Spark").closest("li")!;
    expect(starred.textContent).toContain("Unstar in Navidrome to remove");
    expect(starred.querySelector("button")).toBeNull();
  });

  it.each(["streaming", "hot", "offline", "low_space"] as PauseReason[])("explains a pause: %s", async (reason) => {
    mockFetch({ "GET /api/accounts/storage": { ...OVERVIEW, downloads: { ...OVERVIEW.downloads, paused: reason } } });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText(PAUSED_TEXT[reason])).toBeTruthy();
  });

  it("says when the drive is below the reserve and how many were skipped", async () => {
    mockFetch({ "GET /api/accounts/storage": {
      ...OVERVIEW, drive: { ...OVERVIEW.drive, free_bytes: 10 * GiB },
      downloads: { ...OVERVIEW.downloads, no_space: 3 } } });
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText(/Low space — downloads stop until more than 20.0 GB is free/)).toBeTruthy();
    expect(screen.getByText("3 skipped — not enough space")).toBeTruthy();
  });

  it("Remove posts the item and reports what was freed", async () => {
    const fetchMock = mockFetch({
      "GET /api/accounts/storage": OVERVIEW,
      "POST /api/accounts/storage/remove": { ok: true, removed_tracks: 4, freed_bytes: 300 * 1024 ** 2 },
    });
    render(<StorageSection desktop={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Blue" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/accounts/storage/remove",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ kind: "album", id: "al1" }) })));
    expect(await screen.findByText("Removed Blue — 300 MB freed.")).toBeTruthy();
  });

  it("Retry failed re-queues them", async () => {
    mockFetch({ "GET /api/accounts/storage": OVERVIEW,
                "POST /api/accounts/storage/retry": { ok: true, retried: 2 } });
    render(<StorageSection desktop={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry failed" }));
    expect(await screen.findByText("Retrying 2 downloads.")).toBeTruthy();
  });

  it("library down: a message and Retry", async () => {
    mockFetch({ "GET /api/accounts/storage": { ok: false, error: "library service not answering" } }, 502);
    render(<StorageSection desktop={false} />);
    expect(await screen.findByText("library service not answering")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("an expired admin session goes back to the lock screen", async () => {
    mockFetch({ "GET /api/accounts/storage": { error: "admin session required" } }, 401);
    render(<StorageSection desktop={false} />);
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
  });
});
```

In `remote-ui/src/lib/route.test.ts` add `"storage"` to the route list in "parses the spec's section routes"; in `remote-ui/src/components/TabBar.test.tsx` add `"storage"` to the `for (const r of [...] as const)` list. Append to `remote-ui/src/components/AppShell.test.tsx` inside `describe("AppShell admin", …)`:

```tsx
  it("Storage is an admin section: locked, in the sidebar and in More", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    adminSession.clear("logout");
    setViewport(1440, 900);
    window.location.hash = "#/storage";
    renderShell();
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
    const sidebar = screen.getByRole("navigation", { name: "Sections" });
    expect(within(sidebar).getByRole("button", { name: "Storage" }).textContent).toContain("🔒");
    setViewport(390, 844);
    act(() => { window.location.hash = "#/more"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByRole("button", { name: /Storage/ })).toBeTruthy();
    vi.unstubAllGlobals();
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd remote-ui && npx vitest run src/admin/StorageSection.test.tsx src/lib/route.test.ts src/components/TabBar.test.tsx src/components/AppShell.test.tsx`
Expected: FAIL — `Failed to resolve import "./StorageSection"`; `parseHash("#/storage")` gives `now`.

- [ ] **Step 3: Implement routing and navigation**

`remote-ui/src/lib/route.ts`:

```ts
export type Route =
  | "now" | "music" | "video" | "search" | "playlists" | "files" | "accounts" | "storage" | "more";

export const ROUTES: readonly Route[] = [
  "now", "music", "video", "search", "playlists", "files", "accounts", "storage", "more",
];
```

`remote-ui/src/components/Sidebar.tsx`: after `{item("accounts", "Accounts", adminLocked ? "🔒" : "🔓")}` add `{item("storage", "Storage", adminLocked ? "🔒" : "🔓")}`.

`remote-ui/src/screens/More.tsx`: docstring "The phone's More tab: Playlists, Files, Admin → Accounts / Storage, Settings."; after the Accounts row add:

```ts
    { label: "Storage", icon: adminLocked ? "🔒" : "🔓", hint: "Admin",
      onClick: () => navigate("storage") },
```

`remote-ui/src/components/AppShell.tsx`: `import { StorageSection } from "../admin/StorageSection";` and in `renderSection` after the accounts case: `case "storage": return <StorageSection desktop={p.desktop} />;`

`remote-ui/src/admin/LockScreen.tsx`: signature `export function LockScreen({ expired, purpose = "manage accounts" }: { expired: boolean; purpose?: string })` and the non-expired text becomes `` `Enter the boombox web password to ${purpose}.` ``.

- [ ] **Step 4: Implement the Storage section**

Create `remote-ui/src/admin/storage/types.ts`:

```ts
export type PauseReason = "offline" | "low_space" | "hot" | "streaming";
export interface StorageDrive {
  present: boolean; internal: boolean; mount_path: string | null;
  total_bytes: number | null; free_bytes: number | null; reserve_bytes: number;
  music_bytes: number; kept_tracks: number;
}
export interface KeptItem {
  kind: "album" | "artist" | "playlist" | "starred_tracks"; id: string; name: string;
  source: "user" | "starred"; tracks_total: number; tracks_present: number; bytes: number;
}
export interface Downloads {
  active: boolean; queued: number; in_flight: { id: string; title: string }[];
  paused: PauseReason | null; failed: number; no_space: number;
}
export interface StorageOverview { drive: StorageDrive; kept: KeptItem[]; downloads: Downloads }
export interface Failure { ok: false; error?: string }
export interface RemoveResult { ok: true; removed_tracks: number; freed_bytes: number }
export interface RetryResult { ok: true; retried: number }
```

Create `remote-ui/src/admin/storage/api.ts`:

```ts
import { accountsApi } from "../accounts/api";
import type { Failure, RemoveResult, RetryResult, StorageOverview } from "./types";

/** Admin → Storage (/api/accounts/storage*, admin session). */
export const storageApi = {
  overview: () => accountsApi.get<StorageOverview | Failure>("storage"),
  remove: (kind: string, id: string) =>
    accountsApi.post<RemoveResult | Failure>("storage/remove", { kind, id }),
  retry: () => accountsApi.post<RetryResult | Failure>("storage/retry", {}),
};
```

Create `remote-ui/src/admin/StorageSection.tsx`:

```tsx
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { ErrorText, SecondaryButton } from "./ui";
import { LockScreen } from "./LockScreen";
import { lock, useAdminSession } from "./session";
import { UNREACHABLE, ACCOUNTS_DESKTOP_COLUMNS } from "./AccountsSection";
import { storageApi } from "./storage/api";
import type { KeptItem, PauseReason, StorageOverview } from "./storage/types";
import { SectionMessage } from "../components/SectionMessage";

export const STORAGE_POLL_MS = 5000;
export const PAUSED_TEXT: Record<PauseReason, string> = {
  streaming: "Paused while music streams from the Home Library.",
  hot: "Paused — the boombox is hot (70 °C or more); checking again every minute.",
  offline: "Paused — the Home Library server can't be reached.",
  low_space: "Stopped — free space is below the reserve.",
};
const KIND_LABEL: Record<KeptItem["kind"], string> = {
  album: "Album", artist: "Artist", playlist: "Playlist", starred_tracks: "Songs",
};

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u += 1; }
  return `${u === 0 || v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[u]}`;
}

function Panel({ title, wide, children }: { title: string; wide?: boolean; children: ReactNode }) {
  return (
    <section style={{ border: "1px solid var(--rule)", borderRadius: 14, padding: 16, minWidth: 0,
                      gridColumn: wide ? "1 / -1" : undefined }}>
      <h2 style={{ fontSize: 18, margin: "0 0 12px" }}>{title}</h2>
      {children}
    </section>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0" }}>
      <dt style={muted}>{k}</dt><dd style={{ margin: 0, textAlign: "right" }}>{v}</dd>
    </div>
  );
}

function Header() {
  return (
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
      <h1 style={{ fontSize: 24, margin: 0 }}>Storage</h1>
      <SecondaryButton aria-label="Lock admin" onClick={() => void lock()}
                       style={{ width: "auto", minHeight: 40, padding: "8px 14px" }}>🔒 Lock</SecondaryButton>
    </header>
  );
}

function StoragePanel({ desktop, extra }: { desktop: boolean; extra?: ReactNode }) {
  const [data, setData] = useState<StorageOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const r = await storageApi.overview();
      if ("drive" in r) { setData(r); setError(null); }
      else setError(r.error || UNREACHABLE);
    } catch {
      setError(UNREACHABLE);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), STORAGE_POLL_MS);
    return () => window.clearInterval(t);
  }, [refresh, attempt]);

  const remove = async (item: KeptItem) => {
    if (!window.confirm(`Remove ${item.name} from the boombox?`)) return;
    setBusy(true);
    try {
      const r = await storageApi.remove(item.kind, item.id);
      setNotice(r.ok ? `Removed ${item.name} — ${fmtBytes(r.freed_bytes)} freed.`
                     : (r.error || "Couldn't remove it."));
    } catch {
      setNotice(UNREACHABLE);
    }
    setBusy(false);
    void refresh();
  };

  const retry = async () => {
    setBusy(true);
    try {
      const r = await storageApi.retry();
      setNotice(r.ok ? `Retrying ${r.retried} download${r.retried === 1 ? "" : "s"}.`
                     : (r.error || "Couldn't retry."));
    } catch {
      setNotice(UNREACHABLE);
    }
    setBusy(false);
    void refresh();
  };

  if (!data) {
    return (
      <div style={page}>
        <Header />
        {error
          ? <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} />
          : <p style={muted}>Loading…</p>}
      </div>
    );
  }
  const { drive, downloads, kept } = data;
  const low = drive.present && drive.free_bytes != null && drive.free_bytes < drive.reserve_bytes;
  return (
    <div style={page}>
      <Header />
      {error && <ErrorText>{error}</ErrorText>}
      {notice && <div role="status" style={noticeStyle}>{notice}</div>}
      <div data-testid="storage-grid" style={{
        display: "grid", gap: 16, alignItems: "start",
        gridTemplateColumns: desktop ? ACCOUNTS_DESKTOP_COLUMNS : "minmax(0, 1fr)",
      }}>
        <Panel title="Drive">
          {!drive.present ? <p style={muted}>No music storage — downloads are off.</p> : (
            <dl style={{ margin: 0 }}>
              <Fact k="Where" v={drive.internal ? "Internal drive" : `USB drive at ${drive.mount_path ?? "?"}`} />
              <Fact k="Size" v={fmtBytes(drive.total_bytes)} />
              <Fact k="Free" v={fmtBytes(drive.free_bytes)} />
              <Fact k="Always kept free" v={fmtBytes(drive.reserve_bytes)} />
              <Fact k="Music on the boombox" v={`${fmtBytes(drive.music_bytes)} · ${drive.kept_tracks} tracks`} />
            </dl>
          )}
          {low && <ErrorText>Low space — downloads stop until more than {fmtBytes(drive.reserve_bytes)} is free.</ErrorText>}
        </Panel>
        <Panel title="Downloads">
          {!downloads.active ? (
            <p style={muted}>Downloads aren't running — no music storage or no music server set up.</p>
          ) : (
            <>
              <p style={muted}>{downloads.in_flight.length} downloading · {downloads.queued} queued</p>
              {downloads.in_flight.length > 0 && (
                <ul style={list}>{downloads.in_flight.map((t) => <li key={t.id}>⬇ {t.title}</li>)}</ul>
              )}
              {downloads.paused && <p role="note" style={pausedStyle}>{PAUSED_TEXT[downloads.paused]}</p>}
            </>
          )}
          {downloads.no_space > 0 && <p style={muted}>{downloads.no_space} skipped — not enough space</p>}
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={muted}>{downloads.failed} failed</span>
            <SecondaryButton disabled={busy || downloads.failed + downloads.no_space === 0}
                             onClick={() => void retry()} style={smallBtn}>Retry failed</SecondaryButton>
          </div>
        </Panel>
        <Panel title="Kept offline" wide>
          {kept.length === 0 ? (
            <p style={muted}>Nothing kept yet — open an album in Music and tap Keep offline.</p>
          ) : (
            <ul style={list}>
              {kept.map((it) => (
                <li key={`${it.kind}:${it.id}`} style={keptRow}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={ellipsis}>{it.name}</div>
                    <div style={small}>
                      {KIND_LABEL[it.kind]} · {it.source === "user" ? "you" : "starred"} · {it.tracks_present} / {it.tracks_total} · {fmtBytes(it.bytes)}
                    </div>
                  </div>
                  {it.source === "user" ? (
                    <SecondaryButton aria-label={`Remove ${it.name}`} disabled={busy}
                                     onClick={() => void remove(it)} style={smallBtn}>Remove</SecondaryButton>
                  ) : (
                    <span style={small}>Unstar in Navidrome to remove</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
        {extra}
      </div>
    </div>
  );
}

/** Admin → Storage: the music drive, the download queue and kept items,
 *  behind the web password like Accounts. */
export function StorageSection({ desktop }: { desktop: boolean }) {
  const { unlocked, expired } = useAdminSession();
  if (!unlocked) return <LockScreen expired={expired} purpose="manage storage" />;
  return <StoragePanel desktop={desktop} />;
}

const page: CSSProperties = { padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 16 };
const muted: CSSProperties = { color: "var(--ink2)", margin: "4px 0" };
const small: CSSProperties = { color: "var(--ink2)", fontSize: 13 };
const list: CSSProperties = { listStyle: "none", margin: "4px 0", padding: 0 };
const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const keptRow: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--rule)",
};
const smallBtn: CSSProperties = { width: "auto", minHeight: 40, padding: "8px 14px" };
const pausedStyle: CSSProperties = { margin: "6px 0", color: "var(--ink)", fontSize: 14 };
const noticeStyle: CSSProperties = {
  padding: "8px 12px", borderRadius: 8, background: "var(--panel)", color: "var(--ink2)", fontSize: 13,
};
```

- [ ] **Step 5: Run the tests**

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`
Expected: tsc clean; all tests pass; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add remote-ui/src/lib/route.ts remote-ui/src/lib/route.test.ts remote-ui/src/components/Sidebar.tsx remote-ui/src/components/AppShell.tsx remote-ui/src/components/AppShell.test.tsx remote-ui/src/components/TabBar.test.tsx remote-ui/src/screens/More.tsx remote-ui/src/admin/LockScreen.tsx remote-ui/src/admin/storage remote-ui/src/admin/StorageSection.tsx remote-ui/src/admin/StorageSection.test.tsx
git commit -m "feat(remote-ui): Admin → Storage — drive, downloads with pause reasons, kept items, remove, retry

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Uploads move to Storage; household Files becomes read-only

**Files:**
- Rewrite: `remote-ui/src/screens/Files.tsx` (`FileBrowser` + household `Files`)
- Modify: `remote-ui/src/admin/accounts/api.ts` (`accountsApi.upload`), `remote-ui/src/admin/storage/api.ts` (`adminFilesClient`), `remote-ui/src/admin/StorageSection.tsx` (Uploads panel), `remote-ui/src/components/AppShell.tsx` (`files` case)
- Modify: `CHANGELOG.md` (new top section)
- Test: `remote-ui/src/screens/Files.test.tsx` (rewrite), `remote-ui/src/admin/StorageSection.test.tsx` (append)

**Interfaces:**
- Consumes: household `GET api/remote/files/browse?path=`, `POST api/remote/library/rescan`; admin `GET /api/accounts/storage/files/browse?path=`, `POST /api/accounts/storage/files/upload` (multipart), `POST /api/accounts/storage/files/delete {path}` (Task 8).
- Produces (`screens/Files.tsx`): `interface FilesClient { browse(path): Promise<BrowseResult>; upload?(files: File[]): Promise<{ saved: string[] }>; remove?(path: string): Promise<unknown>; rescan?(): Promise<unknown> }`, `FileBrowser({ client })` (upload / delete / rescan controls appear only when the client has them; a browse failure shows its message + **Retry**), `Files({ navigate })` (read-only, note "Uploading and deleting files moved to Admin → Storage." + **Open Storage** → `navigate("storage")`).
- Produces (`admin/accounts/api.ts`): `accountsApi.upload<T>(path, files)`; (`admin/storage/api.ts`): `adminFilesClient: FilesClient`.

- [ ] **Step 1: Write the failing tests**

Replace `remote-ui/src/screens/Files.test.tsx` with:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Files, FileBrowser, type FilesClient } from "./Files";
import { ApiProvider, type RemoteApi } from "../lib/api";

const sample = {
  path: "",
  parent: null,
  entries: [
    { name: "Albums", kind: "dir" as const, tracks: 42 },
    { name: "Song.mp3", kind: "file" as const, size: 5 * 1024 * 1024, deletable: true },
  ],
};

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://localhost/",
    get: vi.fn().mockResolvedValue(sample),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function adminClient(overrides: Partial<FilesClient> = {}) {
  return {
    browse: vi.fn().mockResolvedValue(sample),
    upload: vi.fn().mockResolvedValue({ saved: ["uploads/foo.mp3"] }),
    remove: vi.fn().mockResolvedValue({ deleted: "Song.mp3" }),
    ...overrides,
  };
}

describe("Files (household, read-only)", () => {
  it("browses, offers no upload or delete, and points to Storage", async () => {
    const navigate = vi.fn();
    const api = mockApi();
    render(<ApiProvider api={api}><Files navigate={navigate} /></ApiProvider>);
    expect(await screen.findByText("Albums")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith("api/remote/files/browse?path=");
    expect(screen.queryByRole("button", { name: "+ Upload" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete Song.mp3" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Storage" }));
    expect(navigate).toHaveBeenCalledWith("storage");
  });

  it("enters a directory", async () => {
    const api = mockApi();
    render(<ApiProvider api={api}><Files navigate={vi.fn()} /></ApiProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /Albums/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("api/remote/files/browse?path=Albums"));
  });
});

describe("FileBrowser with the admin client", () => {
  beforeEach(() => { (globalThis as { confirm?: () => boolean }).confirm = () => true; });
  afterEach(() => { delete (globalThis as { confirm?: () => boolean }).confirm; });

  it("uploads files", async () => {
    const c = adminClient();
    render(<FileBrowser client={c} />);
    await screen.findByText("Albums");
    const input = screen.getByLabelText(/Choose files/i) as HTMLInputElement;
    const file = new File(["x"], "foo.mp3", { type: "audio/mpeg" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(c.upload).toHaveBeenCalledWith([file]));
    expect(await screen.findByText("Uploaded: 1 file(s)")).toBeTruthy();
  });

  it("deletes a file after confirming", async () => {
    const c = adminClient();
    render(<FileBrowser client={c} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete Song.mp3" }));
    await waitFor(() => expect(c.remove).toHaveBeenCalledWith("Song.mp3"));
  });

  it("a browse failure shows the message and Retry", async () => {
    const c = adminClient({ browse: vi.fn().mockRejectedValueOnce(new Error("library down"))
                                             .mockResolvedValue(sample) });
    render(<FileBrowser client={c} />);
    expect(await screen.findByText("library down")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Albums")).toBeTruthy();
  });
});
```

Append to `remote-ui/src/admin/StorageSection.test.tsx` inside `describe("StorageSection", …)`:

```tsx
  it("the Uploads panel browses the music folder with the admin session", async () => {
    const fetchMock = mockFetch({
      "GET /api/accounts/storage": OVERVIEW,
      "GET /api/accounts/storage/files/browse?path=": {
        path: "", parent: null, entries: [{ name: "uploads", kind: "dir", tracks: 3 }] },
    });
    render(<StorageSection desktop />);
    expect(await screen.findByText("uploads")).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Upload" })).toBeTruthy();
    const call = fetchMock.mock.calls.find(([u]) => u === "/api/accounts/storage/files/browse?path=")!;
    expect((call[1] as RequestInit).headers).toEqual(expect.objectContaining({ Authorization: "Bearer tok" }));
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd remote-ui && npx vitest run src/screens/Files.test.tsx src/admin/StorageSection.test.tsx`
Expected: FAIL — `FileBrowser` is not exported; no "Open Storage"; no Uploads panel.

- [ ] **Step 3: Implement**

Replace `remote-ui/src/screens/Files.tsx` with:

```tsx
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useApi, ApiError, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { SkeletonRows } from "../components/Skeleton";
import { SectionMessage } from "../components/SectionMessage";

export interface Entry {
  name: string; kind: "dir" | "file"; size?: number; mtime?: number; tracks?: number; deletable?: boolean;
}
export interface BrowseResult { path: string; parent: string | null; entries: Entry[] }

/** Where a FileBrowser reads and writes. Household: browse (+ rescan) via
 *  the pair token. Admin → Storage: browse, upload, delete via the admin
 *  session. Controls appear only for what the client can do. */
export interface FilesClient {
  browse(path: string): Promise<BrowseResult>;
  upload?(files: File[]): Promise<{ saved: string[] }>;
  remove?(path: string): Promise<unknown>;
  rescan?(): Promise<unknown>;
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function errorText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return apiErrorMessage(e, fallback);
  if (e instanceof TypeError) return "Couldn't reach the boombox.";
  return e instanceof Error && e.message ? e.message : fallback;
}

/** The music folder (hidden files filtered server-side except the .usb
 *  mount link). Uploads land in uploads/ and trigger a library scan. */
export function FileBrowser({ client }: { client: FilesClient }) {
  const [path, setPath] = useState("");
  const [data, setData] = useState<BrowseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reload = (p = path) => {
    setBusy(true);
    setErr(null);
    client.browse(p)
      .then((r) => { setData(r); setPath(r.path); })
      .catch((e: unknown) => setErr(errorText(e, "Couldn't list the files")))
      .finally(() => setBusy(false));
  };

  useEffect(() => { reload(""); /* mount-only */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const enterDir = (name: string) => reload(path ? `${path}/${name}` : name);
  const upDir = () => {
    if (data?.parent === null && path === "") return;
    reload(data?.parent ?? "");
  };

  const onUpload = async (files: FileList | null) => {
    if (!client.upload || !files || files.length === 0) return;
    setStatus(`Uploading ${files.length} file(s)…`);
    try {
      const res = await client.upload(Array.from(files));
      setStatus(`Uploaded: ${res.saved.length} file(s)`);
      reload();
    } catch (e: unknown) {
      setStatus(errorText(e, "Upload failed"));
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const onDelete = async (name: string) => {
    if (!client.remove || !window.confirm(`Delete ${name}?`)) return;
    try {
      await client.remove(path ? `${path}/${name}` : name);
      reload();
    } catch (e: unknown) {
      setStatus(errorText(e, "Delete failed"));
    }
  };

  const onRescan = async () => {
    if (!client.rescan) return;
    setStatus("Rescanning library…");
    try {
      await client.rescan();
      setStatus("Library rescan started (can take a few minutes).");
    } catch (e: unknown) {
      setStatus(errorText(e, "Rescan failed"));
    }
  };

  return (
    <div>
      <header style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <button type="button" onClick={upDir} disabled={path === "" && data?.parent === null}
                aria-label="Up" style={iconBtn}>‹</button>
        <div style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--ink2)", flex: 1,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          /{path || ""}
        </div>
        {client.rescan && (
          <button type="button" onClick={() => void onRescan()} style={smallBtn}
                  aria-label="Rescan library">↻</button>
        )}
        {client.upload && (
          <>
            <button type="button" onClick={() => fileInputRef.current?.click()} style={primaryBtn}>
              + Upload</button>
            <input ref={fileInputRef} type="file" multiple style={{ display: "none" }}
                   aria-label="Choose files to upload" onChange={(e) => void onUpload(e.target.files)} />
          </>
        )}
      </header>
      {status && <div role="status" style={statusStyle}>{status}</div>}
      {err ? (
        <SectionMessage message={err} onRetry={() => reload()} />
      ) : (
        <>
          {busy && !data && <SkeletonRows count={8} />}
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data?.entries.map((e) => (
              <li key={e.name} style={{ display: "flex", alignItems: "center", gap: 12,
                                        padding: "10px 4px", borderBottom: "1px solid var(--rule)" }}>
                {e.kind === "dir" ? (
                  <button type="button" onClick={() => enterDir(e.name)}
                          style={{ ...rowBtn, textAlign: "left", flex: 1 }}>
                    <span style={{ marginRight: 8 }}>📁</span>{e.name}
                    {typeof e.tracks === "number" && e.tracks > 0 && (
                      <span style={{ marginLeft: 8, color: "var(--ink2)", fontSize: 12 }}>({e.tracks})</span>
                    )}
                  </button>
                ) : (
                  <>
                    <span style={{ flex: 1 }}>
                      <span style={{ marginRight: 8 }}>🎵</span>{e.name}
                      {typeof e.size === "number" && (
                        <span style={{ marginLeft: 8, color: "var(--ink2)", fontSize: 12 }}>{fmtSize(e.size)}</span>
                      )}
                    </span>
                    {client.remove && e.deletable && (
                      <button type="button" onClick={() => void onDelete(e.name)}
                              aria-label={`Delete ${e.name}`} style={iconBtn}>×</button>
                    )}
                  </>
                )}
              </li>
            ))}
            {data && data.entries.length === 0 && (
              <li style={{ padding: "16px 4px", color: "var(--ink2)" }}>Empty directory.</li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}

/** Household Files tab: browse only. Uploading and deleting live in
 *  Admin → Storage (the server refuses them on the pair-token tier). */
export function Files({ navigate }: { navigate: Navigate }) {
  const api = useApi();
  const client = useMemo<FilesClient>(() => ({
    browse: (p) => api.get<BrowseResult>(`api/remote/files/browse?path=${encodeURIComponent(p)}`),
    rescan: () => api.post<{ ok: boolean }>("api/remote/library/rescan"),
  }), [api]);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      <div role="note" style={pointer}>
        <span style={{ flex: 1, minWidth: 0 }}>Uploading and deleting files moved to Admin → Storage.</span>
        <button type="button" onClick={() => navigate("storage")} style={smallBtn}>Open Storage</button>
      </div>
      <FileBrowser client={client} />
    </div>
  );
}

const iconBtn: CSSProperties = {
  width: 36, height: 36, borderRadius: 18, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", cursor: "pointer", fontSize: 18,
};
const primaryBtn: CSSProperties = {
  padding: "8px 14px", borderRadius: 8, border: 0, background: "var(--accent)",
  color: "var(--bg)", fontSize: 14, fontWeight: 600, cursor: "pointer",
};
const rowBtn: CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink)", fontSize: 15, padding: "4px 0", cursor: "pointer",
};
const smallBtn: CSSProperties = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 13, cursor: "pointer", flexShrink: 0,
};
const statusStyle: CSSProperties = {
  padding: "8px 12px", marginBottom: 12, borderRadius: 8, background: "var(--panel)",
  color: "var(--ink2)", fontSize: 13,
};
const pointer: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "10px 12px",
  borderRadius: 10, background: "var(--panel)", color: "var(--ink2)", fontSize: 14,
};
```

In `remote-ui/src/admin/accounts/api.ts` add before `export const accountsApi` and extend it:

```ts
/** Multipart upload (field "file") with the admin token. */
async function upload<T>(path: string, files: File[]): Promise<T> {
  const form = new FormData();
  for (const f of files) form.append("file", f, f.name);
  const headers: Record<string, string> = {};
  const token = adminSession.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(BASE + path, { method: "POST", credentials: "same-origin", headers, body: form });
  if (r.status === 401) adminSession.clear("expired");
  try {
    return (await r.json()) as T;
  } catch {
    throw new Error(`HTTP ${r.status}`);
  }
}

export const accountsApi = {
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body?: unknown) => call<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => call<T>("PUT", path, body),
  upload: <T>(path: string, files: File[]) => upload<T>(path, files),
};
```

Append to `remote-ui/src/admin/storage/api.ts`:

```ts
import type { BrowseResult, FilesClient } from "../../screens/Files";

/** Admin → Storage file browser: browse / upload / delete with the admin
 *  session. accountsApi resolves JSON error bodies, so turn them into throws. */
export const adminFilesClient: FilesClient = {
  async browse(path) {
    const r = await accountsApi.get<BrowseResult | { error?: string }>(
      `storage/files/browse?path=${encodeURIComponent(path)}`);
    if ("entries" in r) return r;
    throw new Error(r.error || "Couldn't list the files");
  },
  async upload(files) {
    const r = await accountsApi.upload<{ saved?: string[]; error?: string }>("storage/files/upload", files);
    if (Array.isArray(r.saved)) return { saved: r.saved };
    throw new Error(r.error || "Upload failed");
  },
  async remove(path) {
    const r = await accountsApi.post<{ deleted?: string; error?: string }>("storage/files/delete", { path });
    if (r.deleted === undefined) throw new Error(r.error || "Delete failed");
    return r;
  },
};
```

(move the new `import type` line to the top of the file with the other imports.)

In `remote-ui/src/admin/StorageSection.tsx`: `import { FileBrowser } from "../screens/Files";` and `import { adminFilesClient, storageApi } from "./storage/api";`; `StorageSection` renders

```tsx
  return (
    <StoragePanel desktop={desktop} extra={
      <Panel title="Uploads" wide><FileBrowser client={adminFilesClient} /></Panel>} />
  );
```

In `remote-ui/src/components/AppShell.tsx`: `case "files": return <Files navigate={p.navigate} />;`

In `CHANGELOG.md`, insert above `## Unreleased — LAN app`:

```markdown
## Unreleased — offline music (LAN app 2A)

The boombox keeps music for the road on its own drive.

### Migration

`install.sh` now creates `/opt/boombox/storage/music` (boombox user, 0755);
`boombox-library` also creates it on start when it can. A `library.yml`
still carrying the old 1 GiB `reserve_bytes` default is read as 20 GiB.
nginx gains `location = /api/accounts/storage/files/upload` (synced by
`apply-release.sh swap` like the rest of the site).

### Added

- **Keep offline** on Home Library albums / artists / playlists in the LAN
  app, with "N / M on the boombox" progress; everything starred in Navidrome
  is kept automatically. Originals download to `/opt/boombox/storage/music`
  (`cache.internal_path`), ≤ 2 at a time, paused while a stream plays, while
  the SoC is ≥ 70 °C and while the homelab is unreachable; 20 GiB is always
  kept free.
- **Offline mode**: with the homelab unreachable the Music section says
  "Offline — showing kept music", dims what isn't on the boombox and plays
  only kept tracks; RFID cards do the same.
- **Admin → Storage** (`#/storage`): drive size / free / reserve, kept items
  with Remove, the download queue with its pause reason, Retry failed, and
  the music-folder uploader.

### Changed

- Uploading and deleting files moved from the household Files tab to
  Admin → Storage (`/api/accounts/storage/files/*`, admin session);
  `POST /api/remote/files/upload|delete` now answer 403. Paired phones
  browse and download only.
```

- [ ] **Step 4: Run the tests**

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`
Expected: tsc clean; all tests pass; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/screens/Files.tsx remote-ui/src/screens/Files.test.tsx remote-ui/src/admin/accounts/api.ts remote-ui/src/admin/storage/api.ts remote-ui/src/admin/StorageSection.tsx remote-ui/src/admin/StorageSection.test.tsx remote-ui/src/components/AppShell.tsx CHANGELOG.md
git commit -m "feat(remote-ui): uploads move to Admin → Storage; household Files is read-only

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 12: Deploy to MarkII and verify on the device

**Device facts:** MarkII = `192.168.1.81` (`markii.local`), DietPi, service user `dietpi` (uid 1000); `ssh root@192.168.1.81` / `ssh dietpi@192.168.1.81`. Releases live in `/opt/boombox/releases/<sha>`, `/opt/boombox/current` → `releases/6c421ce` before this deploy. Navidrome is remote at `music.coblr.io`. Mopidy runs as the system user `mopidy` and must be able to read the kept files. **Never build on the Pi. Deploy only when the Pi is < 65 °C and the minute is not within 2 of `:38`** (hourly library sync; MarkII brown-outs under load). The first sync after the restart reconciles starred items and starts their downloads — watch the temperature; the queue backs off by itself at ≥ 70 °C.

**Files:** none (fixes found here go back to the owning task's files, with a failing test first, as their own commits).

- [ ] **Step 1: Preconditions**

```bash
ssh root@192.168.1.81 'vcgencmd measure_temp; date +%M; uptime; readlink -f /opt/boombox/current; df -h /opt/boombox | tail -1'
```
Expected: `temp=` below `65.0'C`; minute not in 36–40; current → `/opt/boombox/releases/6c421ce`; ≥ 100 GB available on `/opt/boombox`'s filesystem. If hot or near `:38`, wait and re-check.

- [ ] **Step 2: Build every UI on the Mac and stage the release**

```bash
cd /Users/jwc/code/Boombox
(cd ui && npm ci && npm run build) && (cd remote-ui && npm ci && npm run build) && (cd setup-ui && npm ci && npm run build)
SHA=$(git rev-parse --short HEAD); echo "$SHA"
CUR=$(ssh dietpi@192.168.1.81 'basename "$(readlink -f /opt/boombox/current)"'); echo "$CUR"   # 6c421ce
ssh root@192.168.1.81 "cp -a /opt/boombox/releases/$CUR /opt/boombox/releases/$SHA"
git archive HEAD | ssh dietpi@192.168.1.81 "tar -x -C /opt/boombox/releases/$SHA"
for d in ui remote-ui setup-ui; do
  rsync -a --delete "$d/dist/" "dietpi@192.168.1.81:/opt/boombox/releases/$SHA/$d/dist/"
done
ssh dietpi@192.168.1.81 "printf '%s\n' $SHA > /opt/boombox/releases/$SHA/VERSION && chmod -R a+rX /opt/boombox/releases/$SHA/ui/dist /opt/boombox/releases/$SHA/remote-ui/dist /opt/boombox/releases/$SHA/setup-ui/dist"
```
Expected: `/opt/boombox/releases/$SHA/services/boombox_library/keep.py` and `.../remote-ui/dist/index.html` exist on the Pi.

- [ ] **Step 3: Root: storage directory; root helper only if it changed**

```bash
ssh root@192.168.1.81 "install -d -o dietpi -g dietpi -m 0755 /opt/boombox/storage /opt/boombox/storage/music && ls -ld /opt/boombox /opt/boombox/storage /opt/boombox/storage/music"
git diff --quiet "$CUR" HEAD -- install/bin/boombox-setup-apply install/sudoers/boombox && echo "helper unchanged" || echo "HELPER CHANGED"
```
Expected: three `drwxr-xr-x` lines, the last two owned by `dietpi dietpi`; `helper unchanged` (this plan does not touch the helper). Only if it printed `HELPER CHANGED`: `ssh root@192.168.1.81 "install -m 0755 -o root -g root /opt/boombox/releases/$SHA/install/bin/boombox-setup-apply /usr/local/sbin/boombox-setup-apply"` before Step 4.

- [ ] **Step 4: Apply as `dietpi`**

```bash
ssh dietpi@192.168.1.81 "export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
  R=/opt/boombox/releases/$SHA
  \$R/install/apply-release.sh preflight $SHA &&
  \$R/install/apply-release.sh swap $SHA &&
  \$R/install/apply-release.sh restart &&
  \$R/install/apply-release.sh verify; echo rc=\$?"
```
Expected: `swap` logs the nginx site + snippet in sync (the new upload location ships with the snippet); `verify` passes; `rc=0`. On failure: `\$R/install/apply-release.sh revert` and investigate.

- [ ] **Step 5: Services, storage and admin API**

```bash
B=http://192.168.1.81:8090
ssh dietpi@192.168.1.81 "curl -s http://127.0.0.1:6687/api/library/health"          # "internal_storage": true, "cache_mount": "/opt/boombox/storage/music"
ssh dietpi@192.168.1.81 "ls -la /opt/boombox/storage/music; readlink /opt/boombox/cache-mount"   # .boombox-cache, audio/ meta/ tmp/; → /opt/boombox/storage/music
ssh dietpi@192.168.1.81 "journalctl --user -u boombox-library --since '-5 min' | grep -E 'cache drive present|downloads (paused|resumed)|Traceback'"   # 'cache drive present at /opt/boombox/storage/music'; no Traceback
curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/accounts/storage/files/upload   # 401 (admin session required, via the new exact location)
curl -s -o /dev/null -w "%{http_code}\n" $B/api/accounts/storage                         # 401
PW=$(ssh root@192.168.1.81 "sed -n 's/^BOOMBOX_WEB_PASSWORD=//p' /etc/boombox/web-auth.env")
TOKEN=$(curl -s -X POST -H 'Content-Type: application/json' -H "Origin: $B" \
  --data "$(python3 -c 'import json,sys; print(json.dumps({"password": sys.argv[1]}))' "$PW")" \
  $B/api/accounts/session | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" $B/api/accounts/storage | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["drive"]); print(d["downloads"]); print(len(d["kept"]), "kept items")'
```
Expected: `drive.internal True`, `reserve_bytes 21474836480` (the device's old 1 GiB value is upgraded), `total_bytes`/`free_bytes` of the NVMe; `downloads.active True`; kept items include `source: "starred"` entries once the first sync finished (re-run after a minute if the sync is still going).

Pair a temporary client:

```bash
PIN=$(ssh dietpi@192.168.1.81 "curl -s -X POST http://127.0.0.1/api/remote/pair/start" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pin"])')
RT=$(curl -s -X POST -H 'Content-Type: application/json' -d "{\"pin\":\"$PIN\",\"label\":\"deploy-check\"}" $B/api/remote/pair | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth_token"])')
curl -s -H "Authorization: Bearer $RT" $B/api/remote/home/status        # {"online": true, "internal_storage": true}
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $RT" -X POST $B/api/remote/files/delete -H 'Content-Type: application/json' -d '{"path":"x.mp3"}'   # 403 (moved)
```

- [ ] **Step 6: Keep an album; files appear; Mopidy can read them; starred downloads run**

```bash
AL=$(curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/browse?type=albums" | python3 -c '
import json,sys; items=json.load(sys.stdin)["items"]; print(items[len(items)//3]["id"])')
curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/album/$AL" | python3 -c '
import json,sys; d=json.load(sys.stdin); print(d["album"]["name"], len(d["tracks"]), "tracks", d["keep"])'
curl -s -X POST -H "Authorization: Bearer $RT" -H 'Content-Type: application/json' -d "{\"kind\":\"album\",\"id\":\"$AL\"}" $B/api/remote/home/keep
for i in $(seq 1 30); do
  ssh root@192.168.1.81 'vcgencmd measure_temp'
  curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/album/$AL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["keep"])'
  curl -s -H "Authorization: Bearer $TOKEN" $B/api/accounts/storage | python3 -c 'import json,sys; print(json.load(sys.stdin)["downloads"])'
  sleep 10
done
ssh root@192.168.1.81 "ls -la /opt/boombox/storage/music/audio | head; ls /opt/boombox/storage/music/tmp; f=\$(ls /opt/boombox/storage/music/audio | head -1); sudo -u mopidy test -r /opt/boombox/storage/music/audio/\$f && echo mopidy-can-read"
```
Expected: `keep` goes to `{"state": "kept", "tracks_total": N, "tracks_present": N}`; never more than 2 in `in_flight`; if the temperature reaches 70 °C, `paused: "hot"` appears and downloads resume after it drops (re-checked every 60 s); `audio/` holds `<track_id>.<original suffix>` files (original format, e.g. `.flac`), `tmp/` is empty once idle; `mopidy-can-read`. The audio file count keeps rising for starred albums.

Streaming pause: in the app (Step 9 browser or curl) play an album that is **not** kept, then:

```bash
curl -s -X POST -H "Authorization: Bearer $RT" -H 'Content-Type: application/json' -d "{\"ids\": $(curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/album/$(curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/browse?type=albums" | python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][7]["id"])')" | python3 -c 'import json,sys; print(json.dumps([t["id"] for t in json.load(sys.stdin)["tracks"]][:3]))'), \"mode\": \"play\"}" $B/api/remote/home/play
sleep 20; curl -s -H "Authorization: Bearer $TOKEN" $B/api/accounts/storage | python3 -c 'import json,sys; print(json.load(sys.stdin)["downloads"]["paused"])'
```
Expected: `streaming` while queued downloads remain (or `None` if the queue is already empty — then note it and re-check during the starred backlog). Keep the volume ≤ 20 %; pause playback afterwards.

- [ ] **Step 7: Offline test — block `music.coblr.io`, play kept music, then RESTORE `/etc/hosts`**

Wait until the kept album shows all tracks present. Then:

```bash
ssh root@192.168.1.81 "cp -p /etc/hosts /root/hosts.bak-offline-music && grep -c music.coblr.io /etc/hosts; printf '127.0.0.1 music.coblr.io\n' >> /etc/hosts"
ssh dietpi@192.168.1.81 "curl -s -X POST http://127.0.0.1:6687/api/library/sync/run; sleep 15; curl -s http://127.0.0.1:6687/api/library/health"   # "navidrome_reachable": false
curl -s -H "Authorization: Bearer $RT" $B/api/remote/home/status                                      # {"online": false, ...}
IDS=$(curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/album/$AL" | python3 -c 'import json,sys; print(json.dumps([t["id"] for t in json.load(sys.stdin)["tracks"]]))')
ssh dietpi@192.168.1.81 "curl -s -X POST -H 'Content-Type: application/json' -d '{\"ids\": $IDS}' http://127.0.0.1:6687/api/library/resolve" | python3 -c '
import json,sys; print({i["source"] for i in json.load(sys.stdin)["items"]})'                         # {'cache'} — the kiosk's resolve path
curl -s -X POST -H "Authorization: Bearer $RT" -H 'Content-Type: application/json' -d "{\"ids\": $IDS, \"mode\": \"play\"}" $B/api/remote/home/play   # {"ok": true, "count": N, "skipped": 0}
ssh dietpi@192.168.1.81 "curl -s -X POST -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"core.playback.get_current_track\"}' http://127.0.0.1:6680/mopidy/rpc; curl -s -X POST -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"core.playback.get_state\"}' http://127.0.0.1:6680/mopidy/rpc"
```
Expected: current track `uri` = `file:///opt/boombox/storage/music/audio/...`, state `playing` (audible on the boombox). If a card is bound to a kept album, tap it: `journalctl --user -u boombox-rfid --since '-2 min'` shows "Home Library unreachable — playing kept tracks only" and playback starts.

Browser check of the offline app (phone 390×844):

```bash
agent-browser open http://192.168.1.81:8090/
agent-browser eval "localStorage.setItem('boombox-remote-pairing', JSON.stringify({base: 'http://192.168.1.81:8090', token: '$RT', name: 'MarkII'})); location.reload()"
agent-browser set viewport 390 844
agent-browser open "http://192.168.1.81:8090/#/music/home/albums"; agent-browser wait 3000; agent-browser screenshot /tmp/offline-albums.png
agent-browser open "http://192.168.1.81:8090/#/music/home/album/$AL"; agent-browser wait 2500; agent-browser screenshot /tmp/offline-kept-album.png
```
Expected (read the PNGs): "Offline — showing kept music" banner; un-kept album tiles dimmed with "not offline"; the kept album's tracks all normal, "All N on the boombox". Optionally view the kiosk: `ssh -N -L 9223:127.0.0.1:9222 dietpi@192.168.1.81 &` then `agent-browser connect 9223 && agent-browser screenshot /tmp/kiosk-offline.png` (Now Playing shows the kept track) and `kill %1`.

**Restore — always run this, even if a check above failed:**

```bash
ssh root@192.168.1.81 "cp -p /root/hosts.bak-offline-music /etc/hosts && grep -c music.coblr.io /etc/hosts; rm /root/hosts.bak-offline-music"
ssh dietpi@192.168.1.81 "curl -s -X POST http://127.0.0.1:6687/api/library/sync/run; sleep 20; curl -s http://127.0.0.1:6687/api/library/health"   # "navidrome_reachable": true
curl -s -H "Authorization: Bearer $RT" $B/api/remote/home/status    # {"online": true, ...}
```
Expected: the `grep -c` prints the same count as before the block (normally `0`); online again; the app's banner disappears within 30 s; downloads resume (`paused` back to `null`).

- [ ] **Step 8: Storage page in the browser (desktop 1440×900)**

```bash
agent-browser set viewport 1440 900
agent-browser open "http://192.168.1.81:8090/#/storage"; agent-browser wait 1500
agent-browser snapshot   # find the Web password field ref
```
Fill the password with `agent-browser fill <ref> "$PW"` → **Unlock** → screenshot `/tmp/storage-desktop.png`: Drive (Internal drive, size/free/20.0 GB kept free), Downloads (count, pause reason if any, Retry failed), Kept offline (the test album "· you ·" with Remove; starred items with "Unstar in Navidrome to remove"), Uploads (music folder). Click **Remove** on the test album (unless the owner wants to keep it) → notice "Removed … freed." and `ssh dietpi@192.168.1.81 "ls /opt/boombox/storage/music/audio | wc -l"` drops by its track count (unless those tracks are also starred). Upload a small `.mp3` through the Uploads panel → it appears under `uploads/`; delete it again. Open `#/files` at 390×844: no Upload button, the "moved to Admin → Storage" note with **Open Storage**.

- [ ] **Step 9: Clean up and record**

```bash
ssh dietpi@192.168.1.81 "curl -s -X POST -H 'Content-Type: application/json' -d '{\"token\":\"$RT\"}' http://127.0.0.1/api/remote/admin/unpair"   # {"ok": true}
curl -s -X DELETE -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{}' $B/api/accounts/session   # {"ok": true}
ssh root@192.168.1.81 'vcgencmd measure_temp; grep -c music.coblr.io /etc/hosts'
unset PW TOKEN RT
```
Record the results (screenshots, curl outputs, temperatures, any deviations) in the PR description. Any fix found here gets a failing test first, in the owning task's files, as its own commit.

---

## Spec coverage map

| Spec requirement | Task |
|---|---|
| `cache.internal_path` default `/opt/boombox/storage/music`, created 0755 boombox user, marker, always-present, preferred over `/media`; `""` → `/media` fallback | 1, 3, 12 |
| `cache.reserve_bytes` default 20 GiB, read by the downloader; crossing it → `no_space`; Storage says so | 1, 2, 3, 5, 10 |
| Existing `cache_state` rows untouched | 1, 3 (no data migration; reconcile unchanged) |
| ≤ `sync.max_concurrent_downloads` | 2, 3 |
| Pause while Mopidy plays a stream-proxy URI (in-flight finish) | 2, 3, 12 |
| Thermal backoff ≥ 70 °C, 60 s re-check, absent file → none | 2, 3, 12 |
| Offline: queue idles, no retry storm, resumes on reachability | 2, 3, 12 |
| Failed keeps `error` + reason, retried on the hourly sync only | 2, 3, 5 (explicit Retry failed) |
| `POST /api/remote/home/keep` → pin(user) + enqueue | 4, 7 |
| `DELETE /api/remote/home/keep` → unpin(user); orphans evictable or removed via Storage "Remove" | 4, 5, 7 |
| Detail responses gain `keep` and per-track `offline` | 4, 7 |
| `GET /api/remote/home/status` → `{online, internal_storage}` | 4, 7 |
| Offline banner, browse/search from local catalog, un-kept tiles/rows dimmed "not offline", play sends only present tracks | 4, 7, 9 |
| Keep offline toggle with progress "32 / 40 on the boombox" | 9 |
| Storage admin section `#/storage` (sidebar + More, lock icon) via `/api/accounts/storage*` proxying boombox-library | 8, 10 |
| Drive: total / free / reserve, music bytes, kept track count | 5, 10 |
| Kept items: size, progress, source, Remove (user only; starred → "unstar in Navidrome to remove") | 5, 10 |
| Downloads: queue length, in-flight, paused reason (streaming / hot / offline / low space), failed count + Retry failed | 2, 5, 10 |
| Uploads move to Storage; Files shows a pointer; household read-only browse | 8, 11 |
| Every storage call degrades to a message with Retry; missing thermal / Mopidy / Navidrome never crash the queue | 2, 7, 8, 9, 10, 11 |
| Disk-full: reserve check before each download + hard stop when free < reserve | 2 |
| Keep/remove idempotent; removing while downloading cancels the queued ones | 2, 4, 5 |
| Success: kiosk, LAN app and RFID play every kept track offline | 6, 9, 12 |
| Testing — Python, UI, on MarkII (keep → files, block homelab, kept plays, Offline shown, un-kept dimmed, unblock, starred auto-download) | 1–11, 12 |
