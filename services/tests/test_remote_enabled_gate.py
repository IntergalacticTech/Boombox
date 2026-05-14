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
    body = await resp.json()
    assert body["error"] == "remote_disabled"


@pytest.mark.asyncio
async def test_pair_403_when_disabled(disabled_app, aiohttp_client):
    client = await aiohttp_client(disabled_app)
    resp = await client.post("/api/remote/pair", json={"pin": "000000"})
    assert resp.status == 403
    # /api/remote/pair also 403s on a bad PIN; assert on the error key so
    # this proves the *gate* fired, not the bad-PIN path.
    body = await resp.json()
    assert body["error"] == "remote_disabled"


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


@pytest.fixture
def toggleable_app(tmp_path, monkeypatch):
    """An app whose remote_enabled flag starts ON but can be toggled at
    runtime via remote_access.set_enabled (which re-reads BOOMBOX_REMOTE_STATE
    on every call). The peers.json token 't' stays fixed throughout."""
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"enabled": True}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    return boombox_remote.create_app()


@pytest.mark.asyncio
async def test_token_durable_across_off_on_toggle(toggleable_app, aiohttp_client):
    # Spec requirement: a paired token still authenticates after the
    # remote_enabled flag is toggled off → on. peers.json is never rewritten;
    # only the access flag round-trips.
    import remote_access
    client = await aiohttp_client(toggleable_app)

    # Flag OFF: the gate fires regardless of the (still-valid) token.
    remote_access.set_enabled(False)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 403

    # Flag back ON: the same token must still authenticate. Not 401 (token
    # still known) and not 403 (gate open again). 503 (no aggregator) is fine.
    remote_access.set_enabled(True)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status != 401
    assert resp.status != 403
