# PWA Phone Remote — Phase 1: Backend Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate `boombox-remote` and `boombox-uploader` into one phone-facing service — a single bearer-token API at `/api/remote/` covering control, files, library/playlists, video, and theming — gated by a default-off `remote_enabled` flag, with `boombox-uploader` retired.

**Architecture:** `boombox-remote.py` stays the single aiohttp service on `127.0.0.1:6685`. New cohesive concerns land in focused modules (`remote_access.py`, `remote_files.py`, `remote_library.py`, `jellyfin_client.py`) that `boombox-remote.py` wires to routes. A new `require_remote_enabled` middleware 403s the phone surface when the flag is off; localhost-only `admin/*` routes flip the flag. `boombox-uploader.py`, its systemd unit, its nginx block, and `boombox-state`'s `/upload/*` endpoints are deleted; the kiosk Settings drawer is repointed at the new admin routes.

**Tech Stack:** Python 3.11 / asyncio / aiohttp, pytest + pytest-asyncio (`asyncio_mode = "auto"`), React 19 + TypeScript (kiosk SPA edits only), bash installers, nginx.

**Scope note:** This is Phase 1 of 2. Phase 2 (`remote-ui/` — the installable PWA, transport layer, screens, PWA manifest, the `/remote/` nginx block, and the `remote-ui` build step) is a separate plan written against the API this phase produces. Phase 1 is independently shippable: it ships the consolidated API and retires the uploader.

**Spec:** `docs/superpowers/specs/2026-05-14-pwa-remote-design.md`

---

## File Structure

**New files:**
- `services/remote_access.py` — the persisted `remote_enabled` flag (read/write `state.json`). One responsibility: access-flag persistence.
- `services/remote_files.py` — file browse/upload/download/delete logic + path-safety helpers, migrated from `boombox-uploader.py`. One responsibility: the music/video file surface.
- `services/remote_library.py` — Mopidy library-search + playlist + queue wrappers. One responsibility: curation operations over Mopidy JSON-RPC.
- `services/jellyfin_client.py` — Jellyfin REST client + local-session targeting. One responsibility: talking to Jellyfin.
- `services/tests/test_remote_access.py`, `test_remote_enabled_gate.py`, `test_remote_admin.py`, `test_remote_files.py`, `test_remote_library.py`, `test_remote_video.py` — test files for the above.

**Modified files:**
- `services/boombox-remote.py` — add the enable-gate middleware, register new routes, wire the new modules, add `theme` to the state payload.
- `services/boombox_remote.py` — the import shim; re-export anything tests need directly.
- `services/actions.py` — add the `source` action handler.
- `services/boombox-state.py` — remove the `/upload/*` endpoints and uploader systemctl plumbing.
- `services/tests/conftest.py` — autouse fixture defaulting the flag ON so existing remote tests still pass.
- `services/tests/test_actions.py` — add `source` action tests.
- `install/config/nginx-boombox-common.conf` — remove the `/upload/` block; add upload limits to `/api/remote/`.
- `install/install.sh` — drop the uploader "not enabled" comment.
- `ui/src/lib/SettingsDrawer.tsx` — replace the "Remote mode" section with a Phone Remote panel driven by `/api/remote/admin/*`.
- `ui/src/overlays/QrOverlay.tsx` — repoint at `/remote/` and `/api/remote/admin/enable`.
- `docs/SERVICES.md` — update the `boombox-remote` section, delete the `boombox-uploader` section.

**Deleted files:**
- `services/boombox-uploader.py`
- `install/systemd/user/boombox-uploader.service`

---

## Task 1: `remote_access.py` — the `remote_enabled` flag

**Files:**
- Create: `services/remote_access.py`
- Test: `services/tests/test_remote_access.py`

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_access.py`:

```python
"""Tests for the remote_enabled flag (services/remote_access.py)."""
from __future__ import annotations

import remote_access


def test_missing_file_reads_as_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(tmp_path / "state.json"))
    assert remote_access.is_enabled() is False


def test_set_enabled_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(tmp_path / "state.json"))
    remote_access.set_enabled(True)
    assert remote_access.is_enabled() is True
    remote_access.set_enabled(False)
    assert remote_access.is_enabled() is False


def test_malformed_file_reads_as_disabled(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("{not json")
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    assert remote_access.is_enabled() is False


def test_set_enabled_creates_parent_dir(tmp_path, monkeypatch):
    state = tmp_path / "nested" / "dir" / "state.json"
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    remote_access.set_enabled(True)
    assert state.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_remote_access.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'remote_access'`

- [ ] **Step 3: Write minimal implementation**

Create `services/remote_access.py`:

```python
"""Persistent 'remote access enabled' flag for boombox-remote.

The phone-facing remote surface is gated by a single on/off flag, default
off, persisted alongside peers.json. The touchscreen toggles it. The BLE
peripheral and the already-paired CYD hardware remote are NOT gated by it —
the flag is a privacy gate against arbitrary phones on the WiFi, not a
master kill switch for paired hardware.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_STATE = Path.home() / ".config" / "boombox-remote" / "state.json"


def _state_path() -> Path:
    """Resolve the state file path. Re-reads env on every call so tests can
    override BOOMBOX_REMOTE_STATE between calls."""
    return Path(os.environ.get("BOOMBOX_REMOTE_STATE", str(DEFAULT_STATE)))


def is_enabled() -> bool:
    """True when remote access is on. A missing or malformed file reads as
    off — the conservative default."""
    try:
        data = json.loads(_state_path().read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return bool(data.get("enabled", False))


def set_enabled(enabled: bool) -> None:
    """Persist the flag. Creates the parent directory if needed."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": bool(enabled)}, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest services/tests/test_remote_access.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/remote_access.py services/tests/test_remote_access.py
git commit -m "feat(remote): persisted remote_enabled flag"
```

---

## Task 2: enable-gate middleware + conftest fixture

This gate 403s the phone-facing routes when the flag is off. Existing remote tests don't set the flag, so they would all start failing — the conftest autouse fixture defaults it ON for the whole suite; the gate's own test overrides that.

**Files:**
- Modify: `services/tests/conftest.py`
- Modify: `services/boombox-remote.py` (middleware list ~line 229; add middleware near `require_auth` ~line 129; WS handler ~line 287)
- Modify: `services/boombox_remote.py` (re-export the middleware)
- Test: `services/tests/test_remote_enabled_gate.py`

- [ ] **Step 1: Add the autouse fixture to conftest.py**

Append to `services/tests/conftest.py`:

```python
import json

import pytest


