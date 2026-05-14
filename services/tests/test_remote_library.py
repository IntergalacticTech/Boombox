"""Tests for /api/remote/library, /playlists, /queue (remote_library.py)."""
from __future__ import annotations

import json

import pytest


class FakeMopidy:
    """Stand-in for clients.MopidyRpc — records calls, returns canned data."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    async def call(self, method, params=None):
        self.calls.append((method, params or {}))
        return self.responses.get(method, {"result": None})


@pytest.fixture
def library_app(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    fake = FakeMopidy()
    import boombox_remote
    app = boombox_remote.create_app()
    import remote_library
    remote_library.add_routes(app, fake)
    return app, fake


@pytest.mark.asyncio
async def test_search_returns_tracks(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.library.search"] = {"result": [
        {"tracks": [{"uri": "local:track:a", "name": "Song A",
                     "artists": [{"name": "Band"}]}]},
    ]}
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/library/search?q=song",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    assert body["tracks"][0]["uri"] == "local:track:a"
    assert ("core.library.search", {"query": {"any": ["song"]}}) in fake.calls


@pytest.mark.asyncio
async def test_search_missing_q_returns_400(library_app, aiohttp_client):
    app, _ = library_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/library/search",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_list_playlists(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.playlists.as_list"] = {"result": [
        {"name": "Road trip", "uri": "m3u:road.m3u"},
    ]}
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/playlists",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert (await resp.json())["playlists"][0]["name"] == "Road trip"


@pytest.mark.asyncio
async def test_create_playlist_round_trip(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.playlists.create"] = {
        "result": {"name": "New", "uri": "m3u:new.m3u", "tracks": []}}
    fake.responses["core.playlists.save"] = {
        "result": {"name": "New", "uri": "m3u:new.m3u"}}
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/playlists",
                             json={"name": "New",
                                   "uris": ["local:track:a"]},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    methods = [m for m, _ in fake.calls]
    assert "core.playlists.create" in methods
    assert "core.playlists.save" in methods


@pytest.mark.asyncio
async def test_playlist_items_returns_uris(library_app, aiohttp_client):
    app, fake = library_app
    fake.responses["core.playlists.get_items"] = {"result": [
        {"uri": "local:track:a"}, {"uri": "local:track:b"},
    ]}
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/playlists/m3u:road.m3u/items",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert (await resp.json())["uris"] == ["local:track:a", "local:track:b"]
    assert ("core.playlists.get_items", {"uri": "m3u:road.m3u"}) in fake.calls


@pytest.mark.asyncio
async def test_create_playlist_failure_returns_502(library_app, aiohttp_client):
    # FakeMopidy returns {"result": None} for unconfigured methods, so
    # core.playlists.create yields no playlist → 502 create_failed.
    app, _ = library_app
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/playlists",
                             json={"name": "X", "uris": ["local:track:a"]},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 502


@pytest.mark.asyncio
async def test_queue_replaces_and_plays(library_app, aiohttp_client):
    app, fake = library_app
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/queue",
                             json={"uris": ["local:track:a"], "play": True},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    methods = [m for m, _ in fake.calls]
    assert methods == ["core.tracklist.clear", "core.tracklist.add",
                       "core.playback.play"]
