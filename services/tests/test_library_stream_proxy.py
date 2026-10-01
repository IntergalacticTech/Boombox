"""Tests for the boombox-library HTTP additions: the local stream proxy
(/api/library/stream/<id>), batch resolve, and the artist/album/playlist
detail endpoints."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from boombox_library import stream_proxy
from boombox_library.api import build_app
from boombox_library.db import connect, migrate

AUDIO = bytes(range(256)) * 40  # 10 240 bytes of recognisable payload


class Ctx:
    """Minimal runtime context — only what the routes under test touch."""

    def __init__(self, conn, source, online=True):
        self.conn = conn
        self.cfg = SimpleNamespace(source=source)
        self._online = online
        self.online_calls = 0
        self.marked_offline = 0
        self.art_cache_dir = Path("/tmp/boombox-art-test")
        self.snapshot_dir = Path("/tmp/boombox-snap-test")

    async def is_online(self) -> bool:
        self.online_calls += 1
        return self._online

    def mark_offline(self) -> None:
        self.marked_offline += 1


def _seed(conn):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,art_id,updated_at) "
                 "VALUES('ar1','ABBA','abba',3,'ar-ar1',0)")
    for al_id, name, year in (("al2", "Voulez-Vous", 1979), ("al1", "Arrival", 1976),
                              ("al0", "Gold", None), ("al3", "Abba", 1976)):
        conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,year,song_count,"
                     "duration_s,art_id,is_compilation,navidrome_starred,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,0,0,0)",
                     (al_id, name, name.lower(), "ar1", year, 2, 60, f"al-{al_id}"))
    rows = [
        ("t3", "al1", "Tiger", 1, 2),
        ("t1", "al1", "Dancing Queen", 1, 1),
        ("t2", "al1", "Money Money Money", 2, 1),
    ]
    for tid, al, title, track_no, disc_no in rows:
        conn.execute("INSERT INTO tracks(id,album_id,title,track_no,disc_no,duration_s,"
                     "suffix,size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES(?,?,?,?,?,200,'mp3',1000,'audio/mpeg',0,0)",
                     (tid, al, title, track_no, disc_no))
    conn.execute("INSERT INTO playlists(id,name,song_count,updated_at) "
                 "VALUES('pl1','Road Trip',3,0)")
    for pos, tid in enumerate(["t2", "ghost", "t1"]):
        conn.execute("INSERT INTO playlist_tracks(playlist_id,track_id,position) "
                     "VALUES('pl1',?,?)", (tid, pos))


# ----- fake Navidrome -----

class Upstream:
    def __init__(self):
        self.requests: list[web.Request] = []
        self.mode = "ok"
        self.aborted = asyncio.Event()

    async def handler(self, req: web.Request) -> web.StreamResponse:
        self.requests.append(req)
        if self.mode == "subsonic_error":
            return web.json_response(
                {"subsonic-response": {"status": "failed",
                                       "error": {"code": 70, "message": "not found"}}})
        if self.mode == "auth_error":
            return web.json_response(
                {"subsonic-response": {"status": "failed",
                                       "error": {"code": 40, "message": "bad creds"}}})
        if self.mode == "string_error":
            return web.json_response(
                {"subsonic-response": {"status": "failed", "error": "bad"}})
        if self.mode == "http500":
            return web.Response(status=500, text="boom")
        if self.mode == "http530":
            return web.Response(status=530, text="origin unreachable")
        if self.mode == "slow":
            await asyncio.sleep(2)
        if self.mode == "endless":
            # A paused/playing track: the relay never finishes on its own.
            resp = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
            await resp.prepare(req)
            while True:
                await resp.write(b"x" * 4096)
                await asyncio.sleep(0.01)
        if self.mode == "trickle":
            resp = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
            await resp.prepare(req)
            try:
                for _ in range(500):
                    await resp.write(b"x" * 4096)
                    await asyncio.sleep(0.01)
            except (ConnectionResetError, asyncio.CancelledError):
                self.aborted.set()
                raise
            return resp
        rng = req.headers.get("Range")
        if rng:
            start_s, _, end_s = rng.removeprefix("bytes=").partition("-")
            start = int(start_s)
            if start >= len(AUDIO):
                return web.Response(status=416,
                                    headers={"Content-Range": f"bytes */{len(AUDIO)}"})
            end = int(end_s) if end_s else len(AUDIO) - 1
            return web.Response(
                status=206, body=AUDIO[start:end + 1],
                headers={"Content-Type": "audio/mpeg", "Accept-Ranges": "bytes",
                         "Content-Range": f"bytes {start}-{end}/{len(AUDIO)}"})
        return web.Response(body=AUDIO, headers={"Content-Type": "audio/mpeg",
                                                 "Accept-Ranges": "bytes"})


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.delenv("BOOMBOX_LIBRARY_STREAM_BASE", raising=False)
    up = Upstream()
    up_app = web.Application()
    up_app.router.add_get("/rest/stream.view", up.handler)
    async with TestServer(up_app) as up_server:
        conn = connect(tmp_path / "l.db"); migrate(conn)
        _seed(conn)
        source = SimpleNamespace(url=str(up_server.make_url("/")).rstrip("/") + "/",
                                 username="admin", password="s3cret")
        ctx = Ctx(conn, source)
        async with TestClient(TestServer(build_app(ctx))) as c:
            yield c, ctx, up, conn


# ----- A. stream proxy -----

async def test_stream_relays_body_with_server_side_auth(env):
    c, _, up, _ = env
    r = await c.get("/api/library/stream/t1")
    assert r.status == 200
    assert r.headers["Content-Type"] == "audio/mpeg"
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.headers["Content-Length"] == str(len(AUDIO))
    assert await r.read() == AUDIO
    q = up.requests[0].query
    assert q["id"] == "t1" and q["u"] == "admin"
    assert "t" in q and "s" in q and "p" not in q
    assert "s3cret" not in str(up.requests[0].url)
    # Original quality by default: no transcode params.
    assert "maxBitRate" not in q and "format" not in q


async def test_stream_passes_range_and_relays_206(env):
    c, _, up, _ = env
    r = await c.get("/api/library/stream/t1", headers={"Range": "bytes=100-199"})
    assert r.status == 206
    assert r.headers["Content-Range"] == f"bytes 100-199/{len(AUDIO)}"
    assert await r.read() == AUDIO[100:200]
    assert up.requests[0].headers["Range"] == "bytes=100-199"


async def test_stream_relays_416(env):
    c, _, _, _ = env
    r = await c.get("/api/library/stream/t1", headers={"Range": "bytes=999999-"})
    assert r.status == 416
    assert r.headers["Content-Range"] == f"bytes */{len(AUDIO)}"


async def test_stream_head_sends_headers_only(env):
    c, _, _, _ = env
    r = await c.head("/api/library/stream/t1")
    assert r.status == 200
    assert r.headers["Content-Type"] == "audio/mpeg"
    assert r.headers["Content-Length"] == str(len(AUDIO))


async def test_stream_transcode_params_when_bitrate_capped(env):
    c, ctx, up, _ = env
    ctx.cfg.source.max_bitrate_kbps = 192
    r = await c.get("/api/library/stream/t1")
    assert r.status == 200
    await r.read()
    q = up.requests[0].query
    assert q["maxBitRate"] == "192" and q["format"] == "mp3"


@pytest.mark.parametrize("bad", ["t1&u=evil", "a%3Db", "x y", "a;b", "é", "a" * 129])
async def test_stream_rejects_invalid_id(env, bad):
    c, _, up, _ = env
    r = await c.get("/api/library/stream/" + bad)
    assert r.status == 400
    assert up.requests == []


async def test_stream_unknown_track_404(env):
    c, _, up, _ = env
    r = await c.get("/api/library/stream/nope")
    assert r.status == 404
    assert up.requests == []


async def test_stream_unconfigured_source_503(env):
    c, ctx, up, _ = env
    ctx.cfg.source.password = ""
    r = await c.get("/api/library/stream/t1")
    assert r.status == 503
    assert up.requests == []


async def test_stream_subsonic_not_found_maps_to_404(env):
    c, _, up, _ = env
    up.mode = "subsonic_error"
    r = await c.get("/api/library/stream/t1")
    assert r.status == 404


async def test_stream_subsonic_auth_error_is_502_without_leaking(env):
    c, _, up, _ = env
    up.mode = "auth_error"
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502
    text = await r.text()
    assert "s3cret" not in text and "t=" not in text


async def test_stream_upstream_5xx_is_502(env):
    c, _, up, _ = env
    up.mode = "http500"
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502


async def test_stream_upstream_unreachable_is_502(env):
    c, ctx, _, _ = env
    ctx.cfg.source.url = "http://127.0.0.1:9"  # discard port: refused
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502
    assert "unreachable" in await r.text()


async def test_stream_link_failure_marks_the_server_offline(env):
    c, ctx, _, _ = env
    ctx.cfg.source.url = "http://127.0.0.1:9"  # refused: the link, not the track
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502
    assert ctx.marked_offline == 1


async def test_stream_tunnel_down_status_marks_offline_but_track_errors_do_not(env):
    c, ctx, up, _ = env
    up.mode = "http500"                        # Navidrome itself answered
    await c.get("/api/library/stream/t1")
    assert ctx.marked_offline == 0
    up.mode = "http530"                        # Cloudflare: origin unreachable
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502
    assert ctx.marked_offline == 1


async def test_stream_link_failure_without_a_mark_offline_hook_is_still_502(env):
    c, ctx, _, _ = env
    ctx.mark_offline = None                    # an older context: nothing to call
    ctx.cfg.source.url = "http://127.0.0.1:9"
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502


async def test_stream_upstream_timeout_is_504(env, monkeypatch):
    c, ctx, up, _ = env
    up.mode = "slow"
    monkeypatch.setattr(stream_proxy, "UPSTREAM_TIMEOUT",
                        aiohttp.ClientTimeout(total=None, connect=1, sock_read=0.2))
    r = await c.get("/api/library/stream/t1")
    assert r.status == 504
    assert ctx.marked_offline == 1


async def test_stream_client_disconnect_releases_upstream(env):
    c, _, up, _ = env
    up.mode = "trickle"
    r = await c.get("/api/library/stream/t1")
    assert r.status == 200
    await r.content.readexactly(4096)
    r.close()
    await asyncio.wait_for(up.aborted.wait(), timeout=5)


async def test_stream_non_dict_subsonic_error_is_502(env):
    c, _, up, _ = env
    up.mode = "string_error"
    r = await c.get("/api/library/stream/t1")
    assert r.status == 502


def test_subsonic_error_status_tolerates_odd_envelopes():
    f = stream_proxy._subsonic_error_status
    assert f(b'{"subsonic-response":{"error":"bad"}}') == (502, "upstream error")
    assert f(b'{"subsonic-response":{"error":["x"]}}') == (502, "upstream error")
    assert f(b"<xml/>") == (502, "upstream error")
    assert f(b'{"subsonic-response":{"error":{"code":70}}}')[0] == 404


async def test_shutdown_aborts_active_streams_promptly(env):
    """A long-lived relay must not hold runner.cleanup() for aiohttp's
    default 60 s shutdown_timeout (x2) — past systemd's stop timeout."""
    _, ctx, up, _ = env
    up.mode = "endless"
    runner = web.AppRunner(build_app(ctx))  # default shutdown_timeout
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    async with aiohttp.ClientSession() as cs:
        r = await cs.get(f"http://127.0.0.1:{port}/api/library/stream/t1")
        assert r.status == 200
        await r.content.readexactly(4096)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.wait_for(runner.cleanup(), timeout=15)
        assert loop.time() - t0 < 5
        r.close()


