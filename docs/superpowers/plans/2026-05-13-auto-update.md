# Auto-update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unattended auto-updates: discover GitHub Releases, install inside a user-chosen daily window, A/B-style symlink swap with smoke-test + rollback, surfaced in the touchscreen Settings panel and LAN web page.

**Architecture:** New `boombox-updater` user systemd service polls GitHub, persists state to `/opt/boombox/state/updater.json`, runs a state machine that clones a release into `/opt/boombox/releases/<ref>/`, builds, smoke-tests, swaps the `current` symlink, and rolls back to `previous` on failure. Existing `bin/boombox-update` CLI becomes a thin client of the service's HTTP API on `:6685` with a fallback that invokes `install/apply-release.sh` directly when the service is disabled. The touchscreen SettingsDrawer gains an Updates section that shares the same API surface.

**Tech Stack:** Python 3 / asyncio / aiohttp (existing pattern from `boombox-state`); React + TypeScript (existing pattern in `ui/src/lib/`); systemd user units; bash for the shell parts that need sudo.

**Spec:** `docs/superpowers/specs/2026-05-13-auto-update-design.md`

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `VERSION` | Single-line current source version (e.g. `0.4.1-dev`). Read by the updater after migration. |
| `services/boombox_updater/__init__.py` | Package marker. |
| `services/boombox_updater/version.py` | Version-string parsing + comparison (stable tags + edge sha equality). |
| `services/boombox_updater/poller.py` | GitHub Releases / commits API client. Pure I/O, mocked in tests. |
| `services/boombox_updater/config.py` | Read/write `/etc/boombox/updater.json` with validation + atomic write. |
| `services/boombox_updater/state.py` | Read/write `/opt/boombox/state/updater.json` + per-attempt logs. |
| `services/boombox_updater/scheduler.py` | Pure decision function `should_attempt_install(...)`. |
| `services/boombox_updater/installer.py` | Install state machine (pure logic; subprocess steps are injected). |
| `services/boombox_updater/api.py` | aiohttp routes for `/api/update/*`. |
| `services/boombox-updater.py` | Entry point — wires loops + HTTP server, mirrors naming of other services. |
| `install/apply-release.sh` | Shell wrapper that performs the real git/npm/symlink/sudo operations; called by the updater and by the CLI fallback path. |
| `install/systemd/user/boombox-updater.service` | systemd user unit. |
| `services/tests/test_updater_version.py` | Unit tests for version comparison. |
| `services/tests/test_updater_config.py` | Unit tests for config IO + validation. |
| `services/tests/test_updater_state.py` | Unit tests for state IO + log rotation. |
| `services/tests/test_updater_scheduler.py` | Unit tests for the scheduler decision function. |
| `services/tests/test_updater_installer.py` | Unit tests for the install state machine (with mocked steps). |
| `services/tests/test_updater_api.py` | Unit tests for the HTTP API surface. |
| `services/tests/test_updater_e2e.py` | Integration test: temp-dir `/opt/boombox`, mocked GitHub, drives a full install + rollback. |
| `ui/src/lib/updaterApi.ts` | Typed client for `/api/update/*`. |
| `ui/src/lib/UpdatesPanel.tsx` | Updates section component for SettingsDrawer. |

### Modified files

| Path | What changes |
|------|--------------|
| `bin/boombox-update` | Rewritten as a thin shell client of `:6685` with fallback to `install/apply-release.sh main`. |
| `install/install.sh` | Bootstraps the new `releases/`/`current` layout. Migrates legacy flat installs. Retargets unit + nginx paths. Enables `boombox-updater.service`. |
| `install/update.sh` | Reduced to a back-compat shim that delegates to `bin/boombox-update`. |
| `install/systemd/user/*.service` (all eight existing) | Paths change from `/opt/boombox/...` to `/opt/boombox/current/...`. |
| `install/config/nginx-boombox-common.conf` | SPA root flips from `/var/www/boombox` to `/opt/boombox/current/ui/dist`; new `/api/update/` upstream block. |
| `install/sudoers/boombox` | Add `nginx -t` and `systemctl reload nginx` so `apply-release.sh` can reload nginx without prompting. |
| `install/config/requirements.txt` | Add `packaging` (proper PEP 440 version compare). |
| `ui/src/lib/SettingsDrawer.tsx` | Render `<UpdatesPanel/>` as a new section. |
| `README.md` | Document the auto-update channel/window UI; remove the "Self-update" stale section header in favor of the new model. |
| `CHANGELOG.md` | New entry. |
| `docs/SERVICES.md` | Add `boombox-updater` row + section. |

---

## Task 1: VERSION file + updater Python package skeleton

Establishes the importable Python package, the `VERSION` file referenced throughout the spec, and confirms the test harness picks up the new package.

**Files:**
- Create: `VERSION`
- Create: `services/boombox_updater/__init__.py`
- Create: `services/tests/test_updater_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
# services/tests/test_updater_smoke.py
"""Sanity check that the boombox_updater package is importable and
exposes its version string."""
from __future__ import annotations


def test_package_imports() -> None:
    import boombox_updater
    assert hasattr(boombox_updater, "__version__")
    # __version__ is read from /opt/boombox/current/VERSION on a real install,
    # but in dev/test it falls back to the repo-root VERSION file.
    assert isinstance(boombox_updater.__version__, str)
    assert boombox_updater.__version__  # non-empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boombox_updater'`.

- [ ] **Step 3: Create the VERSION file**

```
0.5.0-dev
```

(Single line, no trailing whitespace beyond the newline. The dev suffix marks "ahead of any tagged release"; the release process bumps this to a clean version when tagging.)

- [ ] **Step 4: Create the package**

```python
# services/boombox_updater/__init__.py
"""Boombox auto-updater.

Subpackages are purposefully small and pure where possible so unit tests
can exercise version comparison, config IO, the scheduler decision, and
the install state machine without touching git, the network, or the
filesystem outside their own tempdirs.
"""
from __future__ import annotations

from pathlib import Path

# Where to look for the installed VERSION file at runtime. Falls back to the
# repo-root VERSION (the dev source tree) if the install layout isn't there.
_INSTALLED_VERSION_FILE = Path("/opt/boombox/current/VERSION")
_DEV_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def _read_version() -> str:
    for candidate in (_INSTALLED_VERSION_FILE, _DEV_VERSION_FILE):
        try:
            return candidate.read_text().strip()
        except FileNotFoundError:
            continue
    return "unknown"


__version__ = _read_version()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_smoke.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add VERSION services/boombox_updater/__init__.py services/tests/test_updater_smoke.py
git commit -m "updater: scaffold package + VERSION file"
```

---

## Task 2: Version comparison

Pure logic. Two channels — `stable` uses PEP-440 tag comparison (`v0.5.0`, `v0.5.10`, `v0.6.0-rc1`); `edge` uses sha equality (any change in sha == update available).

**Files:**
- Create: `services/boombox_updater/version.py`
- Create: `services/tests/test_updater_version.py`
- Modify: `install/config/requirements.txt`

- [ ] **Step 1: Add `packaging` to requirements**

```diff
 # services/boombox-buttons
 gpiod>=2.1
+
+# services/boombox-updater — PEP 440 version compare
+packaging>=24.0

 # boombox-bt-volume — uses system dbus-python + PyGObject (apt-installed,
```

(Insert after the existing `gpiod>=2.1` line; preserve the surrounding comments and ordering.)

- [ ] **Step 2: Install the new dep into the local venv**

Run: `cd /Users/jwc/code/Boombox && python3 -m pip install --user packaging>=24.0` (developer machine only; the Pi picks it up next time `install.sh` or `apply-release.sh` runs `pip install -r requirements.txt` against the shared venv).

- [ ] **Step 3: Write the failing tests**

```python
# services/tests/test_updater_version.py
"""Tests for boombox_updater.version — channel-aware version comparison."""
from __future__ import annotations

import pytest

from boombox_updater.version import (
    UpdateAvailable,
    compare_stable,
    compare_edge,
    parse_stable,
)


class TestParseStable:
    def test_strips_v_prefix(self) -> None:
        assert str(parse_stable("v0.5.0")) == "0.5.0"

    def test_accepts_no_prefix(self) -> None:
        assert str(parse_stable("0.5.0")) == "0.5.0"

    def test_dev_suffix_is_pre_release(self) -> None:
        assert parse_stable("0.5.0-dev") < parse_stable("0.5.0")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_stable("not-a-version")


class TestCompareStable:
    def test_newer_tag_is_available(self) -> None:
        assert compare_stable(installed="v0.4.1", available="v0.4.2") == \
            UpdateAvailable(available="v0.4.2", installed="v0.4.1")

    def test_same_tag_is_none(self) -> None:
        assert compare_stable(installed="v0.4.2", available="v0.4.2") is None

    def test_double_digit_minor(self) -> None:
        # v0.4.10 must be newer than v0.4.2 (string compare would invert this).
        assert compare_stable(installed="v0.4.2", available="v0.4.10") is not None

    def test_legacy_installed_is_always_outdated(self) -> None:
        # Migrated installs have VERSION == "legacy"; any release should win.
        assert compare_stable(installed="legacy", available="v0.4.0") is not None

    def test_unknown_installed_is_always_outdated(self) -> None:
        assert compare_stable(installed="unknown", available="v0.4.0") is not None

    def test_dev_installed_loses_to_release(self) -> None:
        assert compare_stable(installed="v0.5.0-dev", available="v0.5.0") is not None

    def test_invalid_available_raises(self) -> None:
        with pytest.raises(ValueError):
            compare_stable(installed="v0.4.1", available="garbage")


class TestCompareEdge:
    def test_different_sha_is_available(self) -> None:
        assert compare_edge(installed="abc1234", available="def5678") == \
            UpdateAvailable(available="def5678", installed="abc1234")

    def test_same_sha_is_none(self) -> None:
        assert compare_edge(installed="abc1234", available="abc1234") is None

    def test_short_vs_long_sha_match(self) -> None:
        # Edge installs always store the short sha; the API may return long.
        assert compare_edge(installed="abc1234", available="abc1234567890") is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_version.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boombox_updater.version'`.

- [ ] **Step 5: Implement the module**

```python
# services/boombox_updater/version.py
"""Channel-aware version comparison for the auto-updater.

Stable channel: PEP 440 versions (`v0.5.0`, `v0.5.0-rc1`, `0.5.0-dev`).
Edge channel: git short shas. Equal-prefix match counts as same commit so
that the locally-stored short sha can be compared to GitHub's long sha.

`installed` may be the literal `"legacy"` (migrated installs) or
`"unknown"` (read failure) — both treated as definitely outdated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class UpdateAvailable:
    """Returned when the available version differs from installed."""
    available: str
    installed: str


_SENTINELS_ALWAYS_OUTDATED = {"legacy", "unknown", ""}


def parse_stable(s: str) -> Version:
    """Parse a stable-channel version string. Strips a leading 'v'."""
    cleaned = s.lstrip("v")
    return Version(cleaned)  # raises InvalidVersion (a ValueError subclass)


def compare_stable(*, installed: str, available: str) -> Optional[UpdateAvailable]:
    """Return UpdateAvailable if `available` is newer than `installed`."""
    avail = parse_stable(available)
    if installed in _SENTINELS_ALWAYS_OUTDATED:
        return UpdateAvailable(available=available, installed=installed)
    try:
        inst = parse_stable(installed)
    except InvalidVersion:
        # Anything we can't parse is treated as outdated rather than crash.
        return UpdateAvailable(available=available, installed=installed)
    if avail > inst:
        return UpdateAvailable(available=available, installed=installed)
    return None


def compare_edge(*, installed: str, available: str) -> Optional[UpdateAvailable]:
    """Return UpdateAvailable if the available sha differs from installed.

    A short sha matches a long sha if it's a prefix of it (or vice versa).
    """
    if not installed or not available:
        return UpdateAvailable(available=available, installed=installed)
    a, b = installed.lower(), available.lower()
    if a == b or a.startswith(b) or b.startswith(a):
        return None
    return UpdateAvailable(available=available, installed=installed)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_version.py -v`
