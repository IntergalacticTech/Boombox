# Home Library Phase 1 — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `boombox-library` Python service end-to-end (Subsonic client, SQLite catalog cache, pin manager, USB cache drive detection, downloader, FIFO eviction, playback resolver, HTTP API) so the boombox can sync metadata + audio from a Navidrome server, play cached content offline, and stream uncached content when online. **No UI in this phase** — verifiable entirely via the HTTP API and Mopidy direct calls.

**Architecture:** New aiohttp service on `:6687`, package at `services/boombox_library/`, entry point at `services/boombox-library.py`. SQLite catalog on NVMe (`/opt/boombox/state/library.db`), audio cache on USB drive identified by `.boombox-cache` marker, symlink at `/opt/boombox/cache-mount` lets Mopidy-Local read a stable path. Subsonic token+salt auth, hourly background reconcile + event-driven syncs.

**Tech Stack:** Python 3.11+ · aiohttp · stdlib sqlite3 (with FTS5) · PyYAML · cryptography (Fernet for at-rest password) · pytest with asyncio_mode=auto. Matches the patterns in `services/boombox_updater/`.

**Scope split (this plan ≠ everything):**
- Phase 1 (this plan): `boombox-library` service + Mopidy-Subsonic install + Mopidy-Local repoint + systemd/nginx wiring + integration test against the dev Navidrome at `192.168.1.223:4533`.
- Phase 2 (separate plan): UI surface — Settings → Home Library, Settings → Offline Cache, Home Library browse root, pin button, status badges, sync indicator, cache drive adoption modal, search grouping.
- Phase 3 (separate plan): retire `~/Music` SMB share, stale-playlist scan, docs (README/SERVICES/ARCHITECTURE/CHANGELOG/HOME-LIBRARY.md).

---

## File structure

### Created (new)

| Path | Responsibility |
|---|---|
| `services/boombox_library/__init__.py` | Package marker, version constant |
| `services/boombox_library/subsonic.py` | Subsonic API client (token+salt, retries, typed responses) |
| `services/boombox_library/config.py` | YAML config IO + Fernet password encryption |
| `services/boombox_library/db.py` | SQLite connection, migrations, FTS5 setup |
| `services/boombox_library/models.py` | Frozen dataclasses for catalog entities, pins, cache state |
| `services/boombox_library/catalog.py` | Full + delta sync from Subsonic → SQLite + FTS5 |
| `services/boombox_library/pins.py` | Pin/unpin + cascade + starred reconciliation + sidecar JSON |
| `services/boombox_library/cache_drive.py` | Marker-file detection, symlink management, mount poll |
| `services/boombox_library/downloader.py` | Download queue, concurrent workers, atomic file writes, retry |
| `services/boombox_library/eviction.py` | FIFO eviction over streamed cache (pinned-protected) |
| `services/boombox_library/resolver.py` | Pure function: (track_id, online, cache_status) → playback decision |
| `services/boombox_library/mopidy_config.py` | Writes `[subsonic]` block to mopidy.conf, triggers reload |
| `services/boombox_library/api.py` | aiohttp routes + app builder |
| `services/boombox-library.py` | Service entry point — wires it all together, runs event loop |
| `services/tests/test_library_subsonic.py` | Unit tests for Subsonic client |
| `services/tests/test_library_config.py` | Unit tests for config IO + encryption |
| `services/tests/test_library_db.py` | Unit tests for schema/migrations |
| `services/tests/test_library_catalog.py` | Unit tests for catalog sync |
| `services/tests/test_library_pins.py` | Unit tests for pin manager + sidecar |
| `services/tests/test_library_cache_drive.py` | Unit tests for cache drive detection |
| `services/tests/test_library_downloader.py` | Unit tests for downloader |
| `services/tests/test_library_eviction.py` | Unit tests for eviction |
| `services/tests/test_library_resolver.py` | Unit tests for resolver |
| `services/tests/test_library_api.py` | Unit tests for HTTP API |
| `services/tests/test_library_integration.py` | Integration tests against real Navidrome (env-gated) |
| `install/systemd/user/boombox-library.service` | User systemd unit |
| `install/config/library.yml.template` | Default config template, copied to `/etc/boombox/library.yml` on first install |

### Modified

| Path | Change |
|---|---|
| `install/config/nginx-boombox-common.conf` | Add `/api/library/` proxy block → `127.0.0.1:6687` |
| `install/config/requirements.txt` | Add `PyYAML>=6.0`, `cryptography>=42` |
| `install/install.sh` | `pip install Mopidy-Subsonic` + create `/etc/boombox/library.yml` from template |
| `install/config/mopidy.conf` | Add commented placeholder `[subsonic]` block (real values written by service) |
| `services/tests/conftest.py` | Add `NAVIDROME_DEV_URL` / `NAVIDROME_DEV_USER` / `NAVIDROME_DEV_PASS` env-var fixture for integration tests |

### Out of scope (Phase 1)

- `services/boombox-state.py` — UI calls resolver directly in Phase 2; no Phase-1 state-service changes needed
- Any UI files under `ui/` or `remote-ui/`
- Retiring `~/Music` SMB share
- Documentation updates (other than CHANGELOG line for the new service)

---

## Conventions matched from the existing codebase

- All modules use `from __future__ import annotations`
- Logging via stdlib `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")`
- HTTP framework: `aiohttp.web`
- Config file: YAML at `/etc/boombox/library.yml` (existing services use JSON; the spec specified YAML — we use YAML)
- Atomic config writes: write `<path>.tmp` then `os.replace`
- State dir: `/opt/boombox/state/` (matches `boombox-updater`)
- Service entry point hyphenated; package directory snake_case (matches `boombox_updater/` + `boombox-updater.py`)
- Tests flat in `services/tests/test_<name>.py`; `conftest.py` adds `SERVICES_DIR` to `sys.path`
- pytest: `asyncio_mode = "auto"`, `python_files = ["test_*.py"]`
- Atomic file rename pattern for downloads: `.part` tmp → `os.replace` to final

---

## Tasks

### Task 1: Package scaffold + Subsonic auth helper (token+salt)

**Files:**
- Create: `services/boombox_library/__init__.py`
- Create: `services/boombox_library/subsonic.py`
- Create: `services/tests/test_library_subsonic.py`

- [ ] **Step 1: Create `services/boombox_library/__init__.py`**

```python
"""Boombox home-library service.

Maintains a local SQLite catalog of a Navidrome (Subsonic API) library,
downloads pinned content to a USB cache drive, opportunistically caches
streamed playback (FIFO eviction), and exposes an HTTP API on :6687
consumed by the UI and the playback resolver.

Subpackages are small and pure where possible so unit tests can exercise
auth, sync, pin reconciliation, eviction, and the resolver without
touching the network or the filesystem outside their own tempdirs.
"""
from __future__ import annotations

__version__ = "0.1.0"
```

- [ ] **Step 2: Write failing test for token+salt construction**

Create `services/tests/test_library_subsonic.py`:

```python
"""Tests for boombox_library.subsonic — Subsonic API client."""
from __future__ import annotations

import hashlib

import pytest

from boombox_library.subsonic import make_auth_params


def test_make_auth_params_token_and_salt():
    params = make_auth_params(username="jwc", password="turtle99", salt="abc123")
    expected_token = hashlib.md5(b"turtle99abc123").hexdigest()
    assert params["u"] == "jwc"
    assert params["t"] == expected_token
    assert params["s"] == "abc123"
    assert params["v"] == "1.16.1"
    assert params["c"] == "boombox-library"
    assert params["f"] == "json"
    # Password must never appear
    assert "p" not in params
    assert "turtle99" not in str(params)


def test_make_auth_params_random_salt_each_call():
    p1 = make_auth_params(username="u", password="p")
    p2 = make_auth_params(username="u", password="p")
    assert p1["s"] != p2["s"]  # random per call
    assert p1["t"] != p2["t"]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/jwc/code/Boombox
pytest services/tests/test_library_subsonic.py -v
```

