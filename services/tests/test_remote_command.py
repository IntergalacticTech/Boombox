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