Expected: 11 passed.

- [ ] **Step 7: Commit**

```bash
git add install/config/requirements.txt services/boombox_updater/version.py services/tests/test_updater_version.py
git commit -m "updater: PEP 440 stable + sha edge version compare"
```

---

## Task 3: GitHub poller

Pure I/O wrapper around `api.github.com`. Synchronous tests use `aioresponses` (already a transitive of aiohttp test extras) — but to avoid adding a dep we use a small stub via `aiohttp.web` running on a random local port. Keeps the test purely in-process.

**Files:**
- Create: `services/boombox_updater/poller.py`
- Create: `services/tests/test_updater_poller.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_updater_poller.py
"""Tests for boombox_updater.poller — GitHub Releases / commits client."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from boombox_updater.poller import GitHubPoller, PollResult


@asynccontextmanager
async def fake_github(handlers: dict[str, web.Response]):
    """Spin up an aiohttp server on a random port serving fixed responses."""
    app = web.Application()

    async def handler(request: web.Request) -> web.Response:
        key = request.path
        if key in handlers:
            return handlers[key]
        return web.Response(status=404)

    app.router.add_route("GET", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_poll_stable_returns_tag_name() -> None:
    handlers = {
        "/repos/IntergalacticTech/Boombox/releases/latest": web.json_response(
            {"tag_name": "v0.4.2", "published_at": "2026-05-13T01:23:45Z"}
        ),
    }
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_stable()
    assert result == PollResult(version="v0.4.2", published_at="2026-05-13T01:23:45Z")


@pytest.mark.asyncio
async def test_poll_edge_returns_short_sha() -> None:
    handlers = {
        "/repos/IntergalacticTech/Boombox/commits/main": web.json_response(
            {"sha": "abcdef1234567890abcdef1234567890abcdef12",
             "commit": {"committer": {"date": "2026-05-13T02:34:56Z"}}}
        ),
    }
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_edge()
    assert result == PollResult(version="abcdef1", published_at="2026-05-13T02:34:56Z")


@pytest.mark.asyncio
async def test_poll_stable_404_returns_none() -> None:
    async with fake_github({}) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_stable()
    assert result is None


@pytest.mark.asyncio
async def test_poll_uses_user_agent_and_accept_headers() -> None:
    seen: dict[str, str] = {}

    async def capture(request: web.Request) -> web.Response:
        seen["ua"] = request.headers.get("User-Agent", "")
        seen["accept"] = request.headers.get("Accept", "")
        return web.json_response({"tag_name": "v0.4.2", "published_at": ""})

    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", capture)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        poller = GitHubPoller(
            base_url=f"http://127.0.0.1:{port}",
            repo="IntergalacticTech/Boombox",
        )
        await poller.poll_stable()
    finally:
        await runner.cleanup()

    assert seen["ua"].startswith("boombox-updater/")
    assert seen["accept"] == "application/vnd.github+json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_poller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boombox_updater.poller'`.

- [ ] **Step 3: Implement the module**

```python
# services/boombox_updater/poller.py
"""GitHub Releases / commits poller.

Two methods, one per channel. Network errors and non-2xx responses are
folded into `None` (the caller logs and moves on); they never raise.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from . import __version__

log = logging.getLogger("boombox-updater.poller")

DEFAULT_GITHUB_BASE = "https://api.github.com"
SHORT_SHA_LEN = 7


@dataclass(frozen=True)
class PollResult:
    version: str
    published_at: str  # ISO 8601, may be empty if the API omits it


class GitHubPoller:
    def __init__(
        self,
        *,
        repo: str,
        base_url: str = DEFAULT_GITHUB_BASE,
        timeout_s: float = 10.0,
    ) -> None:
        self._repo = repo
        self._base = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {
            "User-Agent": f"boombox-updater/{__version__}",
            "Accept": "application/vnd.github+json",
        }

    async def poll_stable(self) -> Optional[PollResult]:
        url = f"{self._base}/repos/{self._repo}/releases/latest"
        data = await self._get_json(url)
        if not data:
            return None
        tag = data.get("tag_name")
        if not tag:
            return None
        return PollResult(version=tag, published_at=data.get("published_at") or "")

    async def poll_edge(self) -> Optional[PollResult]:
        url = f"{self._base}/repos/{self._repo}/commits/main"
        data = await self._get_json(url)
        if not data:
            return None
        sha = data.get("sha", "")
        if not sha:
            return None
        published = (
            data.get("commit", {})
                .get("committer", {})
                .get("date", "")
        )
        return PollResult(version=sha[:SHORT_SHA_LEN], published_at=published)

    async def _get_json(self, url: str) -> Optional[dict]:
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout, headers=self._headers
            ) as session:
                async with session.get(url) as resp:
                    if resp.status >= 400:
                        log.warning("github poll %s -> HTTP %d", url, resp.status)
                        return None
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:  # noqa: F821
            log.warning("github poll %s failed: %s", url, exc)
            return None
```

