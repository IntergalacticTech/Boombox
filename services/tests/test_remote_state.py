"""Tests for GET /api/remote/state."""
from __future__ import annotations

import json
import sys

import pytest


@pytest.fixture
async def app_with_stub_upstream(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "test", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))

    import boombox_remote

    class StubAggregator:
        async def consolidated_state(self):
            return {
                "boombox": {"id": "boombox-test", "name": "Test", "version": 1},
                "source": "mopidy",
                "playing": True,
                "track": {"title": "Hey Jude", "artist": "The Beatles",
                          "album": "The Beatles 1967-1970",
                          "duration_s": 431, "position_s": 12},
                "art_hash": "sha1:abc",
                "art_url": "/api/remote/art/abc.jpg",
                "volume": 65,
                "muted": False,
                "sources_available": ["mopidy", "airplay", "spotify",
                                       "bluetooth", "movies"],
                "sleep_timer_s": None,
                "recording": False,
                "mic_on": False,
                "skin": "retro-blue",
                "theme": {},
            }

    app = boombox_remote.create_app(aggregator=StubAggregator())
    return app


@pytest.mark.asyncio
async def test_state_returns_consolidated_payload(
        app_with_stub_upstream, aiohttp_client):
    client = await aiohttp_client(app_with_stub_upstream)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["data"]["track"]["title"] == "Hey Jude"
    assert body["data"]["volume"] == 65
    assert body["data"]["sources_available"] == [
        "mopidy", "airplay", "spotify", "bluetooth", "movies"]


@pytest.mark.asyncio
async def test_state_without_aggregator_returns_503(tmp_path, monkeypatch,
                                                     aiohttp_client):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "test", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))

    import boombox_remote
    app = boombox_remote.create_app()  # no aggregator passed
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/state",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 503
    body = await resp.json()
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_consolidated_state_includes_theme():
    import boombox_remote  # noqa: F401 — loads the impl module
    mod = sys.modules["boombox_remote_impl"]

    agg = mod.StateAggregator(session=None, boombox_id="b", boombox_name="B")

    class FakeMopidy:
        async def call(self, method, params=None):
            return {"result": None}

    class FakeState:
        async def snapshot(self):
            return None

        async def volume_get(self):
            return (0.65, False)

        async def karaoke_state(self):
            return False

        async def power(self):
            return "awake"

    async def fake_theme():
        return {"skinId": "spectrum", "name": "Spectrum",
                "theme": {"bg": "#000", "accent": "#0ff"}}

    agg._mopidy = FakeMopidy()
    agg._state = FakeState()
    agg._fetch_theme = fake_theme

    data = await agg.consolidated_state()
    assert data["skin"] == "spectrum"
    assert data["theme"] == {"bg": "#000", "accent": "#0ff"}


def _agg_with_power(power):
    """A StateAggregator with stubbed upstreams; `power` is the
    StateApi.power coroutine to use."""
    import boombox_remote  # noqa: F401 — loads the impl module
    mod = sys.modules["boombox_remote_impl"]
    agg = mod.StateAggregator(session=None, boombox_id="b", boombox_name="B")

    class FakeMopidy:
        async def call(self, method, params=None):
            return {"result": None}

    class FakeState:
        async def snapshot(self):
            return None

        async def volume_get(self):
            return None

        async def karaoke_state(self):
            return False

    FakeState.power = power  # type: ignore[attr-defined]

    async def fake_theme():
        return {}

    agg._mopidy = FakeMopidy()
    agg._state = FakeState()
    agg._fetch_theme = fake_theme
    return agg


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["awake", "asleep"])
async def test_consolidated_state_includes_power(value):
    async def power(self):
        return value
    data = await _agg_with_power(power).consolidated_state()
    assert data["power"] == value


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.urls: list[str] = []

    def get(self, url, **kw):
        self.urls.append(url)
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


@pytest.mark.asyncio
@pytest.mark.parametrize("resp,expected", [
    (_FakeResp(200, {"state": "asleep", "since": 1.0}), "asleep"),
    (_FakeResp(200, {"state": "awake", "since": 1.0}), "awake"),
    # Unknown / unavailable power manager -> awake, never a crash.
    (_FakeResp(503, {"error": "power manager unavailable"}), "awake"),
    (_FakeResp(200, {"state": "hibernating"}), "awake"),
    (_FakeResp(200, ["not", "a", "dict"]), "awake"),
    (_FakeResp(200, ValueError("bad json")), "awake"),
    (OSError("connection refused"), "awake"),
])
async def test_state_api_power(resp, expected):
    import clients
    sess = _FakeSession(resp)
    assert await clients.StateApi(sess).power() == expected
    assert sess.urls == [clients.STATE_BASE + "/power"]
