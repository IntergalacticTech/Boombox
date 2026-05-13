"""Auth middleware for boombox-remote."""
from __future__ import annotations

import json
import pytest


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
    # /state isn't fully implemented yet — pass-through to whatever stub handler
    # exists. We only assert it's NOT a 401. A 200 or 503 is fine for now.
    assert resp.status != 401