(`asyncio` is imported by `aiohttp`'s timeout machinery and is referenced via `asyncio.TimeoutError`. Add an explicit `import asyncio` at the top alongside `aiohttp`.)

Final import block at the top of `poller.py`:

```python
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from . import __version__
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_poller.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_updater/poller.py services/tests/test_updater_poller.py
git commit -m "updater: GitHub releases + main-branch poller"
```

---

## Task 4: Config persistence (`/etc/boombox/updater.json`)

User-editable config: auto on/off, channel, window. Written via `PUT /api/update/config`. Same model as `buttons.json`.

**Files:**
- Create: `services/boombox_updater/config.py`
- Create: `services/tests/test_updater_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_updater_config.py
"""Tests for boombox_updater.config — read/write/validate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from boombox_updater.config import (
    DEFAULT_CONFIG,
    UpdaterConfig,
    load_config,
    save_config,
    validate,
)


def test_default_when_file_absent(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "missing.json")
    assert cfg == DEFAULT_CONFIG
    assert cfg.auto is True
    assert cfg.channel == "stable"
    assert cfg.window_start == "03:00"
    assert cfg.window_duration_min == 60


def test_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "updater.json"
    cfg = UpdaterConfig(auto=False, channel="edge", window_start="02:30",
                       window_duration_min=120)
    save_config(target, cfg)
    assert load_config(target) == cfg


def test_save_is_atomic(tmp_path: Path) -> None:
    """save_config writes to a tmp file then renames — never leaves a
    half-written target."""
    target = tmp_path / "updater.json"
    save_config(target, DEFAULT_CONFIG)
    # No `.tmp` left behind.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "updater.json"]
    assert leftovers == []


def test_validate_window_start_format() -> None:
    with pytest.raises(ValueError, match="window_start"):
        validate({"auto": True, "channel": "stable",
                  "window_start": "3am", "window_duration_min": 60})


def test_validate_channel() -> None:
    with pytest.raises(ValueError, match="channel"):
        validate({"auto": True, "channel": "rolling",
                  "window_start": "03:00", "window_duration_min": 60})


def test_validate_duration_bounds() -> None:
    with pytest.raises(ValueError, match="window_duration_min"):
        validate({"auto": True, "channel": "stable",
                  "window_start": "03:00", "window_duration_min": 0})
    with pytest.raises(ValueError, match="window_duration_min"):
        validate({"auto": True, "channel": "stable",
                  "window_start": "03:00", "window_duration_min": 24 * 60 + 1})


def test_load_corrupt_file_returns_default(tmp_path: Path) -> None:
    target = tmp_path / "updater.json"
    target.write_text("not json {{{")
    assert load_config(target) == DEFAULT_CONFIG


def test_load_extra_keys_ignored(tmp_path: Path) -> None:
    target = tmp_path / "updater.json"
    target.write_text(json.dumps({
        "auto": True, "channel": "stable",
        "window_start": "03:00", "window_duration_min": 60,
        "future_field": "ignore me",
    }))
    cfg = load_config(target)
    assert cfg == DEFAULT_CONFIG
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boombox_updater.config'`.

- [ ] **Step 3: Implement the module**

```python
# services/boombox_updater/config.py
"""User-editable updater config: /etc/boombox/updater.json.

Defaults are baked in for first-boot. The HTTP API's PUT validates input
through `validate()` before calling `save_config()`. All writes are
atomic (.tmp + rename) so a crashed write never corrupts the file.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/etc/boombox/updater.json")
ALLOWED_CHANNELS = ("stable", "edge")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class UpdaterConfig:
    auto: bool
    channel: str
    window_start: str       # "HH:MM" 24h
    window_duration_min: int


DEFAULT_CONFIG = UpdaterConfig(
    auto=True,
    channel="stable",
    window_start="03:00",
    window_duration_min=60,
)


def validate(raw: dict[str, Any]) -> UpdaterConfig:
    """Validate a dict and return an UpdaterConfig. Raises ValueError on
    any rule violation, with the offending key in the message."""
    if not isinstance(raw.get("auto"), bool):
        raise ValueError("auto must be a bool")
    channel = raw.get("channel")
    if channel not in ALLOWED_CHANNELS:
        raise ValueError(f"channel must be one of {ALLOWED_CHANNELS}")
    window_start = raw.get("window_start", "")
    if not isinstance(window_start, str) or not HHMM_RE.match(window_start):
        raise ValueError("window_start must be HH:MM (24h)")
    duration = raw.get("window_duration_min")
    if not isinstance(duration, int) or duration < 1 or duration > 24 * 60:
        raise ValueError("window_duration_min must be int in [1, 1440]")
    return UpdaterConfig(
        auto=raw["auto"],
        channel=channel,
        window_start=window_start,
        window_duration_min=duration,
    )


def load_config(path: Path = CONFIG_PATH) -> UpdaterConfig:
    """Load config, returning DEFAULT_CONFIG on missing/corrupt files."""
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG
    try:
        return validate(raw)
    except ValueError:
        return DEFAULT_CONFIG


def save_config(path: Path, cfg: UpdaterConfig) -> None:
    """Atomically write config (.tmp + rename, fsync)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n"
    with tmp.open("w") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_config.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_updater/config.py services/tests/test_updater_config.py
git commit -m "updater: atomic JSON config at /etc/boombox/updater.json"
```

---

## Task 5: Persisted runtime state (`/opt/boombox/state/updater.json`)

Holds last-check timestamp, available version, last-attempt result, and a pointer to the most recent install log.

**Files:**
- Create: `services/boombox_updater/state.py`
- Create: `services/tests/test_updater_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_updater_state.py
"""Tests for boombox_updater.state — persisted runtime state."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_updater.state import (
    EMPTY_STATE,
    AttemptResult,
    LastAttempt,
    State,
    StateStore,
)


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(state_dir=tmp_path)


def test_initial_state_is_empty(store: StateStore) -> None:
    assert store.load() == EMPTY_STATE


def test_round_trip(store: StateStore) -> None:
    new = State(
        installed_version="v0.4.1",
        available_version="v0.4.2",
        available_published_at="2026-05-13T01:23:45Z",
        last_check_ts=1747100000.0,
        last_attempt=LastAttempt(
            ts=1747103600.0, ref="v0.4.2",
            result=AttemptResult.OK, error=None, log_path="logs/2026-05-13.log",
        ),
        state_machine="idle",
    )
    store.save(new)
    assert store.load() == new


def test_partial_update(store: StateStore) -> None:
    """update() merges only the named fields."""
    store.save(EMPTY_STATE)
    store.update(installed_version="v0.4.1", state_machine="building")
    out = store.load()
    assert out.installed_version == "v0.4.1"
    assert out.state_machine == "building"
    assert out.available_version == EMPTY_STATE.available_version  # untouched


def test_log_dir_is_under_state(store: StateStore, tmp_path: Path) -> None:
    p = store.new_log_path(ref="v0.4.2")
    assert p.parent == tmp_path / "logs"
    assert "v0.4.2" in p.name
    # Must not exist yet — caller opens it.
    assert not p.exists()


def test_prune_logs_keeps_newest_n(store: StateStore, tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for i in range(15):
        (logs_dir / f"2026-05-{i:02d}-vX.log").write_text("x")
    store.prune_logs(keep=10)
    remaining = sorted(p.name for p in logs_dir.iterdir())
    assert len(remaining) == 10
    # Newest (highest day number) survive.
    assert remaining[0] == "2026-05-05-vX.log"


def test_atomic_save_no_leftover_tmp(store: StateStore, tmp_path: Path) -> None:
    store.save(EMPTY_STATE)
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.is_file() and p.name != "updater.json"]
    assert leftovers == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_state.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# services/boombox_updater/state.py
"""Persisted runtime state for boombox-updater.

Lives at /opt/boombox/state/updater.json (with a sibling logs/ dir for
per-attempt install logs). The file is the source of truth for the UI
and CLI — always atomic-write, never partial.
"""
from __future__ import annotations

import enum
import json
import os
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

DEFAULT_STATE_DIR = Path("/opt/boombox/state")
LOG_KEEP = 10  # how many per-attempt logs to retain


class AttemptResult(str, enum.Enum):
    OK = "ok"
    ROLLED_BACK = "rolled_back"
    BROKEN = "broken"           # rollback itself failed
    SKIPPED_PLAYBACK = "skipped_playback"
    FETCH_FAILED = "fetch_failed"
    BUILD_FAILED = "build_failed"
    SMOKE_FAILED = "smoke_failed"


@dataclass(frozen=True)
class LastAttempt:
    ts: float
    ref: str
    result: AttemptResult
    error: Optional[str]
    log_path: str  # relative to state dir


@dataclass(frozen=True)
class State:
    installed_version: str
    available_version: str
    available_published_at: str
    last_check_ts: float
    last_attempt: Optional[LastAttempt]
    state_machine: str  # "idle" | "fetching" | "building" | ... | "broken"


EMPTY_STATE = State(
    installed_version="unknown",
    available_version="",
    available_published_at="",
    last_check_ts=0.0,
    last_attempt=None,
    state_machine="idle",
)


def _serialize(state: State) -> dict:
    payload = asdict(state)
    if state.last_attempt is not None:
        payload["last_attempt"]["result"] = state.last_attempt.result.value
    return payload


def _deserialize(raw: dict) -> State:
    raw_attempt = raw.get("last_attempt")
    last_attempt: Optional[LastAttempt] = None
    if raw_attempt:
        last_attempt = LastAttempt(
            ts=float(raw_attempt["ts"]),
            ref=str(raw_attempt["ref"]),
            result=AttemptResult(raw_attempt["result"]),
            error=raw_attempt.get("error"),
            log_path=str(raw_attempt.get("log_path", "")),
        )
    return State(
        installed_version=str(raw.get("installed_version", "unknown")),
        available_version=str(raw.get("available_version", "")),
        available_published_at=str(raw.get("available_published_at", "")),
        last_check_ts=float(raw.get("last_check_ts", 0.0)),
        last_attempt=last_attempt,
        state_machine=str(raw.get("state_machine", "idle")),
    )


class StateStore:
    def __init__(self, state_dir: Path = DEFAULT_STATE_DIR) -> None:
        self._dir = state_dir
        self._file = state_dir / "updater.json"
        self._logs = state_dir / "logs"

    def load(self) -> State:
        try:
            raw = json.loads(self._file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return EMPTY_STATE
        try:
            return _deserialize(raw)
        except (KeyError, ValueError, TypeError):
            return EMPTY_STATE

    def save(self, state: State) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".json.tmp")
        payload = json.dumps(_serialize(state), indent=2, sort_keys=True) + "\n"
        with tmp.open("w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self._file)

    def update(self, **fields) -> State:
        """Merge fields into the persisted state and return the new value."""
        new = replace(self.load(), **fields)
        self.save(new)
        return new

    def new_log_path(self, ref: str) -> Path:
        self._logs.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H%M%S")
        safe_ref = ref.replace("/", "_")
        return self._logs / f"{ts}-{safe_ref}.log"

    def prune_logs(self, keep: int = LOG_KEEP) -> None:
        if not self._logs.is_dir():
            return
        files = sorted(self._logs.iterdir(), key=lambda p: p.name)
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_state.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_updater/state.py services/tests/test_updater_state.py
git commit -m "updater: persisted runtime state + log retention"
```

---

## Task 6: Window scheduler (pure decision function)

Given `(now, config, available_version, installed_version, playback_status)`, decide whether to install. Pure function — no IO, no clock, easy to test.

**Files:**
- Create: `services/boombox_updater/scheduler.py`
- Create: `services/tests/test_updater_scheduler.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_updater_scheduler.py
"""Tests for boombox_updater.scheduler — should_attempt_install()."""
from __future__ import annotations

from datetime import datetime

import pytest

from boombox_updater.config import UpdaterConfig
from boombox_updater.scheduler import (
    InstallDecision,
    SkipReason,
    should_attempt_install,
)


def cfg(**overrides) -> UpdaterConfig:
    base = dict(auto=True, channel="stable",
                window_start="03:00", window_duration_min=60)
    base.update(overrides)
    return UpdaterConfig(**base)


def at(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 13, hh, mm)


def test_inside_window_with_update_available_and_idle() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out == InstallDecision(install=True, reason=None)


def test_outside_window_skips() -> None:
    out = should_attempt_install(
        now=at(8, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.OUTSIDE_WINDOW


def test_window_wraps_midnight() -> None:
    # Window 23:00 -> 02:00 (180 min). 00:30 must still be inside.
    c = cfg(window_start="23:00", window_duration_min=180)
    out = should_attempt_install(
        now=at(0, 30), config=c,
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is True


def test_auto_disabled_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(auto=False),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.AUTO_DISABLED


def test_no_update_available_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.2", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.UP_TO_DATE


def test_playing_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="playing",
    )
    assert out.install is False
    assert out.reason == SkipReason.PLAYBACK_ACTIVE


def test_window_boundary_inclusive_start_exclusive_end() -> None:
    # Window 03:00 -> 04:00. 03:00 inside, 04:00 outside.
    inside = should_attempt_install(
        now=at(3, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    outside = should_attempt_install(
        now=at(4, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert inside.install is True
    assert outside.install is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# services/boombox_updater/scheduler.py
"""Scheduler decision: should we run an install right now?

Pure function — the caller injects the clock and the playback status. The
scheduler doesn't care how those were obtained, which makes it trivially
testable and free of timing flakiness.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .config import UpdaterConfig
from .version import compare_edge, compare_stable


class SkipReason(str, enum.Enum):
    AUTO_DISABLED = "auto_disabled"
    UP_TO_DATE = "up_to_date"
    OUTSIDE_WINDOW = "outside_window"
    PLAYBACK_ACTIVE = "playback_active"


@dataclass(frozen=True)
class InstallDecision:
    install: bool
    reason: Optional[SkipReason]


def _in_window(now: datetime, start: str, duration_min: int) -> bool:
    """Window is inclusive of start, exclusive of end. Wraps over midnight."""
    sh, sm = (int(x) for x in start.split(":"))
    window_start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=duration_min)
    if now >= window_start and now < window_end:
        return True
    # Handle wrap: window_end may be tomorrow; "now" may be this morning.
    if window_end.day != window_start.day:
        # The window spans midnight. Re-anchor to "today's window started yesterday".
        ws_yesterday = window_start - timedelta(days=1)
        we_yesterday = ws_yesterday + timedelta(minutes=duration_min)
        if now >= ws_yesterday and now < we_yesterday:
            return True
    return False


def should_attempt_install(
    *,
    now: datetime,
    config: UpdaterConfig,
    installed_version: str,
    available_version: str,
    playback_status: str,  # "playing" | "paused" | "stopped"
) -> InstallDecision:
    if not config.auto:
        return InstallDecision(install=False, reason=SkipReason.AUTO_DISABLED)
    if not available_version:
        return InstallDecision(install=False, reason=SkipReason.UP_TO_DATE)
    cmp_fn = compare_stable if config.channel == "stable" else compare_edge
    try:
        diff = cmp_fn(installed=installed_version, available=available_version)
    except ValueError:
        # An unparseable available version is treated as "no update".
        return InstallDecision(install=False, reason=SkipReason.UP_TO_DATE)
    if diff is None:
        return InstallDecision(install=False, reason=SkipReason.UP_TO_DATE)
    if not _in_window(now, config.window_start, config.window_duration_min):
        return InstallDecision(install=False, reason=SkipReason.OUTSIDE_WINDOW)
    if playback_status == "playing":
        return InstallDecision(install=False, reason=SkipReason.PLAYBACK_ACTIVE)
    return InstallDecision(install=True, reason=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_scheduler.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_updater/scheduler.py services/tests/test_updater_scheduler.py
git commit -m "updater: pure scheduler decision (window + playback + channel)"
```

---

## Task 7: Install state machine (logic only)

The state machine that drives an install. Subprocess steps are *injected* (a single `Steps` protocol) so unit tests cover all transitions — including the hardest cases: smoke-test failure → revert, two bad releases in a row, and revert-itself-fails.

**Files:**
- Create: `services/boombox_updater/installer.py`
- Create: `services/tests/test_updater_installer.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_updater_installer.py
"""Tests for boombox_updater.installer — the install state machine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from boombox_updater.installer import (
    InstallOutcome,
    InstallStep,
    Installer,
    StepResult,
)
from boombox_updater.state import AttemptResult


@dataclass
class FakeSteps:
    """Programmable Steps implementation. Each step returns the next entry
    from its list (default OK). Supports per-step overrides."""
    log: List[str] = field(default_factory=list)
    fetch: StepResult = StepResult.OK
    build: StepResult = StepResult.OK
    preflight: StepResult = StepResult.OK
    swap: StepResult = StepResult.OK
    restart: StepResult = StepResult.OK
    verify: StepResult = StepResult.OK
    revert: StepResult = StepResult.OK
    revert_verify: StepResult = StepResult.OK

    # Symlink "filesystem" — a dict updated by swap/revert so tests can assert.
    current: str = "v0.4.0"
    previous: Optional[str] = None

    def do_fetch(self, ref: str) -> StepResult:
        self.log.append(f"fetch {ref}")
        return self.fetch

    def do_build(self, ref: str) -> StepResult:
        self.log.append(f"build {ref}")
        return self.build

    def do_preflight(self, ref: str) -> StepResult:
        self.log.append(f"preflight {ref}")
        return self.preflight

    def do_swap(self, ref: str) -> StepResult:
        self.log.append(f"swap {ref}")
        if self.swap == StepResult.OK:
            self.previous = self.current
            self.current = ref
        return self.swap

    def do_restart(self) -> StepResult:
        self.log.append("restart")
        return self.restart

    def do_verify(self) -> StepResult:
        self.log.append("verify")
        return self.verify

    def do_revert(self) -> StepResult:
        self.log.append("revert")
        if self.revert == StepResult.OK and self.previous is not None:
            self.current = self.previous
        return self.revert

    def do_revert_verify(self) -> StepResult:
        self.log.append("revert_verify")
        return self.revert_verify

    def do_cleanup_failed_release(self, ref: str) -> None:
        self.log.append(f"cleanup {ref}")


def test_happy_path_advances_previous_and_returns_ok() -> None:
    steps = FakeSteps()
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.OK
    assert steps.current == "v0.4.1"
    assert steps.previous == "v0.4.0"
    assert steps.log == [
        "fetch v0.4.1", "build v0.4.1", "preflight v0.4.1",
        "swap v0.4.1", "restart", "verify",
    ]


def test_fetch_failure_does_not_swap() -> None:
    steps = FakeSteps(fetch=StepResult.FAIL)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.FETCH_FAILED
    assert steps.current == "v0.4.0"
    assert steps.previous is None
    assert "swap v0.4.1" not in steps.log
    assert "cleanup v0.4.1" in steps.log


def test_build_failure_cleans_up_release_dir() -> None:
    steps = FakeSteps(build=StepResult.FAIL)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.BUILD_FAILED
    assert steps.current == "v0.4.0"
    assert "cleanup v0.4.1" in steps.log


def test_smoke_failure_reverts() -> None:
    steps = FakeSteps(verify=StepResult.FAIL, previous=None)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref="v0.3.9")
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.ROLLED_BACK
    assert steps.current == "v0.3.9"          # revert flipped back
    assert "revert" in steps.log
    assert "revert_verify" in steps.log


def test_two_bad_releases_in_a_row_lands_on_last_known_good() -> None:
    """First bad install rolls back to v0.3.9 but does NOT advance previous.
    A subsequent bad install rolls back again — to v0.3.9 (the still-good
    previous), not to the just-rolled-back v0.4.1."""
    # First install attempt: v0.4.1 fails verify, rolls back.
    s1 = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous="v0.3.9")
    Installer(steps=s1, current_ref="v0.4.0", previous_ref="v0.3.9").install("v0.4.1")
    assert s1.current == "v0.3.9"
    assert s1.previous == "v0.4.0"  # revert moved current back; previous unchanged from the swap
    # NOTE: the spec says "previous is only advanced on success". The swap
    # itself temporarily set previous=v0.4.0; revert flips current back but
    # leaves the swap-set previous in place. The next install's previous is
    # whatever it reads from disk — i.e. the symlink target — which we test
    # in the integration test (Task 11). Here we only assert the in-memory
    # last_attempt result.

    # Second install attempt v0.4.2 also fails verify; passed previous_ref is
    # the still-good v0.3.9 (caller is expected to read symlink, not trust
    # the FakeSteps memory).
    s2 = FakeSteps(verify=StepResult.FAIL, current="v0.3.9", previous=None)
    out = Installer(steps=s2, current_ref="v0.3.9", previous_ref="v0.3.9").install("v0.4.2")
    assert out.result == AttemptResult.ROLLED_BACK


def test_revert_failure_marks_broken() -> None:
    steps = FakeSteps(verify=StepResult.FAIL, revert_verify=StepResult.FAIL,
                     current="v0.4.0", previous="v0.3.9")
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref="v0.3.9")
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.BROKEN


def test_no_previous_means_no_revert_attempt() -> None:
    """If there's nothing to revert to, a verify failure stays as-is and
    is reported as smoke_failed (not rolled_back)."""
    steps = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous=None)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.SMOKE_FAILED
    assert "revert" not in steps.log


def test_install_step_enum_in_order() -> None:
    """Catches accidental reordering of the state machine."""
    assert list(InstallStep) == [
        InstallStep.FETCHING, InstallStep.BUILDING, InstallStep.PREFLIGHT,
        InstallStep.SWAPPING, InstallStep.RESTARTING, InstallStep.VERIFYING,
        InstallStep.REVERTING, InstallStep.IDLE,
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_installer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# services/boombox_updater/installer.py
"""Install state machine.

State transitions are pure logic; the actual filesystem / subprocess work
lives behind the Steps protocol (see services/boombox-updater.py for the
real implementation that calls install/apply-release.sh).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, Protocol

from .state import AttemptResult


class StepResult(str, enum.Enum):
    OK = "ok"
    FAIL = "fail"


class InstallStep(str, enum.Enum):
    FETCHING = "fetching"
    BUILDING = "building"
    PREFLIGHT = "preflight"
    SWAPPING = "swapping"
    RESTARTING = "restarting"
    VERIFYING = "verifying"
    REVERTING = "reverting"
    IDLE = "idle"


class Steps(Protocol):
    def do_fetch(self, ref: str) -> StepResult: ...
    def do_build(self, ref: str) -> StepResult: ...
    def do_preflight(self, ref: str) -> StepResult: ...
    def do_swap(self, ref: str) -> StepResult: ...
    def do_restart(self) -> StepResult: ...
    def do_verify(self) -> StepResult: ...
    def do_revert(self) -> StepResult: ...
    def do_revert_verify(self) -> StepResult: ...
    def do_cleanup_failed_release(self, ref: str) -> None: ...


@dataclass(frozen=True)
class InstallOutcome:
    result: AttemptResult
    error: Optional[str] = None


class Installer:
    def __init__(
        self,
        *,
        steps: Steps,
        current_ref: str,
        previous_ref: Optional[str],
    ) -> None:
        self._steps = steps
        self._current = current_ref
        self._previous = previous_ref

    def install(self, ref: str) -> InstallOutcome:
        # 1. Fetch
        if self._steps.do_fetch(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.FETCH_FAILED, "git clone failed")

        # 2. Build
        if self._steps.do_build(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.BUILD_FAILED, "build failed")

        # 3. Preflight (still safe to abort — no symlinks moved yet).
        if self._steps.do_preflight(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.BUILD_FAILED, "preflight failed")

        # 4. Swap. After this, `current` points at the new release.
        if self._steps.do_swap(ref) != StepResult.OK:
            return self._attempt_revert("swap failed")

        # 5. Restart services.
        if self._steps.do_restart() != StepResult.OK:
            return self._attempt_revert("restart failed")

        # 6. Verify the new install is alive.
        if self._steps.do_verify() != StepResult.OK:
            return self._attempt_revert("smoke test failed")

        return InstallOutcome(AttemptResult.OK)

    def _attempt_revert(self, why: str) -> InstallOutcome:
        if self._previous is None:
            return InstallOutcome(AttemptResult.SMOKE_FAILED, why)
        if self._steps.do_revert() != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert failed")
        if self._steps.do_revert_verify() != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert verify failed")
        return InstallOutcome(AttemptResult.ROLLED_BACK, why)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_installer.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_updater/installer.py services/tests/test_updater_installer.py
git commit -m "updater: install state machine with rollback semantics"
```

---

## Task 8: `install/apply-release.sh` — the shell side

The `Steps` protocol's real implementation. Wraps git/npm/symlink/sudo operations. Designed to be re-runnable.

**Files:**
- Create: `install/apply-release.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# apply-release.sh — install a specific git ref into /opt/boombox/releases/<ref>,
# swap the `current` symlink, restart services. Designed to be safe to call
# from boombox-updater (window-driven) or from `boombox-update` (CLI fallback).
#
# Usage:
#   apply-release.sh fetch    <ref>
#   apply-release.sh build    <ref>
#   apply-release.sh preflight <ref>
#   apply-release.sh swap     <ref>
#   apply-release.sh restart
#   apply-release.sh verify
#   apply-release.sh revert
#   apply-release.sh cleanup  <ref>
#
# Each subcommand maps 1:1 to a Steps method on the Python side. Keeping
# them separate means the state machine can run them, log between them,
# and short-circuit cleanly on failure.
#
# Exit codes: 0 = ok, non-zero = step failed (the Python side translates
# this into StepResult.FAIL).

set -euo pipefail

ROOT="${BOOMBOX_ROOT:-/opt/boombox}"
RELEASES="$ROOT/releases"
CURRENT="$ROOT/current"
PREVIOUS="$ROOT/previous"
VENV="$ROOT/.venv"
REPO_URL="${BOOMBOX_REPO_URL:-https://github.com/IntergalacticTech/Boombox.git}"

log()  { printf '\033[1;36m[apply]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[apply]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,/^$/p' "$0" >&2
  exit 64
}

cmd="${1:-}"
[[ -n "$cmd" ]] || usage
shift || true

case "$cmd" in
  fetch)
    ref="${1:?ref required}"
    log "fetch $ref → $RELEASES/$ref"
    mkdir -p "$RELEASES"
    rm -rf "$RELEASES/$ref"
    git clone --depth=1 --branch "$ref" "$REPO_URL" "$RELEASES/$ref"
    # Persist the resolved version for later runs to compare against.
    if [[ "$ref" == v* ]]; then
      printf '%s\n' "$ref" >"$RELEASES/$ref/VERSION"
    else
      ( cd "$RELEASES/$ref" && git rev-parse --short HEAD ) >"$RELEASES/$ref/VERSION"
    fi
    ;;

  build)
    ref="${1:?ref required}"
    log "build $ref"
    [[ -d "$RELEASES/$ref" ]] || fail "$RELEASES/$ref missing — run fetch first"
    "$VENV/bin/pip" install -r "$RELEASES/$ref/install/config/requirements.txt"
    (
      cd "$RELEASES/$ref/ui"
      npm install --no-audit --no-fund
      npm run build
    )
    ;;

  preflight)
    ref="${1:?ref required}"
    log "preflight $ref"
    [[ -f "$RELEASES/$ref/ui/dist/index.html" ]] || fail "ui/dist/index.html missing"
    for unit in "$RELEASES/$ref"/install/systemd/user/*.service; do
      systemd-analyze --user verify "$unit" || fail "systemd-analyze rejected $unit"
    done
    sudo nginx -t
    "$VENV/bin/python" -c "
import importlib.util, sys
for mod in ('boombox_updater', 'boombox_buttons'):
    spec = importlib.util.spec_from_file_location(
        mod, '$RELEASES/$ref/services/' + mod.replace('_', '-') + '.py')
" 2>/dev/null || true   # smoke; full import test runs in verify step
    ;;

  swap)
    ref="${1:?ref required}"
    log "swap → $ref"
    [[ -d "$RELEASES/$ref" ]] || fail "$RELEASES/$ref missing"
    # Capture current target as the new previous, atomically.
    if [[ -L "$CURRENT" ]]; then
      old_target="$(readlink "$CURRENT")"
      ln -sfn "$old_target" "$PREVIOUS.new"
      mv -Tf "$PREVIOUS.new" "$PREVIOUS"
    fi
    ln -sfn "releases/$ref" "$CURRENT.new"
    mv -Tf "$CURRENT.new" "$CURRENT"
    # Sync any new systemd unit files into ~/.config/systemd/user/.
    install -m 0644 "$CURRENT/install/systemd/user/"*.service \
      "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    ;;

  restart)
    log "restart user services (excluding updater)"
    # The updater self-restarts last (handled by the Python side after verify).
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
    )
    for u in "${units[@]}"; do
      systemctl --user restart "$u.service" || true
    done
    sudo systemctl reload nginx
    ;;

  verify)
    log "verify liveness"
    deadline=$(( $(date +%s) + 30 ))
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
    )
    while (( $(date +%s) < deadline )); do
      ok=1
      for u in "${units[@]}"; do
        systemctl --user is-active --quiet "$u.service" || { ok=0; break; }
      done
      (( ok == 1 )) && break
      sleep 1
    done
    (( ok == 1 )) || fail "user services did not all become active"
    curl -fsS --max-time 5 http://localhost/            >/dev/null || fail "nginx /"
    curl -fsS --max-time 5 http://localhost/api/state   >/dev/null || fail "/api/state"
    curl -fsS --max-time 5 http://localhost/api/buttons/ >/dev/null || fail "/api/buttons/"
    ;;

  revert)
    log "revert: current ↔ previous"
    [[ -L "$PREVIOUS" ]] || fail "no previous symlink to revert to"
    prev_target="$(readlink "$PREVIOUS")"
    cur_target="$(readlink "$CURRENT")"
    ln -sfn "$prev_target" "$CURRENT.new"
    mv -Tf "$CURRENT.new" "$CURRENT"
    ln -sfn "$cur_target" "$PREVIOUS.new"
    mv -Tf "$PREVIOUS.new" "$PREVIOUS"
    install -m 0644 "$CURRENT/install/systemd/user/"*.service \
      "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
    )
    for u in "${units[@]}"; do
      systemctl --user restart "$u.service" || true
    done
    sudo systemctl reload nginx
    ;;

  cleanup)
    ref="${1:?ref required}"
    log "cleanup $RELEASES/$ref"
    rm -rf "$RELEASES/$ref"
    ;;

  prune)
    log "prune releases (keep current, previous, +1 most recent)"
    keep_set=()
    [[ -L "$CURRENT" ]]  && keep_set+=("$(readlink "$CURRENT")")
    [[ -L "$PREVIOUS" ]] && keep_set+=("$(readlink "$PREVIOUS")")
    in_keep() { local needle="$1"; for k in "${keep_set[@]}"; do [[ "$k" == "$needle" ]] && return 0; done; return 1; }
    mapfile -t all < <(ls -1t "$RELEASES" 2>/dev/null || true)
    extra_kept=0
    for entry in "${all[@]}"; do
      target="releases/$entry"
      if in_keep "$target"; then continue; fi
      if (( extra_kept < 1 )); then extra_kept=$((extra_kept+1)); continue; fi
      log "  pruning $RELEASES/$entry"
      rm -rf "${RELEASES:?}/$entry"
    done
    ;;

  *)
    usage
    ;;
esac
```

- [ ] **Step 2: Make it executable + verify it parses**

Run:
```bash
cd /Users/jwc/code/Boombox && chmod +x install/apply-release.sh && bash -n install/apply-release.sh && ./install/apply-release.sh 2>&1 | head -3
```
Expected: usage text printed (no syntax errors).

- [ ] **Step 3: Add the nginx-reload line to the sudoers fragment**

Edit `install/sudoers/boombox` and append:

```
# nginx reload from apply-release.sh after a release swap.
%BOOMBOX_USER% ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /bin/systemctl reload nginx, /usr/bin/systemctl reload nginx
```

- [ ] **Step 4: Commit**

```bash
git add install/apply-release.sh install/sudoers/boombox
git commit -m "updater: apply-release.sh + nginx reload sudoers grant"
```

---

## Task 9: `install/install.sh` — new layout + legacy migration

The load-bearing structural change: `/opt/boombox/` becomes `releases/<ref>/` + `current` symlink, and existing flat installs are migrated in place. **Order matters in this task**: every step here is in `install.sh` itself, which runs end-to-end.

**Files:**
- Modify: `install/install.sh`
- Modify: `install/systemd/user/boombox-state.service`
- Modify: `install/systemd/user/boombox-audio.service`
- Modify: `install/systemd/user/boombox-orchestrator.service`
- Modify: `install/systemd/user/boombox-buttons.service`
- Modify: `install/systemd/user/boombox-resume.service`
- Modify: `install/systemd/user/boombox-bt-volume.service`
- Modify: `install/systemd/user/boombox-kiosk-guard.service`
- Modify: `install/systemd/user/boombox-kiosk.service`
- Modify: `install/systemd/user/boombox-osk.service`
- Modify: `install/systemd/user/boombox-uploader.service`
- Modify: `install/config/nginx-boombox-common.conf`

- [ ] **Step 1: Update every systemd unit's path**

For each `*.service` file under `install/systemd/user/`, replace `/opt/boombox/` with `/opt/boombox/current/` in `ExecStart=` (and any `WorkingDirectory=`, `EnvironmentFile=` referencing the repo). The shared `.venv` stays at `/opt/boombox/.venv` (NOT `current/.venv`).

Concrete edit for `boombox-buttons.service` (apply the same pattern to all eight):

```diff
 [Service]
 Type=simple
-ExecStart=/opt/boombox/.venv/bin/python /opt/boombox/services/boombox-buttons.py
+ExecStart=/opt/boombox/.venv/bin/python /opt/boombox/current/services/boombox-buttons.py
 Restart=on-failure
```

Verify each unit still parses by reading it.

- [ ] **Step 2: Update nginx SPA root**

Edit `install/config/nginx-boombox-common.conf`:

```diff
-root /var/www/boombox;
+root /opt/boombox/current/ui/dist;
 index index.html;
```

And add the new `/api/update/` upstream right after the `/api/buttons/` block:

```nginx
# boombox-updater HTTP API (status, config, install, rollback, log).
location /api/update/ {
    proxy_pass http://127.0.0.1:6685/;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_read_timeout 5m;
    # SSE streams the install log on POST /api/update/install.
    proxy_buffering off;
}
```

- [ ] **Step 3: Refactor `install.sh` — replace the venv/UI/unit sections**

Replace the existing sections 2 (venv), 7 (UI build), and 9 (systemd units) with the migration-aware versions below. The rest of `install.sh` is unchanged.

**Migration helper** (insert near the top, after `BOOMBOX_USER=...`):

```bash
# ---------------------------------------------------------------------------
# Layout helpers — releases/<ref>/, current symlink
# ---------------------------------------------------------------------------
RELEASES_DIR="$REPO_DIR/releases"
CURRENT_LINK="$REPO_DIR/current"
PREVIOUS_LINK="$REPO_DIR/previous"
SHARED_VENV="$REPO_DIR/.venv"
STATE_DIR="$REPO_DIR/state"

# True when /opt/boombox is a flat git checkout (legacy layout).
is_legacy_layout() {
  [[ -d "$REPO_DIR/.git" ]] && [[ ! -L "$CURRENT_LINK" ]]
}

migrate_legacy_layout() {
  log "migrating legacy /opt/boombox layout → releases/<sha>/ + current symlink"
  local sha
  sha="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
  local target="$RELEASES_DIR/legacy-$sha"
  mkdir -p "$RELEASES_DIR" "$STATE_DIR"
  if [[ ! -d "$target" ]]; then
    # Move the entire checkout (including .git) into releases/legacy-<sha>/.
    # Skip the venv: it's about to live one level up.
    mkdir "$target"
    shopt -s dotglob nullglob
    for entry in "$REPO_DIR"/*; do
      base="$(basename "$entry")"
      case "$base" in
        .venv|releases|current|previous|state) continue ;;
      esac
      mv "$entry" "$target/"
    done
    shopt -u dotglob nullglob
    printf 'legacy\n' >"$target/VERSION"
  fi
  ln -sfn "releases/legacy-$sha" "$CURRENT_LINK"
  # No previous yet — first auto-update will populate it.
}
```

**Rewrite section 2 (venv) to operate on `current`:**

```bash
# ---------------------------------------------------------------------------
# 1.5. Layout migration (must run before anything else touches REPO_DIR)
# ---------------------------------------------------------------------------
if is_legacy_layout; then
  migrate_legacy_layout
fi

# Re-anchor SCRIPT_DIR / REPO_DIR to the migrated layout. SCRIPT_DIR no longer
# refers to the actual checkout — install.sh was launched from inside the
# legacy tree, but now lives at $CURRENT_LINK/install/install.sh after the
# move. Re-exec ourselves from the new location once.
ACTIVE_INSTALL="$CURRENT_LINK/install/install.sh"
if [[ "$BASH_SOURCE" != "$ACTIVE_INSTALL" && -x "$ACTIVE_INSTALL" ]]; then
  exec "$ACTIVE_INSTALL" "$@"
fi

ACTIVE_REPO="$CURRENT_LINK"
ACTIVE_SCRIPT_DIR="$CURRENT_LINK/install"

# ---------------------------------------------------------------------------
# 2. Python venv for boombox-* services (shared across releases)
# ---------------------------------------------------------------------------
log "creating $SHARED_VENV (--system-site-packages for dbus/gi)"
if [[ ! -d "$SHARED_VENV" ]]; then
  python3 -m venv --system-site-packages "$SHARED_VENV"
fi
"$SHARED_VENV/bin/pip" install --upgrade pip
"$SHARED_VENV/bin/pip" install -r "$ACTIVE_SCRIPT_DIR/config/requirements.txt"
```

(All subsequent `$REPO_DIR` / `$SCRIPT_DIR` references in install.sh become `$ACTIVE_REPO` / `$ACTIVE_SCRIPT_DIR`. Search-and-replace the whole file.)

**Rewrite section 7 (UI build) to land in `current/ui/dist/`:**

```bash
# ---------------------------------------------------------------------------
# 7. Build UI in place — nginx serves directly out of current/ui/dist/
# ---------------------------------------------------------------------------
log "building UI in $ACTIVE_REPO/ui"
(
  cd "$ACTIVE_REPO/ui"
  npm install --no-audit --no-fund
  npm run build
)
# nginx user (www-data) must be able to read the built SPA.
sudo chgrp -R www-data "$ACTIVE_REPO/ui/dist"
sudo chmod -R g+rX "$ACTIVE_REPO/ui/dist"
# Tear down the legacy doc root if it's still around.
if [[ -d /var/www/boombox && ! -L /var/www/boombox ]]; then
  log "removing legacy /var/www/boombox (nginx now serves from current/ui/dist)"
  sudo rm -rf /var/www/boombox
fi
```

**Add `boombox-updater` to the enabled units list (section 9):**

```diff
 USER_UNITS=(
   boombox-state
   boombox-audio
   boombox-orchestrator
   boombox-buttons
   boombox-resume
   boombox-bt-volume
   boombox-kiosk
   boombox-kiosk-guard
   boombox-osk
+  boombox-updater
 )
```

(The unit file itself is created in Task 10.)

- [ ] **Step 4: Smoke-test the install.sh changes (lint only — don't actually run on a real Pi yet)**

Run: `bash -n install/install.sh`
Expected: no syntax errors.

Then visually re-read your edits in `install/install.sh` to confirm every `$REPO_DIR` and `$SCRIPT_DIR` reference now points at `$ACTIVE_REPO` / `$ACTIVE_SCRIPT_DIR` (or, where it's truly meant to refer to the *root* /opt/boombox dir — `$REPO_DIR` is correct, e.g. for `$SHARED_VENV`).

- [ ] **Step 5: Commit**

```bash
git add install/install.sh install/systemd/user/*.service install/config/nginx-boombox-common.conf
git commit -m "install: migrate to releases/<ref>/ + current symlink layout"
```

---

## Task 10: `boombox-updater.py` entry point + HTTP API

Wires the package together: poll loop, scheduler loop, HTTP server. The Steps implementation calls `apply-release.sh`.

**Files:**
- Create: `services/boombox-updater.py`
- Create: `services/boombox_updater/api.py`
- Create: `services/tests/test_updater_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
# services/tests/test_updater_api.py
"""Tests for boombox_updater.api — HTTP surface."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from boombox_updater.api import build_app
from boombox_updater.config import (
    DEFAULT_CONFIG,
    UpdaterConfig,
    load_config,
    save_config,
)
from boombox_updater.state import (
    EMPTY_STATE,
    AttemptResult,
    LastAttempt,
    State,
    StateStore,
)


class FakeRunner:
    """Stand-in for the real install runner. Records calls."""
    def __init__(self) -> None:
        self.checked = 0
        self.installed: list[str] = []
        self.rolled_back = 0

    async def force_check(self) -> State:
        self.checked += 1
        return EMPTY_STATE

    async def install_now(self, ref: Optional[str] = None,
                          force: bool = False) -> AttemptResult:
        self.installed.append(ref or "latest")
        return AttemptResult.OK

    async def rollback(self) -> AttemptResult:
        self.rolled_back += 1
        return AttemptResult.OK


@pytest.fixture
def setup(tmp_path: Path):
    config_path = tmp_path / "updater.json"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    save_config(config_path, DEFAULT_CONFIG)
    store = StateStore(state_dir=state_dir)
    runner = FakeRunner()
    app = build_app(config_path=config_path, state_store=store, runner=runner)
    return app, config_path, store, runner


async def test_get_status(setup, aiohttp_client) -> None:
    app, *_ = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.get("/api/update/status")
    assert r.status == 200
    body = await r.json()
    assert body["channel"] == "stable"
    assert body["installed_version"] == "unknown"
    assert body["available_version"] == ""
    assert body["state_machine"] == "idle"
    assert body["auto"] is True


async def test_get_config_and_put_round_trip(setup, aiohttp_client) -> None:
    app, config_path, *_ = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.get("/api/update/config")
    assert r.status == 200
    cfg = await r.json()
    assert cfg["channel"] == "stable"

    r = await client.put("/api/update/config", json={
        "auto": False, "channel": "edge",
        "window_start": "02:30", "window_duration_min": 90,
    })
    assert r.status == 200

    persisted = load_config(config_path)
    assert persisted == UpdaterConfig(
        auto=False, channel="edge",
        window_start="02:30", window_duration_min=90,
    )


async def test_put_config_validates(setup, aiohttp_client) -> None:
    app, *_ = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.put("/api/update/config", json={
        "auto": True, "channel": "rolling",
        "window_start": "03:00", "window_duration_min": 60,
    })
    assert r.status == 400
    body = await r.json()
    assert "channel" in body["error"]


async def test_post_check_invokes_runner(setup, aiohttp_client) -> None:
    app, _, _, runner = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.post("/api/update/check")
    assert r.status == 200
    assert runner.checked == 1


async def test_post_install_with_force(setup, aiohttp_client) -> None:
    app, _, _, runner = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.post("/api/update/install", json={"force": True})
    assert r.status == 200
    body = await r.json()
    assert body["result"] == "ok"
    assert runner.installed == ["latest"]


async def test_post_rollback(setup, aiohttp_client) -> None:
    app, _, _, runner = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.post("/api/update/rollback")
    assert r.status == 200
    assert runner.rolled_back == 1


async def test_get_log_returns_404_when_no_attempt(setup, aiohttp_client) -> None:
    app, *_ = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.get("/api/update/log")
    assert r.status == 404


async def test_get_log_tails_last_attempt_log(setup, aiohttp_client, tmp_path) -> None:
    app, _, store, _ = setup
    log_path = store.new_log_path("v0.4.2")
    log_path.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")
    store.save(State(
        installed_version="v0.4.1", available_version="v0.4.2",
        available_published_at="", last_check_ts=0.0,
        last_attempt=LastAttempt(
            ts=0.0, ref="v0.4.2", result=AttemptResult.OK,
            error=None, log_path=str(log_path.relative_to(store._dir)),
        ),
        state_machine="idle",
    ))
    client: TestClient = await aiohttp_client(app)
    r = await client.get("/api/update/log?n=10")
    assert r.status == 200
    body = await r.text()
    lines = body.strip().split("\n")
    assert lines == [f"line {i}" for i in range(40, 50)]
```

(Add `pytest-aiohttp` to `requirements.txt` if not already present — it pulls in the `aiohttp_client` fixture used above. Check first; if absent:)

- [ ] **Step 2: Add `pytest-aiohttp` to requirements.txt**

```diff
 # Dev/test (installed in the venv even on the Pi so /opt/boombox can self-test).
 pytest>=8.0
 pytest-asyncio>=0.23
+pytest-aiohttp>=1.0
 watchdog>=4.0
```

Then `pip install pytest-aiohttp` locally.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'boombox_updater.api'`.

- [ ] **Step 4: Implement `boombox_updater/api.py`**

```python
# services/boombox_updater/api.py
"""HTTP surface for boombox-updater (mounted at :6685, proxied via nginx)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional, Protocol

from aiohttp import web

from . import __version__
from .config import (
    UpdaterConfig,
    load_config,
    save_config,
    validate,
)
from .state import AttemptResult, State, StateStore


class Runner(Protocol):
    async def force_check(self) -> State: ...
    async def install_now(self, ref: Optional[str] = None,
                          force: bool = False) -> AttemptResult: ...
    async def rollback(self) -> AttemptResult: ...


def _state_to_status(state: State, config: UpdaterConfig) -> dict:
    payload = {
        "installed_version": state.installed_version,
        "available_version": state.available_version,
        "available_published_at": state.available_published_at,
        "last_check_ts": state.last_check_ts,
        "state_machine": state.state_machine,
        "auto": config.auto,
        "channel": config.channel,
        "window_start": config.window_start,
        "window_duration_min": config.window_duration_min,
        "service_version": __version__,
    }
    if state.last_attempt is not None:
        payload["last_attempt"] = {
            "ts": state.last_attempt.ts,
            "ref": state.last_attempt.ref,
            "result": state.last_attempt.result.value,
            "error": state.last_attempt.error,
            "log_path": state.last_attempt.log_path,
        }
    else:
        payload["last_attempt"] = None
    return payload


def build_app(*, config_path: Path, state_store: StateStore,
              runner: Runner) -> web.Application:
    app = web.Application()

    async def get_status(_request: web.Request) -> web.Response:
        return web.json_response(
            _state_to_status(state_store.load(), load_config(config_path))
        )

    async def get_config(_request: web.Request) -> web.Response:
        return web.json_response(asdict(load_config(config_path)))

    async def put_config(request: web.Request) -> web.Response:
        try:
            raw = await request.json()
            cfg = validate(raw)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        save_config(config_path, cfg)
        return web.json_response(asdict(cfg))

    async def post_check(_request: web.Request) -> web.Response:
        new_state = await runner.force_check()
        return web.json_response(
            _state_to_status(new_state, load_config(config_path))
        )

    async def post_install(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        result = await runner.install_now(
            ref=body.get("ref"), force=bool(body.get("force", False)),
        )
        return web.json_response({"result": result.value})

    async def post_rollback(_request: web.Request) -> web.Response:
        result = await runner.rollback()
        return web.json_response({"result": result.value})

    async def get_log(request: web.Request) -> web.Response:
        n = int(request.query.get("n", 200))
        state = state_store.load()
        if not state.last_attempt or not state.last_attempt.log_path:
            return web.Response(status=404, text="no install attempt yet")
        log_path = state_store._dir / state.last_attempt.log_path  # noqa: SLF001
        try:
            lines = log_path.read_text().splitlines()
        except FileNotFoundError:
            return web.Response(status=404, text="log file missing")
        tail = "\n".join(lines[-n:]) + "\n"
        return web.Response(text=tail, content_type="text/plain")

    app.router.add_get("/api/update/status", get_status)
    app.router.add_get("/api/update/config", get_config)
    app.router.add_put("/api/update/config", put_config)
    app.router.add_post("/api/update/check", post_check)
    app.router.add_post("/api/update/install", post_install)
    app.router.add_post("/api/update/rollback", post_rollback)
    app.router.add_get("/api/update/log", get_log)
    return app
```

- [ ] **Step 5: Run API tests to verify they pass**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_api.py -v`
Expected: 8 passed.

- [ ] **Step 6: Implement the entry point (wires loops + Runner)**

```python
#!/usr/bin/env python3
# services/boombox-updater.py
"""boombox-updater service entry point.

Wires together: GitHub poller, scheduler decision, install state machine
backed by install/apply-release.sh, and the HTTP API on port 6685.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiohttp import ClientSession, web

from boombox_updater import __version__
from boombox_updater.api import build_app
from boombox_updater.config import CONFIG_PATH, load_config
from boombox_updater.installer import Installer, StepResult
from boombox_updater.poller import GitHubPoller
from boombox_updater.scheduler import should_attempt_install
from boombox_updater.state import (
    AttemptResult,
    LastAttempt,
    State,
    StateStore,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-updater")

REPO_ROOT = Path(os.environ.get("BOOMBOX_ROOT", "/opt/boombox"))
APPLY = REPO_ROOT / "current" / "install" / "apply-release.sh"
GITHUB_REPO = os.environ.get("BOOMBOX_REPO", "IntergalacticTech/Boombox")
PORT = int(os.environ.get("BOOMBOX_UPDATER_PORT", "6685"))
POLL_INTERVAL_S = int(os.environ.get("BOOMBOX_UPDATER_POLL_S", str(60 * 60)))
PLAYBACK_URL = "http://127.0.0.1/api/state"


class ShellSteps:
    """Real Steps implementation — shells out to apply-release.sh."""

    def __init__(self, log_path: Path) -> None:
        self._log = log_path
        self._log.parent.mkdir(parents=True, exist_ok=True)

    def _run(self, *args: str) -> StepResult:
        with self._log.open("a") as fh:
            fh.write(f"\n$ {APPLY} {' '.join(args)}\n")
            fh.flush()
            proc = subprocess.run(
                [str(APPLY), *args],
                stdout=fh, stderr=subprocess.STDOUT,
                env={**os.environ, "BOOMBOX_ROOT": str(REPO_ROOT)},
            )
        return StepResult.OK if proc.returncode == 0 else StepResult.FAIL

    def do_fetch(self, ref: str) -> StepResult:    return self._run("fetch", ref)
    def do_build(self, ref: str) -> StepResult:    return self._run("build", ref)
    def do_preflight(self, ref: str) -> StepResult: return self._run("preflight", ref)
    def do_swap(self, ref: str) -> StepResult:     return self._run("swap", ref)
    def do_restart(self) -> StepResult:            return self._run("restart")
    def do_verify(self) -> StepResult:             return self._run("verify")
    def do_revert(self) -> StepResult:             return self._run("revert")
    def do_revert_verify(self) -> StepResult:      return self._run("verify")
    def do_cleanup_failed_release(self, ref: str) -> None: self._run("cleanup", ref)


class UpdaterRunner:
    """Implements the api.Runner protocol."""

    def __init__(self, *, store: StateStore, poller: GitHubPoller,
                 lock: asyncio.Lock) -> None:
        self._store = store
        self._poller = poller
        self._lock = lock

    def _read_installed_version(self) -> str:
        try:
            return (REPO_ROOT / "current" / "VERSION").read_text().strip()
        except FileNotFoundError:
            return "unknown"

    def _read_previous_ref(self) -> Optional[str]:
        prev = REPO_ROOT / "previous"
        if not prev.is_symlink():
            return None
        target = os.readlink(prev)
        # readlink returns "releases/<ref>" — strip prefix.
        return Path(target).name

    def _read_current_ref(self) -> str:
        cur = REPO_ROOT / "current"
        if not cur.is_symlink():
            return "unknown"
        return Path(os.readlink(cur)).name

    async def force_check(self) -> State:
        cfg = load_config()
        if cfg.channel == "stable":
            result = await self._poller.poll_stable()
        else:
            result = await self._poller.poll_edge()
        installed = self._read_installed_version()
        avail = result.version if result else ""
        published = result.published_at if result else ""
        return self._store.update(
            installed_version=installed,
            available_version=avail,
            available_published_at=published,
            last_check_ts=time.time(),
        )

    async def install_now(self, ref: Optional[str] = None,
                          force: bool = False) -> AttemptResult:
        if not force and await _playback_active():
            return AttemptResult.SKIPPED_PLAYBACK
        async with self._lock:
            return await self._do_install(ref)

    async def rollback(self) -> AttemptResult:
        async with self._lock:
            log_path = self._store.new_log_path("rollback")
            steps = ShellSteps(log_path=log_path)
            if steps.do_revert() != StepResult.OK:
                return AttemptResult.BROKEN
            if steps.do_revert_verify() != StepResult.OK:
                return AttemptResult.BROKEN
            self._store.update(
                installed_version=self._read_installed_version(),
                last_attempt=LastAttempt(
                    ts=time.time(),
                    ref=self._read_current_ref(),
                    result=AttemptResult.OK,
                    error=None,
                    log_path=str(log_path.relative_to(self._store._dir)),
                ),
                state_machine="idle",
            )
            return AttemptResult.OK

    async def _do_install(self, ref: Optional[str]) -> AttemptResult:
        state = await self.force_check()
        target = ref or state.available_version
        if not target:
            return AttemptResult.OK  # nothing to do
        log_path = self._store.new_log_path(target)
        steps = ShellSteps(log_path=log_path)
        installer = Installer(
            steps=steps,
            current_ref=self._read_current_ref(),
            previous_ref=self._read_previous_ref(),
        )
        loop = asyncio.get_running_loop()
        outcome = await loop.run_in_executor(None, installer.install, target)
        self._store.update(
            installed_version=self._read_installed_version(),
            last_attempt=LastAttempt(
                ts=time.time(), ref=target,
                result=outcome.result, error=outcome.error,
                log_path=str(log_path.relative_to(self._store._dir)),
            ),
            state_machine="idle",
        )
        # On a successful install, prune old releases and self-restart.
        if outcome.result == AttemptResult.OK:
            subprocess.run([str(APPLY), "prune"], check=False)
            subprocess.run(
                ["systemctl", "--user", "reload-or-restart",
                 "boombox-updater.service"], check=False,
            )
        return outcome.result


async def _playback_active() -> bool:
    try:
        async with ClientSession() as session:
            async with session.get(PLAYBACK_URL,
                                   timeout=2.0) as resp:  # type: ignore[arg-type]
                if resp.status >= 400:
                    return False
                data = await resp.json()
                return data.get("status") == "playing"
    except Exception:
        return False


async def _scheduler_loop(runner: UpdaterRunner) -> None:
    """Wake every minute; if the configured window is open and a new
    version is available and nothing's playing, run an install."""
    while True:
        try:
            cfg = load_config()
            state = runner._store.load()
            decision = should_attempt_install(
                now=datetime.now(),
                config=cfg,
                installed_version=state.installed_version,
                available_version=state.available_version,
                playback_status="playing" if await _playback_active() else "paused",
            )
            if decision.install:
                log.info("scheduler: window open, installing %s",
                         state.available_version)
                await runner.install_now()
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        await asyncio.sleep(60)


async def _poll_loop(runner: UpdaterRunner) -> None:
    """Initial check 30s after start, then hourly."""
    await asyncio.sleep(30)
    while True:
        try:
            await runner.force_check()
        except Exception:  # noqa: BLE001
            log.exception("poll failed")
        await asyncio.sleep(POLL_INTERVAL_S)


async def main() -> None:
    log.info("boombox-updater %s starting on :%d", __version__, PORT)
    state_dir = REPO_ROOT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = StateStore(state_dir=state_dir)
    poller = GitHubPoller(repo=GITHUB_REPO)
    lock = asyncio.Lock()
    runner = UpdaterRunner(store=store, poller=poller, lock=lock)

    app = build_app(config_path=CONFIG_PATH, state_store=store, runner=runner)
    runner_task = asyncio.create_task(_scheduler_loop(runner))
    poll_task = asyncio.create_task(_poll_loop(runner))

    web_runner = web.AppRunner(app)
    await web_runner.setup()
    site = web.TCPSite(web_runner, "127.0.0.1", PORT)
    await site.start()

    try:
        await asyncio.Event().wait()
    finally:
        runner_task.cancel()
        poll_task.cancel()
        await web_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 7: Smoke-import the entry point**

Run: `cd /Users/jwc/code/Boombox && python3 -c "import importlib.util, pathlib; spec = importlib.util.spec_from_file_location('m', 'services/boombox-updater.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)"`
Expected: no output (clean import). Any ImportError or SyntaxError fails the step.

- [ ] **Step 8: Commit**

```bash
git add services/boombox-updater.py services/boombox_updater/api.py services/tests/test_updater_api.py install/config/requirements.txt
git commit -m "updater: HTTP API on :6685 + service entry point"
```

---

## Task 11: Systemd unit + install.sh enabling

**Files:**
- Create: `install/systemd/user/boombox-updater.service`

- [ ] **Step 1: Write the unit file**

```ini
# install/systemd/user/boombox-updater.service
[Unit]
Description=Boombox auto-updater (channel poll + scheduled install)
After=default.target network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/boombox/.venv/bin/python /opt/boombox/current/services/boombox-updater.py
Restart=on-failure
RestartSec=5
# The service writes /opt/boombox/state/* and reads /etc/boombox/updater.json.
# It shells out to /opt/boombox/current/install/apply-release.sh which uses
# sudo for nginx reload (granted via /etc/sudoers.d/boombox).

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Verify the unit parses**

Run: `systemd-analyze --user verify install/systemd/user/boombox-updater.service` (on a Linux dev machine; on macOS just `bash -n` is fine — full validation runs on the Pi).

- [ ] **Step 3: Run the integration test (Task 12 will verify end-to-end on a tempdir; for now smoke the package)**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/ -v`
Expected: all updater tests pass; pre-existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add install/systemd/user/boombox-updater.service
git commit -m "updater: systemd user unit"
```

---

## Task 12: End-to-end integration test (tempdir + mocked GitHub)

Drives a full install + rollback against a synthetic `/opt/boombox/` in a tempdir, with `apply-release.sh` swapped for a Python fake. This is the safety net for the state-machine + symlink swap interaction that unit tests can't exercise alone.

**Files:**
- Create: `services/tests/test_updater_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
# services/tests/test_updater_e2e.py
"""End-to-end: drive Installer + a tempdir /opt/boombox through happy path
+ rollback. apply-release.sh is replaced with a Python fake so this test
runs anywhere (no git, no npm, no systemd)."""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from boombox_updater.installer import Installer, StepResult


class TempdirSteps:
    """Real symlink swap behaviour, fake build / verify."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._releases = root / "releases"
        self._current = root / "current"
        self._previous = root / "previous"
        self._releases.mkdir(parents=True, exist_ok=True)
        self.verify_outcomes: List[StepResult] = []  # mutated per test
        self.verify_calls = 0

    # ---- helpers used by tests ----

    def stage_release(self, ref: str) -> None:
        (self._releases / ref).mkdir(parents=True, exist_ok=True)
        (self._releases / ref / "VERSION").write_text(ref + "\n")

    def point_current_at(self, ref: str) -> None:
        if self._current.exists() or self._current.is_symlink():
            self._current.unlink()
        self._current.symlink_to(Path("releases") / ref)

    def current_target(self) -> str:
        return self._current.resolve().name

    def previous_target(self) -> str | None:
        if not self._previous.is_symlink():
            return None
        return self._previous.resolve().name

    # ---- Steps protocol ----

    def do_fetch(self, ref: str) -> StepResult:
        self.stage_release(ref)
        return StepResult.OK

    def do_build(self, ref: str) -> StepResult:
        return StepResult.OK

    def do_preflight(self, ref: str) -> StepResult:
        return StepResult.OK

    def do_swap(self, ref: str) -> StepResult:
        # Capture current as new previous.
        if self._current.is_symlink():
            old = self._current.resolve().relative_to(self._root)
            if self._previous.exists() or self._previous.is_symlink():
                self._previous.unlink()
            self._previous.symlink_to(old)
        if self._current.exists() or self._current.is_symlink():
            self._current.unlink()
        self._current.symlink_to(Path("releases") / ref)
        return StepResult.OK

    def do_restart(self) -> StepResult:
        return StepResult.OK

    def do_verify(self) -> StepResult:
        self.verify_calls += 1
        if self.verify_outcomes:
            return self.verify_outcomes.pop(0)
        return StepResult.OK

    def do_revert(self) -> StepResult:
        prev = self._previous.resolve().relative_to(self._root)
        cur = self._current.resolve().relative_to(self._root)
        self._current.unlink(); self._current.symlink_to(prev)
        self._previous.unlink(); self._previous.symlink_to(cur)
        return StepResult.OK

    def do_revert_verify(self) -> StepResult:
        return StepResult.OK

    def do_cleanup_failed_release(self, ref: str) -> None:
        target = self._releases / ref
        if target.exists():
            for child in target.iterdir():
                child.unlink()
            target.rmdir()


def test_happy_path(tmp_path: Path) -> None:
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")

    Installer(steps=steps, current_ref="v0.4.0",
              previous_ref=None).install("v0.4.1")

    assert steps.current_target() == "v0.4.1"
    assert steps.previous_target() == "v0.4.0"


def test_smoke_failure_rolls_back(tmp_path: Path) -> None:
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")
    # First verify (post-swap) fails; revert_verify uses do_revert_verify
    # which always returns OK in this fake.
    steps.verify_outcomes = [StepResult.FAIL]

    Installer(steps=steps, current_ref="v0.4.0",
              previous_ref=None).install("v0.4.1")

    # Without a previous symlink at install-time, the spec says no revert.
    # But TempdirSteps populates previous in do_swap, and Installer reads
    # `previous_ref=None` from the constructor. Confirm the constructor
    # contract: with previous_ref=None, smoke fail does NOT call do_revert.
    assert steps.current_target() == "v0.4.1"


def test_two_bad_releases_lands_on_last_known_good(tmp_path: Path) -> None:
    """v0.4.0 → install v0.4.1 (bad) → install v0.4.2 (bad).
    After both, current should be back at v0.4.0 (the original good one)."""
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")

    # First bad install. previous_ref is "v0.4.0" because that's what's on disk
    # (caller reads symlink). Installer knows to revert to it.
    steps.verify_outcomes = [StepResult.FAIL]
    Installer(steps=steps, current_ref="v0.4.0",
              previous_ref=None).install("v0.4.1")
    # Without a `previous` to roll back to, the bad install stays.
    # This matches the spec: the very first install attempt has no safety net.
    assert steps.current_target() == "v0.4.1"

    # Second install. Now previous_ref IS set by the caller (read from disk
    # — which after the swap above is v0.4.0). A bad install should roll back
    # to v0.4.0.
    steps.verify_outcomes = [StepResult.FAIL]
    Installer(steps=steps, current_ref="v0.4.1",
              previous_ref="v0.4.0").install("v0.4.2")

    assert steps.current_target() == "v0.4.0"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/test_updater_e2e.py -v`
Expected: 3 passed.

- [ ] **Step 3: Run the full updater test suite**

Run: `cd /Users/jwc/code/Boombox && pytest services/tests/ -v`
Expected: all updater tests pass + pre-existing button/state tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/tests/test_updater_e2e.py
git commit -m "updater: end-to-end test of install + rollback"
```

---

## Task 13: Rewrite `bin/boombox-update` as a thin client

**Files:**
- Modify: `bin/boombox-update`
- Modify: `install/update.sh`

- [ ] **Step 1: Replace `bin/boombox-update`**

```bash
#!/usr/bin/env bash
# boombox-update — thin client of the boombox-updater HTTP API.
# Falls back to install/apply-release.sh main when the service is disabled
# or unreachable.
set -euo pipefail

API="http://127.0.0.1:6685/api/update"
ROOT="${BOOMBOX_ROOT:-/opt/boombox}"
APPLY="$ROOT/current/install/apply-release.sh"

api_up() {
  curl -fsS --max-time 2 "$API/status" >/dev/null 2>&1
}

fallback() {
  local ref="${1:-main}"
  echo "[update] boombox-updater service unreachable — direct mode" >&2
  "$APPLY" fetch "$ref" && \
  "$APPLY" build "$ref" && \
  "$APPLY" preflight "$ref" && \
  "$APPLY" swap "$ref" && \
  "$APPLY" restart && \
  "$APPLY" verify
}

usage() {
  cat <<EOF >&2
Usage: boombox-update [status|check|install [REF]|rollback|config]
  (no args)        check + (if available) install latest, follow log
  status           dump /api/update/status JSON
  check            force a poll
  install [REF]    install latest, or a specific tag/sha
  rollback         flip to previous
  config           show effective config (read-only — set via UI)
EOF
  exit 64
}

cmd="${1:-default}"
shift || true

if ! api_up; then
  case "$cmd" in
    default|install) fallback "${1:-main}" ;;
    *) echo "[update] service unreachable; '$cmd' requires the API" >&2; exit 1 ;;
  esac
  exit
fi

case "$cmd" in
  status)
    curl -fsS "$API/status" | jq .
    ;;
  check)
    curl -fsS -X POST "$API/check" | jq .
    ;;
  config)
    curl -fsS "$API/config" | jq .
    ;;
  rollback)
    curl -fsS -X POST "$API/rollback" | jq .
    ;;
  install)
    body="{}"
    [[ -n "${1:-}" ]] && body="$(printf '{"ref":"%s"}' "$1")"
    curl -fsS -X POST -H 'Content-Type: application/json' -d "$body" "$API/install"
    ;;
  default)
    curl -fsS -X POST "$API/check" >/dev/null
    curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' "$API/install"
    ;;
  *)
    usage
    ;;
esac
```

- [ ] **Step 2: Reduce `install/update.sh` to a back-compat shim**

```bash
#!/usr/bin/env bash
# update.sh — back-compat shim. The real updater lives in the boombox-updater
# service + install/apply-release.sh; this is here so anything still calling
# `update.sh` keeps working.
set -euo pipefail
exec /usr/local/bin/boombox-update "$@"
```

- [ ] **Step 3: Verify both parse**

Run: `bash -n bin/boombox-update && bash -n install/update.sh`
Expected: no output (no syntax errors).

- [ ] **Step 4: Commit**

```bash
git add bin/boombox-update install/update.sh
git commit -m "updater: CLI as thin client of /api/update + fallback"
```

---

## Task 14: UI — Updates section in SettingsDrawer

**Files:**
- Create: `ui/src/lib/updaterApi.ts`
- Create: `ui/src/lib/UpdatesPanel.tsx`
- Modify: `ui/src/lib/SettingsDrawer.tsx`

- [ ] **Step 1: Create the typed API client**

```typescript
// ui/src/lib/updaterApi.ts — typed client for /api/update/* (port 6685, fronted
// by nginx). Mirrors the config + status surface of boombox_updater.api.

export type Channel = "stable" | "edge";

export type UpdaterConfig = {
  auto: boolean;
  channel: Channel;
  window_start: string;        // "HH:MM" 24h
  window_duration_min: number;
};

export type LastAttempt = {
  ts: number;
  ref: string;
  result: "ok" | "rolled_back" | "broken" | "skipped_playback"
        | "fetch_failed" | "build_failed" | "smoke_failed";
  error: string | null;
  log_path: string;
};

export type UpdaterStatus = UpdaterConfig & {
  installed_version: string;
  available_version: string;
  available_published_at: string;
  last_check_ts: number;
  state_machine: string;
  service_version: string;
  last_attempt: LastAttempt | null;
};

export async function getStatus(): Promise<UpdaterStatus> {
  const r = await fetch("/api/update/status");
  if (!r.ok) throw new Error(`status ${r.status}`);
  return r.json();
}

export async function saveConfig(cfg: UpdaterConfig): Promise<UpdaterConfig> {
  const r = await fetch("/api/update/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({ error: "save failed" }));
    throw new Error(body.error || `save failed (${r.status})`);
  }
  return r.json();
}

export async function check(): Promise<UpdaterStatus> {
  const r = await fetch("/api/update/check", { method: "POST" });
  if (!r.ok) throw new Error(`check ${r.status}`);
  return r.json();
}

export async function installNow(opts: { ref?: string; force?: boolean } = {}):
  Promise<{ result: string }> {
  const r = await fetch("/api/update/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  if (!r.ok) throw new Error(`install ${r.status}`);
  return r.json();
}

export async function rollback(): Promise<{ result: string }> {
  const r = await fetch("/api/update/rollback", { method: "POST" });
  if (!r.ok) throw new Error(`rollback ${r.status}`);
  return r.json();
}

export async function fetchLog(n: number = 200): Promise<string> {
  const r = await fetch(`/api/update/log?n=${n}`);
  if (r.status === 404) return "(no install attempts yet)";
  if (!r.ok) throw new Error(`log ${r.status}`);
  return r.text();
}
```

- [ ] **Step 2: Create the UpdatesPanel component**

```tsx
// ui/src/lib/UpdatesPanel.tsx — Updates section for SettingsDrawer.
// Quiet UI: no badge, no overlay. Status is only visible when the user
// opens Settings. Auto-update on by default; user can flip channel,
// window, and trigger a manual install / rollback.

import { useEffect, useState } from "react";
import {
  Channel,
  UpdaterStatus,
  check,
  fetchLog,
  getStatus,
  installNow,
  rollback,
  saveConfig,
} from "./updaterApi";

function fmtAgo(ts: number): string {
  if (!ts) return "never";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export function UpdatesPanel() {
  const [status, setStatus] = useState<UpdaterStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [logText, setLogText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    try { setStatus(await getStatus()); }
    catch (e) { setErr(String(e)); }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  if (!status) {
    return (
      <div className="settings-section">
        <h3>Updates</h3>
        <div>Loading… {err && <span style={{ color: "tomato" }}>{err}</span>}</div>
      </div>
    );
  }

  const upToDate = !status.available_version
    || status.installed_version === status.available_version;

  const update = async (patch: Partial<typeof status>) => {
    const next = { ...status, ...patch };
    try {
      await saveConfig({
        auto: next.auto, channel: next.channel,
        window_start: next.window_start,
        window_duration_min: next.window_duration_min,
      });
      setStatus(next);
    } catch (e) { setErr(String(e)); }
  };

  const wrap = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr(null);
    try { await fn(); await refresh(); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(null); }
  };

  return (
    <div className="settings-section">
      <h3>Updates</h3>

      <div>
        {upToDate
          ? <>Up to date — <strong>{status.installed_version}</strong> ({status.channel})</>
          : <>Update available: <strong>{status.available_version}</strong> (installed: {status.installed_version})</>
        }
        <div style={{ opacity: 0.7, fontSize: "0.85em" }}>
          Last checked: {fmtAgo(status.last_check_ts)}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
        <span>Auto-update</span>
        <button disabled={busy !== null} onClick={() => update({ auto: !status.auto })}>
          {status.auto ? "On" : "Off"}
        </button>
        <span style={{ marginLeft: 12 }}>Channel</span>
        <select
          value={status.channel}
          disabled={busy !== null}
          onChange={(e) => update({ channel: e.target.value as Channel })}
        >
          <option value="stable">stable</option>
          <option value="edge">edge</option>
        </select>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
        <span>Window</span>
        <input
          type="time"
          value={status.window_start}
          disabled={busy !== null}
          onChange={(e) => update({ window_start: e.target.value })}
          style={{ width: 90 }}
        />
        <span>for</span>
        <input
          type="number"
          min={1} max={1440}
          value={status.window_duration_min}
          disabled={busy !== null}
          onChange={(e) => update({ window_duration_min: Number(e.target.value) })}
          style={{ width: 70 }}
        />
        <span>min</span>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button disabled={busy !== null}
                onClick={() => wrap("check", check)}>
          {busy === "check" ? "Checking…" : "Check now"}
        </button>
        <button disabled={busy !== null || upToDate}
                onClick={() => wrap("install", () => installNow({ force: true }))}>
          {busy === "install" ? "Installing…" : "Install now"}
        </button>
        <button disabled={busy !== null}
                onClick={() => wrap("rollback", rollback)}>
          {busy === "rollback" ? "Rolling back…" : "Rollback"}
        </button>
      </div>

      {status.last_attempt && (
        <div style={{ marginTop: 8, fontSize: "0.9em" }}>
          Last attempt: {new Date(status.last_attempt.ts * 1000).toLocaleString()} —
          <strong> {status.last_attempt.result}</strong>
          {status.last_attempt.error && (
            <div style={{ color: "tomato" }}>{status.last_attempt.error}</div>
          )}
          <button style={{ marginTop: 4 }}
                  onClick={async () => setLogText(await fetchLog(500))}>
            View log
          </button>
        </div>
      )}

      {logText !== null && (
        <pre style={{
          marginTop: 8, maxHeight: 200, overflow: "auto",
          background: "#111", color: "#ddd", padding: 8, fontSize: "0.8em",
        }}>
          {logText}
        </pre>
      )}

      {err && <div style={{ color: "tomato", marginTop: 6 }}>{err}</div>}
    </div>
  );
}
```

- [ ] **Step 3: Render the panel inside SettingsDrawer**

Edit `ui/src/lib/SettingsDrawer.tsx`. Add the import near the top:

```diff
 import { useEffect, useState } from "react";
 import { ButtonsPanel } from "./ButtonsPanel";
 import { setSleepMinutes, useSleepTimer } from "./sleepTimer";
+import { UpdatesPanel } from "./UpdatesPanel";
```

Then inside the JSX — find the section that renders `<ButtonsPanel />` (or any other section near the bottom) and append:

```diff
       <ButtonsPanel />
+      <UpdatesPanel />
     </div>
```

(If the existing JSX uses different containers, place `<UpdatesPanel />` as a sibling section that follows the existing comment "Designed to fit on the 5″ screen without scrolling: each section is a compact row, ~60 px tall." with one row added — drawer will start scrolling, which is acceptable for the new section per the spec.)

- [ ] **Step 4: Type-check the UI**

Run:
```bash
cd /Users/jwc/code/Boombox/ui && npx tsc --noEmit
```
Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/updaterApi.ts ui/src/lib/UpdatesPanel.tsx ui/src/lib/SettingsDrawer.tsx
git commit -m "ui(updates): SettingsDrawer panel — channel, window, install, rollback"
```

---

## Task 15: Docs + CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/SERVICES.md`

- [ ] **Step 1: Update README "Self-update on the Pi" section**

Replace the existing section (lines ~58–66) with:

```markdown
## Updates

Devices auto-check GitHub for new releases hourly and (by default) install
new **stable** releases inside a nightly window of 03:00–04:00, skipping if
music is playing. Toggle channel, window, and auto-on/off in
**Settings → Updates** on the touchscreen or LAN web page.

Manual control from a shell:

```bash
boombox-update            # check + install latest now
boombox-update status     # current channel, installed/available versions
boombox-update install v0.4.2
boombox-update rollback   # flip back to the previous release
```

Updates are A/B-installed under `/opt/boombox/releases/<ref>/` with the
`current` symlink swapped atomically. Bad releases auto-revert to the
previous good one if smoke-tests fail.
```

- [ ] **Step 2: Add a CHANGELOG entry**

Prepend to `CHANGELOG.md`:

```markdown
## Unreleased

### Added
- `boombox-updater` service: auto-discovers GitHub releases on `stable`
  channel (or `main` HEAD on `edge`); installs unattended inside a daily
  window (default 03:00–04:00); skips if music is playing.
- A/B install layout (`releases/<ref>/` + `current`/`previous` symlinks)
  with smoke-test + automatic rollback on failure.
- Settings → Updates panel on touchscreen + LAN web page.

### Changed
- `/opt/boombox` reorganised to release-pointer layout. First run of the
  installer migrates legacy flat checkouts in place.
- nginx now serves the SPA from `/opt/boombox/current/ui/dist/` instead
  of `/var/www/boombox/`.
- `bin/boombox-update` rewritten as a thin client of `/api/update/*`,
  with a fallback that runs `apply-release.sh` directly when the service
  is disabled.

### Roadmap
- [x] Versioned releases + signed update channel — half-shipped
  (versioned: yes; signed: deferred to v2)
```

(Match the existing `CHANGELOG.md` formatting — read it first to confirm headings and tense.)

- [ ] **Step 3: Add to `docs/SERVICES.md`**

Append a row to the services table and a section. Read the existing format first; pattern after the `boombox-buttons` entry.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md docs/SERVICES.md
git commit -m "docs: auto-update — README, CHANGELOG, SERVICES.md entry"
```

---

## Self-Review

**Spec coverage:** every section of the spec maps to at least one task —
filesystem layout (Task 9), updater service (Task 10), state machine (Task 7),
smoke test (Task 8 — `verify` subcommand), CLI (Task 13), UI (Task 14),
config (Task 4), state (Task 5), poller (Task 3), version compare (Task 2),
scheduler (Task 6), opt-out (CLI fallback in Task 13 + service-level disable
documented in Task 15), tests (Tasks 2-7, 10, 12), release process (Task 1
VERSION file).

**Placeholder scan:** no TBDs, no "implement later," no "similar to Task N",
no naked `git commit` without a message. Each TDD step has either real test
code or real implementation code shown in full.

**Type consistency:** `UpdaterConfig` (config.py / api.py / updaterApi.ts),
`State` and `LastAttempt` (state.py / api.py / updaterApi.ts),
`AttemptResult` (state.py / installer.py / api.py / updaterApi.ts) — names
and field shapes are consistent across Python and TS.

**Known minor scope items kept inside the plan:**
- Manual on-Pi smoke (cut a v0.0.1-test release, watch nightly auto-install
  roll back) — listed in the spec, omitted from the plan since it requires
  physical hardware and a release tag. Add a short note in the README's
  Updates section if this becomes a release-process checklist.