@pytest.fixture(autouse=True)
def _remote_enabled_by_default(tmp_path_factory, monkeypatch):
    """Default the remote_enabled flag ON for the test suite so the access
    gate doesn't 403 every existing remote test. Tests that exercise the
    *disabled* path override BOOMBOX_REMOTE_STATE in their own fixture,
    which runs after this autouse fixture and so wins."""
    state = tmp_path_factory.mktemp("remote-access") / "state.json"
    state.write_text(json.dumps({"enabled": True}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
```

- [ ] **Step 2: Write the failing test**

Create `services/tests/test_remote_enabled_gate.py`:

```python
"""Tests for the remote_enabled access gate in boombox-remote."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def disabled_app(tmp_path, monkeypatch):
    """An app whose remote_enabled flag is OFF. Overrides the autouse
    conftest fixture by re-pointing BOOMBOX_REMOTE_STATE at a disabled file."""
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"enabled": False}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    return boombox_remote.create_app()


@pytest.mark.asyncio
async def test_state_403_when_disabled(disabled_app, aiohttp_client):
    client = await aiohttp_client(disabled_app)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 403
    body = await resp.json()
    assert body["error"] == "remote_disabled"


@pytest.mark.asyncio
async def test_command_403_when_disabled(disabled_app, aiohttp_client):
    client = await aiohttp_client(disabled_app)
    resp = await client.post("/api/remote/command", json={"action": "next"},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 403


@pytest.mark.asyncio
async def test_pair_403_when_disabled(disabled_app, aiohttp_client):
    client = await aiohttp_client(disabled_app)
    resp = await client.post("/api/remote/pair", json={"pin": "000000"})
    assert resp.status == 403


@pytest.mark.asyncio
async def test_ws_closes_4403_when_disabled(disabled_app, aiohttp_client):
    client = await aiohttp_client(disabled_app)
    ws = await client.ws_connect("/api/remote/ws?token=t")
    msg = await ws.receive()
    assert msg.type.name in ("CLOSE", "CLOSING", "CLOSED")
    assert ws.close_code == 4403


@pytest.mark.asyncio
async def test_state_200_when_enabled(aiohttp_client, tmp_path, monkeypatch):
    # The autouse fixture already enabled the flag; just need peers + an app.
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    app = boombox_remote.create_app()
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    # 503 (no aggregator wired) is fine — the point is it's NOT 403.
    assert resp.status != 403
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest services/tests/test_remote_enabled_gate.py -v`
Expected: FAIL — `test_state_403_when_disabled` gets a non-403 (gate not implemented yet)

- [ ] **Step 4: Add the middleware to boombox-remote.py**

In `services/boombox-remote.py`, add `import remote_access` to the imports block (near `import actions` / `import clients`, ~line 32).

Add this middleware immediately after the `require_auth` middleware definition (after line 156):

```python
@web.middleware
async def require_remote_enabled(request: web.Request, handler):
    """403 every phone-facing route when the remote_enabled flag is off.

    Exempt: /api/remote/admin/* (that's how the flag gets turned on; those
    handlers are localhost-gated) and /api/remote/ws (a WebSocket can't
    return a JSON 403 — the ws handler checks the flag itself and closes
    with code 4403).
    """
    path = request.path
    if path == "/api/remote/ws" or path.startswith("/api/remote/admin/"):
        return await handler(request)
    if not remote_access.is_enabled():
        return web.json_response(
            {"ok": False, "error": "remote_disabled"}, status=403)
    return await handler(request)
```

In `create_app` (line 229), change the middleware list — the enable-gate runs first so a disabled remote 403s regardless of token:

```python
    app = web.Application(
        middlewares=[require_remote_enabled, require_auth])
```

In `_ws_handler` (line 287), after the token check block that closes with `4401` (after line 300), add the flag check:

```python
    if not remote_access.is_enabled():
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4403, message=b"remote_disabled")
        return ws
```

- [ ] **Step 5: Re-export the middleware via the shim**

In `services/boombox_remote.py`, add to the re-export block at the bottom:

```python
create_app             = _mod.create_app
require_auth           = _mod.require_auth
require_remote_enabled = _mod.require_remote_enabled
```

- [ ] **Step 6: Run the gate test and the full remote suite**

Run: `pytest services/tests/test_remote_enabled_gate.py services/tests/test_remote_command.py services/tests/test_remote_state.py services/tests/test_remote_auth.py services/tests/test_remote_ws.py -v`
Expected: PASS — the gate tests pass and the pre-existing remote tests still pass (autouse fixture keeps them enabled)

- [ ] **Step 7: Commit**

```bash
git add services/boombox-remote.py services/boombox_remote.py services/tests/conftest.py services/tests/test_remote_enabled_gate.py
git commit -m "feat(remote): remote_enabled access gate (403 + ws 4403 when off)"
```

---

## Task 3: admin endpoints — status / enable / disable / unpair

Localhost-only routes the touchscreen uses to flip the flag and manage peers. They are exempt from the enable-gate (Task 2) but must be exempt from `require_auth` too (the touchscreen has no token) and gated to localhost in-handler — the same pattern `_post_pair_start` already uses (line 375-382).

**Files:**
- Modify: `services/boombox-remote.py` (`require_auth` exempt list ~line 142; `create_app` routes ~line 232; new handlers)
- Test: `services/tests/test_remote_admin.py`

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_admin.py`:

```python
"""Tests for the localhost-only /api/remote/admin/* endpoints."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"enabled": False}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({
        "tok-a": {"label": "kitchen phone", "paired_at": 100},
    }))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    return boombox_remote.create_app(), state, peers


@pytest.mark.asyncio
async def test_status_reports_flag_and_peers(admin_app, aiohttp_client):
    app, _, _ = admin_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/admin/status")
    assert resp.status == 200
    body = await resp.json()
    assert body["enabled"] is False
    assert body["peers"] == [{"label": "kitchen phone", "paired_at": 100}]


@pytest.mark.asyncio
async def test_enable_then_disable(admin_app, aiohttp_client):
    app, _, _ = admin_app
    client = await aiohttp_client(app)
    await client.post("/api/remote/admin/enable")
    resp = await client.get("/api/remote/admin/status")
    assert (await resp.json())["enabled"] is True
    await client.post("/api/remote/admin/disable")
    resp = await client.get("/api/remote/admin/status")
    assert (await resp.json())["enabled"] is False


@pytest.mark.asyncio
async def test_disable_does_not_clear_peers(admin_app, aiohttp_client):
    app, _, peers = admin_app
    client = await aiohttp_client(app)
    await client.post("/api/remote/admin/disable")
    assert "tok-a" in json.loads(peers.read_text())


@pytest.mark.asyncio
async def test_unpair_removes_one_peer(admin_app, aiohttp_client):
    app, _, peers = admin_app
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/admin/unpair",
                             json={"token": "tok-a"})
    assert resp.status == 200
    assert json.loads(peers.read_text()) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_remote_admin.py -v`
Expected: FAIL — 404 on all routes (handlers not registered)

- [ ] **Step 3: Implement the admin handlers**

In `services/boombox-remote.py`, extend the `require_auth` exempt-path tuple (line 142-143) to include the admin routes:

```python
    if request.path in ("/api/remote/ws", "/api/remote/pair/start",
                          "/api/remote/pair", "/api/remote/admin/status",
                          "/api/remote/admin/enable",
                          "/api/remote/admin/disable",
                          "/api/remote/admin/unpair"):
        return await handler(request)
```

Add a localhost helper and the four handlers near `_post_pair_start` (after line 392). Reuse the same localhost check `_post_pair_start` uses:

```python
def _is_localhost(request: web.Request) -> bool:
    return request.remote in ("127.0.0.1", "::1", "localhost")


async def _get_admin_status(request: web.Request) -> web.Response:
    """Report the enable flag + paired peers. Localhost-only (the kiosk)."""
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    peers = _load_peers()
    return web.json_response({
        "ok": True,
        "enabled": remote_access.is_enabled(),
        "peers": [{"label": p.get("label", "remote"),
                   "paired_at": p.get("paired_at", 0)}
                  for p in peers.values()],
    })


async def _post_admin_enable(request: web.Request) -> web.Response:
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    remote_access.set_enabled(True)
    log.info("remote access enabled")
    return web.json_response({"ok": True, "enabled": True})


async def _post_admin_disable(request: web.Request) -> web.Response:
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    remote_access.set_enabled(False)
    log.info("remote access disabled")
    return web.json_response({"ok": True, "enabled": False})


async def _post_admin_unpair(request: web.Request) -> web.Response:
    """Remove one peer by token. Authorization is otherwise durable — this
    is the only way a peer loses access."""
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"},
                                 status=400)
    token = body.get("token") if isinstance(body, dict) else None
    if not token or not isinstance(token, str):
        return web.json_response({"ok": False, "error": "missing_token"},
                                 status=400)
    peers = _load_peers()
    peers.pop(token, None)
    path = Path(os.environ.get("BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(peers, indent=2))
    log.info("unpaired one remote")
    return web.json_response({"ok": True})
```

Register the routes in `create_app` (after line 237):

```python
    app.router.add_get("/api/remote/admin/status", _get_admin_status)
    app.router.add_post("/api/remote/admin/enable", _post_admin_enable)
    app.router.add_post("/api/remote/admin/disable", _post_admin_disable)
    app.router.add_post("/api/remote/admin/unpair", _post_admin_unpair)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest services/tests/test_remote_admin.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_admin.py
git commit -m "feat(remote): localhost admin routes — status/enable/disable/unpair"
```

---

## Task 4: `source` action in `actions.py`

The CYD firmware already sends `source` commands; `actions.fire()` currently rejects them with `unknown_action:source`. Add a value-parameterized handler that dispatches to the existing per-source handlers.

**Files:**
- Modify: `services/actions.py` (add handler after `_h_skin`, ~line 263)
- Test: `services/tests/test_actions.py` (add to the existing file)

- [ ] **Step 1: Write the failing test**

Add to `services/tests/test_actions.py`:

```python
@pytest.mark.asyncio
async def test_source_action_routes_to_movies(monkeypatch):
    import actions
    calls = []

    async def fake_movies(d):
        calls.append("movies")

    monkeypatch.setitem(actions._HANDLERS, ("movies", "short_press"),
                        fake_movies)
    d = actions.Dispatcher(mopidy=None, state=None, kiosk=None,
                           recorder=None, display=None, sleep=None)
    result = await actions.fire(d, "source", "movies", source="test")
    assert result == {"ok": True}
    assert calls == ["movies"]


@pytest.mark.asyncio
async def test_source_action_aliases_library_to_mopidy(monkeypatch):
    import actions
    calls = []

    async def fake_library(d):
        calls.append("library")

    monkeypatch.setitem(actions._HANDLERS, ("library", "short_press"),
                        fake_library)
    d = actions.Dispatcher(mopidy=None, state=None, kiosk=None,
                           recorder=None, display=None, sleep=None)
    # both "library" and "mopidy" must route to the library handler
    await actions.fire(d, "source", "mopidy", source="test")
    await actions.fire(d, "source", "library", source="test")
    assert calls == ["library", "library"]


@pytest.mark.asyncio
async def test_source_action_unknown_value_returns_error():
    import actions
    d = actions.Dispatcher(mopidy=None, state=None, kiosk=None,
                           recorder=None, display=None, sleep=None)
    result = await actions.fire(d, "source", "nonsense", source="test")
    assert result["ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_actions.py -k source -v`
Expected: FAIL — `actions.fire` returns `{"ok": False, "error": "unknown_action:source"}`

- [ ] **Step 3: Implement the `source` handler**

In `services/actions.py`, add after `_h_skin` (after line 262):

```python
# Source switch — value-parameterized umbrella over the per-source handlers.
# The CYD firmware and the PWA send {"action": "source", "value": "<name>"};
# this routes to the existing single-source handlers so there is one code
# path. "library" and "mopidy" are aliases for the same handler.
_SOURCE_ALIASES = {
    "mopidy": "library",
    "library": "library",
    "airplay": "airplay",
    "spotify": "spotify",
    "bluetooth": "bluetooth",
    "movies": "movies",
}


@_handler("source")
async def _h_source(d: Dispatcher, value=None):
    target = _SOURCE_ALIASES.get(str(value).lower()) if value else None
    if target is None:
        raise ValueError(f"unknown source: {value!r}")
    handler = _HANDLERS.get((target, "short_press"))
    if handler is not None:
        await handler(d)
```

Note: `fire()` already turns a raised exception into `{"ok": False, "error": "handler_raised"}` (line 392-394), so the unknown-value case returns an error dict as the test expects.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest services/tests/test_actions.py -k source -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Run the full actions suite for regressions**

Run: `pytest services/tests/test_actions.py -v`
Expected: PASS — all green

- [ ] **Step 6: Commit**

```bash
git add services/actions.py services/tests/test_actions.py
git commit -m "feat(actions): source action — value-parameterized source switch"
```

---

## Task 5: `remote_files.py` + file endpoints

Migrate the file surface from `boombox-uploader.py` into a focused module, re-gated behind the bearer token (the enable-gate from Task 2 already covers it). The path-safety helpers are security-critical and `boombox-uploader.py` is deleted in Task 9, so they are reproduced in full here.

**Files:**
- Create: `services/remote_files.py`
- Modify: `services/boombox-remote.py` (register routes; pass nothing extra — the module is self-contained)
- Test: `services/tests/test_remote_files.py`

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_files.py`:

```python
"""Tests for /api/remote/files/* (services/remote_files.py)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def files_app(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    (music / "Album").mkdir(parents=True)
    (music / "Album" / "track.mp3").write_bytes(b"id3data")
    monkeypatch.setenv("BOOMBOX_MUSIC_DIR", str(music))
    monkeypatch.setenv("BOOMBOX_VIDEO_DIR", str(tmp_path / "Videos"))
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    return boombox_remote.create_app(), music


@pytest.mark.asyncio
async def test_browse_lists_dir(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/browse?path=",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    names = [e["name"] for e in body["entries"]]
    assert "Album" in names


@pytest.mark.asyncio
async def test_browse_rejects_traversal(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/browse?path=../../etc",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_browse_requires_token(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/browse?path=")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_download_streams_file(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/download/Album/track.mp3",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert await resp.read() == b"id3data"


@pytest.mark.asyncio
async def test_delete_removes_file(files_app, aiohttp_client):
    app, music = files_app
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/files/delete",
                             json={"path": "Album/track.mp3"},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert not (music / "Album" / "track.mp3").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_remote_files.py -v`
Expected: FAIL — 404 on every route (not registered)

- [ ] **Step 3: Create `services/remote_files.py`**

Create `services/remote_files.py`. The path-safety helpers (`safe_filename`, `unique_path`, `safe_compose`, `under_root`, `browse_dir`, `_count_audio_recursive`) and the ext sets are copied verbatim from `boombox-uploader.py` (lines 44-202) — they are correct and security-reviewed; do not rewrite them. The handlers are new (bearer-token gated, registered under `/api/remote/files/`):

```python
"""File surface for boombox-remote — browse / download / upload / delete.

Migrated from the retired boombox-uploader. The path-safety helpers are
unchanged from that service (security-reviewed); only the auth model
changed — these routes sit behind boombox-remote's bearer-token middleware
instead of the old PIN cookie.
"""
from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from pathlib import Path

from aiohttp import web

log = logging.getLogger("boombox-remote")

HOME = Path(os.environ.get("HOME", str(Path.home())))


def _music_root() -> Path:
    return Path(os.environ.get("BOOMBOX_MUSIC_DIR", str(HOME / "Music")))


def _video_root() -> Path:
    return Path(os.environ.get("BOOMBOX_VIDEO_DIR", str(HOME / "Videos")))


AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wav", ".aiff", ".alac", ".wma",
}
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".wmv",
    ".mpg", ".mpeg", ".ts", ".3gp",
}
ALLOWED_EXTS = AUDIO_EXTS | VIDEO_EXTS
MAX_FILE_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB cap per file (movies)
SCAN_TRIGGER_URL = "http://127.0.0.1:6681/library/scan"
JELLYFIN_KEY_FILE = Path(os.environ.get(
    "BOOMBOX_JELLYFIN_KEY", "/etc/boombox/jellyfin-api-key"))


def safe_filename(name: str) -> str:
    """Strip directory components, leave a sane filename."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = name.strip().lstrip(".")
    return name or "untitled"


def unique_path(target: Path) -> Path:
    """Return target if free, else target with -1, -2... before the ext."""
    if not target.exists():
        return target
    stem, ext = target.stem, target.suffix
    n = 1
    while True:
        cand = target.with_name(f"{stem}-{n}{ext}")
        if not cand.exists():
            return cand
        n += 1


def safe_compose(root: Path, rel_path: str) -> Path | None:
    """Compose root / rel_path, rejecting '..' segments or absolute paths.

    Deliberately does NOT call .resolve() — there are intentional symlinks
    under MUSIC_ROOT/.usb/ pointing at mounted USB drives; symlink targets
    are root-trusted. Returns None if the path is unsafe.
    """
    parts: list[str] = []
    for seg in rel_path.replace("\\", "/").split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            return None
        if "/" in seg or seg.startswith("/"):
            return None
        parts.append(seg)
    return root.joinpath(*parts) if parts else root


def under_root(p: Path, root: Path) -> bool:
    """True iff p resolves to somewhere inside root. Used for upload/delete
    targets, where we DO want resolve() to catch symlink tricks."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _count_audio_recursive(d: Path, limit: int = 5000) -> int:
    """Count audio files under d, capped so a multi-thousand-file drive
    doesn't make the listing slow."""
    n = 0
    try:
        for p in d.rglob("*"):
            try:
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                    n += 1
                    if n >= limit:
                        return n
            except OSError:
                continue
    except OSError:
        pass
    return n


def browse_dir(rel_path: str) -> dict:
    """Directory listing at MUSIC_ROOT / rel_path. Hidden entries skipped
    except the special '.usb' mount-link folder."""
    root = _music_root()
    target = safe_compose(root, rel_path)
    if target is None or not target.is_dir():
        return {"error": "not a directory"}
    rel_parts = [s for s in rel_path.replace("\\", "/").split("/")
                 if s and s != "."]
    rel_str = "/".join(rel_parts)
    parent_str = "/".join(rel_parts[:-1])
    dirs: list[dict] = []
    files: list[dict] = []
    try:
        for entry in target.iterdir():
            name = entry.name
            if name.startswith(".") and name != ".usb":
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": name, "kind": "dir",
                                 "tracks": _count_audio_recursive(entry)})
                elif entry.is_file() and entry.suffix.lower() in AUDIO_EXTS:
                    st = entry.stat()
                    files.append({
                        "name": name, "kind": "file", "size": st.st_size,
                        "mtime": int(st.st_mtime),
                        "deletable": under_root(entry, root),
                    })
            except (OSError, ValueError):
                continue
    except PermissionError:
        return {"error": "permission denied"}
    dirs.sort(key=lambda r: r["name"].lower())
    files.sort(key=lambda r: r["name"].lower())
    return {"path": rel_str, "parent": parent_str if rel_str else None,
            "entries": dirs + files}


async def _trigger_scan() -> None:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(SCAN_TRIGGER_URL,
                         timeout=aiohttp.ClientTimeout(total=2))
    except Exception as e:
        log.debug("scan trigger failed: %s", e)


async def _trigger_jellyfin_scan() -> None:
    try:
        token = JELLYFIN_KEY_FILE.read_text().strip()
    except (FileNotFoundError, OSError):
        return
    if not token:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post("http://127.0.0.1:8096/Library/Refresh",
                         headers={"X-MediaBrowser-Token": token},
                         timeout=aiohttp.ClientTimeout(total=3))
    except Exception as e:
        log.debug("jellyfin scan trigger failed: %s", e)


# ---- handlers (bearer-token gated by boombox-remote's middleware) --------

async def browse(request: web.Request) -> web.Response:
    rel = (request.query.get("path", "") or "").strip("/").replace("\\", "/")
    result = browse_dir(rel)
    if "error" in result:
        return web.json_response(result, status=404)
    return web.json_response(result)


async def download(request: web.Request) -> web.StreamResponse:
    rel = urllib.parse.unquote(request.match_info.get("path", ""))
    target = safe_compose(_music_root(), rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(target)


async def upload(request: web.Request) -> web.Response:
    music_uploads = _music_root() / "uploads"
    video_uploads = _video_root() / "uploads"
    music_uploads.mkdir(parents=True, exist_ok=True)
    video_uploads.mkdir(parents=True, exist_ok=True)
    saved_audio: list[str] = []
    saved_video: list[str] = []
    reader = await request.multipart()
    async for part in reader:
        if part.name != "file" or not part.filename:
            continue
        name = safe_filename(part.filename)
        ext = Path(name).suffix.lower()
        if ext in AUDIO_EXTS:
            dest_dir, dest_root, bucket = (music_uploads, _music_root(),
                                           saved_audio)
        elif ext in VIDEO_EXTS:
            dest_dir, dest_root, bucket = (video_uploads, _video_root(),
                                           saved_video)
        else:
            return web.json_response(
                {"error": f"unsupported type: {ext}"}, status=400)
        target = unique_path(dest_dir / name)
        if not under_root(target, dest_root):
            return web.json_response({"error": "bad path"}, status=400)
        size = 0
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
        log.info("uploaded %s (%d bytes)", target, size)
        bucket.append(str(target.relative_to(dest_root)))
    if saved_audio:
        asyncio.create_task(_trigger_scan())
    if saved_video:
        asyncio.create_task(_trigger_jellyfin_scan())
    return web.json_response({"saved": saved_audio + saved_video})


async def delete(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    rel = str(body.get("path", "") or "").strip("/").replace("\\", "/")
    root = _music_root()
    target = safe_compose(root, rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    if not under_root(target, root):
        return web.json_response(
            {"error": "USB and symlinked files are read-only"}, status=403)
    if target.suffix.lower() not in ALLOWED_EXTS:
        return web.json_response({"error": "unsupported file type"},
                                 status=400)
    try:
        target.unlink()
    except OSError as e:
        return web.json_response({"error": str(e)}, status=500)
    asyncio.create_task(_trigger_scan())
    return web.json_response({"deleted": rel})


def add_routes(app: web.Application) -> None:
    """Register /api/remote/files/* on the given app."""
    app.router.add_get("/api/remote/files/browse", browse)
    app.router.add_get("/api/remote/files/download/{path:.+}", download)
    app.router.add_post("/api/remote/files/upload", upload)
    app.router.add_post("/api/remote/files/delete", delete)
```

- [ ] **Step 4: Wire the routes into boombox-remote.py**

In `services/boombox-remote.py`, add `import remote_files` to the imports block. In `create_app`, after the existing `add_*` route registrations (after line 237), add:

```python
    remote_files.add_routes(app)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest services/tests/test_remote_files.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Commit**

```bash
git add services/remote_files.py services/boombox-remote.py services/tests/test_remote_files.py
git commit -m "feat(remote): files API — browse/download/upload/delete"
```

---

## Task 6: `remote_library.py` + library/playlist/queue endpoints

Server-side wrappers over Mopidy JSON-RPC so the PWA never speaks Mopidy directly. Uses `clients.MopidyRpc` (already in the repo, `services/clients.py:29`).

**Files:**
- Create: `services/remote_library.py`
- Modify: `services/boombox-remote.py` (wire routes; pass the shared `ClientSession`)
- Test: `services/tests/test_remote_library.py`

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_library.py`:

```python
"""Tests for /api/remote/library, /playlists, /queue (remote_library.py)."""
from __future__ import annotations

import json

import pytest


class FakeMopidy:
    """Stand-in for clients.MopidyRpc — records calls, returns canned data."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    async def call(self, method, params=None):
        self.calls.append((method, params or {}))
        return self.responses.get(method, {"result": None})


@pytest.fixture
def library_app(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    fake = FakeMopidy()
    import boombox_remote
    app = boombox_remote.create_app()
    import remote_library
    remote_library.add_routes(app, fake)
    return app, fake


@pytest.mark.asyncio
async def test_search_returns_tracks(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.library.search"] = {"result": [
        {"tracks": [{"uri": "local:track:a", "name": "Song A",
                     "artists": [{"name": "Band"}]}]},
    ]}
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/library/search?q=song",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    assert body["tracks"][0]["uri"] == "local:track:a"
    assert ("core.library.search", {"query": {"any": ["song"]}}) in fake.calls


@pytest.mark.asyncio
async def test_search_missing_q_returns_400(library_app, aiohttp_client):
    app, _ = library_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/library/search",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_list_playlists(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.playlists.as_list"] = {"result": [
        {"name": "Road trip", "uri": "m3u:road.m3u"},
    ]}
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/playlists",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert (await resp.json())["playlists"][0]["name"] == "Road trip"


@pytest.mark.asyncio
async def test_create_playlist_round_trip(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.playlists.create"] = {
        "result": {"name": "New", "uri": "m3u:new.m3u", "tracks": []}}
    fake.responses["core.playlists.save"] = {
        "result": {"name": "New", "uri": "m3u:new.m3u"}}
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/playlists",
                             json={"name": "New",
                                   "uris": ["local:track:a"]},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    methods = [m for m, _ in fake.calls]
    assert "core.playlists.create" in methods
    assert "core.playlists.save" in methods


@pytest.mark.asyncio
async def test_queue_replaces_and_plays(library_app, aiohttp_client):
    app, fake = library_app
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/queue",
                             json={"uris": ["local:track:a"], "play": True},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    methods = [m for m, _ in fake.calls]
    assert methods == ["core.tracklist.clear", "core.tracklist.add",
                       "core.playback.play"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_remote_library.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'remote_library'`

- [ ] **Step 3: Create `services/remote_library.py`**

```python
"""Library + playlist + queue surface for boombox-remote.

Thin server-side wrappers over Mopidy JSON-RPC so the PWA talks only to
/api/remote/* with one bearer token and never reaches Mopidy directly.
The Mopidy client is injected (clients.MopidyRpc) so it is trivially
mockable in tests.
"""
from __future__ import annotations

import logging

from aiohttp import web

log = logging.getLogger("boombox-remote")


def _track_summary(t: dict) -> dict:
    """Flatten a Mopidy track into the shape the PWA renders."""
    return {
        "uri": t.get("uri"),
        "title": t.get("name"),
        "artist": ", ".join(a.get("name", "") for a in t.get("artists") or [])
                  or None,
        "album": (t.get("album") or {}).get("name"),
        "duration_s": (t.get("length") or 0) // 1000,
    }


def _make_handlers(mopidy):
    async def search(request: web.Request) -> web.Response:
        q = (request.query.get("q") or "").strip()
        if not q:
            return web.json_response({"ok": False, "error": "missing_q"},
                                     status=400)
        res = await mopidy.call("core.library.search",
                                {"query": {"any": [q]}})
        results = res.get("result") or []
        tracks = [_track_summary(t) for group in results
                  for t in (group.get("tracks") or [])][:80]
        return web.json_response({"ok": True, "tracks": tracks})

    async def list_playlists(request: web.Request) -> web.Response:
        res = await mopidy.call("core.playlists.as_list")
        refs = res.get("result") or []
        return web.json_response({
            "ok": True,
            "playlists": [{"name": r.get("name"), "uri": r.get("uri")}
                          for r in refs],
        })

    async def create_playlist(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        name = (body or {}).get("name") if isinstance(body, dict) else None
        uris = (body or {}).get("uris") if isinstance(body, dict) else None
        if not name or not isinstance(uris, list) or not uris:
            return web.json_response(
                {"ok": False, "error": "name_and_uris_required"}, status=400)
        created = (await mopidy.call(
            "core.playlists.create",
            {"name": name, "uri_scheme": "m3u"})).get("result")
        if not created:
            return web.json_response({"ok": False, "error": "create_failed"},
                                     status=502)
        created["tracks"] = [{"uri": u} for u in uris]
        saved = (await mopidy.call(
            "core.playlists.save", {"playlist": created})).get("result")
        if not saved:
            return web.json_response({"ok": False, "error": "save_failed"},
                                     status=502)
        await mopidy.call("core.playlists.refresh", {"uri_scheme": "m3u"})
        return web.json_response({"ok": True, "uri": saved.get("uri"),
                                  "name": saved.get("name")})

    async def playlist_items(request: web.Request) -> web.Response:
        uri = request.match_info["uri"]
        res = await mopidy.call("core.playlists.get_items", {"uri": uri})
        items = res.get("result") or []
        return web.json_response({
            "ok": True,
            "uris": [it.get("uri") for it in items if it.get("uri")],
        })

    async def queue(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        uris = (body or {}).get("uris") if isinstance(body, dict) else None
        if not isinstance(uris, list) or not uris:
            return web.json_response({"ok": False, "error": "uris_required"},
                                     status=400)
        play = bool((body or {}).get("play", True))
        await mopidy.call("core.tracklist.clear")
        await mopidy.call("core.tracklist.add", {"uris": uris})
        if play:
            await mopidy.call("core.playback.play")
        return web.json_response({"ok": True})

    return search, list_playlists, create_playlist, playlist_items, queue


def add_routes(app: web.Application, mopidy) -> None:
    """Register library/playlist/queue routes. `mopidy` is a
    clients.MopidyRpc (or any object with an async .call(method, params))."""
    search, list_pls, create_pl, pl_items, queue = _make_handlers(mopidy)
    app.router.add_get("/api/remote/library/search", search)
    app.router.add_get("/api/remote/playlists", list_pls)
    app.router.add_post("/api/remote/playlists", create_pl)
    app.router.add_get("/api/remote/playlists/{uri}/items", pl_items)
    app.router.add_post("/api/remote/queue", queue)
```

- [ ] **Step 4: Wire it in `boombox-remote.py`'s `main()`**

The test injects a fake Mopidy via `add_routes(app, fake)`. Production wires the real one in `main()`. In `services/boombox-remote.py`, `main()` already builds a `clients.MopidyRpc(session)` for the dispatcher (line 453). After `app = create_app(...)` (line 461), add:

```python
        import remote_library
        remote_library.add_routes(app, clients.MopidyRpc(session))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest services/tests/test_remote_library.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Commit**

```bash
git add services/remote_library.py services/boombox-remote.py services/tests/test_remote_library.py
git commit -m "feat(remote): library/playlists/queue API over Mopidy"
```

---

## Task 7: `jellyfin_client.py` + video endpoints

Server-side Jellyfin REST proxy. The PWA gets video transport without Jellyfin creds or CORS in the browser.

**Files:**
- Create: `services/jellyfin_client.py`
- Modify: `services/boombox-remote.py` (wire routes in `main()`)
- Test: `services/tests/test_remote_video.py`

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_video.py`:

```python
"""Tests for /api/remote/video/* (services/jellyfin_client.py)."""
from __future__ import annotations

import json

import pytest


class FakeJellyfin:
    """Stand-in for jellyfin_client.JellyfinClient."""

    def __init__(self, state=None):
        self._state = state or {"active": False}
        self.commands = []

    async def local_session_state(self):
        return self._state

    async def command(self, action, value=None):
        self.commands.append((action, value))
        return {"ok": True}


@pytest.fixture
def video_app(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    app = boombox_remote.create_app()
    return app


@pytest.mark.asyncio
async def test_state_reports_inactive(video_app, aiohttp_client):
    import jellyfin_client
    fake = FakeJellyfin({"active": False})
    jellyfin_client.add_routes(video_app, fake)
    client = await aiohttp_client(video_app)
    resp = await client.get("/api/remote/video/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert (await resp.json())["active"] is False


@pytest.mark.asyncio
async def test_state_reports_playing(video_app, aiohttp_client):
    import jellyfin_client
    fake = FakeJellyfin({"active": True, "playing": True, "title": "Sintel",
                         "position_s": 12, "duration_s": 888,
                         "volume": 80, "muted": False})
    jellyfin_client.add_routes(video_app, fake)
    client = await aiohttp_client(video_app)
    resp = await client.get("/api/remote/video/state",
                            headers={"Authorization": "Bearer t"})
    body = await resp.json()
    assert body["title"] == "Sintel"
    assert body["playing"] is True


@pytest.mark.asyncio
async def test_command_maps_play_pause(video_app, aiohttp_client):
    import jellyfin_client
    fake = FakeJellyfin()
    jellyfin_client.add_routes(video_app, fake)
    client = await aiohttp_client(video_app)
    resp = await client.post("/api/remote/video/command",
                             json={"action": "play_pause"},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert fake.commands == [("play_pause", None)]


@pytest.mark.asyncio
async def test_command_rejects_unknown_action(video_app, aiohttp_client):
    import jellyfin_client
    fake = FakeJellyfin()
    jellyfin_client.add_routes(video_app, fake)
    client = await aiohttp_client(video_app)
    resp = await client.post("/api/remote/video/command",
                             json={"action": "explode"},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_remote_video.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jellyfin_client'`

- [ ] **Step 3: Create `services/jellyfin_client.py`**

```python
"""Jellyfin REST proxy for boombox-remote — video transport control.

boombox-remote calls Jellyfin server-side with the stored API key so the
PWA never sees Jellyfin credentials or hits CORS. Targets the Jellyfin
"session" running on the boombox's own kiosk Chromium.

Jellyfin API reference used here:
  GET  /Sessions                          → active sessions
  POST /Sessions/{id}/Playing/PlayPause   → toggle
  POST /Sessions/{id}/Playing/Stop
  POST /Sessions/{id}/Playing/NextTrack
  POST /Sessions/{id}/Playing/PreviousTrack
  POST /Sessions/{id}/Playing/Seek?seekPositionTicks=<100ns ticks>
  POST /Sessions/{id}/Command  body {"Name": "SetVolume", "Arguments": {...}}
  POST /Sessions/{id}/Command  body {"Name": "Mute" | "Unmute"}
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import aiohttp
from aiohttp import web

log = logging.getLogger("boombox-remote")

JELLYFIN_BASE = os.environ.get("BOOMBOX_JELLYFIN_BASE",
                               "http://127.0.0.1:8096")
JELLYFIN_KEY_FILE = Path(os.environ.get(
    "BOOMBOX_JELLYFIN_KEY", "/etc/boombox/jellyfin-api-key"))
_TICKS_PER_SECOND = 10_000_000

# action → (HTTP path suffix under /Sessions/{id}/Playing, or "Command")
_PLAYING_ACTIONS = {
    "play_pause": "PlayPause",
    "stop": "Stop",
    "next": "NextTrack",
    "previous": "PreviousTrack",
}
_VALID_ACTIONS = set(_PLAYING_ACTIONS) | {"seek", "volume", "mute"}


class JellyfinClient:
    """Talks to the local Jellyfin server with the boombox-managed API key."""

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    def _token(self) -> str | None:
        try:
            return JELLYFIN_KEY_FILE.read_text().strip() or None
        except (FileNotFoundError, OSError):
            return None

    def _headers(self) -> dict | None:
        tok = self._token()
        return {"X-MediaBrowser-Token": tok} if tok else None

    async def _local_session(self) -> dict | None:
        """Return the Jellyfin session running on this device, or None.

        Heuristic: prefer a session whose RemoteEndPoint is loopback (the
        kiosk Chromium); fall back to the most recently active session.
        """
        headers = self._headers()
        if headers is None:
            return None
        try:
            async with self._sess.get(
                    f"{JELLYFIN_BASE}/Sessions", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=2)) as r:
                if r.status != 200:
                    return None
                sessions = await r.json()
        except Exception as e:
            log.debug("jellyfin /Sessions failed: %s", e)
            return None
        playing = [s for s in sessions if s.get("NowPlayingItem")]
        if not playing:
            return None
        local = [s for s in playing
                 if str(s.get("RemoteEndPoint", "")).startswith("127.")
                 or str(s.get("RemoteEndPoint", "")) in ("::1", "localhost")]
        pool = local or playing
        pool.sort(key=lambda s: s.get("LastActivityDate", ""), reverse=True)
        return pool[0]

    async def local_session_state(self) -> dict:
        """Consolidated state for the local Jellyfin session."""
        s = await self._local_session()
        if s is None:
            return {"active": False}
        item = s.get("NowPlayingItem") or {}
        play = s.get("PlayState") or {}
        runtime_ticks = item.get("RunTimeTicks") or 0
        position_ticks = play.get("PositionTicks") or 0
        return {
            "active": True,
            "playing": not play.get("IsPaused", False),
            "title": item.get("Name"),
            "position_s": position_ticks // _TICKS_PER_SECOND,
            "duration_s": runtime_ticks // _TICKS_PER_SECOND,
            "volume": play.get("VolumeLevel"),
            "muted": bool(play.get("IsMuted", False)),
        }

    async def command(self, action: str, value=None) -> dict:
        """Map a remote command onto the Jellyfin session API."""
        headers = self._headers()
        if headers is None:
            return {"ok": False, "error": "jellyfin_unconfigured"}
        s = await self._local_session()
        if s is None:
            return {"ok": False, "error": "no_session"}
        sid = s.get("Id")
        base = f"{JELLYFIN_BASE}/Sessions/{sid}"
        try:
            if action in _PLAYING_ACTIONS:
                url = f"{base}/Playing/{_PLAYING_ACTIONS[action]}"
                await self._sess.post(url, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=2))
            elif action == "seek":
                ticks = int(float(value or 0) * _TICKS_PER_SECOND)
                url = (f"{base}/Playing/Seek"
                       f"?seekPositionTicks={ticks}")
                await self._sess.post(url, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=2))
            elif action == "volume":
                await self._sess.post(
                    f"{base}/Command", headers=headers,
                    json={"Name": "SetVolume",
                          "Arguments": {"Volume": str(int(value or 0))}},
                    timeout=aiohttp.ClientTimeout(total=2))
            elif action == "mute":
                await self._sess.post(
                    f"{base}/Command", headers=headers,
                    json={"Name": "ToggleMute"},
                    timeout=aiohttp.ClientTimeout(total=2))
            else:
                return {"ok": False, "error": f"unknown_action:{action}"}
        except Exception as e:
            log.warning("jellyfin command %s failed: %s", action, e)
            return {"ok": False, "error": "jellyfin_unreachable"}
        return {"ok": True}


def _make_handlers(client):
    async def state(request: web.Request) -> web.Response:
        return web.json_response(await client.local_session_state())

    async def command(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        action = (body or {}).get("action") if isinstance(body, dict) else None
        if action not in _VALID_ACTIONS:
            return web.json_response(
                {"ok": False, "error": "bad_action"}, status=400)
        result = await client.command(action, (body or {}).get("value"))
        status = 200 if result.get("ok") else 502
        return web.json_response(result, status=status)

    return state, command


def add_routes(app: web.Application, client) -> None:
    """Register /api/remote/video/* . `client` is a JellyfinClient (or any
    object with async local_session_state() and command(action, value))."""
    state, command = _make_handlers(client)
    app.router.add_get("/api/remote/video/state", state)
    app.router.add_post("/api/remote/video/command", command)
```

- [ ] **Step 4: Wire it in `boombox-remote.py`'s `main()`**

In `services/boombox-remote.py` `main()`, after the `remote_library.add_routes(...)` line from Task 6:

```python
        import jellyfin_client
        jellyfin_client.add_routes(
            app, jellyfin_client.JellyfinClient(session))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest services/tests/test_remote_video.py -v`
Expected: PASS — 4 passed

- [ ] **Step 6: Commit**

```bash
git add services/jellyfin_client.py services/boombox-remote.py services/tests/test_remote_video.py
git commit -m "feat(remote): video API — Jellyfin session transport proxy"
```

---

## Task 8: theme in the consolidated state payload

`StateAggregator.consolidated_state()` currently returns `"skin": None` (line 218). Pull `boombox-state`'s `GET /theme` and populate `skin` + a new `theme` object so the PWA restyles live over the WS.

**Files:**
- Modify: `services/boombox-remote.py` (`StateAggregator`, lines 159-219)
- Test: `services/tests/test_remote_state.py` (add to the existing file)

- [ ] **Step 1: Write the failing test**

`test_remote_state.py` uses a hand-written `StubAggregator`, not the real `StateAggregator`. This new test builds the real one and replaces its sub-clients with fakes so `consolidated_state()` runs without network. Add to `services/tests/test_remote_state.py` (`import sys` at the top of the file if not already present):

```python
@pytest.mark.asyncio
async def test_consolidated_state_includes_theme():
    import boombox_remote  # noqa: F401 — loads the impl module
    mod = sys.modules["boombox_remote_impl"]

    agg = mod.StateAggregator(session=None, boombox_id="b", boombox_name="B")

    class FakeMopidy:
        async def call(self, method, params=None):
            return {"result": None}

    class FakeState:
        async def current_source(self):
            return "mopidy"

        async def volume_get(self):
            return (0.65, False)

        async def karaoke_state(self):
            return False

    async def fake_theme():
        return {"skinId": "spectrum", "name": "Spectrum",
                "theme": {"bg": "#000", "accent": "#0ff"}}

    agg._mopidy = FakeMopidy()
    agg._state = FakeState()
    agg._fetch_theme = fake_theme

    data = await agg.consolidated_state()
    assert data["skin"] == "spectrum"
    assert data["theme"] == {"bg": "#000", "accent": "#0ff"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest services/tests/test_remote_state.py::test_consolidated_state_includes_theme -v`
Expected: FAIL — `consolidated_state` has no `_fetch_theme` to call / `theme` key missing from the payload

- [ ] **Step 3: Implement theme fetching in `StateAggregator`**

In `services/boombox-remote.py`, add a `_fetch_theme` method to `StateAggregator` (after `consolidated_state`, ~line 219):

```python
    async def _fetch_theme(self) -> dict:
        """Pull the active theme from boombox-state. Returns {} on failure —
        the PWA falls back to its built-in default styling."""
        try:
            async with self._sess.get(
                    "http://127.0.0.1:6681/theme",
                    timeout=aiohttp_client_lib.ClientTimeout(total=1.5)) as r:
                if r.status != 200:
                    return {}
                return await r.json()
        except Exception:
            return {}
```

In `consolidated_state()`, add the theme fetch to the existing `asyncio.gather` block (line 178-187) — append `self._fetch_theme()` as the last coroutine and unpack it:

```python
        (source, track_info, state_info, position_info, vol_info, karaoke,
         theme_payload) = await asyncio.gather(
            self._state.current_source(),
            self._mopidy.call("core.playback.get_current_track"),
            self._mopidy.call("core.playback.get_state"),
            self._mopidy.call("core.playback.get_time_position"),
            self._state.volume_get(),
            self._state.karaoke_state(),
            self._fetch_theme(),
        )
```

Then replace the `"skin": None,` line (line 218) with:

```python
            "skin":  theme_payload.get("skinId"),
            "theme": theme_payload.get("theme") or {},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest services/tests/test_remote_state.py -v`
Expected: PASS — the new theme test passes, existing state tests still pass

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_state.py
git commit -m "feat(remote): include skin + theme in the state payload"
```

---

## Task 9: retire `boombox-uploader`

Delete the service, its unit, its nginx block, and `boombox-state`'s `/upload/*` plumbing. Tasks 5–8 already moved every still-wanted capability into `boombox-remote`.

**Files:**
- Delete: `services/boombox-uploader.py`, `install/systemd/user/boombox-uploader.service`
- Modify: `install/config/nginx-boombox-common.conf` (lines 83-99), `install/install.sh` (lines 399-400), `services/boombox-state.py` (the `/upload/*` section ~lines 622-737 + route registrations ~lines 984-986)

- [ ] **Step 1: Delete the uploader service and unit**

```bash
git rm services/boombox-uploader.py install/systemd/user/boombox-uploader.service
```

- [ ] **Step 2: Remove the `/upload/` nginx block**

In `install/config/nginx-boombox-common.conf`, delete the entire `# boombox-uploader ...` comment block and `location /upload/ { ... }` (lines 83-99).

In the same file, add upload limits to the existing `location /api/remote/` block (after line 67, `proxy_set_header X-Real-IP $remote_addr;`):

```nginx
    client_max_body_size 1100M;
    proxy_request_buffering off;     # stream uploads, don't buffer to /tmp
```

- [ ] **Step 3: Remove `/upload/*` from `boombox-state.py`**

In `services/boombox-state.py`, delete the `upload_status`, `upload_enable`, `upload_disable` handlers and the `UPLOADER_UNIT` / `UPLOADER_PIN_FILE` / `_read_pin` / `_systemctl_user` plumbing that exists only to serve them (the section starting at the `# Access (/upload, ...)` comment, ~line 622, through `upload_disable`, ~line 737 — keep anything in that range still used by USB/library endpoints; `_primary_lan_ip` and `_read_web_auth` are reused elsewhere, leave those). Remove the three route registrations:

```python
    app.router.add_get("/upload/status", upload_status)
    app.router.add_post("/upload/enable", upload_enable)
    app.router.add_post("/upload/disable", upload_disable)
```

Run `grep -n "upload\|UPLOADER" services/boombox-state.py` afterwards and confirm only unrelated matches remain (e.g. USB copy text). If `_read_web_auth` / `_primary_lan_ip` / `_systemctl_user` become unused after this, delete them too.

- [ ] **Step 4: Clean the install.sh comment**

In `install/install.sh`, delete the now-stale comment (lines 399-400):

```bash
# boombox-uploader is intentionally NOT enabled — it's toggled by the
# touchscreen Settings drawer.
```

The unit-install glob (`install -m 0644 .../systemd/user/*.service`) and the `USER_UNITS` enable loop need no change — there is simply no `boombox-uploader.service` file to install or enable anymore.

- [ ] **Step 5: Verify nothing else references the uploader**

Run: `grep -rn "boombox-uploader\|boombox_uploader\|/upload/\|UPLOADER" services/ install/ --include='*.py' --include='*.sh' --include='*.conf' --include='*.service'`
Expected: no matches (the kiosk SPA references in `ui/` are handled in Task 10).

- [ ] **Step 6: Run the full Python suite + nginx syntax check**

Run: `pytest services/tests/ -q && sudo nginx -t -c /dev/stdin <<< 'events{} http{ server{ include '"$PWD"'/install/config/nginx-boombox-common.conf; } }'` — if `nginx` isn't available on the dev box, skip the nginx check (it runs in `apply-release.sh preflight` on the Pi).
Expected: pytest all green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(remote): retire boombox-uploader — folded into boombox-remote"
```

---

## Task 10: kiosk SPA — Phone Remote panel + QR repoint

The Settings drawer's "Remote mode" section and the `QrOverlay` both call the dead `/api/upload/*` endpoints. Repoint them at `/api/remote/admin/*` and `/pair/start`.

**Files:**
- Modify: `ui/src/lib/SettingsDrawer.tsx` (lines 36-46 type, 67-68 state, 93-98 + 113 refresh, 168-178 toggle, 355-418 the section)
- Modify: `ui/src/overlays/QrOverlay.tsx`

- [ ] **Step 1: Replace the `UploadStatus` type and state in SettingsDrawer.tsx**

Replace the `UploadStatus` type (lines 36-46) with:

```tsx
type RemoteStatus = {
  ok?: boolean;
  enabled: boolean;
  peers: { label: string; paired_at: number }[];
};
```

Replace the state declarations (lines 67-68):

```tsx
  const [remote, setRemote] = useState<RemoteStatus | null>(null);
  const [remotePending, setRemotePending] = useState(false);
```

- [ ] **Step 2: Replace the refresh + toggle functions**

Replace `refreshUpload` (lines 93-98) with:

```tsx
  const refreshRemote = async () => {
    try {
      const r = await fetch("/api/remote/admin/status");
      if (r.ok) setRemote(await r.json());
    } catch { /* ignore */ }
  };
