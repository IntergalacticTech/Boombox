"""Tests for /api/remote/video/* (services/jellyfin_client.py)."""
from __future__ import annotations

import json

import pytest


class FakeJellyfin:
    """Stand-in for jellyfin_client.JellyfinClient."""

    def __init__(self, state=None, command_result=None):
        self._state = state or {"active": False}
        self._command_result = command_result or {"ok": True}
        self.commands = []

    async def local_session_state(self):
        return self._state

    async def command(self, action, value=None):
        self.commands.append((action, value))
        return self._command_result


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


@pytest.mark.asyncio
async def test_video_routes_require_token(video_app, aiohttp_client):
    # Routes must be registered first (video_app returns a bare app), then
    # a request with no Authorization header → require_auth middleware 401s
    # before the handler. Proves the video surface isn't exposed unauthed.
    import jellyfin_client
    jellyfin_client.add_routes(video_app, FakeJellyfin())
    client = await aiohttp_client(video_app)
    resp = await client.get("/api/remote/video/state")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_command_returns_502_when_jellyfin_fails(video_app, aiohttp_client):
    import jellyfin_client
    fake = FakeJellyfin(command_result={"ok": False, "error": "no_session"})
    jellyfin_client.add_routes(video_app, fake)
    client = await aiohttp_client(video_app)
    resp = await client.post("/api/remote/video/command",
                             json={"action": "play_pause"},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 502
    assert (await resp.json())["error"] == "no_session"