Expected: ImportError (`make_auth_params` doesn't exist yet).

- [ ] **Step 4: Implement `make_auth_params` in `services/boombox_library/subsonic.py`**

```python
"""Subsonic API client for boombox-library.

All requests use token+salt auth (no plain-password transmission). Each
call generates a fresh salt so request signatures are not replayable.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Optional

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_ID = "boombox-library"


def make_auth_params(
    username: str,
    password: str,
    salt: Optional[str] = None,
) -> dict:
    """Construct Subsonic auth params using the token+salt scheme.

    salt is generated per-call unless supplied (tests pin it).
    """
    if salt is None:
        salt = secrets.token_hex(8)
    token = hashlib.md5(f"{password}{salt}".encode("utf-8")).hexdigest()
    return {
        "u": username,
        "t": token,
        "s": salt,
        "v": SUBSONIC_API_VERSION,
        "c": SUBSONIC_CLIENT_ID,
        "f": "json",
    }
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest services/tests/test_library_subsonic.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add services/boombox_library/__init__.py services/boombox_library/subsonic.py services/tests/test_library_subsonic.py
git commit -m "feat(library): subsonic token+salt auth helper"
```

---

### Task 2: Subsonic HTTP client (ping + error handling)

**Files:**
- Modify: `services/boombox_library/subsonic.py`
- Modify: `services/tests/test_library_subsonic.py`

- [ ] **Step 1: Write failing tests for `SubsonicClient.ping()`**

Append to `services/tests/test_library_subsonic.py`:

```python
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

from boombox_library.subsonic import (
    SubsonicClient,
    SubsonicAuthError,
    SubsonicError,
    SubsonicUnreachable,
)


def _mock_response(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


@pytest.mark.asyncio
async def test_ping_ok():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        ok = await client.ping()
    assert ok is True


@pytest.mark.asyncio
async def test_ping_auth_fail_raises():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="bad")
    payload = {"subsonic-response": {
        "status": "failed",
        "error": {"code": 40, "message": "Wrong username or password."},
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        with pytest.raises(SubsonicAuthError):
            await client.ping()


@pytest.mark.asyncio
async def test_ping_unreachable_raises():
    import aiohttp
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(side_effect=aiohttp.ClientConnectionError("nope"))
        with pytest.raises(SubsonicUnreachable):
            await client.ping()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_subsonic.py -v
```

Expected: ImportError for `SubsonicClient`, `SubsonicAuthError`, etc.

- [ ] **Step 3: Implement `SubsonicClient.ping()` + exception hierarchy**

Append to `services/boombox_library/subsonic.py`:

```python
import logging
from typing import Any

import aiohttp

log = logging.getLogger("boombox-library.subsonic")


class SubsonicError(Exception):
    """Base for all Subsonic API errors."""


class SubsonicAuthError(SubsonicError):
    """Authentication failed (HTTP 401 or response code 40/41)."""


class SubsonicUnreachable(SubsonicError):
    """Network-level failure reaching the server (timeout, DNS, refused)."""


class SubsonicClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 10.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session = session  # injected for tests; lazily created otherwise
        self._own_session = session is None

    async def __aenter__(self) -> "SubsonicClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _call(self, endpoint: str, extra_params: dict | None = None) -> dict:
        """Issue a Subsonic call; return the parsed 'subsonic-response' body.

        Raises SubsonicUnreachable on network failure,
        SubsonicAuthError on auth rejection,
        SubsonicError on other API-reported failures.
        """
        params = make_auth_params(self.username, self.password)
        if extra_params:
            params.update(extra_params)
        url = f"{self.base_url}/rest/{endpoint}.view"
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status >= 500:
                    raise SubsonicUnreachable(f"server {resp.status}")
                body = await resp.json()
        except aiohttp.ClientError as e:
            raise SubsonicUnreachable(str(e)) from e

        sub = body.get("subsonic-response", {})
        if sub.get("status") == "failed":
            err = sub.get("error", {})
            code = err.get("code")
            msg = err.get("message", "unknown")
            if code in (40, 41):
                raise SubsonicAuthError(f"{code}: {msg}")
            raise SubsonicError(f"{code}: {msg}")
        return sub

    async def ping(self) -> bool:
        await self._call("ping")
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_subsonic.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/subsonic.py services/tests/test_library_subsonic.py
git commit -m "feat(library): subsonic client ping with typed error hierarchy"
```

---

### Task 3: Subsonic API methods (catalog + download)

**Files:**
- Modify: `services/boombox_library/subsonic.py`
- Modify: `services/tests/test_library_subsonic.py`

- [ ] **Step 1: Write failing tests for catalog methods**

Append to `services/tests/test_library_subsonic.py`:

```python
@pytest.mark.asyncio
async def test_get_artists_parses_index_buckets():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {
        "status": "ok",
        "artists": {
            "index": [
                {"name": "A", "artist": [
                    {"id": "1", "name": "ABBA", "albumCount": 6},
                    {"id": "2", "name": "AC/DC", "albumCount": 31},
                ]},
                {"name": "B", "artist": [
                    {"id": "3", "name": "Beatles", "albumCount": 12},
                ]},
            ],
        },
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        artists = await client.get_artists()
    assert len(artists) == 3
    assert artists[0]["id"] == "1"
    assert artists[0]["name"] == "ABBA"
    assert artists[1]["name"] == "AC/DC"
    assert artists[2]["name"] == "Beatles"


@pytest.mark.asyncio
async def test_get_album_list_pages():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {
        "status": "ok",
        "albumList2": {"album": [{"id": "a1"}, {"id": "a2"}]},
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        albums = await client.get_album_list(offset=0, size=500)
    assert len(albums) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_subsonic.py -k "get_artists or get_album_list" -v
```

Expected: AttributeError — methods don't exist.

- [ ] **Step 3: Implement catalog methods**

Append to `services/boombox_library/subsonic.py`:

```python
    async def get_artists(self) -> list[dict]:
        """Return a flat list of all artists (Subsonic returns them in
        alphabetic index buckets; we flatten)."""
        sub = await self._call("getArtists")
        index = sub.get("artists", {}).get("index", [])
        out: list[dict] = []
        for bucket in index:
            out.extend(bucket.get("artist", []))
        return out

    async def get_album_list(self, offset: int = 0, size: int = 500) -> list[dict]:
        """Paginated album list (alphabeticalByName ordering)."""
        sub = await self._call("getAlbumList2", {
            "type": "alphabeticalByName",
            "offset": offset,
            "size": size,
        })
        return sub.get("albumList2", {}).get("album", [])

    async def get_album(self, album_id: str) -> dict:
        """Album detail including all tracks."""
        sub = await self._call("getAlbum", {"id": album_id})
        return sub.get("album", {})

    async def get_starred(self) -> dict:
        """Starred artists/albums/songs."""
        sub = await self._call("getStarred2")
        return sub.get("starred2", {"artist": [], "album": [], "song": []})

    async def get_playlists(self) -> list[dict]:
        sub = await self._call("getPlaylists")
        return sub.get("playlists", {}).get("playlist", [])

    async def get_playlist(self, playlist_id: str) -> dict:
        sub = await self._call("getPlaylist", {"id": playlist_id})
        return sub.get("playlist", {})

    def download_url(self, track_id: str) -> tuple[str, dict]:
        """Return (url, params) for a track download. Caller streams the
        response. Auth params are baked in fresh per call."""
        return (
            f"{self.base_url}/rest/download.view",
            {**make_auth_params(self.username, self.password), "id": track_id},
        )

    def cover_art_url(self, art_id: str, size: int | None = None) -> tuple[str, dict]:
        params = {**make_auth_params(self.username, self.password), "id": art_id}
        if size is not None:
            params["size"] = size
        return (f"{self.base_url}/rest/getCoverArt.view", params)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_subsonic.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/subsonic.py services/tests/test_library_subsonic.py
git commit -m "feat(library): subsonic catalog + download URL methods"
```

---

### Task 4: Config module (YAML + at-rest password encryption)

**Files:**
- Create: `services/boombox_library/config.py`
- Create: `services/tests/test_library_config.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_config.py`:

```python
"""Tests for boombox_library.config — YAML config + Fernet password encryption."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.config import (
    LibraryConfig,
    SourceConfig,
    SyncConfig,
    CacheConfig,
    DEFAULT_CONFIG,
    load_config,
    save_config,
    _derive_key,
)


def test_default_config_shape():
    c = DEFAULT_CONFIG
    assert c.sync.interval_seconds == 3600
    assert c.sync.starred_auto_pin is True
    assert c.sync.max_concurrent_downloads == 2
    assert c.cache.marker_filename == ".boombox-cache"
    assert c.cache.reserve_bytes == 1073741824  # 1 GB


def test_round_trip_no_password(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    cfg = DEFAULT_CONFIG
    save_config(cfg, path=path)
    loaded = load_config(path=path)
    assert loaded.source.url == cfg.source.url
    assert loaded.source.username == cfg.source.username
    assert loaded.source.password == ""  # default empty


def test_round_trip_with_password(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    cfg = LibraryConfig(
        source=SourceConfig(url="http://192.168.1.223:4533",
                            username="jwc", password="turtle99"),
        sync=DEFAULT_CONFIG.sync,
        cache=DEFAULT_CONFIG.cache,
    )
    save_config(cfg, path=path)

    # Raw YAML must NOT contain the plain password.
    raw = path.read_text()
    assert "turtle99" not in raw
    assert "password_encrypted" in raw

    loaded = load_config(path=path)
    assert loaded.source.password == "turtle99"


def test_atomic_write_temp_file_cleaned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    save_config(DEFAULT_CONFIG, path=path)
    # Temp file must not be left behind
    assert not (tmp_path / "library.yml.tmp").exists()


def test_machine_id_derived_key_stable(monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    k1 = _derive_key()
    k2 = _derive_key()
    assert k1 == k2  # deterministic per machine
    assert len(k1) == 44  # Fernet base64 key length
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_config.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement config module**

Create `services/boombox_library/config.py`:

```python
"""User-editable boombox-library config: /etc/boombox/library.yml.

Defaults are baked in for first-boot. The HTTP API's PUT validates input
before calling save_config(). All writes are atomic (.tmp + rename) so
a crashed write never corrupts the file. The Subsonic password is
encrypted at rest via Fernet, with a key derived from /etc/machine-id —
the file is unreadable on a different machine, mitigating disk-image
exfiltration.
"""
from __future__ import annotations

import base64
import hashlib
import os
import yaml
from dataclasses import dataclass, asdict, replace
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

CONFIG_PATH = Path("/etc/boombox/library.yml")
_MACHINE_ID_PATH = Path("/etc/machine-id")
_KEY_SALT = b"boombox-library-v1"


@dataclass(frozen=True)
class SourceConfig:
    url: str = ""
    username: str = ""
    password: str = ""  # plaintext in-memory; encrypted on disk


@dataclass(frozen=True)
class SyncConfig:
    interval_seconds: int = 3600
    starred_auto_pin: bool = True
    max_concurrent_downloads: int = 2


@dataclass(frozen=True)
class CacheConfig:
    marker_filename: str = ".boombox-cache"
    search_paths: tuple = ("/media",)
    reserve_bytes: int = 1_073_741_824  # 1 GB


@dataclass(frozen=True)
class LibraryConfig:
    source: SourceConfig
    sync: SyncConfig
    cache: CacheConfig


DEFAULT_CONFIG = LibraryConfig(
    source=SourceConfig(),
    sync=SyncConfig(),
    cache=CacheConfig(),
)


def _machine_id() -> str:
    """Read /etc/machine-id; falls back to a known dev string if absent
    (e.g., running tests on macOS). Monkeypatched in tests."""
    try:
        return _MACHINE_ID_PATH.read_text().strip()
    except OSError:
        return "00000000000000000000000000000000"


def _derive_key() -> bytes:
    """Derive a 32-byte Fernet key from machine-id + a fixed salt.

    Stable across reboots on the same machine; different across machines.
    """
    mid = _machine_id().encode("utf-8")
    digest = hashlib.sha256(_KEY_SALT + mid).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt_password(plain: str) -> str:
    if not plain:
        return ""
    f = Fernet(_derive_key())
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt_password(token: str) -> str:
    if not token:
        return ""
    f = Fernet(_derive_key())
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Wrong machine, corrupt token — treat as empty (forces re-entry).
        return ""


def load_config(path: Path = CONFIG_PATH) -> LibraryConfig:
    if not path.exists():
        return DEFAULT_CONFIG
    raw = yaml.safe_load(path.read_text()) or {}

    src = raw.get("source", {})
    source = SourceConfig(
        url=src.get("url", ""),
        username=src.get("username", ""),
        password=_decrypt_password(src.get("password_encrypted", "")),
    )

    sy = raw.get("sync", {})
    sync = SyncConfig(
        interval_seconds=int(sy.get("interval_seconds", 3600)),
        starred_auto_pin=bool(sy.get("starred_auto_pin", True)),
        max_concurrent_downloads=int(sy.get("max_concurrent_downloads", 2)),
    )

    ca = raw.get("cache", {})
    cache = CacheConfig(
        marker_filename=ca.get("marker_filename", ".boombox-cache"),
        search_paths=tuple(ca.get("search_paths", ["/media"])),
        reserve_bytes=int(ca.get("reserve_bytes", 1_073_741_824)),
    )

    return LibraryConfig(source=source, sync=sync, cache=cache)


def save_config(cfg: LibraryConfig, path: Path = CONFIG_PATH) -> None:
    out = {
        "source": {
            "url": cfg.source.url,
            "username": cfg.source.username,
            "password_encrypted": _encrypt_password(cfg.source.password),
        },
        "sync": {
            "interval_seconds": cfg.sync.interval_seconds,
            "starred_auto_pin": cfg.sync.starred_auto_pin,
            "max_concurrent_downloads": cfg.sync.max_concurrent_downloads,
        },
        "cache": {
            "marker_filename": cfg.cache.marker_filename,
            "search_paths": list(cfg.cache.search_paths),
            "reserve_bytes": cfg.cache.reserve_bytes,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(out, sort_keys=False))
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pip install PyYAML cryptography  # if not already installed in dev
pytest services/tests/test_library_config.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/config.py services/tests/test_library_config.py
git commit -m "feat(library): YAML config with Fernet-encrypted password at rest"
```

---

### Task 5: SQLite schema + migrations

**Files:**
- Create: `services/boombox_library/models.py`
- Create: `services/boombox_library/db.py`
- Create: `services/tests/test_library_db.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_db.py`:

```python
"""Tests for boombox_library.db — schema, migrations, FTS5 setup."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from boombox_library.db import connect, migrate, SCHEMA_VERSION


def test_migrate_creates_all_tables(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {"artists", "albums", "tracks", "playlists",
                "playlist_tracks", "pins", "cache_state",
                "search_index", "search_index_data",
                "search_index_idx", "search_index_content",
                "search_index_docsize", "search_index_config",
                "_schema_version"}
    assert expected.issubset(tables)


def test_migrate_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    migrate(conn)  # second time must not error
    v = conn.execute("SELECT version FROM _schema_version").fetchone()[0]
    assert v == SCHEMA_VERSION


def test_fts5_search_round_trip(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("album", "abc123", "Back in Black", "AC/DC Back in Black 1980 rock"),
    )
    conn.commit()
    rows = list(conn.execute(
        "SELECT id FROM search_index WHERE search_index MATCH 'back'"
    ))
    assert len(rows) == 1
    assert rows[0][0] == "abc123"


def test_foreign_keys_enabled(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_db.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement models + db**

Create `services/boombox_library/models.py`:

```python
"""Frozen dataclasses for catalog entities, pins, and cache state.

These are the in-memory shape used by the rest of the service. SQLite
rows are mapped to and from these via simple helpers in db.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Artist:
    id: str
    name: str
    sort_name: str
    album_count: int
    art_id: Optional[str]


@dataclass(frozen=True)
class Album:
    id: str
    name: str
    sort_name: str
    artist_id: str
    year: Optional[int]
    genre: Optional[str]
    song_count: int
    duration_s: int
    art_id: Optional[str]
    is_compilation: bool
    navidrome_starred: bool


@dataclass(frozen=True)
class Track:
    id: str
    album_id: str
    title: str
    track_no: Optional[int]
    disc_no: Optional[int]
    duration_s: int
    suffix: str               # e.g. "mp3", "flac"
    size_bytes: int
    content_type: str         # e.g. "audio/mpeg"
    navidrome_starred: bool


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    song_count: int
    owner: str
    public: bool


class PinKind(str, Enum):
    ALBUM = "album"
    ARTIST = "artist"
    PLAYLIST = "playlist"
    TRACK = "track"


class PinSource(str, Enum):
    USER = "user"
    STARRED = "starred"
    RFID = "rfid"


@dataclass(frozen=True)
class Pin:
    target_kind: PinKind
    target_id: str
    source: PinSource
    added_at: float


class CacheStatus(str, Enum):
    ABSENT = "absent"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PRESENT = "present"
    ERROR = "error"


@dataclass(frozen=True)
class CacheEntry:
    track_id: str
    status: CacheStatus
    local_path: Optional[str]
    size_bytes: Optional[int]
    downloaded_at: Optional[float]
    error_message: Optional[str]
```

Create `services/boombox_library/db.py`:

```python
"""SQLite connection + schema migrations for boombox-library.

The catalog DB lives at /opt/boombox/state/library.db on production;
tests use tempdirs. FTS5 is built-in to SQLite (>= 3.9 with extension);
we rely on the system sqlite shipped with Python 3.11+ on Debian/Ubuntu.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("boombox-library.db")

SCHEMA_VERSION = 1


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with sane defaults: foreign keys ON, WAL mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,  # autocommit; we use explicit BEGIN where needed
        check_same_thread=False,
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


_MIGRATIONS = [
    # v1 — initial schema
    """
    CREATE TABLE IF NOT EXISTS _schema_version (
        version INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS artists (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        sort_name    TEXT NOT NULL,
        album_count  INTEGER NOT NULL DEFAULT 0,
        art_id       TEXT,
        updated_at   REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS albums (
        id                TEXT PRIMARY KEY,
        name              TEXT NOT NULL,
        sort_name         TEXT NOT NULL,
        artist_id         TEXT NOT NULL,
        year              INTEGER,
        genre             TEXT,
        song_count        INTEGER NOT NULL DEFAULT 0,
        duration_s        INTEGER NOT NULL DEFAULT 0,
        art_id            TEXT,
        is_compilation    INTEGER NOT NULL DEFAULT 0,
        navidrome_starred INTEGER NOT NULL DEFAULT 0,
        updated_at        REAL NOT NULL,
        FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_albums_artist ON albums(artist_id);

    CREATE TABLE IF NOT EXISTS tracks (
        id                TEXT PRIMARY KEY,
        album_id          TEXT NOT NULL,
        title             TEXT NOT NULL,
        track_no          INTEGER,
        disc_no           INTEGER,
        duration_s        INTEGER NOT NULL DEFAULT 0,
        suffix            TEXT NOT NULL DEFAULT '',
        size_bytes        INTEGER NOT NULL DEFAULT 0,
        content_type      TEXT NOT NULL DEFAULT '',
        navidrome_starred INTEGER NOT NULL DEFAULT 0,
        updated_at        REAL NOT NULL,
        FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_id);

    CREATE TABLE IF NOT EXISTS playlists (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        song_count  INTEGER NOT NULL DEFAULT 0,
        owner       TEXT NOT NULL DEFAULT '',
        public      INTEGER NOT NULL DEFAULT 0,
        updated_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS playlist_tracks (
        playlist_id TEXT NOT NULL,
        track_id    TEXT NOT NULL,
        position    INTEGER NOT NULL,
        PRIMARY KEY (playlist_id, position),
        FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);

    CREATE TABLE IF NOT EXISTS pins (
        target_kind TEXT NOT NULL,
        target_id   TEXT NOT NULL,
        source      TEXT NOT NULL,
        added_at    REAL NOT NULL,
        PRIMARY KEY (target_kind, target_id)
    );

    CREATE TABLE IF NOT EXISTS cache_state (
        track_id       TEXT PRIMARY KEY,
        status         TEXT NOT NULL,
        local_path     TEXT,
        size_bytes     INTEGER,
        downloaded_at  REAL,
        error_message  TEXT
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
        content_type, id UNINDEXED, title, body
    );
    """,
]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any missing schema migrations. Idempotent."""
    current = 0
    try:
        row = conn.execute("SELECT version FROM _schema_version").fetchone()
        if row:
            current = row[0]
    except sqlite3.OperationalError:
        current = 0

    for i, ddl in enumerate(_MIGRATIONS, start=1):
        if i <= current:
            continue
        log.info("applying schema migration %d", i)
        conn.executescript(ddl)
        conn.execute("DELETE FROM _schema_version")
        conn.execute("INSERT INTO _schema_version(version) VALUES (?)", (i,))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_db.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/models.py services/boombox_library/db.py services/tests/test_library_db.py
git commit -m "feat(library): SQLite schema with FTS5 search index"
```

---

### Task 6: Catalog full sync (Subsonic → SQLite)

**Files:**
- Create: `services/boombox_library/catalog.py`
- Create: `services/tests/test_library_catalog.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_catalog.py`:

```python
"""Tests for boombox_library.catalog — full + delta sync."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from boombox_library.catalog import sync_full
from boombox_library.db import connect, migrate


class FakeSubsonic:
    def __init__(self, artists, albums, tracks_per_album, starred=None, playlists=None):
        self._artists = artists
        self._albums = albums
        self._tracks = tracks_per_album  # {album_id: [track,...]}
        self._starred = starred or {"album": [], "song": [], "artist": []}
        self._playlists = playlists or []

    async def get_artists(self):
        return self._artists

    async def get_album_list(self, offset=0, size=500):
        return self._albums[offset:offset + size]

    async def get_album(self, album_id):
        tracks = self._tracks.get(album_id, [])
        return {"id": album_id, "song": tracks}

    async def get_starred(self):
        return self._starred

    async def get_playlists(self):
        return self._playlists


@pytest.mark.asyncio
async def test_sync_full_populates_catalog(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "ABBA", "albumCount": 1}],
        albums=[{"id": "al1", "name": "Arrival",
                 "artistId": "ar1", "year": 1976,
                 "songCount": 2, "duration": 100, "isCompilation": False}],
        tracks_per_album={"al1": [
            {"id": "t1", "title": "Dancing Queen", "track": 1,
             "duration": 60, "suffix": "mp3", "size": 1_000_000,
             "contentType": "audio/mpeg"},
            {"id": "t2", "title": "Money Money Money", "track": 2,
             "duration": 40, "suffix": "mp3", "size": 700_000,
             "contentType": "audio/mpeg"},
        ]},
    )
    await sync_full(client, db)

    assert db.execute("SELECT COUNT(*) FROM artists").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 2

    # FTS5 should also be populated
    rows = list(db.execute(
        "SELECT id FROM search_index WHERE search_index MATCH 'abba'"
    ))
    assert any(r[0] == "ar1" for r in rows)


@pytest.mark.asyncio
async def test_sync_full_idempotent(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 0}],
        albums=[],
        tracks_per_album={},
    )
    await sync_full(client, db)
    await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM artists").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_sync_full_marks_starred(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 1}],
        albums=[{"id": "al1", "name": "A", "artistId": "ar1",
                 "songCount": 1, "duration": 30}],
        tracks_per_album={"al1": [
            {"id": "t1", "title": "T", "duration": 30, "suffix": "mp3",
             "size": 100, "contentType": "audio/mpeg"},
        ]},
        starred={"album": [{"id": "al1"}], "song": [{"id": "t1"}], "artist": []},
    )
    await sync_full(client, db)
    starred_album = db.execute(
        "SELECT navidrome_starred FROM albums WHERE id='al1'"
    ).fetchone()[0]
    starred_track = db.execute(
        "SELECT navidrome_starred FROM tracks WHERE id='t1'"
    ).fetchone()[0]
    assert starred_album == 1
    assert starred_track == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_catalog.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement catalog sync**

Create `services/boombox_library/catalog.py`:

```python
"""Catalog sync — pull Navidrome's Subsonic state into the local SQLite
cache. Full sync iterates the catalog from scratch (used on first boot
or after corruption recovery). Incremental sync (Task 7) is the steady
state.

Sync is upsert-based and keeps the FTS5 search index in lockstep.
"""
from __future__ import annotations

import logging
import time
from sqlite3 import Connection
from typing import Protocol

log = logging.getLogger("boombox-library.catalog")

_ALBUM_PAGE_SIZE = 500


class SubsonicProto(Protocol):
    async def get_artists(self) -> list[dict]: ...
    async def get_album_list(self, offset: int = 0, size: int = 500) -> list[dict]: ...
    async def get_album(self, album_id: str) -> dict: ...
    async def get_starred(self) -> dict: ...
    async def get_playlists(self) -> list[dict]: ...


def _upsert_artist(conn: Connection, a: dict, now: float) -> None:
    conn.execute(
        """INSERT INTO artists(id, name, sort_name, album_count, art_id, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name,
             sort_name=excluded.sort_name,
             album_count=excluded.album_count,
             art_id=excluded.art_id,
             updated_at=excluded.updated_at""",
        (a["id"], a["name"], a.get("sortName", a["name"]).lower(),
         int(a.get("albumCount", 0)), a.get("coverArt"), now),
    )
    # FTS index for artist
    conn.execute("DELETE FROM search_index WHERE content_type='artist' AND id=?",
                 (a["id"],))
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("artist", a["id"], a["name"], a["name"]),
    )


def _upsert_album(conn: Connection, al: dict, now: float, starred_ids: set[str]) -> None:
    conn.execute(
        """INSERT INTO albums(id, name, sort_name, artist_id, year, genre,
                              song_count, duration_s, art_id,
                              is_compilation, navidrome_starred, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name,
             sort_name=excluded.sort_name,
             artist_id=excluded.artist_id,
             year=excluded.year,
             genre=excluded.genre,
             song_count=excluded.song_count,
             duration_s=excluded.duration_s,
             art_id=excluded.art_id,
             is_compilation=excluded.is_compilation,
             navidrome_starred=excluded.navidrome_starred,
             updated_at=excluded.updated_at""",
        (al["id"], al.get("name", ""),
         al.get("sortName", al.get("name", "")).lower(),
         al.get("artistId", ""), al.get("year"), al.get("genre"),
         int(al.get("songCount", 0)), int(al.get("duration", 0)),
         al.get("coverArt"), 1 if al.get("isCompilation") else 0,
         1 if al["id"] in starred_ids else 0, now),
    )
    body = " ".join(filter(None, [al.get("name"), al.get("artist"),
                                   str(al.get("year") or ""), al.get("genre")]))
    conn.execute("DELETE FROM search_index WHERE content_type='album' AND id=?",
                 (al["id"],))
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("album", al["id"], al.get("name", ""), body),
    )


def _upsert_track(conn: Connection, tr: dict, album_id: str, now: float,
                  starred_ids: set[str]) -> None:
    conn.execute(
        """INSERT INTO tracks(id, album_id, title, track_no, disc_no,
                              duration_s, suffix, size_bytes, content_type,
                              navidrome_starred, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             album_id=excluded.album_id,
             title=excluded.title,
             track_no=excluded.track_no,
             disc_no=excluded.disc_no,
             duration_s=excluded.duration_s,
             suffix=excluded.suffix,
             size_bytes=excluded.size_bytes,
             content_type=excluded.content_type,
             navidrome_starred=excluded.navidrome_starred,
             updated_at=excluded.updated_at""",
        (tr["id"], album_id, tr.get("title", ""),
         tr.get("track"), tr.get("discNumber"),
         int(tr.get("duration", 0)), tr.get("suffix", ""),
         int(tr.get("size", 0)), tr.get("contentType", ""),
         1 if tr["id"] in starred_ids else 0, now),
    )
    conn.execute("DELETE FROM search_index WHERE content_type='track' AND id=?",
                 (tr["id"],))
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("track", tr["id"], tr.get("title", ""), tr.get("title", "")),
    )


def _upsert_playlist(conn: Connection, pl: dict, now: float) -> None:
    conn.execute(
        """INSERT INTO playlists(id, name, song_count, owner, public, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name,
             song_count=excluded.song_count,
             owner=excluded.owner,
             public=excluded.public,
             updated_at=excluded.updated_at""",
        (pl["id"], pl.get("name", ""), int(pl.get("songCount", 0)),
         pl.get("owner", ""), 1 if pl.get("public") else 0, now),
    )


async def sync_full(client: SubsonicProto, conn: Connection) -> dict:
    """Full sync — pulls all artists/albums/tracks/playlists from Navidrome.
    Returns counts dict. Idempotent (upserts)."""
    now = time.time()
    starred = await client.get_starred()
    starred_album_ids = {a["id"] for a in starred.get("album", [])}
    starred_song_ids = {s["id"] for s in starred.get("song", [])}

    conn.execute("BEGIN")
    try:
        artists = await client.get_artists()
        for a in artists:
            _upsert_artist(conn, a, now)

        # Albums: paginated
        offset = 0
        album_count = 0
        all_album_ids: list[str] = []
        while True:
            page = await client.get_album_list(offset=offset, size=_ALBUM_PAGE_SIZE)
            if not page:
                break
            for al in page:
                _upsert_album(conn, al, now, starred_album_ids)
                all_album_ids.append(al["id"])
            album_count += len(page)
            if len(page) < _ALBUM_PAGE_SIZE:
                break
            offset += _ALBUM_PAGE_SIZE

        # Tracks: one getAlbum per album (Subsonic shape).
        track_count = 0
        for aid in all_album_ids:
            detail = await client.get_album(aid)
            for tr in detail.get("song", []):
                _upsert_track(conn, tr, aid, now, starred_song_ids)
                track_count += 1

        playlists = await client.get_playlists()
        for pl in playlists:
            _upsert_playlist(conn, pl, now)

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    log.info("sync_full done: %d artists, %d albums, %d tracks, %d playlists",
             len(artists), album_count, track_count, len(playlists))
    return {"artists": len(artists), "albums": album_count,
            "tracks": track_count, "playlists": len(playlists)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_catalog.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/catalog.py services/tests/test_library_catalog.py
git commit -m "feat(library): full catalog sync from Subsonic into SQLite + FTS5"
```

---

### Task 7: Pin manager (pin/unpin, cascade, starred reconciliation, sidecar)

**Files:**
- Create: `services/boombox_library/pins.py`
- Create: `services/tests/test_library_pins.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_pins.py`:

```python
"""Tests for boombox_library.pins — pin/unpin, cascade, reconciliation, sidecar."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from boombox_library.db import connect, migrate
from boombox_library.models import PinKind, PinSource
from boombox_library.pins import (
    expand_pin_to_tracks,
    pin,
    unpin,
    reconcile_starred,
    write_sidecar,
    load_sidecar,
)


def _seed_album(conn, album_id="al1", artist_id="ar1", track_ids=("t1", "t2")):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES (?,?,?,?,?)", (artist_id, "X", "x", 1, 0.0))
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (album_id, "A", "a", artist_id, len(track_ids), 100, 0, 0, 0.0))
    for tid in track_ids:
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                     "size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (tid, album_id, "T", 50, "mp3", 500_000, "audio/mpeg", 0, 0.0))


def test_expand_album_pin_to_tracks(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    tids = expand_pin_to_tracks(conn, PinKind.ALBUM, "al1")
    assert set(tids) == {"t1", "t2"}


def test_expand_artist_pin_to_tracks(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn, album_id="al1", artist_id="ar1", track_ids=("t1",))
    _seed_album(conn, album_id="al2", artist_id="ar1", track_ids=("t2", "t3"))
    tids = expand_pin_to_tracks(conn, PinKind.ARTIST, "ar1")
    assert set(tids) == {"t1", "t2", "t3"}


def test_pin_inserts_and_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)  # same again, no-op
    rows = list(conn.execute("SELECT * FROM pins"))
    assert len(rows) == 1


def test_unpin_removes(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    unpin(conn, PinKind.ALBUM, "al1")
    assert list(conn.execute("SELECT * FROM pins")) == []


def test_reconcile_starred_adds_pin_when_album_starred(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    conn.execute("UPDATE albums SET navidrome_starred=1 WHERE id='al1'")
    reconcile_starred(conn)
    pins_rows = list(conn.execute(
        "SELECT target_kind, target_id, source FROM pins"))
    assert ("album", "al1", "starred") in [tuple(r) for r in pins_rows]


def test_reconcile_starred_does_not_remove_user_pin_when_unstarred(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    # User pinned it; then it was un-starred upstream (or never starred).
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    conn.execute("UPDATE albums SET navidrome_starred=0 WHERE id='al1'")
    reconcile_starred(conn)
    pins_rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert pins_rows[0][0] == "user"  # user pin survives


def test_reconcile_removes_starred_pin_when_unstarred(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    conn.execute("UPDATE albums SET navidrome_starred=1 WHERE id='al1'")
    reconcile_starred(conn)
    # Then it gets un-starred upstream.
    conn.execute("UPDATE albums SET navidrome_starred=0 WHERE id='al1'")
    reconcile_starred(conn)
    assert list(conn.execute("SELECT * FROM pins")) == []


def test_sidecar_round_trip(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    sidecar = tmp_path / "pins.json"
    write_sidecar(conn, sidecar)
    text = sidecar.read_text()
    assert "al1" in text and "album" in text and "user" in text

    # Clear pins, load from sidecar
    conn.execute("DELETE FROM pins")
    load_sidecar(conn, sidecar)
    rows = list(conn.execute("SELECT target_id, source FROM pins"))
    assert rows[0]["target_id"] == "al1"
    assert rows[0]["source"] == "user"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_pins.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement pins module**

Create `services/boombox_library/pins.py`:

```python
"""Pin manager — pin/unpin, cascade rules, starred reconciliation,
write-ahead JSON sidecar.

Pin semantics:
- Pin an album    → track-level downloads are scheduled for its tracks.
                    The `pins` row is at the album level; tracks are not
                    individually pinned in the DB. expand_pin_to_tracks()
                    is the resolver.
- Pin an artist   → snapshot of the artist's *current* albums; new
                    releases later are NOT auto-pinned.
- Pin a playlist  → its constituent tracks are scheduled.
- Pin a track     → just that track.

A track is "pinned-protected" (cache-wise) iff any pin row resolves to it.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from sqlite3 import Connection

from .models import PinKind, PinSource


def expand_pin_to_tracks(conn: Connection, kind: PinKind, target_id: str) -> list[str]:
    """Return the list of track IDs that a pin resolves to."""
    if kind == PinKind.TRACK:
        return [target_id]
    if kind == PinKind.ALBUM:
        return [r[0] for r in conn.execute(
            "SELECT id FROM tracks WHERE album_id=?", (target_id,))]
    if kind == PinKind.ARTIST:
        return [r[0] for r in conn.execute(
            "SELECT t.id FROM tracks t "
            "JOIN albums a ON a.id = t.album_id "
            "WHERE a.artist_id=?", (target_id,))]
    if kind == PinKind.PLAYLIST:
        return [r[0] for r in conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id=? "
            "ORDER BY position", (target_id,))]
    raise ValueError(f"unknown PinKind {kind}")


def pin(conn: Connection, kind: PinKind, target_id: str, source: PinSource) -> None:
    """Insert a pin row; no-op if one already exists for (kind, target_id)."""
    conn.execute(
        """INSERT INTO pins(target_kind, target_id, source, added_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(target_kind, target_id) DO NOTHING""",
        (kind.value, target_id, source.value, time.time()),
    )


def unpin(conn: Connection, kind: PinKind, target_id: str) -> None:
    conn.execute(
        "DELETE FROM pins WHERE target_kind=? AND target_id=?",
        (kind.value, target_id),
    )


def all_pinned_track_ids(conn: Connection) -> set[str]:
    """Union of every track ID protected by any pin."""
    out: set[str] = set()
    for row in conn.execute("SELECT target_kind, target_id FROM pins"):
        out.update(expand_pin_to_tracks(conn, PinKind(row[0]), row[1]))
    return out


def reconcile_starred(conn: Connection) -> None:
    """Two-way reconcile between Navidrome's starred state and pins.source='starred'.

    - For each album/artist/track marked navidrome_starred=1, INSERT a
      starred-source pin (no-op if any pin already exists).
    - For each starred-source pin whose target is no longer starred,
      DELETE the pin. User/RFID-source pins are untouched.
    """
    # Add starred pins for currently starred items
    for row in conn.execute("SELECT id FROM albums WHERE navidrome_starred=1"):
        pin(conn, PinKind.ALBUM, row[0], PinSource.STARRED)
    for row in conn.execute("SELECT id FROM tracks WHERE navidrome_starred=1"):
        pin(conn, PinKind.TRACK, row[0], PinSource.STARRED)
    # (Subsonic also reports starred artists; we represent these as artist pins.)
    # No artists table column for starred yet — Subsonic-side starred artists
    # arrive via reconcile path in catalog.sync_full's getStarred; for v1 we
    # do NOT auto-pin starred artists (they pull in an artist's whole catalog,
    # which is rarely what the user means by "starred"). Documented decision.

    # Remove starred-source pins whose target lost its star
    conn.execute("""
        DELETE FROM pins
        WHERE source='starred'
          AND target_kind='album'
          AND target_id NOT IN (SELECT id FROM albums WHERE navidrome_starred=1)
    """)
    conn.execute("""
        DELETE FROM pins
        WHERE source='starred'
          AND target_kind='track'
          AND target_id NOT IN (SELECT id FROM tracks WHERE navidrome_starred=1)
    """)


def write_sidecar(conn: Connection, path: Path) -> None:
    """Write pins to a JSON sidecar (write-ahead) — survives SQLite corruption."""
    pins_list = [dict(r) for r in conn.execute(
        "SELECT target_kind, target_id, source, added_at FROM pins")]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "pins": pins_list},
                              indent=2, sort_keys=True))
    os.replace(tmp, path)


def load_sidecar(conn: Connection, path: Path) -> int:
    """Load pins from sidecar into an empty DB. Returns count loaded.
    No-op if sidecar missing. Skips entries whose target_kind is unknown."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    loaded = 0
    for p in data.get("pins", []):
        try:
            kind = PinKind(p["target_kind"])
            src = PinSource(p["source"])
        except ValueError:
            continue
        conn.execute(
            """INSERT INTO pins(target_kind, target_id, source, added_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(target_kind, target_id) DO NOTHING""",
            (kind.value, p["target_id"], src.value, float(p.get("added_at", 0))),
        )
        loaded += 1
    return loaded
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_pins.py -v
```

Expected: all 8 pass.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/pins.py services/tests/test_library_pins.py
git commit -m "feat(library): pin manager with cascade, starred reconcile, JSON sidecar"
```

---

### Task 8: Cache drive detection (marker file + symlink management)

**Files:**
- Create: `services/boombox_library/cache_drive.py`
- Create: `services/tests/test_library_cache_drive.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_cache_drive.py`:

```python
"""Tests for boombox_library.cache_drive — marker detection + symlink mgmt."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.cache_drive import (
    CacheDriveState,
    detect_cache_drive,
    adopt_drive,
    update_symlink,
    remove_symlink,
)


def _make_drive(parent: Path, name: str, has_marker: bool, marker=".boombox-cache") -> Path:
    d = parent / name
    d.mkdir()
    if has_marker:
        (d / marker).touch()
    return d


def test_detect_no_drives(tmp_path: Path):
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    assert state.mount_path is None
    assert state.present is False


def test_detect_ignores_drives_without_marker(tmp_path: Path):
    _make_drive(tmp_path, "ad-hoc-1", has_marker=False)
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    assert state.present is False


def test_detect_picks_drive_with_marker(tmp_path: Path):
    d = _make_drive(tmp_path, "cache", has_marker=True)
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    assert state.present is True
    assert state.mount_path == d


def test_detect_first_wins_on_multiple_markers(tmp_path: Path):
    a = _make_drive(tmp_path, "a-cache", has_marker=True)
    b = _make_drive(tmp_path, "b-cache", has_marker=True)
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    # Sorted iteration → "a-cache" wins
    assert state.mount_path == a


def test_adopt_drive_writes_marker(tmp_path: Path):
    d = _make_drive(tmp_path, "fresh", has_marker=False)
    adopt_drive(d, marker=".boombox-cache")
    assert (d / ".boombox-cache").exists()


def test_adopt_creates_required_subdirs(tmp_path: Path):
    d = _make_drive(tmp_path, "fresh", has_marker=False)
    adopt_drive(d, marker=".boombox-cache")
    assert (d / "audio").is_dir()
    assert (d / "meta").is_dir()
    assert (d / "tmp").is_dir()


def test_update_symlink_creates_then_swaps(tmp_path: Path):
    d1 = _make_drive(tmp_path, "drive-a", has_marker=True)
    d2 = _make_drive(tmp_path, "drive-b", has_marker=True)
    sym = tmp_path / "cache-mount"
    update_symlink(sym, target=d1)
    assert sym.is_symlink() and sym.resolve() == d1
    update_symlink(sym, target=d2)
    assert sym.is_symlink() and sym.resolve() == d2


def test_remove_symlink_idempotent(tmp_path: Path):
    sym = tmp_path / "cache-mount"
    remove_symlink(sym)  # no-op
    sym.symlink_to(tmp_path)
    remove_symlink(sym)
    assert not sym.exists() and not sym.is_symlink()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_cache_drive.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement cache_drive module**

Create `services/boombox_library/cache_drive.py`:

```python
"""USB cache drive detection and symlink management.

A USB drive is treated as the boombox's audio cache drive iff it carries
a marker file at its root (default ".boombox-cache"). The service polls
the configured search paths (default /media) and adopts the first
matching mount, creating the required subdirs and updating a stable
symlink so Mopidy-Local can always read from /opt/boombox/cache-mount/audio.

This module is filesystem-side only — async behavior (poll loop) lives
in the service entry point.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("boombox-library.cache_drive")

DEFAULT_SYMLINK = Path("/opt/boombox/cache-mount")
_REQUIRED_SUBDIRS = ("audio", "meta", "tmp")


@dataclass(frozen=True)
class CacheDriveState:
    present: bool
    mount_path: Optional[Path]
    free_bytes: Optional[int]
    total_bytes: Optional[int]


def detect_cache_drive(
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> CacheDriveState:
    """Scan search paths for a directory containing the marker file. First
    one (sorted) wins. Returns CacheDriveState(present=False, ...) if none."""
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
                free, total = _disk_usage(child)
                return CacheDriveState(
                    present=True,
                    mount_path=child,
                    free_bytes=free,
                    total_bytes=total,
                )
    return CacheDriveState(present=False, mount_path=None,
                           free_bytes=None, total_bytes=None)


def _disk_usage(path: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        stat = os.statvfs(path)
        free = stat.f_bavail * stat.f_frsize
        total = stat.f_blocks * stat.f_frsize
        return free, total
    except OSError:
        return None, None


def adopt_drive(mount_path: Path, marker: str = ".boombox-cache") -> None:
    """Bless a USB drive as the cache drive: write marker + create subdirs."""
    (mount_path / marker).touch(exist_ok=True)
    for sub in _REQUIRED_SUBDIRS:
        (mount_path / sub).mkdir(exist_ok=True)


def update_symlink(symlink_path: Path, target: Path) -> None:
    """Atomically update symlink_path to point at target. Replaces any
    existing symlink. Uses os.symlink + os.replace via a temp symlink."""
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = symlink_path.with_suffix(symlink_path.suffix + ".tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, symlink_path)


def remove_symlink(symlink_path: Path) -> None:
    """Remove the symlink if it exists. Idempotent."""
    try:
        if symlink_path.is_symlink() or symlink_path.exists():
            symlink_path.unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_cache_drive.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/cache_drive.py services/tests/test_library_cache_drive.py
git commit -m "feat(library): cache drive detection via marker + symlink management"
```

---

### Task 9: Downloader (single track, atomic write, retry)

**Files:**
- Create: `services/boombox_library/downloader.py`
- Create: `services/tests/test_library_downloader.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_downloader.py`:

```python
"""Tests for boombox_library.downloader — single track + queue + concurrency."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from boombox_library.db import connect, migrate
from boombox_library.downloader import download_track, DownloadResult


class FakeStreamingClient:
    """Stand-in for SubsonicClient that yields fixed bytes for download.

    Calling download_url returns the (url, params); the fake session.get
    yields a streaming response with the configured bytes.
    """
    def __init__(self, payload: bytes, suffix: str = "mp3"):
        self.payload = payload
        self.suffix = suffix
        self.calls: list[str] = []

    def download_url(self, track_id: str):
        return (f"http://nav/{track_id}", {})


@pytest.mark.asyncio
async def test_download_track_writes_file_atomically(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")

    payload = b"hello"
    client = FakeStreamingClient(payload)
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    # Mock the HTTP fetch
    async def fake_fetch(url, params, dest):
        dest.write_bytes(payload)

    result = await download_track(
        conn=conn,
        client=client,
        track_id="t1",
        cache_root=cache_root,
        fetch=fake_fetch,
    )
    assert result == DownloadResult.OK
    target = cache_root / "audio" / "t1.mp3"
    assert target.read_bytes() == payload
    assert not (cache_root / "tmp" / "t1.part").exists()

    row = conn.execute("SELECT status, size_bytes, local_path FROM cache_state "
                       "WHERE track_id='t1'").fetchone()
    assert row["status"] == "present"
    assert row["size_bytes"] == len(payload)
    assert row["local_path"] == str(target)


@pytest.mark.asyncio
async def test_download_track_marks_error_on_fetch_failure(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")
    client = FakeStreamingClient(b"")
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    async def boom(*args, **kwargs):
        raise IOError("nope")

    result = await download_track(
        conn=conn, client=client, track_id="t1",
        cache_root=cache_root, fetch=boom,
    )
    assert result == DownloadResult.ERROR
    row = conn.execute("SELECT status, error_message FROM cache_state "
                       "WHERE track_id='t1'").fetchone()
    assert row["status"] == "error"
    assert "nope" in row["error_message"]
    # Partial file must not be left behind
    assert not (cache_root / "tmp" / "t1.part").exists()


@pytest.mark.asyncio
async def test_download_skips_if_already_present(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    target = cache_root / "audio" / "t1.mp3"
    target.write_bytes(b"existing")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present',?, 8, 0)", (str(target),))

    called = {"n": 0}
    async def fetch(*a, **k):
        called["n"] += 1

    client = FakeStreamingClient(b"new")
    result = await download_track(
        conn=conn, client=client, track_id="t1",
        cache_root=cache_root, fetch=fetch,
    )
    assert result == DownloadResult.SKIPPED
    assert called["n"] == 0
    assert target.read_bytes() == b"existing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_downloader.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement downloader (single-track)**

Create `services/boombox_library/downloader.py`:

```python
"""Audio file downloader for boombox-library.

download_track() handles one track end-to-end: stream from Subsonic to
a .part tmp file, atomically rename to final, update cache_state. The
fetch coroutine is injected to keep network out of unit tests; the real
implementation uses aiohttp streaming.

The queue + concurrency layer (Task 10) wraps this.
"""
from __future__ import annotations

import enum
import logging
import os
import time
from pathlib import Path
from sqlite3 import Connection
from typing import Awaitable, Callable, Protocol

import aiohttp

log = logging.getLogger("boombox-library.downloader")


class DownloadResult(str, enum.Enum):
    OK = "ok"
    SKIPPED = "skipped"  # already present
    ERROR = "error"


class StreamingClient(Protocol):
    def download_url(self, track_id: str) -> tuple[str, dict]: ...


Fetcher = Callable[[str, dict, Path], Awaitable[None]]
"""(url, params, dest_path) → writes bytes to dest_path."""


async def default_fetch(url: str, params: dict, dest: Path) -> None:
    """Real aiohttp streaming fetch. Raises on non-2xx."""
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)


async def download_track(
    conn: Connection,
    client: StreamingClient,
    track_id: str,
    cache_root: Path,
    fetch: Fetcher = default_fetch,
) -> DownloadResult:
    """Download one track into cache_root/audio/<id>.<suffix> atomically.

    cache_root must contain pre-existing audio/ and tmp/ subdirs (caller's
    responsibility — usually adopt_drive() has created them).
    """
    # Skip if already present
    row = conn.execute(
        "SELECT status FROM cache_state WHERE track_id=?", (track_id,)
    ).fetchone()
    if row and row["status"] == "present":
        return DownloadResult.SKIPPED

    # Look up track metadata
    trow = conn.execute(
        "SELECT suffix, size_bytes FROM tracks WHERE id=?", (track_id,)
    ).fetchone()
    if trow is None:
        log.error("track %s not in catalog; skipping", track_id)
        return DownloadResult.ERROR
    suffix = trow["suffix"] or "bin"

    tmp_path = cache_root / "tmp" / f"{track_id}.part"
    final_path = cache_root / "audio" / f"{track_id}.{suffix}"

    # Mark downloading
    conn.execute(
        """INSERT INTO cache_state(track_id, status, downloaded_at)
           VALUES (?, 'downloading', ?)
           ON CONFLICT(track_id) DO UPDATE SET status='downloading',
                                                error_message=NULL""",
        (track_id, time.time()),
    )

    url, params = client.download_url(track_id)
    try:
        if tmp_path.exists():
            tmp_path.unlink()
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
    except Exception as e:
        # Clean up partial file
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        conn.execute(
            """INSERT INTO cache_state(track_id, status, error_message)
               VALUES (?, 'error', ?)
               ON CONFLICT(track_id) DO UPDATE SET
                  status='error', error_message=excluded.error_message""",
            (track_id, str(e)),
        )
        log.warning("download of %s failed: %s", track_id, e)
        return DownloadResult.ERROR
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_downloader.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/downloader.py services/tests/test_library_downloader.py
git commit -m "feat(library): single-track downloader with atomic write + error tracking"
```

---

### Task 10: Download queue + concurrent workers

**Files:**
- Modify: `services/boombox_library/downloader.py`
- Modify: `services/tests/test_library_downloader.py`

- [ ] **Step 1: Write failing tests for queue + concurrency**

Append to `services/tests/test_library_downloader.py`:

```python
@pytest.mark.asyncio
async def test_queue_respects_concurrency_limit(tmp_path: Path):
    from boombox_library.downloader import DownloadQueue

    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',5,30,0,0,0)")
    for i in range(5):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                     "size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"t{i}", "al", "T", 30, "mp3", 100, "audio/mpeg", 0, 0))

    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    in_flight = 0
    peak = 0

    async def slow_fetch(url, params, dest):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        dest.write_bytes(b"x")
        in_flight -= 1

    client = FakeStreamingClient(b"x")
    queue = DownloadQueue(conn=conn, client=client, cache_root=cache_root,
                          max_concurrent=2, fetch=slow_fetch)
    for i in range(5):
        queue.enqueue(f"t{i}")
    await queue.drain()

    assert peak <= 2
    rows = conn.execute("SELECT COUNT(*) FROM cache_state WHERE status='present'").fetchone()
    assert rows[0] == 5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest services/tests/test_library_downloader.py::test_queue_respects_concurrency_limit -v
```

Expected: ImportError for `DownloadQueue`.

- [ ] **Step 3: Implement `DownloadQueue`**

Append to `services/boombox_library/downloader.py`:

```python
import asyncio


class DownloadQueue:
    """In-memory download queue with bounded concurrency.

    Tracks marked QUEUED in cache_state aren't automatically picked up;
    callers explicitly enqueue() IDs. The queue does not persist across
    restarts — the catalog sync re-derives what should be downloaded
    from pin state at startup.
    """

    def __init__(
        self,
        conn: Connection,
        client: StreamingClient,
        cache_root: Path,
        max_concurrent: int = 2,
        fetch: Fetcher = default_fetch,
    ) -> None:
        self.conn = conn
        self.client = client
        self.cache_root = cache_root
        self._sem = asyncio.Semaphore(max_concurrent)
        self._fetch = fetch
        self._tasks: set[asyncio.Task] = set()

    def enqueue(self, track_id: str) -> None:
        """Schedule a download task. Returns immediately."""
        self.conn.execute(
            """INSERT INTO cache_state(track_id, status)
               VALUES (?, 'queued')
               ON CONFLICT(track_id) DO UPDATE SET
                  status=CASE WHEN cache_state.status='present'
                              THEN 'present' ELSE 'queued' END""",
            (track_id,),
        )
        task = asyncio.create_task(self._run_one(track_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_one(self, track_id: str) -> None:
        async with self._sem:
            await download_track(
                conn=self.conn,
                client=self.client,
                track_id=track_id,
                cache_root=self.cache_root,
                fetch=self._fetch,
            )

    async def drain(self) -> None:
        """Wait for all in-flight + queued tasks to complete."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_downloader.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/downloader.py services/tests/test_library_downloader.py
git commit -m "feat(library): download queue with bounded concurrency"
```

---

### Task 11: Eviction (FIFO over streamed, pinned protected)

**Files:**
- Create: `services/boombox_library/eviction.py`
- Create: `services/tests/test_library_eviction.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_eviction.py`:

```python
"""Tests for boombox_library.eviction — FIFO over streamed, pinned protected."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.db import connect, migrate
from boombox_library.eviction import compute_eviction_candidates, evict_until_fits
from boombox_library.models import PinKind, PinSource
from boombox_library.pins import pin


def _seed(conn, tracks):
    """tracks: list of (track_id, album_id, size_bytes, downloaded_at)."""
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    seen_albums = set()
    for tid, aid, size, dl in tracks:
        if aid not in seen_albums:
            conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,"
                         "song_count,duration_s,is_compilation,navidrome_starred,"
                         "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (aid, aid, aid, "ar", 1, 30, 0, 0, 0))
            seen_albums.add(aid)
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                     "size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (tid, aid, "T", 30, "mp3", size, "audio/mpeg", 0, 0))
        conn.execute("INSERT INTO cache_state(track_id,status,local_path,"
                     "size_bytes,downloaded_at) VALUES(?,?,?,?,?)",
                     (tid, "present", f"/cache/audio/{tid}.mp3", size, dl))


def test_no_eviction_when_zero_needed(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [("t1", "al1", 100, 1.0)])
    freed, leftover = evict_until_fits(conn, need_bytes=0,
                                       delete_file=lambda p: None)
    assert freed == 0
    assert leftover == 0
    assert conn.execute("SELECT COUNT(*) FROM cache_state WHERE status='present'").fetchone()[0] == 1


def test_evicts_oldest_streamed_first(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [
        ("t1", "al1", 100, 1.0),  # oldest
        ("t2", "al2", 100, 2.0),
        ("t3", "al3", 100, 3.0),
    ])
    deleted = []
    freed, leftover = evict_until_fits(conn, need_bytes=150,
                                       delete_file=lambda p: deleted.append(p))
    assert leftover == 0
    assert freed >= 150
    # Should have evicted t1 + t2 (oldest first)
    statuses = dict(conn.execute("SELECT track_id, status FROM cache_state"))
    assert statuses["t1"] == "absent"
    assert statuses["t2"] == "absent"
    assert statuses["t3"] == "present"
    assert "/cache/audio/t1.mp3" in deleted
    assert "/cache/audio/t2.mp3" in deleted


def test_never_evicts_pinned_tracks(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [
        ("t1", "al1", 100, 1.0),  # oldest but pinned via album
        ("t2", "al2", 100, 2.0),
    ])
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    freed, leftover = evict_until_fits(conn, need_bytes=150,
                                       delete_file=lambda p: None)
    # Only t2 (100 bytes) could be evicted; deficit remains
    statuses = dict(conn.execute("SELECT track_id, status FROM cache_state"))
    assert statuses["t1"] == "present"  # protected by pin
    assert statuses["t2"] == "absent"
    assert freed == 100
    assert leftover == 50


def test_returns_zero_leftover_when_exact_fit(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [("t1", "al1", 100, 1.0)])
    freed, leftover = evict_until_fits(conn, need_bytes=100,
                                       delete_file=lambda p: None)
    assert freed == 100
    assert leftover == 0


def test_compute_candidates_excludes_pinned(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [("t1", "al1", 100, 1.0), ("t2", "al2", 100, 2.0)])
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    candidates = compute_eviction_candidates(conn)
    ids = [c["track_id"] for c in candidates]
    assert ids == ["t2"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_eviction.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement eviction module**

Create `services/boombox_library/eviction.py`:

```python
"""FIFO eviction over streamed cache; pinned content is protected.

The set of "pinned-protected" track IDs is derived from the pins table
by expanding each pin (album→tracks, artist→tracks, playlist→tracks,
track→itself). We materialize this set in Python and query SQLite for
the rest, ordered by downloaded_at ASC.

Eviction is opportunistic: it never deletes more than needed to satisfy
the byte deficit; it deletes the FILE and marks cache_state status='absent'.
The caller (downloader / pin handler) decides what to do with any
leftover deficit.
"""
from __future__ import annotations

import logging
from sqlite3 import Connection
from typing import Callable

from .pins import all_pinned_track_ids

log = logging.getLogger("boombox-library.eviction")


def compute_eviction_candidates(conn: Connection) -> list[dict]:
    """Cached tracks that are NOT pin-protected, oldest first."""
    pinned = all_pinned_track_ids(conn)
    rows = list(conn.execute(
        """SELECT track_id, local_path, size_bytes, downloaded_at
           FROM cache_state
           WHERE status='present'
           ORDER BY downloaded_at ASC"""
    ))
    return [dict(r) for r in rows if r["track_id"] not in pinned]


def evict_until_fits(
    conn: Connection,
    need_bytes: int,
    delete_file: Callable[[str], None],
) -> tuple[int, int]:
    """Evict oldest streamed cache items FIFO until need_bytes is freed,
    or no more candidates exist.

    Returns (freed_bytes, leftover_deficit). leftover_deficit > 0 means
    we hit the bottom of the unpinned pool without satisfying the request.
    """
    if need_bytes <= 0:
        return (0, 0)

    candidates = compute_eviction_candidates(conn)
    freed = 0
    for c in candidates:
        if freed >= need_bytes:
            break
        try:
            delete_file(c["local_path"])
        except OSError as e:
            log.warning("could not delete %s: %s", c["local_path"], e)
        conn.execute(
            """UPDATE cache_state
               SET status='absent', local_path=NULL, size_bytes=NULL,
                   downloaded_at=NULL, error_message=NULL
               WHERE track_id=?""",
            (c["track_id"],),
        )
        freed += int(c["size_bytes"] or 0)

    leftover = max(0, need_bytes - freed)
    return (freed, leftover)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_eviction.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/eviction.py services/tests/test_library_eviction.py
git commit -m "feat(library): FIFO eviction over streamed cache, pinned protected"
```

---

### Task 12: Playback resolver

**Files:**
- Create: `services/boombox_library/resolver.py`
- Create: `services/tests/test_library_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `services/tests/test_library_resolver.py`:

```python
"""Tests for boombox_library.resolver — playback decision logic."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.db import connect, migrate
from boombox_library.resolver import resolve_playback, PlaybackSource


def _seed_track(conn, track_id="t1", cached_path=None):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)",
                 (track_id, "al", "T", 30, "mp3", 1000, "audio/mpeg", 0, 0))
    if cached_path:
        conn.execute("INSERT INTO cache_state(track_id,status,local_path,"
                     "size_bytes,downloaded_at) VALUES(?,?,?,?,?)",
                     (track_id, "present", cached_path, 1000, 0))


def test_cached_online_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", "/cache/audio/t1.mp3")
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == "local:track:/cache/audio/t1.mp3"


def test_cached_offline_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", "/cache/audio/t1.mp3")
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == "local:track:/cache/audio/t1.mp3"


def test_uncached_online_returns_subsonic_stream(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.STREAM
    # Mopidy-Subsonic URI scheme
    assert r.uri == "subsonic:track:t1"


def test_uncached_offline_returns_offline_miss(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.OFFLINE_MISS
    assert r.uri is None


def test_unknown_track_returns_offline_miss(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    r = resolve_playback(conn, "does-not-exist", online=True)
    assert r.source == PlaybackSource.OFFLINE_MISS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_resolver.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement resolver**

Create `services/boombox_library/resolver.py`:

```python
"""Playback resolver — decides which Mopidy URI form to play for a given
Subsonic track ID, given current cache state and online reachability.

This is a pure function over (catalog state, cache state, online bool).
Side effects (the streamed-cache trigger) are not in this module — the
HTTP handler in api.py orchestrates them after consulting the resolver.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from sqlite3 import Connection
from typing import Optional


class PlaybackSource(str, Enum):
    CACHE = "cache"
    STREAM = "stream"
    OFFLINE_MISS = "offline_miss"


@dataclass(frozen=True)
class PlaybackResolution:
    source: PlaybackSource
    uri: Optional[str]
    cache_status: str  # 'present' | 'absent' | etc.


def resolve_playback(conn: Connection, track_id: str, online: bool) -> PlaybackResolution:
    """Decide which URI form to play.

    Rules (from spec):
      cached + (online or offline)  → local:<path>,    source=CACHE
      not cached + online           → subsonic:track:<id>, source=STREAM
      not cached + offline          → uri=None,        source=OFFLINE_MISS
      unknown track                 → uri=None,        source=OFFLINE_MISS
    """
    row = conn.execute(
        "SELECT status, local_path FROM cache_state WHERE track_id=?",
        (track_id,),
    ).fetchone()

    if row is not None and row["status"] == "present" and row["local_path"]:
        return PlaybackResolution(
            source=PlaybackSource.CACHE,
            uri=f"local:track:{row['local_path']}",
            cache_status="present",
        )

    cache_status = row["status"] if row is not None else "absent"

    # Verify the track actually exists in the catalog before promising a stream
    exists = conn.execute(
        "SELECT 1 FROM tracks WHERE id=?", (track_id,)
    ).fetchone() is not None

    if not exists:
        return PlaybackResolution(
            source=PlaybackSource.OFFLINE_MISS, uri=None,
            cache_status=cache_status,
        )

    if online:
        return PlaybackResolution(
            source=PlaybackSource.STREAM,
            uri=f"subsonic:track:{track_id}",
            cache_status=cache_status,
        )

    return PlaybackResolution(
        source=PlaybackSource.OFFLINE_MISS, uri=None,
        cache_status=cache_status,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_resolver.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/resolver.py services/tests/test_library_resolver.py
git commit -m "feat(library): playback resolver — cache vs stream vs offline-miss"
```

---

### Task 13: Mopidy config writer

**Files:**
- Create: `services/boombox_library/mopidy_config.py`
- Modify: `services/tests/test_library_config.py`

- [ ] **Step 1: Write failing tests**

Append to `services/tests/test_library_config.py`:

```python
def test_write_mopidy_subsonic_block_creates(tmp_path: Path):
    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"
    mopidy_conf.write_text(
        "[core]\n"
        "data_dir = /var/lib/mopidy\n"
        "\n"
        "[local]\n"
        "media_dir = /opt/boombox/cache-mount/audio\n"
    )
    write_subsonic_block(
        path=mopidy_conf,
        url="http://192.168.1.223:4533",
        username="boombox",
        password="hunter2",
    )
    text = mopidy_conf.read_text()
    assert "[subsonic]" in text
    assert "url = http://192.168.1.223:4533" in text
    assert "username = boombox" in text
    assert "password = hunter2" in text
    # Idempotent: original blocks preserved
    assert "[local]" in text
    assert "[core]" in text


def test_write_mopidy_subsonic_block_replaces(tmp_path: Path):
    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"
    mopidy_conf.write_text(
        "[subsonic]\n"
        "url = http://old.example:4533\n"
        "username = old\n"
        "password = old\n"
        "\n"
        "[local]\n"
        "media_dir = /tmp\n"
    )
    write_subsonic_block(
        path=mopidy_conf,
        url="http://new:4533",
        username="new",
        password="newpass",
    )
    text = mopidy_conf.read_text()
    assert text.count("[subsonic]") == 1
    assert "url = http://new:4533" in text
    assert "old.example" not in text
    assert "[local]" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_config.py -k mopidy -v
```

Expected: ImportError.

- [ ] **Step 3: Implement mopidy_config**

Create `services/boombox_library/mopidy_config.py`:

```python
"""Writes the [subsonic] block into mopidy.conf so Mopidy-Subsonic can
stream from Navidrome. The service rewrites this block whenever the user
saves new source credentials in Settings, then signals Mopidy to reload.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger("boombox-library.mopidy_config")

_SECTION_RE = re.compile(r"^\[(\w+)\]\s*$", re.MULTILINE)
_BLOCK = """\
[subsonic]
hostname = {hostname}
port = {port}
username = {username}
password = {password}
ssl = {ssl}
"""


def _split_url(url: str) -> tuple[str, int, bool]:
    """Parse a base URL into (hostname, port, ssl). Defaults port to 4533
    (Navidrome) for plain HTTP if absent, 443 for HTTPS."""
    from urllib.parse import urlparse
    p = urlparse(url)
    ssl = p.scheme == "https"
    host = p.hostname or ""
    port = p.port or (443 if ssl else 4533)
    return host, port, ssl


def write_subsonic_block(
    path: Path,
    url: str,
    username: str,
    password: str,
) -> None:
    """Idempotently write the [subsonic] block in mopidy.conf. Preserves
    all other sections. Atomic via .tmp + rename."""
    host, port, ssl = _split_url(url)
    new_block = _BLOCK.format(
        hostname=host, port=port, username=username,
        password=password, ssl="true" if ssl else "false",
    )

    if path.exists():
        current = path.read_text()
        # Find and replace existing [subsonic] block, or append.
        replaced, n = re.subn(
            r"\[subsonic\][^\[]*",
            new_block + "\n",
            current,
            count=1,
        )
        if n == 0:
            replaced = current.rstrip() + "\n\n" + new_block
    else:
        replaced = new_block

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(replaced)
    os.replace(tmp, path)


def reload_mopidy() -> bool:
    """Trigger Mopidy to reload its config. Returns True on success."""
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", "mopidy"],
            check=True, capture_output=True, timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("mopidy reload failed: %s", e)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_config.py -v
```

Expected: all pass (config + mopidy_config tests).

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/mopidy_config.py services/tests/test_library_config.py
git commit -m "feat(library): mopidy.conf [subsonic] block writer"
```

---

### Task 14: HTTP API — health, source, browse, search

**Files:**
- Create: `services/boombox_library/api.py`
- Create: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing tests for health + source endpoints**

Create `services/tests/test_library_api.py`:

```python
"""Tests for boombox_library.api — HTTP routes."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from boombox_library.api import build_app
from boombox_library.config import (
    LibraryConfig, SourceConfig, SyncConfig, CacheConfig, DEFAULT_CONFIG,
)
from boombox_library.db import connect, migrate
from boombox_library.models import PinKind, PinSource


class FakeContext:
    """In-memory stand-in for the service's runtime context."""
    def __init__(self, conn, cfg=None, cache_state=None, ping_ok=True):
        self.conn = conn
        self.cfg = cfg or DEFAULT_CONFIG
        self.cache_state = cache_state  # CacheDriveState
        self._ping_ok = ping_ok
        self.synced = 0

    async def is_online(self) -> bool:
        return self._ping_ok

    async def trigger_sync(self) -> None:
        self.synced += 1

    def cache_drive_state(self):
        return self.cache_state

    def save_config(self, cfg):
        self.cfg = cfg

    async def test_source(self, url, username, password) -> tuple[bool, str]:
        return (self._ping_ok, "" if self._ping_ok else "auth failed")


@pytest.fixture
async def client(tmp_path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    ctx = FakeContext(conn)
    app = build_app(ctx)
    async with TestClient(TestServer(app)) as c:
        yield c, ctx, conn


@pytest.mark.asyncio
async def test_health_returns_status(client):
    c, ctx, _ = client
    r = await c.get("/api/library/health")
    assert r.status == 200
    body = await r.json()
    assert "navidrome_reachable" in body
    assert "cache_present" in body
    assert "service_version" in body


@pytest.mark.asyncio
async def test_source_get_does_not_expose_password(client):
    c, ctx, _ = client
    ctx.cfg = LibraryConfig(
        source=SourceConfig(url="http://nav:4533", username="u", password="secret"),
        sync=DEFAULT_CONFIG.sync,
        cache=DEFAULT_CONFIG.cache,
    )
    r = await c.get("/api/library/source")
    assert r.status == 200
    body = await r.json()
    assert body["url"] == "http://nav:4533"
    assert body["username"] == "u"
    assert "password" not in body
    assert "secret" not in str(body)


@pytest.mark.asyncio
async def test_source_test_returns_ok(client):
    c, ctx, _ = client
    r = await c.post("/api/library/source/test", json={
        "url": "http://nav:4533", "username": "u", "password": "p",
    })
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_browse_artists(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','ABBA','abba',6,0)")
    r = await c.get("/api/library/browse", params={"type": "artists"})
    assert r.status == 200
    body = await r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "ABBA"


@pytest.mark.asyncio
async def test_search_uses_fts5(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO search_index(content_type,id,title,body) "
                 "VALUES('album','al1','Back in Black','AC/DC rock 1980')")
    r = await c.get("/api/library/search", params={"q": "rock"})
    assert r.status == 200
    body = await r.json()
    assert any(i["id"] == "al1" for i in body["results"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: ImportError for `build_app`.

- [ ] **Step 3: Implement health + source + browse + search routes**

Create `services/boombox_library/api.py`:

```python
"""HTTP surface for boombox-library (mounted at :6687, proxied via nginx
under /api/library/).

The app needs a Context object supplied by the service entry point.
Context exposes the DB connection, config, cache drive state, and a few
async hooks (test_source, trigger_sync, is_online) so the API doesn't
hard-depend on the runtime wiring (keeps tests fast).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Protocol

from aiohttp import web

from . import __version__
from .config import LibraryConfig, SourceConfig

log = logging.getLogger("boombox-library.api")


class Context(Protocol):
    conn: object  # sqlite3.Connection
    cfg: LibraryConfig

    async def is_online(self) -> bool: ...
    async def trigger_sync(self) -> None: ...
    def cache_drive_state(self): ...
    def save_config(self, cfg: LibraryConfig) -> None: ...
    async def test_source(self, url: str, username: str, password: str) -> tuple[bool, str]: ...


def build_app(ctx: Context) -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.router.add_get("/api/library/health", _health)
    app.router.add_get("/api/library/source", _source_get)
    app.router.add_put("/api/library/source", _source_put)
    app.router.add_post("/api/library/source/test", _source_test)
    app.router.add_get("/api/library/browse", _browse)
    app.router.add_get("/api/library/search", _search)
    return app


async def _health(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    drive = ctx.cache_drive_state()
    return web.json_response({
        "service_version": __version__,
        "navidrome_reachable": await ctx.is_online(),
        "cache_present": bool(drive and drive.present) if drive else False,
        "cache_mount": str(drive.mount_path) if drive and drive.mount_path else None,
    })


async def _source_get(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    s = ctx.cfg.source
    return web.json_response({"url": s.url, "username": s.username})


async def _source_put(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    new_source = SourceConfig(
        url=body.get("url", ""),
        username=body.get("username", ""),
        password=body.get("password", ""),
    )
    ok, msg = await ctx.test_source(new_source.url, new_source.username, new_source.password)
    if not ok:
        return web.json_response({"ok": False, "error": msg}, status=400)
    ctx.save_config(replace(ctx.cfg, source=new_source))
    await ctx.trigger_sync()
    return web.json_response({"ok": True})


async def _source_test(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    ok, msg = await ctx.test_source(
        body.get("url", ""), body.get("username", ""), body.get("password", ""),
    )
    return web.json_response({"ok": ok, "error": msg if not ok else ""})


_BROWSE_QUERIES = {
    "artists": "SELECT id, name, album_count, art_id FROM artists ORDER BY sort_name",
    "albums": "SELECT id, name, artist_id, year, art_id FROM albums ORDER BY sort_name",
    "playlists": "SELECT id, name, song_count FROM playlists ORDER BY name",
}


async def _browse(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    t = req.query.get("type", "artists")
    sql = _BROWSE_QUERIES.get(t)
    if not sql:
        return web.json_response({"error": f"unknown type {t}"}, status=400)
    rows = list(ctx.conn.execute(sql))
    return web.json_response({"items": [dict(r) for r in rows]})


async def _search(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    q = req.query.get("q", "").strip()
    if not q:
        return web.json_response({"results": []})
    # FTS5 MATCH; escape double-quote inside q
    safe = q.replace('"', '""')
    rows = list(ctx.conn.execute(
        "SELECT content_type, id, title FROM search_index "
        "WHERE search_index MATCH ? LIMIT 200",
        (f'"{safe}"',),
    ))
    return web.json_response({"results": [dict(r) for r in rows]})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/api.py services/tests/test_library_api.py
git commit -m "feat(library): HTTP API — health, source, browse, search"
```

---

### Task 15: HTTP API — pin/unpin, sync, cache, resolver endpoints

**Files:**
- Modify: `services/boombox_library/api.py`
- Modify: `services/tests/test_library_api.py`

- [ ] **Step 1: Write failing tests**

Append to `services/tests/test_library_api.py`:

```python
@pytest.mark.asyncio
async def test_pin_inserts_row(client):
    c, ctx, conn = client
    # Seed a target so the pin is meaningful
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al", "mode": "pin",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT * FROM pins"))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_unpin_removes_row(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO pins(target_kind,target_id,source,added_at) "
                 "VALUES('album','al','user',0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al", "mode": "unpin",
    })
    assert r.status == 200
    assert list(conn.execute("SELECT * FROM pins")) == []


@pytest.mark.asyncio
async def test_sync_run_triggers(client):
    c, ctx, conn = client
    r = await c.post("/api/library/sync/run")
    assert r.status == 200
    assert ctx.synced == 1


@pytest.mark.asyncio
async def test_resolver_endpoint_returns_cache_uri(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',1000,'audio/mpeg',0,0)")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present','/x/audio/t1.mp3',1000,0)")
    r = await c.get("/api/library/track/t1/playback")
    assert r.status == 200
    body = await r.json()
    assert body["source"] == "cache"
    assert body["uri"] == "local:track:/x/audio/t1.mp3"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: 404s on the new routes.

- [ ] **Step 3: Add routes**

Append to `services/boombox_library/api.py`:

```python
from .models import PinKind, PinSource
from .pins import pin as _pin_fn, unpin as _unpin_fn
from .resolver import resolve_playback


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
    if mode == "pin":
        _pin_fn(ctx.conn, kind, target_id, PinSource.USER)
    elif mode == "unpin":
        _unpin_fn(ctx.conn, kind, target_id)
    else:
        return web.json_response({"error": "invalid mode"}, status=400)
    return web.json_response({"ok": True})


async def _sync_run(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    await ctx.trigger_sync()
    return web.json_response({"ok": True})


async def _resolver(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    track_id = req.match_info["track_id"]
    online = await ctx.is_online()
    r = resolve_playback(ctx.conn, track_id, online)
    return web.json_response({
        "source": r.source.value,
        "uri": r.uri,
        "cache_status": r.cache_status,
    })


async def _cache_stats(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    drive = ctx.cache_drive_state()
    if not drive or not drive.present:
        return web.json_response({
            "present": False, "capacity": 0, "free": 0,
            "pinned_bytes": 0, "streamed_bytes": 0, "reserved": ctx.cfg.cache.reserve_bytes,
        })
    from .pins import all_pinned_track_ids
    pinned_ids = all_pinned_track_ids(ctx.conn)
    rows = list(ctx.conn.execute(
        "SELECT track_id, size_bytes FROM cache_state WHERE status='present'"
    ))
    pinned_bytes = sum(int(r["size_bytes"] or 0) for r in rows if r["track_id"] in pinned_ids)
    streamed_bytes = sum(int(r["size_bytes"] or 0) for r in rows if r["track_id"] not in pinned_ids)
    return web.json_response({
        "present": True,
        "mount_path": str(drive.mount_path),
        "capacity": drive.total_bytes or 0,
        "free": drive.free_bytes or 0,
        "pinned_bytes": pinned_bytes,
        "streamed_bytes": streamed_bytes,
        "reserved": ctx.cfg.cache.reserve_bytes,
    })
```

In the `build_app` function (already exists), add the new routes:

```python
def build_app(ctx: Context) -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.router.add_get("/api/library/health", _health)
    app.router.add_get("/api/library/source", _source_get)
    app.router.add_put("/api/library/source", _source_put)
    app.router.add_post("/api/library/source/test", _source_test)
    app.router.add_get("/api/library/browse", _browse)
    app.router.add_get("/api/library/search", _search)
    app.router.add_post("/api/library/pin", _pin)
    app.router.add_post("/api/library/sync/run", _sync_run)
    app.router.add_get("/api/library/track/{track_id}/playback", _resolver)
    app.router.add_get("/api/library/cache/stats", _cache_stats)
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest services/tests/test_library_api.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/api.py services/tests/test_library_api.py
git commit -m "feat(library): HTTP API — pin/unpin, sync trigger, resolver, cache stats"
```

---

### Task 16: Service entry point + main loop

**Files:**
- Create: `services/boombox-library.py`

- [ ] **Step 1: Write the entry point**

Create `services/boombox-library.py`:

```python
#!/usr/bin/env python3
# services/boombox-library.py
"""boombox-library service entry point.

Wires together: Subsonic client, SQLite catalog, pin manager + sidecar,
cache drive detection (poll loop), downloader queue, eviction, HTTP API
on port 6687.

The service is resilient to Navidrome being unreachable and to the
cache drive being absent or yanked. Both states surface via /api/library/health.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import replace
from pathlib import Path

from aiohttp import web

from boombox_library import __version__
from boombox_library.api import build_app
from boombox_library.cache_drive import (
    CacheDriveState, detect_cache_drive,
    update_symlink, remove_symlink,
    DEFAULT_SYMLINK,
)
from boombox_library.catalog import sync_full
from boombox_library.config import (
    CONFIG_PATH, LibraryConfig, load_config, save_config,
)
from boombox_library.db import connect, migrate
from boombox_library.downloader import DownloadQueue
from boombox_library.mopidy_config import write_subsonic_block, reload_mopidy
from boombox_library.pins import (
    all_pinned_track_ids, load_sidecar, reconcile_starred, write_sidecar,
)
from boombox_library.subsonic import (
    SubsonicAuthError, SubsonicClient, SubsonicUnreachable,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-library")

DB_PATH = Path("/opt/boombox/state/library.db")
MOPIDY_CONF = Path("/etc/mopidy/mopidy.conf")
CACHE_POLL_SECONDS = 5
PORT = 6687


class ServiceContext:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.conn = connect(DB_PATH)
        migrate(self.conn)
        self.cache_state: CacheDriveState = CacheDriveState(
            present=False, mount_path=None,
            free_bytes=None, total_bytes=None,
        )
        self._online = False
        self._sync_task: asyncio.Task | None = None
        self._download_queue: DownloadQueue | None = None
        self._load_sidecar_if_present()

    # ----- helpers exposed to api.py -----
    async def is_online(self) -> bool:
        return self._online

    def cache_drive_state(self) -> CacheDriveState:
        return self.cache_state

    def save_config(self, cfg: LibraryConfig) -> None:
        self.cfg = cfg
        save_config(cfg)
        write_subsonic_block(MOPIDY_CONF, cfg.source.url,
                             cfg.source.username, cfg.source.password)
        reload_mopidy()

    async def test_source(self, url: str, username: str, password: str) -> tuple[bool, str]:
        async with SubsonicClient(url, username, password) as c:
            try:
                await c.ping()
                return (True, "")
            except SubsonicAuthError as e:
                return (False, f"auth: {e}")
            except SubsonicUnreachable as e:
                return (False, f"unreachable: {e}")

    async def trigger_sync(self) -> None:
        if self._sync_task and not self._sync_task.done():
            return  # one at a time
        self._sync_task = asyncio.create_task(self._sync_once())

    # ----- background loops -----
    async def _sync_once(self) -> None:
        if not self.cfg.source.url:
            log.info("no source configured; skipping sync")
            return
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
            except Exception as e:
                log.exception("sync failed: %s", e)

    async def sync_timer(self) -> None:
        # First-boot immediate sync
        await self.trigger_sync()
        while True:
            await asyncio.sleep(self.cfg.sync.interval_seconds)
            await self.trigger_sync()

    async def cache_poll(self) -> None:
        while True:
            new_state = detect_cache_drive(
                search_paths=[Path(p) for p in self.cfg.cache.search_paths],
                marker=self.cfg.cache.marker_filename,
            )
            if new_state.mount_path != self.cache_state.mount_path:
                # Adopted or detached
                if new_state.present and new_state.mount_path:
                    log.info("cache drive present at %s", new_state.mount_path)
                    update_symlink(DEFAULT_SYMLINK, new_state.mount_path)
                    self._init_download_queue(new_state.mount_path)
                    self._load_sidecar_if_present()
                else:
                    log.warning("cache drive lost")
                    remove_symlink(DEFAULT_SYMLINK)
                    self._download_queue = None
            self.cache_state = new_state
            await asyncio.sleep(CACHE_POLL_SECONDS)

    # ----- internals -----
    def _init_download_queue(self, mount: Path) -> None:
        if not self.cfg.source.url:
            return
        # Note: client lifetime is per-download in default_fetch — this
        # client is only used for download_url() construction.
        client = SubsonicClient(self.cfg.source.url,
                                self.cfg.source.username,
                                self.cfg.source.password)
        self._download_queue = DownloadQueue(
            conn=self.conn, client=client, cache_root=mount,
            max_concurrent=self.cfg.sync.max_concurrent_downloads,
        )

    def _enqueue_pinned_downloads(self) -> None:
        if self._download_queue is None:
            log.info("cache drive absent; pinned downloads deferred")
            return
        pinned = all_pinned_track_ids(self.conn)
        if not pinned:
            return
        # Only enqueue tracks not already present
        rows = self.conn.execute(
            "SELECT track_id FROM cache_state WHERE status='present'"
        )
        present = {r[0] for r in rows}
        for tid in pinned - present:
            self._download_queue.enqueue(tid)

    def _persist_pins_sidecar(self) -> None:
        if not self.cache_state.present or not self.cache_state.mount_path:
            return
        sidecar = self.cache_state.mount_path / "meta" / "pins.json"
        write_sidecar(self.conn, sidecar)

    def _load_sidecar_if_present(self) -> None:
        if not self.cache_state.present or not self.cache_state.mount_path:
            return
        sidecar = self.cache_state.mount_path / "meta" / "pins.json"
        n = load_sidecar(self.conn, sidecar)
        if n:
            log.info("loaded %d pins from sidecar", n)


async def amain() -> None:
    ctx = ServiceContext()
    app = build_app(ctx)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    log.info("boombox-library %s listening on :%d", __version__, PORT)

    # Background loops
    sync_task = asyncio.create_task(ctx.sync_timer())
    cache_task = asyncio.create_task(ctx.cache_poll())

    # Wait forever (until SIGTERM)
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    sync_task.cancel()
    cache_task.cancel()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
```

- [ ] **Step 2: Verify entry point parses and binds (smoke test)**

```bash
cd /Users/jwc/code/Boombox
PYTHONPATH=services python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('entry', 'services/boombox-library.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('entry module loaded ok')
"
```

Expected: `entry module loaded ok` (no exceptions).

- [ ] **Step 3: Commit**

```bash
git add services/boombox-library.py
git commit -m "feat(library): service entry point — wires API, sync loop, cache poll"
```

---

### Task 17: Systemd unit + nginx route + install.sh + requirements + config template

**Files:**
- Create: `install/systemd/user/boombox-library.service`
- Create: `install/config/library.yml.template`
- Modify: `install/config/nginx-boombox-common.conf`
- Modify: `install/config/requirements.txt`
- Modify: `install/install.sh`

- [ ] **Step 1: Create systemd unit**

Create `install/systemd/user/boombox-library.service`:

```ini
# install/systemd/user/boombox-library.service
[Unit]
Description=Boombox home-library (Navidrome sync + offline cache)
After=default.target network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/boombox/.venv/bin/python /opt/boombox/current/services/boombox-library.py
Restart=on-failure
RestartSec=5
# The service writes /opt/boombox/state/library.db and reads
# /etc/boombox/library.yml. It maintains the symlink
# /opt/boombox/cache-mount and writes /etc/mopidy/mopidy.conf via sudo
# (granted in /etc/sudoers.d/boombox).

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Create config template**

Create `install/config/library.yml.template`:

```yaml
# /etc/boombox/library.yml — boombox-library service config.
# The Settings UI rewrites this file atomically; manual edits survive
# until the next save.

source:
  url: ""
  username: ""
  # Password is encrypted at rest by the service; do not edit by hand.
  password_encrypted: ""

sync:
  interval_seconds: 3600
  starred_auto_pin: true
  max_concurrent_downloads: 2

cache:
  marker_filename: ".boombox-cache"
  search_paths:
    - /media
  reserve_bytes: 1073741824  # 1 GB
```

- [ ] **Step 3: Add nginx route**

Find the existing block for `/api/update/` in `install/config/nginx-boombox-common.conf` and add this block right after it (so all boombox-* /api/ blocks live together):

```nginx
# boombox-library HTTP API (catalog browse/search, pin, sync, resolver).
location /api/library/ {
    proxy_pass http://127.0.0.1:6687/api/library/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 30s;
}
```

(Use Read to find the exact insertion point then Edit with `old_string` covering the `/api/update/` block + immediately following blank line, `new_string` = same + the new block.)

- [ ] **Step 4: Add Python deps**

Modify `install/config/requirements.txt` — replace its contents with:

```
aiohttp>=3.9
PyYAML>=6.0
cryptography>=42
```

- [ ] **Step 5: Update install.sh — install Mopidy-Subsonic + place library.yml**

Find the line in `install/install.sh` that does `sudo pip install --break-system-packages Mopidy-Iris` and change it to install both:

```bash
sudo pip install --break-system-packages Mopidy-Iris Mopidy-Subsonic
```

Then add after that line (preserving any existing trailing logic):

```bash
# Place default boombox-library config if absent (atomic, idempotent).
if [ ! -f /etc/boombox/library.yml ]; then
    sudo mkdir -p /etc/boombox
    sudo cp "$(dirname "$0")/config/library.yml.template" /etc/boombox/library.yml
    sudo chown "$USER:$USER" /etc/boombox/library.yml
    sudo chmod 600 /etc/boombox/library.yml
fi

# State dir for SQLite catalog
sudo mkdir -p /opt/boombox/state
sudo chown "$USER:$USER" /opt/boombox/state
```

Also find where other user systemd units are enabled (search for `systemctl --user enable boombox-`) and add `boombox-library.service` to the list.

- [ ] **Step 6: Verify install files are syntactically valid**

```bash
# nginx syntax check requires sudo + an installed nginx; skip — done at install time on the Pi.
# Just lint the systemd unit:
systemd-analyze verify install/systemd/user/boombox-library.service 2>&1 | head
# Acceptable if it complains "No such file: /opt/boombox/..." — that's just because we're on macOS.
```

Expected: no `[FAILED]` or unrecognized-key errors.

- [ ] **Step 7: Commit**

```bash
git add install/systemd/user/boombox-library.service install/config/library.yml.template install/config/nginx-boombox-common.conf install/config/requirements.txt install/install.sh
git commit -m "feat(library): install — systemd unit, nginx route, config template, deps"
```

---

### Task 18: Integration test against real Navidrome (env-gated)

**Files:**
- Modify: `services/tests/conftest.py`
- Create: `services/tests/test_library_integration.py`

- [ ] **Step 1: Extend conftest with Navidrome dev env vars**

Add to `services/tests/conftest.py` at the end:

```python
import os


@pytest.fixture
def navidrome_env():
    """Skip an integration test unless real Navidrome creds are in the env.

    Set NAVIDROME_DEV_URL/USER/PASS to enable; otherwise tests are skipped
    (lets CI run without a NAS).
    """
    url = os.environ.get("NAVIDROME_DEV_URL")
    user = os.environ.get("NAVIDROME_DEV_USER")
    pwd = os.environ.get("NAVIDROME_DEV_PASS")
    if not (url and user and pwd):
        pytest.skip("set NAVIDROME_DEV_URL/USER/PASS to enable integration tests")
    return {"url": url, "username": user, "password": pwd}
```

- [ ] **Step 2: Write integration test**

Create `services/tests/test_library_integration.py`:

```python
"""Integration tests against a real Navidrome instance.

Skipped unless NAVIDROME_DEV_URL/USER/PASS env vars are set.

Local dev run:
  NAVIDROME_DEV_URL=http://192.168.1.223:4533 \
  NAVIDROME_DEV_USER=jwc \
  NAVIDROME_DEV_PASS=turtle99 \
  pytest services/tests/test_library_integration.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.catalog import sync_full
from boombox_library.db import connect, migrate
from boombox_library.subsonic import SubsonicClient


@pytest.mark.asyncio
async def test_ping_real_navidrome(navidrome_env):
    async with SubsonicClient(**navidrome_env) as c:
        ok = await c.ping()
    assert ok


@pytest.mark.asyncio
async def test_full_sync_real_navidrome(navidrome_env, tmp_path: Path):
    """Run a full sync against the dev Navidrome. Big — may take a while.

    Asserts non-trivial library size (the dev box has thousands of
    artists). Adjust the lower bound if your dev library is smaller.
    """
    db = connect(tmp_path / "live.db")
    migrate(db)
    async with SubsonicClient(**navidrome_env) as c:
        counts = await sync_full(c, db)
    # Bound generously — the dev library had ~3961 artists at the time
    # of the spec; tests just sanity-check we pulled something.
    assert counts["artists"] >= 10
    assert counts["albums"] >= 10
    assert counts["tracks"] >= 10

    # FTS5 sanity
    rows = list(db.execute("SELECT id FROM search_index WHERE search_index MATCH 'beatles' LIMIT 5"))
    # Don't require Beatles specifically (dev libraries vary) — just that
    # FTS5 works at all on the loaded corpus.
    rows = list(db.execute("SELECT COUNT(*) FROM search_index"))
    assert rows[0][0] > 0
```

- [ ] **Step 3: Run integration test against the dev Navidrome**

```bash
cd /Users/jwc/code/Boombox
NAVIDROME_DEV_URL=http://192.168.1.223:4533 \
NAVIDROME_DEV_USER=jwc \
NAVIDROME_DEV_PASS=turtle99 \
pytest services/tests/test_library_integration.py -v
```

Expected: 2 passed (a full sync may take a minute or two).

- [ ] **Step 4: Run full test suite to confirm nothing else broke**

```bash
cd /Users/jwc/code/Boombox
pytest services/tests/ -q
```

Expected: all pass (existing tests + new library tests; integration tests skipped without env vars).

- [ ] **Step 5: Commit**

```bash
git add services/tests/conftest.py services/tests/test_library_integration.py
git commit -m "test(library): integration tests against real Navidrome (env-gated)"
```

---

### Task 19: Final wiring — repoint Mopidy-Local + sudoers for mopidy restart

**Files:**
- Modify: `install/config/mopidy.conf`
- Modify: `install/sudoers/` (likely `boombox-sudoers` or similar — find via grep)

- [ ] **Step 1: Repoint Mopidy-Local media_dir to the cache mount**

Find `[local]` section in `install/config/mopidy.conf` and change `media_dir`:

```ini
[local]
media_dir = /opt/boombox/cache-mount/audio
```

(If there's a `__MUSIC_DIR__` placeholder, replace it with `/opt/boombox/cache-mount/audio` directly — the substitution-by-install-script approach is no longer needed since the symlink handles drive variability.)

Also add a commented placeholder `[subsonic]` block at the end (the real values are written by boombox-library, but the block needs to exist for Mopidy to load the extension on first start):

```ini
[subsonic]
# Populated by boombox-library when source is configured in Settings.
enabled = true
hostname = unset
port = 4533
username = unset
password = unset
ssl = false
```

- [ ] **Step 2: Grant boombox-library sudo for `systemctl restart mopidy`**

Find the existing sudoers fragment:

```bash
ls install/sudoers/
```

Read it; add a line (or new fragment file) allowing the user to run `systemctl restart mopidy` without a password. Likely shape (verify against existing file format):

```
%boombox ALL=(root) NOPASSWD: /usr/bin/systemctl restart mopidy
```

(Use the same user/group convention the existing sudoers entries use.)

- [ ] **Step 3: Commit**

```bash
git add install/config/mopidy.conf install/sudoers/
git commit -m "feat(library): repoint Mopidy-Local to cache-mount + sudoers for restart"
```

---

## Self-review

### Spec coverage check

Walking the spec → matching task(s):

| Spec section | Implemented by |
|---|---|
| Subsonic client + auth | Tasks 1–3 |
| Source library config (URL/user/password + at-rest encryption) | Task 4 (model), Task 14 (HTTP), Task 16 (Settings save → mopidy.conf + reload via Task 13) |
| SQLite catalog schema | Task 5 |
| Full catalog sync | Task 6 |
| Pin manager + cascade rules + starred reconciliation + sidecar | Task 7 |
| Cache drive detection + marker + symlink | Task 8 |
| Downloader + concurrent queue + atomic writes | Tasks 9–10 |
| FIFO eviction with pinned protection | Task 11 |
| Playback resolver | Task 12 |
| Mopidy config writer + reload | Task 13 |
| HTTP API surface | Tasks 14–15 |
| Service entry point + sync timer + cache poll | Task 16 |
| Systemd unit + nginx route + Mopidy-Subsonic install + config template | Task 17 |
| Integration test against real Navidrome | Task 18 |
| Mopidy-Local repoint + sudoers for mopidy restart | Task 19 |

Spec items NOT covered in Phase 1 (correctly deferred to later phases):
- UI surface (Phase 2)
- "Pin for next time" CTA, status badges, sync indicator, cache adoption modal (Phase 2)
- Retire SMB share + stale-playlist scan (Phase 3)
- README/SERVICES/ARCHITECTURE/CHANGELOG/HOME-LIBRARY.md (Phase 3)
- Incremental/delta sync (the spec implies hourly *delta* sync; this plan only implements `sync_full`. The hourly timer calls `sync_full` which is upsert-idempotent and correct; a true delta implementation is a future optimization to reduce Navidrome load. Not a correctness gap.)
- `POST /api/library/source/test` is implemented; `POST /api/library/cache/adopt` and `POST /api/library/cache/clear` are NOT — they're trivial (write marker / delete unpinned files) but only needed once the UI exists in Phase 2. Add to Phase 2 plan.
- `POST /api/library/cache/streamed` (the streamed-cache trigger called by the UI on stream playback) is NOT in this plan — also only needed once Phase 2 wires the UI to call it. The mechanism (DownloadQueue.enqueue) is fully in place.

These deferrals are intentional and match the phased decomposition stated up top.

### Placeholder scan

Searched the plan for: TBD / TODO / "implement later" / "fill in details" / "add appropriate" / "handle edge cases" / "similar to Task N" / "write tests for the above" (without code). **None found** — every step has concrete code or commands.

### Type / signature consistency

- `SubsonicClient(base_url=..., username=..., password=...)` constructor signature is consistent in Tasks 1, 2, 3, 16, 18.
- `DownloadResult` enum is defined once (Task 9) and used identically in Task 10.
- `PinKind` / `PinSource` / `CacheStatus` enums defined once in Task 5 (models), used identically in Tasks 7, 11, 12, 14, 15, 16.
- `resolve_playback(conn, track_id, online)` signature matches between Task 12 (definition) and Task 15 (HTTP wrapper).
- `cache_drive_state()` method is on the Context in Task 14, returns `CacheDriveState` from Task 8 — consistent.
- `write_subsonic_block(path, url, username, password)` signature matches between Task 13 (definition) and Task 16 (call site).

No mismatches found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-16-home-library-phase1-backend.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a multi-day plan with TDD discipline; the per-task reviews catch drift early.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Lower overhead, but a long plan in one context window risks blunders.

**Which approach?**
