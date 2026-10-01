"""Expansion of bindings → playable URIs via Phase 1 resolver."""
from __future__ import annotations

from pathlib import Path

from boombox_library.db import connect as lib_connect
from boombox_library.db import migrate as lib_migrate
from boombox_rfid.db import migrate as rfid_migrate
from boombox_rfid.models import BindingKind
from boombox_rfid.playback import expand_to_track_ids, library_online, resolve_uris


def _seed(conn):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','ABBA','abba',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,year,"
                 "song_count,duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','Arrival','arrival','ar1',1976,2,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,track_no,disc_no,duration_s,"
                 "suffix,size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al1','Dancing Queen',1,1,30,'mp3',1000,'audio/mpeg',0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,track_no,disc_no,duration_s,"
                 "suffix,size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t2','al1','Money Money Money',2,1,30,'mp3',1000,'audio/mpeg',0,0)")
    return conn


def test_expand_album_returns_track_ids_in_order(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    ids = expand_to_track_ids(conn, BindingKind.ALBUM, "al1")
    assert ids == ["t1", "t2"]


def test_expand_artist_returns_all_tracks(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    ids = expand_to_track_ids(conn, BindingKind.ARTIST, "ar1")
    assert set(ids) == {"t1", "t2"}


def test_expand_track_returns_self(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    ids = expand_to_track_ids(conn, BindingKind.TRACK, "t1")
    assert ids == ["t1"]


def test_resolve_uris_streams_when_online(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BOOMBOX_LIBRARY_STREAM_BASE", raising=False)
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    uris = resolve_uris(
        conn, ["t1", "t2"], online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    # Local stream-proxy URLs — no Navidrome host or auth params leak into
    # the tracklist.
    assert uris == [
        "http://127.0.0.1:6687/api/library/stream/t1",
        "http://127.0.0.1:6687/api/library/stream/t2",
    ]


def test_resolve_uris_returns_file_when_cached(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BOOMBOX_LIBRARY_STREAM_BASE", raising=False)
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    cached = tmp_path / "audio" / "t1.mp3"
    cached.parent.mkdir()
    cached.write_bytes(b"ID3")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present',?,1000,0)", (str(cached),))
    uris = resolve_uris(
        conn, ["t1", "t2"], online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert uris[0] == f"file://{cached}"
    assert uris[1] == "http://127.0.0.1:6687/api/library/stream/t2"


def test_resolve_uris_skips_offline_miss(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    uris = resolve_uris(conn, ["t1", "t2"], online=False)
    assert uris == []  # neither cached + offline → both skipped


# ----- stream-proxy readiness (boombox-library restarting) -----

async def test_wait_for_stream_proxy_skips_when_all_cached(monkeypatch):
    from boombox_rfid.playback import wait_for_stream_proxy
    # Unreachable base, but no URI points at it → no wait, True.
    monkeypatch.setenv("BOOMBOX_LIBRARY_STREAM_BASE", "http://127.0.0.1:1/s")
    assert await wait_for_stream_proxy(["file:///m/a.mp3"], timeout=0) is True


async def test_wait_for_stream_proxy_detects_listener(monkeypatch):
    import asyncio

    from boombox_rfid.playback import wait_for_stream_proxy
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}/api/library/stream"
    monkeypatch.setenv("BOOMBOX_LIBRARY_STREAM_BASE", base)
    try:
        assert await wait_for_stream_proxy([f"{base}/t1"], timeout=1) is True
    finally:
        server.close()
        await server.wait_closed()
    # Now nothing listens on that port: gives up after the timeout.
    assert await wait_for_stream_proxy(
        [f"{base}/t1"], timeout=0.2, interval=0.05) is False


def test_resolve_uris_offline_plays_kept_file(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    kept = tmp_path / "storage" / "music" / "audio" / "t1.mp3"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"ID3")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,downloaded_at) "
                 "VALUES('t1','present',?,3,0)", (str(kept),))
    uris = resolve_uris(conn, ["t1", "t2"], online=False,
                        source_url="http://nav:4533", source_username="u", source_password="p")
    assert uris == [f"file://{kept}"]          # t2 isn't kept: dropped, not a dead stream URL


async def test_library_online_follows_the_library_health(aiohttp_server):
    from aiohttp import web
    state: dict = {"status": 200, "body": {"navidrome_reachable": False}}

    async def health(req):
        return web.json_response(state["body"], status=state["status"])
    app = web.Application()
    app.router.add_get("/api/library/health", health)
    srv = await aiohttp_server(app)
    url = str(srv.make_url("/api/library/health"))
    assert await library_online(url) is False
    state["body"] = {"navidrome_reachable": True}
    assert await library_online(url) is True
    state["status"] = 500
    assert await library_online(url) is True


async def test_library_online_when_the_library_is_down_keeps_the_stream_path():
    assert await library_online("http://127.0.0.1:1/api/library/health", timeout=0.5) is True


async def test_library_online_treats_any_unexpected_failure_as_online(monkeypatch):
    import aiohttp

    class Exploding:
        def __init__(self, *a, **k):
            raise RuntimeError("surprise")
    monkeypatch.setattr(aiohttp, "ClientSession", Exploding)
    assert await library_online("http://127.0.0.1:1/api/library/health") is True


async def test_library_online_unknown_reachability_counts_as_online(aiohttp_server):
    from aiohttp import web

    async def health(req):
        return web.json_response({"navidrome_reachable": True, "reachability_known": False})
    app = web.Application()
    app.router.add_get("/api/library/health", health)
    srv = await aiohttp_server(app)
    assert await library_online(str(srv.make_url("/api/library/health"))) is True
