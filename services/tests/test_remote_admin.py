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
