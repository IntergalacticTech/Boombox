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
    ws = await client.ws_connect("/api/remote/ws?token=wrong")
    # Server closes immediately with code 4401 (custom: auth).
    msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
    assert msg.type.name in ("CLOSE", "CLOSED")