async def test_stream_uses_ctx_http_session_when_present(env):
    c, ctx, up, _ = env
    async with aiohttp.ClientSession() as shared:
        ctx.http = shared
        r = await c.get("/api/library/stream/t1")
        assert await r.read() == AUDIO
        assert c.app[stream_proxy._SESSION_KEY].session is None


# ----- B. resolver endpoints hand out proxy URLs -----

async def test_single_resolve_returns_proxy_url(env):
    c, _, _, _ = env
    r = await c.get("/api/library/track/t1/playback")
    body = await r.json()
    assert body == {"source": "stream",
                    "uri": "http://127.0.0.1:6687/api/library/stream/t1",
                    "cache_status": "absent"}


# ----- D. batch resolve -----

async def test_batch_resolve_preserves_order_one_online_check(env, tmp_path):
    c, ctx, _, conn = env
    f = tmp_path / "t2.mp3"
    f.write_bytes(b"ID3")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t2','present',?,3,0)", (str(f),))
    r = await c.post("/api/library/resolve", json={"ids": ["t3", "t2", "missing", "t1"]})
    assert r.status == 200
    items = (await r.json())["items"]
    assert [i["id"] for i in items] == ["t3", "t2", "missing", "t1"]
    assert items[0] == {"id": "t3", "source": "stream",
                        "uri": "http://127.0.0.1:6687/api/library/stream/t3",
                        "cache_status": "absent"}
    assert items[1]["source"] == "cache" and items[1]["uri"] == f"file://{f}"
    assert items[1]["cache_status"] == "present"
    assert items[2]["source"] == "offline_miss" and items[2]["uri"] is None
    assert ctx.online_calls == 1


