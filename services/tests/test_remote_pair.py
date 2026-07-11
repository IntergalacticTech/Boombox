"""Tests for PIN-based pairing endpoints."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
async def app_with_pairing(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text("{}")
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    monkeypatch.setenv("BOOMBOX_ID", "boombox-test")
    monkeypatch.setenv("BOOMBOX_NAME", "Test")

    import boombox_remote
    return boombox_remote.create_app(), peers


@pytest.mark.asyncio
async def test_pair_start_returns_pin(app_with_pairing, aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/pair/start")
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert len(body["pin"]) == 6
    assert body["pin"].isdigit()
    assert body["expires_at"] > 0


@pytest.mark.asyncio
async def test_pair_redeems_pin_and_writes_peer(app_with_pairing,
                                                  aiohttp_client):
    app, peers_path = app_with_pairing
    client = await aiohttp_client(app)
    pin = (await (await client.post("/api/remote/pair/start"))
            .json())["pin"]

    resp = await client.post("/api/remote/pair",
                              json={"pin": pin, "label": "my-cyd"})
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert len(body["auth_token"]) == 64
    assert body["boombox_id"] == "boombox-test"
    assert body["boombox_name"] == "Test"

    peers = json.loads(peers_path.read_text())
    assert body["auth_token"] in peers
    assert peers[body["auth_token"]]["label"] == "my-cyd"


@pytest.mark.asyncio
async def test_pair_rejects_bad_pin(app_with_pairing, aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    await client.post("/api/remote/pair/start")

    resp = await client.post("/api/remote/pair",
                              json={"pin": "000000", "label": "x"})
    assert resp.status == 403
    body = await resp.json()
    assert body["ok"] is False
    assert body["error"] == "bad_pin"


@pytest.mark.asyncio
async def test_pair_pin_single_use(app_with_pairing, aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    pin = (await (await client.post("/api/remote/pair/start"))
            .json())["pin"]
    # First redemption succeeds
    r1 = await client.post("/api/remote/pair",
                            json={"pin": pin, "label": "a"})
    assert r1.status == 200
    # Second with the same PIN fails (invalidated)
    r2 = await client.post("/api/remote/pair",
                            json={"pin": pin, "label": "b"})
    assert r2.status == 403


@pytest.mark.asyncio
async def test_pair_without_active_pin_rejects(app_with_pairing,
                                                 aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    # No /pair/start has been called
    resp = await client.post("/api/remote/pair",
                              json={"pin": "123456", "label": "x"})
    assert resp.status == 403
