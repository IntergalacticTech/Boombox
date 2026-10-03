"""POST /api/remote/video/play — kiosk session discovery, WATCH wake, PlayNow."""
from __future__ import annotations

import json

import aiohttp
import pytest
from aiohttp import web

AUTH = {"Authorization": "Bearer t"}
KEY = "sekrit-key-0123456789abcdef"
DEVICE = "boombox-markii-kiosk"
LIVE = {"Id": "5e55", "DeviceId": DEVICE, "SupportsRemoteControl": True,
        "LastActivityDate": "2026-09-29T20:00:00Z"}


class FakeJF:
    def __init__(self) -> None:
        self.device_user: str | None = "u1"
        self.sessions: list[dict] = []
        self.session_queries: list[str] = []
        self.plays: list[tuple[str, dict[str, str]]] = []
        self.play_status = 204
        self.ignore_wake = False

    def app(self) -> web.Application:
        async def handle(req: web.Request) -> web.StreamResponse:
            p = req.path
            if p == "/Devices/Info":
                return web.json_response({"LastUserId": self.device_user})
            if p == "/Sessions":
                self.session_queries.append(req.query_string)
                return web.json_response(self.sessions)
            if p.startswith("/Sessions/") and p.endswith("/Playing"):
                self.plays.append((p, dict(req.query)))
                return web.Response(status=self.play_status)
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        return app


@pytest.fixture
async def play_env(aiohttp_server, aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    key = tmp_path / "jellyfin-api-key"
    key.write_text(KEY)
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", DEVICE)
    monkeypatch.setenv("BOOMBOX_REMOTE_VIDEO_CACHE", str(tmp_path / "video-cache"))
    jf = FakeJF()
    srv = await aiohttp_server(jf.app())
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", str(srv.make_url("")).rstrip("/"))
    woke: list[int] = []

    async def wake() -> None:
        woke.append(1)
        if not jf.ignore_wake:
            jf.sessions = [dict(LIVE)]

    import boombox_remote
    import remote_video
    app = boombox_remote.create_app()
    session = aiohttp.ClientSession()
    browser = remote_video.JellyfinBrowser(session, session_wait_s=0.5, poll_s=0.01)
    remote_video.add_routes(app, browser, wake_kiosk=wake)
    client = await aiohttp_client(app)
    yield client, jf, woke
    await session.close()


async def _play(client, body):
    return await client.post("/api/remote/video/play", json=body, headers=AUTH)


async def test_play_requires_pair_token(play_env):
    client, _jf, _woke = play_env
    r = await client.post("/api/remote/video/play", json={"item_id": "aa11"})
    assert r.status == 401


async def test_play_uses_live_session_without_waking(play_env):
    client, jf, woke = play_env
    jf.sessions = [dict(LIVE)]
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and (await r.json()) == {"ok": True}
    assert woke == []
    assert jf.plays == [("/Sessions/5e55/Playing", {"playCommand": "PlayNow", "itemIds": "aa11"})]
    assert f"deviceId={DEVICE}" in jf.session_queries[0]


async def test_play_passes_start_ticks(play_env):
    client, jf, _woke = play_env
    jf.sessions = [dict(LIVE)]
    r = await _play(client, {"item_id": "aa11", "start_ticks": 7_540_000_000})
    assert r.status == 200
    assert jf.plays[0][1]["startPositionTicks"] == "7540000000"


async def test_play_wakes_kiosk_and_waits_for_session(play_env):
    client, jf, woke = play_env
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200
    assert woke == [1]
    assert jf.plays and jf.plays[0][0] == "/Sessions/5e55/Playing"
    assert len(jf.session_queries) >= 2           # checked, woke, polled


async def test_play_ignores_session_without_remote_control(play_env):
    client, jf, woke = play_env
    jf.sessions = [{**LIVE, "SupportsRemoteControl": False}]   # tab gone, socket closed
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and woke == [1]


async def test_play_ignores_other_devices_sessions(play_env):
    client, jf, woke = play_env
    jf.sessions = [{**LIVE, "Id": "7a7a", "DeviceId": "living-room-tv"}]
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and woke == [1]
    assert all(path == "/Sessions/5e55/Playing" for path, _q in jf.plays)


async def test_play_session_never_appears_is_504(play_env):
    client, jf, woke = play_env
    jf.ignore_wake = True
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 504
    assert (await r.json())["error"] == "the boombox's video player didn't open — try again"
    assert woke == [1] and jf.plays == []


async def test_play_overall_timeout_is_504(play_env, monkeypatch):
    import remote_video
    client, jf, _woke = play_env
    jf.ignore_wake = True
    monkeypatch.setattr(remote_video, "PLAY_TIMEOUT_S", 0.05)
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 504
    assert "took too long" in (await r.json())["error"]


async def test_play_not_signed_in_is_409_and_does_not_wake(play_env):
    client, jf, woke = play_env
    jf.device_user = None
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 409
    assert (await r.json())["error"] == "kiosk not signed in"
    assert woke == [] and jf.plays == []


async def test_play_refused_by_server_is_502(play_env):
    client, jf, _woke = play_env
    jf.sessions = [dict(LIVE)]
    jf.play_status = 500
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 502
    assert (await r.json())["error"] == "video server refused to start playback"


@pytest.mark.parametrize("body", [{}, {"item_id": "../x"}, {"item_id": "aa11", "start_ticks": -1},
                                  {"item_id": "aa11", "start_ticks": "5"},
                                  {"item_id": "aa11", "start_ticks": True}, ["aa11"]])
async def test_play_rejects_bad_bodies(play_env, body):
    client, jf, woke = play_env
    r = await _play(client, body)
    assert r.status == 400 and woke == [] and jf.plays == []


async def test_play_without_kiosk_control_is_503(play_env, aiohttp_client):
    import boombox_remote
    import remote_video
    _client, jf, _woke = play_env
    app = boombox_remote.create_app()
    async with aiohttp.ClientSession() as s:
        remote_video.add_routes(app, remote_video.JellyfinBrowser(s))   # no wake callback
        c = await aiohttp_client(app)
        r = await _play(c, {"item_id": "aa11"})
    assert r.status == 503
    assert (await r.json())["error"] == "the boombox screen can't be controlled"
    assert jf.plays == []


async def test_unpinned_builtin_server_uses_loopback_session(play_env, monkeypatch):
    client, jf, woke = play_env
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    monkeypatch.setenv("JELLYFIN_USER_ID", "u1")
    jf.sessions = [{**LIVE, "Id": "7a7a", "DeviceId": "tv", "RemoteEndPoint": "192.168.1.9"},
                   {**LIVE, "Id": "5e55", "DeviceId": "x", "RemoteEndPoint": "127.0.0.1"}]
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and woke == []
    assert jf.plays[0][0] == "/Sessions/5e55/Playing"
