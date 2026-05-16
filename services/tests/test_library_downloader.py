"""Tests for boombox_library.downloader — single track + queue + concurrency."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from boombox_library.db import connect, migrate
from boombox_library.downloader import download_track, DownloadResult


class FakeStreamingClient:
    """Stand-in for SubsonicClient that yields fixed bytes for download.

    Calling download_url returns the (url, params); the fake session.get
    yields a streaming response with the configured bytes.
    """
    def __init__(self, payload: bytes, suffix: str = "mp3"):
        self.payload = payload
        self.suffix = suffix
        self.calls: list[str] = []

    def download_url(self, track_id: str):
        return (f"http://nav/{track_id}", {})


@pytest.mark.asyncio
async def test_download_track_writes_file_atomically(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")

    payload = b"hello"
    client = FakeStreamingClient(payload)
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    # Mock the HTTP fetch
    async def fake_fetch(url, params, dest):
        dest.write_bytes(payload)

    result = await download_track(
        conn=conn,
        client=client,
        track_id="t1",
        cache_root=cache_root,
        fetch=fake_fetch,
    )
    assert result == DownloadResult.OK
    target = cache_root / "audio" / "t1.mp3"
    assert target.read_bytes() == payload
    assert not (cache_root / "tmp" / "t1.part").exists()

    row = conn.execute("SELECT status, size_bytes, local_path FROM cache_state "
                       "WHERE track_id='t1'").fetchone()
    assert row["status"] == "present"
    assert row["size_bytes"] == len(payload)
    assert row["local_path"] == str(target)


@pytest.mark.asyncio
async def test_download_track_marks_error_on_fetch_failure(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")
    client = FakeStreamingClient(b"")
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    async def boom(*args, **kwargs):
        raise IOError("nope")

    result = await download_track(
        conn=conn, client=client, track_id="t1",
        cache_root=cache_root, fetch=boom,
    )
    assert result == DownloadResult.ERROR
    row = conn.execute("SELECT status, error_message FROM cache_state "
                       "WHERE track_id='t1'").fetchone()
    assert row["status"] == "error"
    assert "nope" in row["error_message"]
    # Partial file must not be left behind
    assert not (cache_root / "tmp" / "t1.part").exists()


@pytest.mark.asyncio
async def test_download_skips_if_already_present(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    target = cache_root / "audio" / "t1.mp3"
    target.write_bytes(b"existing")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present',?, 8, 0)", (str(target),))

    called = {"n": 0}
    async def fetch(*a, **k):
        called["n"] += 1

    client = FakeStreamingClient(b"new")
    result = await download_track(
        conn=conn, client=client, track_id="t1",
        cache_root=cache_root, fetch=fetch,
    )
    assert result == DownloadResult.SKIPPED
    assert called["n"] == 0
    assert target.read_bytes() == b"existing"


@pytest.mark.asyncio
async def test_error_message_does_not_leak_auth_params(tmp_path: Path):
    """When a fetch raises an aiohttp.ClientResponseError carrying the
    full request URL (with merged ?u=...&t=...&s=... auth params), the
    persisted error_message must NOT contain those secrets."""
    import aiohttp
    from yarl import URL

    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',5,'audio/mpeg',0,0)")
    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    async def leaky_fetch(url, params, dest):
        # Simulate aiohttp constructing a ClientResponseError with the
        # full merged URL — this is what raise_for_status would produce.
        req_info = aiohttp.RequestInfo(
            url=URL("http://nav/rest/download.view?u=jwc&t=DEADBEEF&s=CAFE&id=t1"),
            method="GET",
            headers={},  # type: ignore[arg-type]
            real_url=URL("http://nav/rest/download.view?u=jwc&t=DEADBEEF&s=CAFE&id=t1"),
        )
        raise aiohttp.ClientResponseError(
            request_info=req_info,
            history=(),
            status=503,
            message="Service Unavailable",
        )

    client = FakeStreamingClient(b"")
    result = await download_track(
        conn=conn, client=client, track_id="t1",
        cache_root=cache_root, fetch=leaky_fetch,
    )
    assert result == DownloadResult.ERROR

    row = conn.execute("SELECT error_message FROM cache_state "
                       "WHERE track_id='t1'").fetchone()
    msg = row["error_message"]
    # Secrets MUST NOT appear in the persisted message:
    assert "DEADBEEF" not in msg
    assert "CAFE" not in msg
    assert "jwc" not in msg
    # Helpful diagnostic info SHOULD be there:
    assert "503" in msg
    assert "Service Unavailable" in msg


@pytest.mark.asyncio
async def test_queue_respects_concurrency_limit(tmp_path: Path):
    from boombox_library.downloader import DownloadQueue

    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',5,30,0,0,0)")
    for i in range(5):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                     "size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"t{i}", "al", "T", 30, "mp3", 100, "audio/mpeg", 0, 0))

    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    in_flight = 0
    peak = 0

    async def slow_fetch(url, params, dest):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        dest.write_bytes(b"x")
        in_flight -= 1

    client = FakeStreamingClient(b"x")
    queue = DownloadQueue(conn=conn, client=client, cache_root=cache_root,
                          max_concurrent=2, fetch=slow_fetch)
    for i in range(5):
        queue.enqueue(f"t{i}")
    await queue.drain()

    assert peak <= 2
    rows = conn.execute("SELECT COUNT(*) FROM cache_state WHERE status='present'").fetchone()
    assert rows[0] == 5
