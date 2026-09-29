"""JellyfinClient session targeting + command HTTP handling."""
from __future__ import annotations

import logging

import aiohttp
import jellyfin_client
import pytest
from aiohttp import web
from jellyfin_client import JellyfinClient, server_is_local


def _sess(sid, *, device_id="d-", name="Chrome", ep="203.0.113.9",
          last="2026-09-28T10:00:00Z", playing=True):
    s = {"Id": sid, "DeviceId": device_id + sid, "DeviceName": name,
         "RemoteEndPoint": ep, "LastActivityDate": last}
    if playing:
        s["NowPlayingItem"] = {"Name": f"movie-{sid}", "RunTimeTicks": 0}
    return s


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID", raising=False)
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_NAME", raising=False)
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")


def _client() -> JellyfinClient:
    return JellyfinClient(session=None)  # type: ignore[arg-type]


# ---- server_is_local ------------------------------------------------------

@pytest.mark.parametrize("base,expected", [
    ("http://127.0.0.1:8096", True),
    ("http://localhost:8096", True),
    ("http://[::1]:8096", True),
    ("http://192.168.1.10:8096", True),
    ("http://10.0.0.5", True),
    ("http://nas:8096", True),
    ("http://jellyfin.local:8096", True),
    ("https://video.example.com", False),
    ("https://video.coblr.io", False),
    ("http://8.8.8.8:8096", False),
    ("http://[2606:4700:4700::1111]:8096", False),
    ("https://[2001:4860:4860::8888]:8096", False),
    ("http://[fd00::10]:8096", True),
    ("http://[fe80::1]:8096", True),
    ("", False),
])
def test_server_is_local(base, expected):
    assert server_is_local(base) is expected


# ---- selection -------------------------------------------------------------

def test_remote_server_without_pin_refuses_arbitrary_session(caplog):
    c = _client()
    sessions = [_sess("tv", last="2026-09-28T12:00:00Z"), _sess("kiosk")]
    with caplog.at_level(logging.INFO, logger="boombox-remote"):
        assert c._select_session(sessions) is None
        assert c._select_session(sessions) is None
    msgs = [r for r in caplog.records if "BOOMBOX_JELLYFIN_DEVICE_ID" in r.getMessage()]
    assert len(msgs) == 1 and msgs[0].levelno == logging.INFO