async def test_batch_resolve_stats_cache_files_off_loop(env, tmp_path, monkeypatch):
    """Cache-file existence checks run in a worker thread, never on the
    loop that feeds live stream relays."""
    import threading

    from boombox_library import api as api_mod
    c, _, _, conn = env
    present = tmp_path / "t1.mp3"
    present.write_bytes(b"ID3")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present',?,3,0)", (str(present),))
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t2','present',?,3,0)",
                 (str(tmp_path / "gone.mp3"),))
    main = threading.get_ident()
    seen: list[int] = []
    real_exists = api_mod.os.path.exists

    def spy(p):
        seen.append(threading.get_ident())
        return real_exists(p)

    monkeypatch.setattr(api_mod.os.path, "exists", spy)
    r = await c.post("/api/library/resolve", json={"ids": ["t1", "t2", "t3"]})
    items = (await r.json())["items"]
    assert [i["source"] for i in items] == ["cache", "stream", "stream"]
    assert items[1]["cache_status"] == "absent"   # row said present, file gone
    assert len(seen) == 2 and main not in seen


async def test_batch_resolve_offline(env):
    c, ctx, _, _ = env
    ctx._online = False
    r = await c.post("/api/library/resolve", json={"ids": ["t1"]})
    items = (await r.json())["items"]
    assert items == [{"id": "t1", "source": "offline_miss", "uri": None,
                      "cache_status": "absent"}]


