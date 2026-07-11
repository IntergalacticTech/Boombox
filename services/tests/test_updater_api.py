# services/tests/test_updater_api.py
"""Tests for boombox_updater.api — HTTP surface."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest
from aiohttp.test_utils import TestClient
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


async def test_post_install_rejects_bad_ref(setup, aiohttp_client) -> None:
    # A path-traversal ref must be rejected before it reaches the shell, and
    # the runner must never be invoked.
    app, _, _, runner = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.post(
        "/api/update/install", json={"ref": "../../home/boombox/.config"}
    )
    assert r.status == 400
    assert runner.installed == []


async def test_post_install_accepts_valid_ref(setup, aiohttp_client) -> None:
    app, _, _, runner = setup
    client: TestClient = await aiohttp_client(app)
    r = await client.post("/api/update/install", json={"ref": "v0.4.2"})
    assert r.status == 200
    assert runner.installed == ["v0.4.2"]


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