```

In the `useEffect` (lines 106-114), replace the two `refreshUpload()` calls with `refreshRemote()`.

Replace `toggleUpload` (lines 168-178) with:

```tsx
  const toggleRemote = async () => {
    if (!remote) return;
    setRemotePending(true);
    try {
      const url = remote.enabled
        ? "/api/remote/admin/disable"
        : "/api/remote/admin/enable";
      const r = await fetch(url, { method: "POST" });
      if (r.ok) await refreshRemote();
    } finally {
      setRemotePending(false);
    }
  };
```

- [ ] **Step 3: Replace the "Remote mode" section markup**

Replace the entire `{/* Remote mode */}` block (lines 355-418) with a Phone Remote panel: the toggle, and when enabled, the paired-device list with revoke buttons. The PIN is minted on demand via the existing `PairOverlay` (already wired to `setShowPair`).

```tsx
          {/* Phone remote */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{display: "flex", alignItems: "center", gap: 14, minHeight: 48}}>
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em"}}>Phone remote</div>
                <div style={{fontSize: 13, color: "rgba(255,255,255,0.65)", marginTop: 2}}>
                  {remote == null
                    ? "loading…"
                    : remote.enabled
                      ? `on — ${remote.peers.length} device${remote.peers.length === 1 ? "" : "s"} paired`
                      : "off — turn on to let phones pair and control the boombox"}
                </div>
              </div>
              <button
                onClick={toggleRemote}
                disabled={remote == null || remotePending}
                style={{
                  ...primaryButton(remote?.enabled ? "#ff7a35" : "#7afcb0"),
                  opacity: (remote == null || remotePending) ? 0.5 : 1,
                }}
              >{remote?.enabled ? "TURN OFF" : "TURN ON"}</button>
            </div>
            {remote?.enabled && (
              <div style={{marginTop: 12, display: "flex", flexDirection: "column", gap: 8}}>
                {remote.peers.length === 0 && (
                  <div style={{fontSize: 13, color: "rgba(255,255,255,0.5)"}}>
                    no devices paired yet — tap “Pair…” below
                  </div>
                )}
                {remote.peers.map(p => (
                  <div key={p.label + p.paired_at} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "8px 12px",
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 10,
                  }}>
                    <div style={{flex: 1, fontWeight: 600}}>{p.label}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
```

(Per-peer revoke needs the token, which `admin/status` does not return. Revoke is deferred to the Phase 2 PWA admin work — the panel lists paired devices; rotating remote access off/on is the v1 kill switch. Leave the list read-only here.)

- [ ] **Step 4: Repoint `QrOverlay.tsx`**

Replace `ui/src/overlays/QrOverlay.tsx` entirely:

```tsx
import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

export function QrOverlay() {
  const [visible, setVisible] = useState(false);
  const [url, setUrl] = useState<string>("");

  useEffect(() => {
    const onShow = async () => {
      // Turning on remote access is best-effort — the QR is still useful
      // even if the enable call fails (the user can toggle it in Settings).
      try {
        await fetch("/api/remote/admin/enable", { method: "POST" });
      } catch { /* ignore */ }
      setUrl(`http://${location.hostname}:8090/remote/`);
      setVisible(v => !v);
    };
    window.addEventListener("boombox:web-qr", onShow as EventListener);
    return () => window.removeEventListener("boombox:web-qr", onShow as EventListener);
  }, []);

  if (!visible || !url) return null;
  return (
    <div onClick={() => setVisible(false)} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9999,
    }}>
      <div style={{ display: "grid", gap: 12, placeItems: "center" }}>
        <div style={{ background: "white", padding: 16 }}>
          <QRCodeSVG value={url} size={320} />
        </div>
        <div style={{ fontSize: 18 }}>{url}</div>
        <div style={{ fontSize: 14, opacity: 0.7 }}>
          open on your phone, then pair with the PIN from Settings
        </div>
        <div style={{ fontSize: 12, opacity: 0.5 }}>tap to dismiss</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Build the SPA to verify it compiles**

Run: `cd ui && npm run build`
Expected: build succeeds, no TypeScript errors. (If `npm install` hasn't been run in `ui/`, run it first.)

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/SettingsDrawer.tsx ui/src/overlays/QrOverlay.tsx
git commit -m "feat(ui): Phone Remote settings panel + QR repointed at /remote/"
```

---

## Task 11: docs — `SERVICES.md`

Update the service reference: rewrite the `boombox-remote` section to cover the new surface, delete the `boombox-uploader` section.

**Files:**
- Modify: `docs/SERVICES.md`

- [ ] **Step 1: Update SERVICES.md**

Read `docs/SERVICES.md`. In the `boombox-remote` section (~lines 256-308 per the spec's exploration), add the new endpoints to the documented API surface: `/api/remote/admin/{status,enable,disable,unpair}` (localhost-only), `/api/remote/files/{browse,download,upload,delete}`, `/api/remote/library/search`, `/api/remote/playlists` (GET/POST), `/api/remote/playlists/{uri}/items`, `/api/remote/queue`, `/api/remote/video/{state,command}`. Document the `remote_enabled` flag (`~/.config/boombox-remote/state.json`, default off, gates the phone surface, not BLE) and the `BOOMBOX_REMOTE_STATE` env knob. Note that `skin` + `theme` are now in the state payload.

Delete the entire `boombox-uploader` section. Search the rest of the file for `boombox-uploader` / `/upload/` references and update them (e.g. any "ports in use" table — 6683 is now free).

- [ ] **Step 2: Verify no stale uploader references remain in docs**

Run: `grep -rn "boombox-uploader\|/upload/" docs/SERVICES.md`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add docs/SERVICES.md
git commit -m "docs(services): document the consolidated boombox-remote API"
```

---

## Final verification

- [ ] **Run the full Python test suite**

Run: `pytest services/tests/ -q`
Expected: all green — including the pre-existing `test_remote_*`, `test_actions`, `test_buttons_*`, `test_updater_*` suites (no regressions) plus the 6 new test files.

- [ ] **Build the kiosk SPA**

Run: `cd ui && npm run build`
Expected: success, no TypeScript errors.

- [ ] **Confirm the uploader is fully gone**

Run: `git ls-files | grep -i uploader`
Expected: no output.

---

## Self-Review (completed during planning)

**Spec coverage:**
- Backend consolidation / retire uploader → Tasks 5, 6, 7, 9
- `remote_enabled` flag, default off → Task 1
- Enable-gate (403 + ws 4403) → Task 2
- Admin routes, durable authorization → Task 3
- `source` action → Task 4
- File endpoints → Task 5
- Library/playlists/queue → Task 6
- Video proxy → Task 7
- Theme in state payload → Task 8
- nginx `/upload/` removal + `/api/remote/` upload limits → Task 9
- Kiosk SPA (SettingsDrawer + QrOverlay) → Task 10
- Docs → Task 11
- *Out of Phase 1 scope, by design:* the `remote-ui` PWA, the `/remote/` nginx location, the `remote-ui` build step in `install.sh`/`apply-release.sh`, the Vitest frontend tests, per-peer revoke UI — all Phase 2.

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. Task 9 is a deletion task; its "tests" are the full suite + nginx check (appropriate for a removal).

**Type consistency:** `remote_access.is_enabled()` / `set_enabled()` used consistently (Tasks 1, 2, 3). `add_routes(app, ...)` injection pattern consistent across `remote_files`, `remote_library`, `jellyfin_client` (Tasks 5, 6, 7). `RemoteStatus` shape in Task 10 matches `_get_admin_status`'s response in Task 3 (`{ok, enabled, peers: [{label, paired_at}]}`).