@pytest.mark.parametrize("payload", [{}, {"ids": "t1"}, {"ids": [1, 2]}, [1],
                                     {"ids": ["x"] * 1001}])
async def test_batch_resolve_rejects_bad_payload(env, payload):
    c, _, _, _ = env
    r = await c.post("/api/library/resolve", json=payload)
    assert r.status == 400


async def test_batch_resolve_rejects_non_json(env):
    c, _, _, _ = env
    r = await c.post("/api/library/resolve", data=b"not json")
    assert r.status == 400


async def test_batch_resolve_empty_list(env):
    c, _, _, _ = env
    r = await c.post("/api/library/resolve", json={"ids": []})
    assert (await r.json()) == {"items": []}


# ----- C. detail endpoints -----

async def test_artist_detail(env):
    c, _, _, _ = env
    r = await c.get("/api/library/artist/ar1")
    assert r.status == 200
    body = await r.json()
    assert body["artist"] == {"id": "ar1", "name": "ABBA", "art_id": "ar-ar1"}
    # Year ascending, ties by sort name, undated last.
    assert [a["id"] for a in body["albums"]] == ["al3", "al1", "al2", "al0"]
    assert body["albums"][1] == {"id": "al1", "name": "Arrival", "year": 1976,
                                 "art_id": "al-al1", "track_count": 2, "offline": False}


async def test_album_detail_tracks_sorted_by_disc_then_track(env):
    c, _, _, conn = env
    conn.execute("INSERT INTO cache_state(track_id,status,local_path) "
                 "VALUES('t2','queued',NULL)")
    r = await c.get("/api/library/album/al1")
    assert r.status == 200
    body = await r.json()
    assert body["album"] == {"id": "al1", "name": "Arrival", "artist": "ABBA",
                             "artist_id": "ar1", "year": 1976, "art_id": "al-al1"}
    assert [t["id"] for t in body["tracks"]] == ["t1", "t2", "t3"]
    assert body["tracks"][0] == {"id": "t1", "title": "Dancing Queen", "artist": "ABBA",
                                 "album_id": "al1", "disc": 1, "track": 1,
                                 "duration": 200, "cache_status": "absent",
                                 "offline": False}
    assert body["tracks"][1]["offline"] is False  # queued is not on disk
    assert body["tracks"][1]["cache_status"] == "queued"


async def test_playlist_detail_in_position_order_skipping_unknown(env):
    c, _, _, _ = env
    r = await c.get("/api/library/playlist/pl1")
    assert r.status == 200
    body = await r.json()
    assert body["playlist"] == {"id": "pl1", "name": "Road Trip"}
    assert [t["id"] for t in body["tracks"]] == ["t2", "t1"]
    assert body["tracks"][0]["title"] == "Money Money Money"
    assert body["tracks"][0]["artist"] == "ABBA"


async def test_track_artist_column_preferred_when_schema_has_it(env):
    c, _, _, conn = env
    conn.execute("ALTER TABLE tracks ADD COLUMN artist TEXT")
    conn.execute("UPDATE tracks SET artist='Frida' WHERE id='t1'")
    conn.execute("UPDATE tracks SET artist='' WHERE id='t2'")
    body = await (await c.get("/api/library/album/al1")).json()
    by_id = {t["id"]: t["artist"] for t in body["tracks"]}
    assert by_id == {"t1": "Frida", "t2": "ABBA", "t3": "ABBA"}


@pytest.mark.parametrize("path", ["artist/zzz", "album/zzz", "playlist/zzz"])
async def test_detail_404(env, path):
    c, _, _, _ = env
    r = await c.get(f"/api/library/{path}")
    assert r.status == 404
    assert "error" in await r.json()
