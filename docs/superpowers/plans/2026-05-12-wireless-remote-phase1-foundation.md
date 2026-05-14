# Wireless remote — Phase 1: Foundation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Pi-side `boombox-remote` HTTP service that exposes the boombox's everyday control surface to any HTTP client (curl, future ESP32 firmware), and refactor `boombox-buttons.py` so GPIO and wireless paths share one action dispatcher.

**Architecture:** Extract three things from the existing 1100-line `boombox-buttons.py`: backend clients (`clients.py`), action dispatcher + handlers (`actions.py`), leaving the GPIO event loop in `boombox-buttons.py`. Build `boombox-remote.py` on top: aiohttp REST + WS, bearer-token auth, mDNS advertisement. No BLE, no ESP32 firmware, no USB installer in this phase — those are explicit follow-ups.

**Tech Stack:** Python 3.11+, aiohttp, python-zeroconf, Pillow (album art resize), pytest + pytest-asyncio. Runs as a systemd unit on the Pi, fronted by nginx.

---

## Roadmap: this is Phase 1 of 7

Each subsequent plan is a separate document, written after the prior phase lands and we have real feedback.

| Phase | Scope | Status |
|---|---|---|
| **1 (this plan)** | `actions.py` refactor + Pi `boombox-remote.py` HTTP/WS/mDNS | this plan |
| 2 | CYD firmware (HTTP-only, no BLE), shared `boombox-remote-core` library, PIN-pairing | next |
| 3 | USB firmware installer on the Pi (udev + esptool + kiosk overlay), USB fast-path pairing | depends on 2 |
| 4 | BLE primary transport — phase-0 spike, GATT server on Pi, NimBLE on CYD, transport switching | depends on 2 |
| 5 | Headless DIY profile + kiosk pin-map config UI | depends on 3 |
| 6 | External profile pack infrastructure (`/etc/boombox/firmware-profiles/`, manifest validation, `bin/boombox-firmware` CLI) | depends on 5 |
| 7 | ELECROW round profile (when user has hardware) | deferred |

**Phase 1 deliverable:** `curl -H "Authorization: Bearer <token>" http://boombox.local:6685/api/remote/state` returns full consolidated state; `POST /api/remote/command {"action":"next"}` skips to the next track. WebSocket pushes state on change. All 23 existing buttons tests still pass + new tests for every new endpoint.

---

## Architectural shape after Phase 1

```
services/
├── clients.py                # NEW — MopidyRpc, StateApi, KioskClient,
│                             #       Display, Recorder, SleepTimer
├── actions.py                # NEW — Dispatcher, _HANDLERS, all action
│                             #       handlers, fire(action, value, source)
├── boombox-buttons.py        # SHRUNK — GPIO event loop, PressClassifier,
│                             #          EncoderDecoder, main(), HTTP API
├── boombox_buttons.py        # UPDATED shim — re-exports from new modules
├── boombox-remote.py         # NEW — aiohttp REST + WS + mDNS, port 6685
├── boombox_remote.py         # NEW shim — for test imports
└── tests/
    ├── conftest.py           # UNCHANGED
    ├── test_buttons_*.py     # UNCHANGED — still pass after refactor
    ├── test_actions.py       # NEW — direct tests for actions.fire()
    └── test_remote_*.py      # NEW — tests for each remote endpoint

install/systemd/
└── boombox-remote.service    # NEW

install/nginx/
└── conf.d/boombox-remote     # NEW — route /api/remote/ → :6685

~/.config/boombox-remote/
└── peers.json                # NEW — runtime: {auth_token, paired_at, label}
```

---

## Conventions used throughout this plan