def test_device_id_pin_wins(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", "d-kiosk")
    sessions = [_sess("tv", last="2026-09-28T12:00:00Z"), _sess("kiosk")]
    assert _client()._select_session(sessions)["Id"] == "kiosk"


def test_device_name_pin(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_NAME", "Boombox")
    sessions = [_sess("tv", name="Living Room", last="2026-09-28T12:00:00Z"),
                _sess("kiosk", name="Boombox")]
    assert _client()._select_session(sessions)["Id"] == "kiosk"


def test_device_id_falls_back_to_name(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", "stale-id")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_NAME", "Boombox")
    sessions = [_sess("tv", name="TV"), _sess("kiosk", name="Boombox")]
    assert _client()._select_session(sessions)["Id"] == "kiosk"


def test_pinned_but_not_playing_never_falls_through(monkeypatch):
    # Even on a LAN server, an explicit pin must not grab another TV.
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://192.168.1.10:8096")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", "d-kiosk")
    sessions = [_sess("tv"), _sess("kiosk", playing=False)]
    assert _client()._select_session(sessions) is None


@pytest.mark.parametrize("base,loopback", [
    ("http://127.0.0.1:8096", True),
    ("http://localhost:8096", True),
    ("http://[::1]:8096", True),
    ("http://192.168.1.10:8096", False),
    ("https://video.coblr.io", False),
])
def test_server_is_loopback(base, loopback):
    assert jellyfin_client.server_is_loopback(base) is loopback


def test_loopback_endpoint_preferred(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://127.0.0.1:8096")
    sessions = [_sess("tv", ep="192.168.1.50", last="2026-09-28T12:00:00Z"),
                _sess("kiosk", ep="127.0.0.1")]
    assert _client()._select_session(sessions)["Id"] == "kiosk"


def test_remote_server_loopback_endpoints_unpinned_refuse():
    # Remote server behind a same-host proxy/tunnel: every client is 127.0.0.1.
    sessions = [_sess("tv", ep="127.0.0.1", last="2026-09-28T12:00:00Z"),
                _sess("kiosk", ep="127.0.0.1")]
    assert _client()._select_session(sessions) is None


def test_remote_server_loopback_endpoints_pinned_no_match(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", "d-kiosk")
    sessions = [_sess("tv", ep="127.0.0.1"), _sess("kiosk", ep="127.0.0.1", playing=False)]
    assert _client()._select_session(sessions) is None


def test_pin_beats_loopback_on_local_server(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://127.0.0.1:8096")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", "d-kiosk")
    sessions = [_sess("tv", ep="127.0.0.1", last="2026-09-28T12:00:00Z"),
                _sess("kiosk", ep="127.0.0.1", playing=False)]
    assert _client()._select_session(sessions) is None


def test_ipv6_public_server_is_not_local_fallback(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://[2606:4700:4700::1111]:8096")
    sessions = [_sess("tv", last="2026-09-28T12:00:00Z"), _sess("kiosk")]
    assert _client()._select_session(sessions) is None


def test_local_server_keeps_most_recent_fallback(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://127.0.0.1:8096")
    sessions = [_sess("old", ep="192.168.1.50", last="2026-09-28T09:00:00Z"),
                _sess("new", ep="192.168.1.51", last="2026-09-28T12:00:00Z")]
    assert _client()._select_session(sessions)["Id"] == "new"


def test_nothing_playing_is_none(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://127.0.0.1:8096")
    assert _client()._select_session([_sess("a", playing=False)]) is None


# ---- command() against a fake Jellyfin --------------------------------------

@pytest.fixture
async def fake_jf(aiohttp_server, tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text("tok\n")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    state = {"posts": [], "status": 204,
             "sessions": [_sess("kiosk", ep="127.0.0.1")]}

    async def sessions(_r):
        return web.json_response(state["sessions"])

    async def post(r: web.Request):
        body = await r.read()
        state["posts"].append((r.path, r.query_string, body))
        return web.Response(status=state["status"])

    app = web.Application()
    app.router.add_get("/Sessions", sessions)
    app.router.add_post("/Sessions/{sid}/{tail:.*}", post)
    srv = await aiohttp_server(app)
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", str(srv.make_url("")))
    return state


async def test_command_posts_and_reports_ok(fake_jf):
    async with aiohttp.ClientSession() as s:
        c = JellyfinClient(s)
        assert await c.command("play_pause") == {"ok": True}
        assert await c.command("seek", 12) == {"ok": True}
        assert await c.command("volume", 40) == {"ok": True}
    paths = [p for p, _q, _b in fake_jf["posts"]]
    assert paths == ["/Sessions/kiosk/Playing/PlayPause",
                     "/Sessions/kiosk/Playing/Seek",
                     "/Sessions/kiosk/Command"]
    assert fake_jf["posts"][1][1] == "seekPositionTicks=120000000"
    assert b"SetVolume" in fake_jf["posts"][2][2]


async def test_command_surfaces_http_error(fake_jf):
    fake_jf["status"] = 404
    async with aiohttp.ClientSession() as s:
        res = await JellyfinClient(s).command("stop")
    assert res == {"ok": False, "error": "jellyfin_http_404"}


async def test_command_no_session(fake_jf):
    fake_jf["sessions"] = []
    async with aiohttp.ClientSession() as s:
        res = await JellyfinClient(s).command("stop")
    assert res == {"ok": False, "error": "no_session"}


async def test_command_unknown_action_short_circuits(fake_jf):
    async with aiohttp.ClientSession() as s:
        res = await JellyfinClient(s).command("explode")
    assert res["error"] == "unknown_action:explode"
    assert fake_jf["posts"] == []


def test_module_exports_env_names():
    assert jellyfin_client.DEVICE_ID_ENV == "BOOMBOX_JELLYFIN_DEVICE_ID"
    assert jellyfin_client.DEVICE_NAME_ENV == "BOOMBOX_JELLYFIN_DEVICE_NAME"