- **Working directory**: `/Users/jwc/code/Boombox/.claude/worktrees/wireless-remote` (the worktree). All paths are relative to this.
- **Python**: `.venv/bin/python` and `.venv/bin/pytest`. The venv was set up by the worktree skill.
- **Test commands**: `.venv/bin/pytest services/tests/ -q` for the full suite; `.venv/bin/pytest services/tests/test_X.py -v` for one file.
- **Commits**: one per task, conventional commit format (`refactor:`, `feat:`, `test:`, `docs:`).
- **Port**: `boombox-remote` listens on `127.0.0.1:6685` (next after buttons' 6684). Nginx fronts it.
- **Auth tokens**: each paired remote gets a 32-byte secret stored hex-encoded in `~/.config/boombox-remote/peers.json`. Phase 1 ships with a single bootstrap token; full pairing arrives in Phase 2.

---

## Stage 1 — Refactor `boombox-buttons.py` for sharing

These five tasks move code around without changing behavior. The 23 existing button tests are the regression net. Each task ends with `pytest services/tests/ -q` passing.

### Task 1: Extract `services/clients.py`

**Files:**
- Create: `services/clients.py`
- Modify: `services/boombox-buttons.py` (remove the moved classes, add import)
- Test: existing `services/tests/test_buttons_dispatch.py` is the regression net

The classes to move (with line ranges from the current file):
- `MopidyRpc` (465–482)
- `StateApi` (484–563)
- `KioskClient` (565–623)
- `Display` (625–702)
- `SleepTimer` (736–787)
- `Recorder` (789–850)

Module-level constants the classes depend on:
- `MOPIDY_RPC`, `STATE_BASE`, `KIOSK_BASE`, `KIOSK_WS` — move into `clients.py` (they're only used by the clients).

- [ ] **Step 1: Confirm baseline is green**

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `23 passed` (or whatever the current count is — record it as the regression target).

- [ ] **Step 2: Create `services/clients.py` with the moved classes**

```python
"""Backend clients used by the boombox action dispatcher.

Each class is a thin async wrapper over an upstream service:
- MopidyRpc:    Mopidy's JSON-RPC at :6680
- StateApi:     boombox-state aggregator at :6681
- KioskClient:  Chromium DevTools WS at :9222
- Display:      wlr-randr backlight on/off
- SleepTimer:   in-process sleep-timer state machine
- Recorder:     parec → flac subprocess manager
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("boombox-clients")

MOPIDY_RPC = os.environ.get("MOPIDY_RPC", "http://127.0.0.1:6680/mopidy/rpc")
STATE_BASE = os.environ.get("STATE_BASE", "http://127.0.0.1:6681")
KIOSK_BASE = os.environ.get("KIOSK_BASE", "http://127.0.0.1:9222")
KIOSK_WS   = os.environ.get("KIOSK_WS",   "ws://127.0.0.1:9222")


# --- paste the six class bodies here, in this order ---
# class MopidyRpc: ...
# class StateApi: ...
# class KioskClient: ...
# class Display: ...
# class SleepTimer: ...
# class Recorder: ...
```

Open `services/boombox-buttons.py`, copy each class body verbatim (no
behavior changes), and paste into `clients.py`. Each class's imports are
already covered by `clients.py`'s import block.

- [ ] **Step 3: Update `boombox-buttons.py` to import from `clients`**

In `services/boombox-buttons.py`:

1. Delete the six class definitions (lines 465–850 approximately).
2. Delete the four constants (`MOPIDY_RPC`, `STATE_BASE`, `KIOSK_BASE`, `KIOSK_WS`) at the top.
3. Add at the top, after the existing imports:

```python
from clients import (
    MopidyRpc, StateApi, KioskClient, Display, SleepTimer, Recorder,
    MOPIDY_RPC, STATE_BASE, KIOSK_BASE, KIOSK_WS,
)
```

The `from clients import` form works because `services/tests/conftest.py`
already adds `services/` to `sys.path`. The running service also imports
from its own dir.

- [ ] **Step 4: Run the regression suite**

Run: `.venv/bin/pytest services/tests/ -q`
Expected: same count as Step 1 — `23 passed`.

If anything fails, the culprit is almost always a missed import or a
constant the dispatcher needs that's still referenced by name in the
file. Read the failure, fix the import, re-run.

- [ ] **Step 5: Commit**

```bash
git add services/clients.py services/boombox-buttons.py
git commit -m "refactor(services): extract backend clients into services/clients.py"
```

---

### Task 2: Extract `services/actions.py`

**Files:**
- Create: `services/actions.py`
- Modify: `services/boombox-buttons.py` (remove dispatcher + handlers, import from actions)
- Test: existing `services/tests/test_buttons_dispatch.py` is the regression net

The symbols to move (line ranges from the current file):
- `Dispatcher` class (217–242)
- `_HANDLERS` dict (247)
- `_handler` decorator (250–254)
- All `_h_*` handler functions (258–442 approximately)
- `_scrub` helper (442–463)
- `shutdown_sequence` function (704–734)

- [ ] **Step 1: Confirm baseline is green**

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `23 passed`.

- [ ] **Step 2: Create `services/actions.py`**

```python
"""Shared action dispatcher for every control surface (GPIO buttons,
wireless remote, future API consumers).

The Dispatcher class holds references to backend clients; action
handlers registered with @_handler look up the right client and fire
the action. Routing decisions (Mopidy vs MPRIS-via-state-API) live in
the handlers themselves — callers only know the action name.

Public API:
    fire(dispatcher, action, value=None, *, source="unknown") -> dict
        High-level entry point. Returns {"ok": True} on success or
        {"ok": False, "error": "<reason>"} otherwise. Used by the
        wireless remote service; GPIO buttons use the older
        dispatch() form which is also still supported.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from typing import Awaitable, Callable

from clients import (
    Display, KioskClient, MopidyRpc, Recorder, SleepTimer, StateApi,
)

log = logging.getLogger("boombox-actions")


# --- paste the Dispatcher dataclass here, verbatim ---


# --- paste _HANDLERS dict + _handler decorator ---


# --- paste all _h_* and _scrub functions, verbatim ---


# --- paste shutdown_sequence, verbatim ---


async def fire(dispatcher: "Dispatcher", action: str, value=None, *,
               source: str = "unknown") -> dict:
    """High-level dispatch entry. Returns {ok, error?}.

    `value` is reserved for actions that take a parameter
    (e.g. {"action": "volume", "value": 70}); short_press handlers
    ignore it. `source` is for telemetry.
    """
    event = "short_press"
    if dispatcher.disabled and action in dispatcher.disabled:
        return {"ok": False, "error": "disabled"}
    handler = _HANDLERS.get((action, event))
    if handler is None:
        return {"ok": False, "error": f"unknown_action:{action}"}
    try:
        await handler(dispatcher)
        log.info("fired %s/%s from %s", action, event, source)
        return {"ok": True}
    except Exception as exc:
        log.warning("handler %s/%s raised: %s", action, event, exc)
        return {"ok": False, "error": "handler_raised"}
```

The `fire()` helper is new. It wraps the existing handler-table
lookup with explicit return values; the older `Dispatcher.dispatch()`
method moves with the class and remains for GPIO use (logs but doesn't
return a value, matching today's behavior).

- [ ] **Step 3: Update `boombox-buttons.py`**

In `services/boombox-buttons.py`:

1. Delete the `Dispatcher` class (217–242).
2. Delete the `_HANDLERS` dict, `_handler` decorator, all `_h_*` and
   `_scrub` functions (247–463).
3. Delete the `shutdown_sequence` function (704–734).
4. Add at the top, after the `from clients import …` line:

```python
from actions import Dispatcher, fire, shutdown_sequence
```

5. The existing GPIO callsite uses `dispatcher.dispatch(action, event)`
   — that still works because `Dispatcher.dispatch` is on the class
   that just moved.

- [ ] **Step 4: Run the regression suite**

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `23 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/actions.py services/boombox-buttons.py
git commit -m "refactor(services): extract action dispatcher into services/actions.py"
```

---

### Task 3: Update the test-import shim for the new layout

**Files:**
- Modify: `services/boombox_buttons.py` (re-exports for tests)
- Test: `services/tests/test_buttons_dispatch.py` (must continue to pass)

The test shim at `services/boombox_buttons.py` re-exports symbols by
name. The tests use `buttons.Dispatcher`, `buttons.default_config`, etc.
After the refactor, `Dispatcher` lives in `actions`, not `boombox-buttons`.
The shim needs updating.

- [ ] **Step 1: Confirm which symbols the tests reference**

Run: `.venv/bin/grep -hE "buttons\.[A-Za-z_]+" services/tests/*.py | sort -u`

Expected output names: `default_config`, `load_config`, `enabled_pins`,
`pin_conflicts`, `PressClassifier`, `EncoderDecoder`, `Dispatcher`.

- [ ] **Step 2: Update `services/boombox_buttons.py`**

Replace the file's contents with:

```python
"""Underscore-named import shim so tests can `import boombox_buttons`.

The shipped service is `boombox-buttons.py` (hyphenated to match systemd
unit naming). Python imports don't allow hyphens, so this shim loads the
real file by path and re-exports its public names — including names that
were extracted into the sibling modules `actions` and `clients`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_real = Path(__file__).resolve().parent / "boombox-buttons.py"
_spec = importlib.util.spec_from_file_location("boombox_buttons_impl", _real)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["boombox_buttons_impl"] = _mod
_spec.loader.exec_module(_mod)

# Re-export from the runtime module (loaded above) for what's still there.
default_config   = _mod.default_config
load_config      = _mod.load_config
enabled_pins     = _mod.enabled_pins
pin_conflicts    = _mod.pin_conflicts
PressClassifier  = _mod.PressClassifier
EncoderDecoder   = _mod.EncoderDecoder

# Re-export from actions/clients (now the source of truth).
import actions   # noqa: E402
import clients   # noqa: E402

Dispatcher       = actions.Dispatcher
fire             = actions.fire
MopidyRpc        = clients.MopidyRpc
StateApi         = clients.StateApi
KioskClient      = clients.KioskClient
```

- [ ] **Step 3: Run the regression suite**

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `23 passed`.

- [ ] **Step 4: Commit**

```bash
git add services/boombox_buttons.py
git commit -m "refactor(services): update test shim to re-export from actions and clients"
```

---

### Task 4: Add a direct test for `actions.fire()`

**Files:**
- Create: `services/tests/test_actions.py`

`fire()` is the new public entry point; it deserves its own test file
(future remote/BLE callers will use it).

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_actions.py`:

```python
"""Tests for the action dispatcher's high-level fire() entry point."""
from __future__ import annotations

import pytest

import actions
import clients


def _make_dispatcher(mopidy=None, state=None, kiosk=None,
                     recorder=None, display=None, sleep=None,
                     disabled=None):
    """Construct a Dispatcher with whatever clients the test supplies.
    Any client left None makes its handler a no-op (handlers null-guard)."""
    return actions.Dispatcher(
        mopidy=mopidy, state=state, kiosk=kiosk,
        recorder=recorder, display=display, sleep=sleep,
        disabled=disabled or set(),
    )


@pytest.mark.asyncio
async def test_fire_unknown_action_returns_error():
    d = _make_dispatcher()
    result = await actions.fire(d, "no_such_action")
    assert result == {"ok": False, "error": "unknown_action:no_such_action"}


@pytest.mark.asyncio
async def test_fire_disabled_action_returns_disabled():
    d = _make_dispatcher(disabled={"play_pause"})
    result = await actions.fire(d, "play_pause")
    assert result == {"ok": False, "error": "disabled"}


@pytest.mark.asyncio
async def test_fire_known_action_returns_ok_when_handler_succeeds():
    # `stop` is the simplest handler: it just calls mopidy.call() if mopidy
    # is non-None. We pass a stub that records the call and returns {}.
    calls = []

    class StubMopidy:
        async def call(self, method, params=None):
            calls.append((method, params))
            return {}

    d = _make_dispatcher(mopidy=StubMopidy())
    result = await actions.fire(d, "stop")
    assert result == {"ok": True}
    assert calls == [("core.playback.stop", None)]


@pytest.mark.asyncio
async def test_fire_handler_exception_returns_error():
    class ExplodingMopidy:
        async def call(self, *a, **kw):
            raise RuntimeError("boom")

    d = _make_dispatcher(mopidy=ExplodingMopidy())
    result = await actions.fire(d, "stop")
    assert result == {"ok": False, "error": "handler_raised"}
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest services/tests/test_actions.py -v`
Expected: 4 passed.

If anything fails, it's almost certainly a `Dispatcher` constructor
signature mismatch — verify the dataclass fields match what
`_make_dispatcher` passes.

- [ ] **Step 3: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `27 passed` (23 prior + 4 new).

- [ ] **Step 4: Commit**

```bash
git add services/tests/test_actions.py
git commit -m "test(actions): direct unit tests for actions.fire()"
```

---

### Task 5: Add `services/boombox_remote.py` import shim

**Files:**
- Create: `services/boombox_remote.py`

Prepare the test-import shim now so Stage-2 tests can `import boombox_remote`
without thinking about it. The file `boombox-remote.py` doesn't exist yet,
so the shim must be defensive about that.

- [ ] **Step 1: Create the shim**

Create `services/boombox_remote.py`:

```python
"""Underscore-named import shim for boombox-remote.py.

The shipped service is `boombox-remote.py`; Python's import doesn't
allow hyphens. Same pattern as `boombox_buttons.py`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_real = Path(__file__).resolve().parent / "boombox-remote.py"
if not _real.exists():
    raise ImportError(
        "services/boombox-remote.py not present yet — implement it before "
        "importing boombox_remote"
    )

_spec = importlib.util.spec_from_file_location("boombox_remote_impl", _real)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["boombox_remote_impl"] = _mod
_spec.loader.exec_module(_mod)

create_app   = _mod.create_app
require_auth = _mod.require_auth
```

- [ ] **Step 2: Verify the shim raises a helpful error today**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'services'); import boombox_remote"`
Expected: `ImportError: services/boombox-remote.py not present yet — implement it before importing boombox_remote`

- [ ] **Step 3: Commit**

```bash
git add services/boombox_remote.py
git commit -m "chore(services): scaffold boombox_remote.py import shim"
```

---

## Stage 2 — Build `services/boombox-remote.py`

### Task 6: Skeleton + bearer-token auth

**Files:**
- Create: `services/boombox-remote.py`
- Create: `services/tests/test_remote_auth.py`

Establish the aiohttp app and the auth middleware first; every subsequent
endpoint plugs into both.

Auth shape: a `peers.json` file at `~/.config/boombox-remote/peers.json`
holds `{<token>: {"label": "...", "paired_at": <epoch>}}`. The middleware
reads `Authorization: Bearer <token>` and rejects requests where the token
isn't in the file. Phase 1 ships with no UI for adding tokens — they're
hand-added for testing.

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_auth.py`:

```python
"""Auth middleware for boombox-remote."""
from __future__ import annotations

import json
import pytest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


@pytest.fixture
async def app_with_token(tmp_path, monkeypatch):
    peers_file = tmp_path / "peers.json"
    peers_file.write_text(json.dumps({
        "good-token": {"label": "test", "paired_at": 0},
    }))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers_file))

    import boombox_remote
    return boombox_remote.create_app()


@pytest.mark.asyncio
async def test_missing_token_returns_401(app_with_token, aiohttp_client):
    client = await aiohttp_client(app_with_token)
    resp = await client.get("/api/remote/state")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_bad_token_returns_401(app_with_token, aiohttp_client):
    client = await aiohttp_client(app_with_token)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer bad-token"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_good_token_passes_auth(app_with_token, aiohttp_client):
    client = await aiohttp_client(app_with_token)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer good-token"})
    # /state isn't implemented yet — pass-through to whatever handler exists.
    # We only assert it's NOT a 401. A 404 or 500 is fine for now.
    assert resp.status != 401
```

- [ ] **Step 2: Run the test (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_auth.py -v`
Expected: ImportError or failures (no `boombox-remote.py` yet).

- [ ] **Step 3: Create `services/boombox-remote.py`**

```python
#!/usr/bin/env python3
"""boombox-remote — wireless-remote-facing HTTP API.

Exposes a consolidated REST + WebSocket interface aimed at ESP32-based
remotes (and any HTTP client). Routes commands through actions.fire()
so the GPIO buttons service and the wireless remotes share one code
path.

Auth: bearer tokens stored in ~/.config/boombox-remote/peers.json.
Phase 1 has no pairing UI — tokens are added by hand for testing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from aiohttp import web

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-remote")

PORT = int(os.environ.get("BOOMBOX_REMOTE_PORT", "6685"))
DEFAULT_PEERS = Path.home() / ".config" / "boombox-remote" / "peers.json"
PEERS_PATH = Path(os.environ.get("BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)))


def _load_peers() -> dict[str, dict]:
    """Read peers.json. Returns {} if the file is missing or malformed."""
    try:
        return json.loads(PEERS_PATH.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("peers.json malformed at %s: %s", PEERS_PATH, e)
        return {}


@web.middleware
async def require_auth(request: web.Request, handler):
    """Bearer-token middleware. 401 on missing or unknown token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"ok": False, "error": "missing_token"},
                                 status=401)
    token = auth[len("Bearer "):]
    peers = _load_peers()
    if token not in peers:
        return web.json_response({"ok": False, "error": "bad_token"},
                                 status=401)
    request["peer"] = peers[token]
    request["peer_token"] = token
    return await handler(request)


def create_app() -> web.Application:
    """Build the aiohttp Application. Used by tests and main()."""
    app = web.Application(middlewares=[require_auth])
    # Endpoints are added in subsequent tasks. We add a stub /state here
    # so the auth tests pass: it just returns 200 with an empty payload.
    app.router.add_get("/api/remote/state", _stub_state)
    return app


async def _stub_state(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "data": {}})


async def main() -> None:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    log.info("boombox-remote listening on 127.0.0.1:%d", PORT)
    # Block forever
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/pytest services/tests/test_remote_auth.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_auth.py
git commit -m "feat(remote): boombox-remote.py skeleton with bearer-token auth"
```

---

### Task 7: `GET /api/remote/state` — consolidated state payload

**Files:**
- Modify: `services/boombox-remote.py` (replace `_stub_state`)
- Create: `services/tests/test_remote_state.py`

The endpoint composes the spec's consolidated payload from upstream
sources: `boombox-state` (`:6681/state`, `/volume`, `/karaoke`), Mopidy
(`:6680/mopidy/rpc` for tracklist + current track), and known per-process
state (recording, sleep_timer — held in-memory by `boombox-buttons.py`
today). Phase 1 returns what we can read over HTTP from existing services;
the in-memory bits (sleep_timer, recording) read from a small new
`/state` endpoint on `boombox-buttons.py` exposed at port 6684.

For testability we inject the upstream clients rather than constructing
them inside the handler.

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_state.py`:

```python
"""Tests for GET /api/remote/state."""
from __future__ import annotations

import json
import pytest
from aiohttp import web


@pytest.fixture
async def app_with_stub_upstream(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "test", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))

    import boombox_remote

    class StubAggregator:
        async def consolidated_state(self):
            return {
                "boombox": {"id": "boombox-test", "name": "Test", "version": 1},
                "source": "mopidy",
                "playing": True,
                "track": {"title": "Hey Jude", "artist": "The Beatles",
                          "album": "The Beatles 1967-1970",
                          "duration_s": 431, "position_s": 12},
                "art_hash": "sha1:abc",
                "art_url": "/api/remote/art/abc.jpg",
                "volume": 65,
                "muted": False,
                "sources_available": ["mopidy", "airplay", "spotify",
                                       "bluetooth", "movies"],
                "sleep_timer_s": None,
                "recording": False,
                "mic_on": False,
                "skin": "retro-blue",
            }

    app = boombox_remote.create_app(aggregator=StubAggregator())
    return app


@pytest.mark.asyncio
async def test_state_returns_consolidated_payload(
        app_with_stub_upstream, aiohttp_client):
    client = await aiohttp_client(app_with_stub_upstream)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["data"]["track"]["title"] == "Hey Jude"
    assert body["data"]["volume"] == 65
    assert body["data"]["sources_available"] == [
        "mopidy", "airplay", "spotify", "bluetooth", "movies"]
```

- [ ] **Step 2: Run the test (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_state.py -v`
Expected: failure — `create_app()` doesn't take an `aggregator` arg, and
the response shape is wrong.

- [ ] **Step 3: Replace `_stub_state` and add `StateAggregator`**

In `services/boombox-remote.py`:

1. Add at the top, with the other imports:

```python
import aiohttp as aiohttp_client_lib

import actions
import clients
```

2. Add a new `StateAggregator` class above `create_app`:

```python
class StateAggregator:
    """Reads upstream services and produces the consolidated payload."""

    def __init__(self, session: aiohttp_client_lib.ClientSession,
                 boombox_id: str = "boombox", boombox_name: str = "Boombox"):
        self._sess = session
        self._boombox_id = boombox_id
        self._boombox_name = boombox_name
        self._mopidy = clients.MopidyRpc(session)
        self._state = clients.StateApi(session)

    async def consolidated_state(self) -> dict:
        # Pull in parallel for snappiness.
        source = await self._state.current_source()
        track_info, vol_info, karaoke = await asyncio.gather(
            self._mopidy.call("core.playback.get_current_track"),
            self._fetch_volume(),
            self._state.karaoke_state(),
        )
        track = (track_info or {}).get("result") or {}
        playing_state = (await self._mopidy.call(
            "core.playback.get_state")).get("result")
        position_ms = (await self._mopidy.call(
            "core.playback.get_time_position")).get("result") or 0

        return {
            "boombox": {
                "id": self._boombox_id,
                "name": self._boombox_name,
                "version": 1,
            },
            "source": source,
            "playing": playing_state == "playing",
            "track": {
                "title":      track.get("name"),
                "artist":     ", ".join(a.get("name", "") for a in
                                         track.get("artists") or []) or None,
                "album":      (track.get("album") or {}).get("name"),
                "duration_s": (track.get("length") or 0) // 1000,
                "position_s": position_ms // 1000,
            } if track else None,
            "art_hash": None,   # populated in Task 10 (album-art endpoint)
            "art_url":  None,
            "volume":   vol_info[0] if vol_info else None,
            "muted":    vol_info[1] if vol_info else False,
            "sources_available": ["mopidy", "airplay", "spotify",
                                   "bluetooth", "movies"],
            "sleep_timer_s": None,  # in-memory; Task 8 wires up buttons
            "recording":     False,
            "mic_on":        karaoke,
            "skin":          None,
        }

    async def _fetch_volume(self) -> tuple[float, bool] | None:
        return await self._state.volume_get()
```

3. Replace `_stub_state` and update `create_app`:

```python
def create_app(aggregator: "StateAggregator | None" = None) -> web.Application:
    app = web.Application(middlewares=[require_auth])
    app["aggregator"] = aggregator  # may be None until startup wires it in
    app.router.add_get("/api/remote/state", _get_state)
    return app


async def _get_state(request: web.Request) -> web.Response:
    agg = request.app.get("aggregator")
    if agg is None:
        return web.json_response(
            {"ok": False, "error": "aggregator_unavailable"}, status=503)
    try:
        data = await agg.consolidated_state()
    except Exception as exc:
        log.warning("state aggregation failed: %s", exc)
        return web.json_response({"ok": False, "error": "upstream"}, status=502)
    return web.json_response({"ok": True, "data": data})
```

4. Update `main()` to construct an aggregator:

```python
async def main() -> None:
    timeout = aiohttp_client_lib.ClientTimeout(total=2)
    async with aiohttp_client_lib.ClientSession(timeout=timeout) as session:
        agg = StateAggregator(session,
                              boombox_id=os.environ.get(
                                  "BOOMBOX_ID", "boombox-default"),
                              boombox_name=os.environ.get(
                                  "BOOMBOX_NAME", "Boombox"))
        app = create_app(aggregator=agg)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", PORT)
        await site.start()
        log.info("boombox-remote listening on 127.0.0.1:%d", PORT)
        await asyncio.Event().wait()
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/pytest services/tests/test_remote_state.py -v`
Expected: 1 passed.

Then run the full suite:

Run: `.venv/bin/pytest services/tests/ -q`
Expected: all green (`31 passed`).

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_state.py
git commit -m "feat(remote): GET /api/remote/state consolidates upstream state"
```

---

### Task 8: `POST /api/remote/command` — fire actions

**Files:**
- Modify: `services/boombox-remote.py` (new endpoint + dispatcher wiring)
- Create: `services/tests/test_remote_command.py`

The command endpoint accepts `{"action": "<name>", "value": <optional>}`
and delegates to `actions.fire(dispatcher, action, value, source="remote:<label>")`.

A `Dispatcher` is built in `main()` with the same backend clients the
buttons service uses. Tests inject a stub dispatcher.

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_command.py`:

```python
"""Tests for POST /api/remote/command."""
from __future__ import annotations

import json
import pytest


@pytest.fixture
async def app_with_stub_dispatcher(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "test-remote",
                                         "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))

    fired = []

    class StubDispatcher:
        disabled: set = set()

    async def stub_fire(dispatcher, action, value=None, *, source="unknown"):
        fired.append({"action": action, "value": value, "source": source})
        if action == "boom":
            return {"ok": False, "error": "handler_raised"}
        return {"ok": True}

    import actions
    monkeypatch.setattr(actions, "fire", stub_fire)

    import boombox_remote
    app = boombox_remote.create_app(dispatcher=StubDispatcher())
    return app, fired


@pytest.mark.asyncio
async def test_command_dispatches_action(app_with_stub_dispatcher,
                                          aiohttp_client):
    app, fired = app_with_stub_dispatcher
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/command",
                              json={"action": "next"},
                              headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    assert body == {"ok": True}
    assert fired == [{"action": "next", "value": None,
                       "source": "remote:test-remote"}]


@pytest.mark.asyncio
async def test_command_with_value(app_with_stub_dispatcher, aiohttp_client):
    app, fired = app_with_stub_dispatcher
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/command",
                              json={"action": "volume", "value": 70},
                              headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert fired[0]["value"] == 70


@pytest.mark.asyncio
async def test_command_missing_action_returns_400(
        app_with_stub_dispatcher, aiohttp_client):
    app, _ = app_with_stub_dispatcher
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/command",
                              json={},
                              headers={"Authorization": "Bearer t"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_command_handler_failure_returns_502(
        app_with_stub_dispatcher, aiohttp_client):
    app, _ = app_with_stub_dispatcher
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/command",
                              json={"action": "boom"},
                              headers={"Authorization": "Bearer t"})
    assert resp.status == 502
    body = await resp.json()
    assert body["ok"] is False
```

- [ ] **Step 2: Run the test (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_command.py -v`
Expected: failures — `create_app()` doesn't accept `dispatcher=` and
the route doesn't exist.

- [ ] **Step 3: Add the endpoint**

In `services/boombox-remote.py`:

1. Update `create_app` signature to accept dispatcher:

```python
def create_app(aggregator: "StateAggregator | None" = None,
               dispatcher: "actions.Dispatcher | None" = None) -> web.Application:
    app = web.Application(middlewares=[require_auth])
    app["aggregator"] = aggregator
    app["dispatcher"] = dispatcher
    app.router.add_get("/api/remote/state", _get_state)
    app.router.add_post("/api/remote/command", _post_command)
    return app
```

2. Add the handler:

```python
async def _post_command(request: web.Request) -> web.Response:
    dispatcher = request.app.get("dispatcher")
    if dispatcher is None:
        return web.json_response(
            {"ok": False, "error": "dispatcher_unavailable"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_json"}, status=400)

    action = body.get("action")
    if not action or not isinstance(action, str):
        return web.json_response(
            {"ok": False, "error": "missing_action"}, status=400)

    value = body.get("value")
    label = request["peer"].get("label", "unknown")

    result = await actions.fire(dispatcher, action, value,
                                 source=f"remote:{label}")
    status = 200 if result.get("ok") else 502
    return web.json_response(result, status=status)
```

3. Update `main()` to construct a `Dispatcher`:

```python
async def main() -> None:
    timeout = aiohttp_client_lib.ClientTimeout(total=2)
    async with aiohttp_client_lib.ClientSession(timeout=timeout) as session:
        agg = StateAggregator(session,
                              boombox_id=os.environ.get(
                                  "BOOMBOX_ID", "boombox-default"),
                              boombox_name=os.environ.get(
                                  "BOOMBOX_NAME", "Boombox"))
        dispatcher = actions.Dispatcher(
            mopidy=clients.MopidyRpc(session),
            state=clients.StateApi(session),
            kiosk=None,        # populated when we wire KioskClient in
            recorder=None,     # populated alongside boombox-buttons
            display=None,
            sleep=None,
            disabled=set(),
        )
        app = create_app(aggregator=agg, dispatcher=dispatcher)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", PORT)
        await site.start()
        log.info("boombox-remote listening on 127.0.0.1:%d", PORT)
        await asyncio.Event().wait()
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/pytest services/tests/test_remote_command.py -v`
Expected: 4 passed.

Run full suite:

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `35 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_command.py
git commit -m "feat(remote): POST /api/remote/command routes through actions.fire()"
```

---

### Task 9: WebSocket `/api/remote/ws` — push state on change

**Files:**
- Modify: `services/boombox-remote.py`
- Create: `services/tests/test_remote_ws.py`

A WebSocket connection authenticates via bearer token in the query string
(`?token=...`) — browsers and ESP32 clients can't easily set headers on
the WS handshake in some libraries. On connect the server pushes the
current state immediately, then pushes again whenever any client
re-reads (we poll the aggregator every 250 ms and diff; if different,
broadcast).

Phase 1's "push on change" is implemented via a 250 ms poll loop; future
phases can subscribe to upstream notifications.

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_ws.py`:

```python
"""Tests for the WebSocket push endpoint."""
from __future__ import annotations

import asyncio
import json
import pytest


@pytest.fixture
async def app_with_changing_state(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "ws-test", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    monkeypatch.setenv("BOOMBOX_REMOTE_WS_POLL_MS", "50")

    state_box = {"playing": False}

    class StubAggregator:
        async def consolidated_state(self):
            return {"playing": state_box["playing"], "track": None,
                    "volume": 50, "muted": False,
                    "sources_available": [],
                    "boombox": {"id": "b", "name": "B", "version": 1},
                    "source": None, "art_hash": None, "art_url": None,
                    "sleep_timer_s": None, "recording": False,
                    "mic_on": False, "skin": None}

    import boombox_remote
    app = boombox_remote.create_app(aggregator=StubAggregator())
    return app, state_box


@pytest.mark.asyncio
async def test_ws_pushes_initial_then_change(app_with_changing_state,
                                              aiohttp_client):
    app, state_box = app_with_changing_state
    client = await aiohttp_client(app)
    ws = await client.ws_connect("/api/remote/ws?token=t")

    # First message is the initial state push.
    msg = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
    assert msg["ok"] is True
    assert msg["data"]["playing"] is False

    # Mutate upstream; expect another push within ~150 ms.
    state_box["playing"] = True
    msg = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
    assert msg["data"]["playing"] is True

    await ws.close()


@pytest.mark.asyncio
async def test_ws_rejects_bad_token(app_with_changing_state, aiohttp_client):
    app, _ = app_with_changing_state
    client = await aiohttp_client(app)
    ws = await client.ws_connect("/api/remote/ws?token=wrong",
                                  allow_redirects=False)
    # Server should close immediately with code 4401 (custom: auth).
    msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
    assert msg.type.name in ("CLOSE", "CLOSED")
```

- [ ] **Step 2: Run the test (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_ws.py -v`
Expected: failure — route doesn't exist.

- [ ] **Step 3: Add the WS handler**

In `services/boombox-remote.py`:

1. Add at the top with imports:

```python
WS_POLL_MS = int(os.environ.get("BOOMBOX_REMOTE_WS_POLL_MS", "250"))
```

2. In `create_app`, add the route:

```python
app.router.add_get("/api/remote/ws", _ws_handler)
```

3. Add the handler:

```python
async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    # Auth via query param ?token=... (the middleware can't intercept
    # before the handshake completes for some clients).
    token = request.query.get("token", "")
    peers = _load_peers()
    if token not in peers:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4401, message=b"bad_token")
        return ws

    agg = request.app.get("aggregator")
    if agg is None:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4503, message=b"aggregator_unavailable")
        return ws

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    last_payload: str | None = None
    try:
        while not ws.closed:
            try:
                data = await agg.consolidated_state()
            except Exception as exc:
                log.warning("ws aggregator error: %s", exc)
                await asyncio.sleep(WS_POLL_MS / 1000)
                continue
            payload = json.dumps({"ok": True, "data": data},
                                  sort_keys=True, default=str)
            if payload != last_payload:
                await ws.send_str(payload)
                last_payload = payload
            await asyncio.sleep(WS_POLL_MS / 1000)
    except asyncio.CancelledError:
        pass
    return ws
```

The middleware only runs for `add_get`/`add_post` routes that use it;
since we accept the WS handshake first and check the token by hand, we
bypass the middleware deliberately. (Alternative: add the WS path to a
middleware allow-list — left for a later cleanup if needed.)

Actually, on a closer read, the `require_auth` middleware DOES run on
every request including WS upgrades. Without an `Authorization` header
the middleware returns 401 before our handler sees the request. We need
to special-case the WS path inside the middleware OR move the auth
inside the handler.

Update the middleware to skip the WS path's token check (it has its own):

```python
@web.middleware
async def require_auth(request: web.Request, handler):
    if request.path == "/api/remote/ws":
        return await handler(request)
    auth = request.headers.get("Authorization", "")
    ...
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/pytest services/tests/test_remote_ws.py -v`
Expected: 2 passed.

Full suite:

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `37 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_ws.py
git commit -m "feat(remote): WebSocket /api/remote/ws pushes state on change"
```

---

### Task 10: Album art endpoint with on-the-fly resize

**Files:**
- Modify: `services/boombox-remote.py`
- Create: `services/tests/test_remote_art.py`

Art comes from Mopidy's `core.library.get_images` for the currently
playing track. We cache a 240×240 JPG keyed by SHA-1 of the source URL.
ETags are the cache key.

This task introduces a Pillow dependency.

- [ ] **Step 1: Add Pillow to the venv**

Run: `.venv/bin/pip install --quiet Pillow`
Verify: `.venv/bin/python -c "from PIL import Image; print(Image.__version__)"`

- [ ] **Step 2: Write the failing test**

Create `services/tests/test_remote_art.py`:

```python
"""Tests for /api/remote/art/{hash}.jpg."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image


def _make_jpeg(color: str = "red") -> bytes:
    img = Image.new("RGB", (500, 500), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture
async def app_with_art_cache(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "art-test", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    cache_dir = tmp_path / "art-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("BOOMBOX_REMOTE_ART_CACHE", str(cache_dir))

    raw = _make_jpeg("red")
    art_hash = hashlib.sha1(raw).hexdigest()
    (cache_dir / f"{art_hash}.src").write_bytes(raw)

    import boombox_remote
    app = boombox_remote.create_app()
    return app, art_hash


@pytest.mark.asyncio
async def test_art_returns_resized_jpeg(app_with_art_cache, aiohttp_client):
    app, art_hash = app_with_art_cache
    client = await aiohttp_client(app)
    resp = await client.get(f"/api/remote/art/{art_hash}.jpg",
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/jpeg"
    assert resp.headers.get("ETag") == f'"{art_hash}"'
    body = await resp.read()
    img = Image.open(io.BytesIO(body))
    assert img.size == (240, 240)


@pytest.mark.asyncio
async def test_art_304_on_etag_match(app_with_art_cache, aiohttp_client):
    app, art_hash = app_with_art_cache
    client = await aiohttp_client(app)
    resp = await client.get(f"/api/remote/art/{art_hash}.jpg",
                             headers={"Authorization": "Bearer t",
                                      "If-None-Match": f'"{art_hash}"'})
    assert resp.status == 304


@pytest.mark.asyncio
async def test_art_unknown_hash_404(app_with_art_cache, aiohttp_client):
    app, _ = app_with_art_cache
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/art/deadbeef.jpg",
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 404
```

- [ ] **Step 3: Run the test (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_art.py -v`
Expected: failure — route doesn't exist.

- [ ] **Step 4: Implement the endpoint**

In `services/boombox-remote.py`:

1. Add at top of imports:

```python
import hashlib
import io
from PIL import Image
```

2. Add the cache-path constant:

```python
DEFAULT_ART_CACHE = Path.home() / ".cache" / "boombox-remote" / "art"
ART_CACHE = Path(os.environ.get("BOOMBOX_REMOTE_ART_CACHE",
                                 str(DEFAULT_ART_CACHE)))
ART_CACHE.mkdir(parents=True, exist_ok=True)
ART_SIZE = (240, 240)
```

3. Add the route in `create_app`:

```python
app.router.add_get("/api/remote/art/{hash}.jpg", _get_art)
```

4. Add the handler:

```python
async def _get_art(request: web.Request) -> web.Response:
    art_hash = request.match_info["hash"]
    # Reject anything that isn't lowercase hex (defense in depth — caller
    # always passes a sha1).
    if not all(c in "0123456789abcdef" for c in art_hash) or not art_hash:
        return web.Response(status=400)

    etag = f'"{art_hash}"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})

    resized_path = ART_CACHE / f"{art_hash}.jpg"
    src_path     = ART_CACHE / f"{art_hash}.src"

    if not resized_path.exists():
        if not src_path.exists():
            return web.Response(status=404)
        # Lazy-resize on first request.
        with Image.open(src_path) as img:
            img = img.convert("RGB")
            img.thumbnail(ART_SIZE, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            resized_path.write_bytes(buf.getvalue())

    return web.Response(
        body=resized_path.read_bytes(),
        content_type="image/jpeg",
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
```

- [ ] **Step 5: Run the test**

Run: `.venv/bin/pytest services/tests/test_remote_art.py -v`
Expected: 3 passed.

Full suite:

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `40 passed`.

- [ ] **Step 6: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_art.py
git commit -m "feat(remote): GET /api/remote/art/{hash}.jpg with on-the-fly resize"
```

---

### Task 11: mDNS advertisement

**Files:**
- Modify: `services/boombox-remote.py`
- Create: `services/tests/test_remote_mdns.py`

Advertise `_boombox._tcp.local` on the boombox-remote port with TXT
records `id`, `name`, `version`. Uses python-zeroconf.

- [ ] **Step 1: Add zeroconf to the venv**

Run: `.venv/bin/pip install --quiet zeroconf`
Verify: `.venv/bin/python -c "import zeroconf; print(zeroconf.__version__)"`

- [ ] **Step 2: Write the failing test**

Create `services/tests/test_remote_mdns.py`:

```python
"""Tests for mDNS advertisement."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_mdns_service_info_shape(monkeypatch):
    """Verify the ServiceInfo we'd register has the right fields."""
    monkeypatch.setenv("BOOMBOX_ID", "boombox-living-room")
    monkeypatch.setenv("BOOMBOX_NAME", "Living Room")

    import boombox_remote_impl as br

    info = br.build_mdns_service_info(port=6685)
    assert info.type == "_boombox._tcp.local."
    assert info.name == "boombox-living-room._boombox._tcp.local."
    assert info.port == 6685
    props = {k.decode(): v.decode() for k, v in info.properties.items()}
    assert props["id"] == "boombox-living-room"
    assert props["name"] == "Living Room"
    assert props["version"] == "1"
```

(The test imports `boombox_remote_impl` directly — the inner module
loaded by the shim — because `ServiceInfo` is a zeroconf construct, not
something we want in the test shim's re-exports.)

- [ ] **Step 3: Run the test (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_mdns.py -v`
Expected: failure — `build_mdns_service_info` not defined.

- [ ] **Step 4: Implement the advertisement**

In `services/boombox-remote.py`:

1. Add at the top:

```python
import socket
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf
```

2. Add the builder:

```python
def build_mdns_service_info(port: int) -> ServiceInfo:
    boombox_id = os.environ.get("BOOMBOX_ID", "boombox-default")
    boombox_name = os.environ.get("BOOMBOX_NAME", "Boombox")
    hostname = socket.gethostname()
    return ServiceInfo(
        type_="_boombox._tcp.local.",
        name=f"{boombox_id}._boombox._tcp.local.",
        port=port,
        properties={
            "id":      boombox_id.encode(),
            "name":    boombox_name.encode(),
            "version": b"1",
        },
        server=f"{hostname}.local.",
    )
```

3. Register on startup, unregister on shutdown. Update `main()`:

```python
async def main() -> None:
    timeout = aiohttp_client_lib.ClientTimeout(total=2)
    async with aiohttp_client_lib.ClientSession(timeout=timeout) as session:
        agg = StateAggregator(session,
                              boombox_id=os.environ.get("BOOMBOX_ID",
                                                          "boombox-default"),
                              boombox_name=os.environ.get("BOOMBOX_NAME",
                                                           "Boombox"))
        dispatcher = actions.Dispatcher(
            mopidy=clients.MopidyRpc(session),
            state=clients.StateApi(session),
            kiosk=None, recorder=None, display=None, sleep=None,
            disabled=set(),
        )
        app = create_app(aggregator=agg, dispatcher=dispatcher)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", PORT)
        await site.start()

        azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        info = build_mdns_service_info(PORT)
        await azc.async_register_service(info)
        log.info("boombox-remote on :%d, mDNS as %s", PORT, info.name)

        try:
            await asyncio.Event().wait()
        finally:
            await azc.async_unregister_service(info)
            await azc.async_close()
```

- [ ] **Step 5: Run the test**

Run: `.venv/bin/pytest services/tests/test_remote_mdns.py -v`
Expected: 1 passed.

Full suite:

Run: `.venv/bin/pytest services/tests/ -q`
Expected: `41 passed`.

- [ ] **Step 6: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_mdns.py
git commit -m "feat(remote): advertise _boombox._tcp.local via zeroconf"
```

---

## Stage 3 — Deployment glue

### Task 12: systemd unit

**Files:**
- Create: `install/systemd/boombox-remote.service`

The service runs as the `boombox` user (matching the rest of the stack)
and starts after `boombox-state.service` and `mopidy.service`.

- [ ] **Step 1: Find the existing systemd patterns**

Run: `ls install/systemd/ 2>/dev/null && cat install/systemd/boombox-state.service 2>/dev/null | head -30`

Use whatever the project's existing convention is for `[Service]`,
`User=`, `Environment=`, etc. If `boombox-state.service` doesn't exist
in `install/systemd/`, search for any service file in the repo:

Run: `find install -name "*.service" -print -exec head -25 {} \;`

- [ ] **Step 2: Create the unit file**

Create `install/systemd/boombox-remote.service` following the existing
patterns. The minimum:

```ini
[Unit]
Description=Boombox wireless-remote HTTP API
After=network-online.target boombox-state.service mopidy.service
Wants=network-online.target

[Service]
Type=simple
User=boombox
Group=boombox
WorkingDirectory=/opt/boombox
EnvironmentFile=-/etc/boombox/boombox-remote.env
ExecStart=/opt/boombox/.venv/bin/python /opt/boombox/services/boombox-remote.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
```

If `boombox-state.service` uses different paths or User=, adopt those
instead. Don't introduce a new convention.

- [ ] **Step 3: Commit**

```bash
git add install/systemd/boombox-remote.service
git commit -m "feat(install): systemd unit for boombox-remote"
```

---

### Task 13: nginx route

**Files:**
- Modify: an existing nginx config file (per the project's pattern)

Path: `/api/remote/` → `http://127.0.0.1:6685`. Same Basic-auth gating
pattern as `/api/` (i.e. *not* under `/upload/`).

- [ ] **Step 1: Find the existing nginx config**

Run: `find install -iname "*nginx*" -o -iname "*.conf" 2>/dev/null | head -10`
Run: `grep -rl "location /api" install/ 2>/dev/null`

Identify the file that handles `/api/...` routing today.

- [ ] **Step 2: Add the new location block**

Following the existing pattern (likely a `proxy_pass` to localhost),
add a sibling location:

```nginx
location /api/remote/ {
    proxy_pass http://127.0.0.1:6685/api/remote/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}
```

The `Upgrade`/`Connection: upgrade` and long timeouts are for the
WebSocket endpoint. Auth/no-auth behavior should mirror the project's
existing `/api/state/` or `/api/buttons/` handling.

- [ ] **Step 3: Validate config syntax locally if possible**

If `nginx -t` is available on the dev machine:

Run: `nginx -t -c <path-to-config>`

Otherwise this is verified during deployment to the Pi.

- [ ] **Step 4: Commit**

```bash
git add <the-nginx-config-file>
git commit -m "feat(install): nginx route /api/remote/ → :6685"
```

---

### Task 14: Document in `docs/SERVICES.md`

**Files:**
- Modify: `docs/SERVICES.md`

Add a new section describing the wireless-remote service, its port,
its endpoints, and how to add a bootstrap auth token for testing.

- [ ] **Step 1: Read the current docs**

Run: `wc -l docs/SERVICES.md && grep -n "^## " docs/SERVICES.md`

Find the right place to insert the new section (probably alongside
`boombox-state` and `boombox-buttons`).

- [ ] **Step 2: Add the section**

Insert (preserving the file's existing format and tone):

```markdown
## boombox-remote (port 6685)

The wireless-remote-facing HTTP API. Exposes a consolidated state
payload and a command endpoint to ESP32-based remotes (and any HTTP
client). Routes commands through the shared `actions.fire()` dispatcher
so GPIO buttons and wireless remotes share one code path.

Endpoints:
- `GET  /api/remote/state` — consolidated state JSON.
- `POST /api/remote/command` — `{action, value?}` → fires the action.
- `GET  /api/remote/ws` — WebSocket; pushes state on change.
- `GET  /api/remote/art/{hash}.jpg` — current track art at 240×240.

All endpoints require `Authorization: Bearer <token>` except the WS
endpoint which accepts the token in the query string (`?token=...`).

Tokens live in `~/.config/boombox-remote/peers.json`:
```json
{
  "<32-byte-hex-token>": {"label": "my-remote", "paired_at": 0}
}
```

Until pairing UI ships (Phase 2), add a bootstrap token by hand to
test:

    mkdir -p ~/.config/boombox-remote
    python3 -c "import secrets; print(secrets.token_hex(32))" > /tmp/t
    jq -n --rawfile t /tmp/t '{($t | rtrimstr("\n")): {label: "bootstrap", paired_at: 0}}' \
      > ~/.config/boombox-remote/peers.json
    curl -H "Authorization: Bearer $(cat /tmp/t)" \
      http://boombox.local:6685/api/remote/state

mDNS: advertised as `_boombox._tcp.local` with TXT records `id`,
`name`, `version`. Discover with `dns-sd -B _boombox._tcp` (macOS) or
`avahi-browse -r _boombox._tcp` (Linux).
```

- [ ] **Step 3: Commit**

```bash
git add docs/SERVICES.md
git commit -m "docs(services): document boombox-remote endpoints and bootstrap token flow"
```

---

### Task 15: End-to-end smoke check (manual, no commit)

Final verification before declaring Phase 1 done. Not a commit — just
proof the slice works end-to-end against a real venv.

- [ ] **Step 1: Start the service locally**

Run in one shell:
```bash
mkdir -p ~/.config/boombox-remote
python3 -c "import secrets; print(secrets.token_hex(32))" > /tmp/t
python3 -c "
import json, pathlib, sys
t = open('/tmp/t').read().strip()
pathlib.Path.home().joinpath('.config/boombox-remote/peers.json').write_text(
  json.dumps({t: {'label': 'smoke', 'paired_at': 0}}))
"
.venv/bin/python services/boombox-remote.py
```

- [ ] **Step 2: Hit /state with curl from another shell**

```bash
curl -s -H "Authorization: Bearer $(cat /tmp/t)" \
  http://127.0.0.1:6685/api/remote/state | jq
```

Expected: a JSON `{"ok": true, "data": {...}}`. Many upstream fields
will be `null` because there's no Mopidy or boombox-state running
locally — that's fine; we're testing the service shape, not upstream
data. (To test upstream too, run on the Pi.)

- [ ] **Step 3: Verify auth rejection**

```bash
curl -s -i http://127.0.0.1:6685/api/remote/state | head -1
```

Expected: `HTTP/1.1 401 Unauthorized`.

- [ ] **Step 4: Verify mDNS**

```bash
dns-sd -t 2 -B _boombox._tcp .
```

Expected: a listing including `boombox-default` (or whatever
`BOOMBOX_ID` is).

- [ ] **Step 5: Stop the service**

Ctrl-C in the first shell.

- [ ] **Step 6: Run the full test suite one more time**

```bash
.venv/bin/pytest services/tests/ -q
```

Expected: `41 passed` (or higher).

If everything passes, Phase 1 is done. The next plan is Phase 2 (CYD
firmware) — start a fresh session with the spec and write that plan.

---

## What's intentionally NOT in Phase 1

- **BLE peripheral on the Pi** — Phase 4 (after phase-0 spike).
- **ESP32 firmware of any kind** — Phase 2 (CYD HTTP-only first).
- **USB firmware installer / kiosk overlay / esptool integration** — Phase 3.
- **Pairing flow / kiosk confirm overlay** — Phase 2 (PIN-pairing first, BLE pairing in Phase 4).
- **External profile packs / manifest validation / CLI** — Phase 6.
- **Headless DIY profile** — Phase 5.
- **ELECROW round profile** — Phase 7.
- **Sleep-timer + recording surfaced in /state** — needs a small `/state` endpoint added to `boombox-buttons.py` for in-memory bits; deferred to Phase 2 when the firmware actually needs them.
- **Album art *fetching* from Mopidy** — Phase 1 has the resize endpoint and cache, but populating the cache from `core.library.get_images` is wired in Phase 2 (the firmware is the only consumer that exercises it).

## Out-of-band notes

- A `services/boombox-buttons.py` modification by another process was
  observed during planning (148 lines added). The refactor in Stage 1
  was written against the file as it stood on `worktree-wireless-remote`
  branch HEAD; if that branch's content has shifted, Stage 1 may need
  small adjustments. The TDD net (existing tests must pass) catches
  any drift.
- `~/.config/boombox-remote/peers.json` is created by hand for Phase 1
  testing; a future task in Phase 2 adds it to the install script with
  correct permissions (0600).
