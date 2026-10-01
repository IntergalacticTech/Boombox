"""Tests for boombox_library.downloader — single track + queue + concurrency."""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
import boombox_library.downloader as dl
import pytest
from aiohttp import web
from boombox_library.db import connect, migrate
from boombox_library.download_gates import read_soc_temp_c
from boombox_library.downloader import (
    DownloadQueue,
    DownloadResult,
    Gates,
    OutOfSpace,
    download_track,
    make_fetch,
)


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


@pytest.mark.asyncio
async def test_download_triggers_eviction_when_low_on_space(tmp_path: Path, monkeypatch):
    """When the cache drive is near full, downloading a pinned track
    must evict streamed (unpinned) tracks first."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',2,30,0,0,0)")
    # Old streamed track in cache
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('old','al','OLD',30,'mp3',5000000,'audio/mpeg',0,0)")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('old','present','/cache/audio/old.mp3',"
                 "5000000, 1.0)")
    # New track to download
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('new','al','NEW',30,'mp3',1000000,'audio/mpeg',0,0)")

    cache_root = tmp_path / "cache"
    (cache_root / "audio").mkdir(parents=True)
    (cache_root / "tmp").mkdir()

    # Mock statvfs to report critically-low free space
    def fake_statvfs(path):
        s = type("S", (), {})()
        s.f_bavail = 1
        s.f_frsize = 1
        s.f_blocks = 10_000_000_000
        return s
    monkeypatch.setattr("boombox_library.downloader.os.statvfs", fake_statvfs)

    deleted_paths = []
    def fake_unlink(p):
        deleted_paths.append(p)
    monkeypatch.setattr("boombox_library.downloader.os.unlink", fake_unlink)

    async def fast_fetch(url, params, dest):
        dest.write_bytes(b"x" * 1_000_000)

    client = FakeStreamingClient(b"x" * 1_000_000)
    result = await download_track(
        conn=conn, client=client, track_id="new",
        cache_root=cache_root, fetch=fast_fetch,
    )
    assert result == DownloadResult.OK
    # The old streamed track should have been evicted
    old_row = conn.execute("SELECT status FROM cache_state WHERE track_id='old'").fetchone()
    assert old_row["status"] == "absent"
    assert "/cache/audio/old.mp3" in deleted_paths


# ---- spec 2A: reserve, link drops, scheduler gates ----


GiB = 1024 ** 3


def _db(tmp_path: Path, n: int = 1, size: int = 100):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,"
                 "is_compilation,navidrome_starred,updated_at) VALUES('al','A','a','ar',?,30,0,0,0)", (n,))
    for i in range(n):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,"
                     "content_type,navidrome_starred,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (f"t{i}", "al", f"T{i}", 30, "mp3", size, "audio/mpeg", 0, 0))
    return conn


def _cache(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    (root / "audio").mkdir(parents=True)
    (root / "tmp").mkdir()
    return root


def _status(conn, tid):
    row = conn.execute("SELECT status FROM cache_state WHERE track_id=?", (tid,)).fetchone()
    return None if row is None else row["status"]


def _fake_free(monkeypatch, free):
    monkeypatch.setattr(dl, "free_bytes", lambda path: free)


class Sleeps:
    """Fake scheduler sleep: records durations, runs a hook, yields once."""
    def __init__(self, on_sleep=None):
        self.calls: list[float] = []
        self.on_sleep = on_sleep

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.on_sleep:
            self.on_sleep(len(self.calls))
        await asyncio.sleep(0)


def _ok_fetch(log: list):
    async def fetch(url, params, dest):
        log.append(url)
        dest.write_bytes(b"x")
    return fetch


async def test_download_skips_with_no_space_when_it_would_cross_the_reserve(tmp_path, monkeypatch):
    conn = _db(tmp_path, size=50 * 2**20)
    root = _cache(tmp_path)
    _fake_free(monkeypatch, 20 * GiB + 10 * 2**20)   # only 10 MiB above the reserve
    called: list = []
    r = await download_track(conn, FakeStreamingClient(b""), "t0", root, _ok_fetch(called),
                             reserve_bytes=20 * GiB)
    assert r is DownloadResult.NO_SPACE and called == []
    row = conn.execute("SELECT status, error_message FROM cache_state WHERE track_id='t0'").fetchone()
    assert row["status"] == "no_space" and "reserved" in row["error_message"]


async def test_download_proceeds_with_room_above_the_reserve(tmp_path, monkeypatch):
    conn = _db(tmp_path, size=5)
    root = _cache(tmp_path)
    _fake_free(monkeypatch, 30 * GiB)
    r = await download_track(conn, FakeStreamingClient(b""), "t0", root, _ok_fetch([]),
                             reserve_bytes=20 * GiB)
    assert r is DownloadResult.OK and _status(conn, "t0") == "present"


async def test_link_drop_mid_transfer_requeues_and_leaves_no_partial(tmp_path):
    conn = _db(tmp_path)
    root = _cache(tmp_path)

    async def fetch(url, params, dest):
        dest.write_bytes(b"half")
        raise aiohttp.ClientPayloadError("Response payload is not completed")

    r = await download_track(conn, FakeStreamingClient(b""), "t0", root, fetch)
    assert r is DownloadResult.OFFLINE
    assert _status(conn, "t0") == "queued"
    assert not (root / "tmp" / "t0.part").exists()
    assert not (root / "audio" / "t0.mp3").exists()


async def test_http_404_is_failed_with_its_reason(tmp_path):
    from yarl import URL
    conn = _db(tmp_path)
    root = _cache(tmp_path)

    async def fetch(url, params, dest):
        info = aiohttp.RequestInfo(url=URL("http://nav/rest/download.view"), method="GET",
                                   headers={},  # type: ignore[arg-type]
                                   real_url=URL("http://nav/rest/download.view"))
        raise aiohttp.ClientResponseError(request_info=info, history=(), status=404,
                                          message="Not Found")

    assert await download_track(conn, FakeStreamingClient(b""), "t0", root, fetch) is DownloadResult.ERROR
    row = conn.execute("SELECT status, error_message FROM cache_state WHERE track_id='t0'").fetchone()
    assert row["status"] == "error" and "404" in row["error_message"]


async def test_out_of_space_mid_transfer_is_no_space_and_leaves_no_partial(tmp_path):
    conn = _db(tmp_path)
    root = _cache(tmp_path)

    async def fetch(url, params, dest):
        dest.write_bytes(b"x" * 10)
        raise OutOfSpace("free 1 < reserve 2")

    assert await download_track(conn, FakeStreamingClient(b""), "t0", root, fetch) is DownloadResult.NO_SPACE
    assert _status(conn, "t0") == "no_space"
    assert not (root / "tmp" / "t0.part").exists()


async def test_guarded_fetch_aborts_when_free_space_drops(tmp_path, aiohttp_server, monkeypatch):
    async def body(req):
        return web.Response(body=b"\0" * (256 * 1024))
    app = web.Application()
    app.router.add_get("/dl", body)
    srv = await aiohttp_server(app)
    monkeypatch.setattr(dl, "SPACE_CHECK_EVERY", 64 * 1024)
    fetch = make_fetch(tmp_path, reserve_bytes=1000)
    _fake_free(monkeypatch, 100)
    with pytest.raises(OutOfSpace):
        await fetch(str(srv.make_url("/dl")), {}, tmp_path / "x.part")
    _fake_free(monkeypatch, 10**12)
    await fetch(str(srv.make_url("/dl")), {}, tmp_path / "y.part")
    assert (tmp_path / "y.part").stat().st_size == 256 * 1024


async def test_pause_reason_order_and_thresholds(tmp_path):
    conn = _db(tmp_path)
    g = Gates()
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), reserve_bytes=100, gates=g)
    assert await q.pause_reason() is None
    g.soc_temp_c = lambda: 69.9
    assert await q.pause_reason() is None
    g.soc_temp_c = lambda: 70.0
    assert await q.pause_reason() == "hot"

    async def streaming():
        return True
    g.soc_temp_c = lambda: None
    g.is_streaming = streaming
    assert await q.pause_reason() == "streaming"
    g.free_bytes = lambda: 99
    assert await q.pause_reason() == "low_space"
    g.is_online = lambda: False
    assert await q.pause_reason() == "offline"


async def test_queue_pauses_while_streaming_then_runs(tmp_path):
    conn = _db(tmp_path, n=2)
    state = {"streaming": True}
    fetched: list = []

    async def streaming():
        return state["streaming"]

    def on_sleep(n):
        assert fetched == []          # nothing started while a stream played
        state["streaming"] = False

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      gates=Gates(is_streaming=streaming), sleep=sleeps)
    q.enqueue("t0"); q.enqueue("t1")
    await q.drain()
    assert sleeps.calls == [15.0] and len(fetched) == 2


async def test_thermal_backoff_reads_the_sysfs_file_and_rechecks_every_minute(tmp_path):
    conn = _db(tmp_path)
    temp = tmp_path / "temp"
    temp.write_text("71500\n")
    fetched: list = []

    def on_sleep(n):
        assert fetched == []
        if n == 2:
            temp.write_text("55000\n")

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      gates=Gates(soc_temp_c=lambda: read_soc_temp_c(temp)), sleep=sleeps)
    q.enqueue("t0")
    await q.drain()
    assert sleeps.calls == [60.0, 60.0] and len(fetched) == 1


async def test_queue_idles_while_offline_and_resumes(tmp_path):
    conn = _db(tmp_path)
    state = {"online": False}
    fetched: list = []

    def on_sleep(n):
        assert fetched == []
        if n == 3:
            state["online"] = True

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      gates=Gates(is_online=lambda: state["online"]), sleep=sleeps)
    q.enqueue("t0")
    await q.drain()
    assert sleeps.calls == [60.0, 60.0, 60.0] and len(fetched) == 1


async def test_link_drop_idles_the_queue_instead_of_failing_every_track(tmp_path):
    conn = _db(tmp_path, n=5)
    now = {"t": 1000.0}
    calls: list = []

    async def fetch(url, params, dest):
        calls.append(url)
        if len(calls) == 1:
            raise aiohttp.ClientConnectionError("connection refused")
        dest.write_bytes(b"x")

    def on_sleep(n):
        now["t"] += 60.0

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 1, fetch,
                      sleep=sleeps, clock=lambda: now["t"])
    for i in range(5):
        q.enqueue(f"t{i}")
    await q.drain()
    assert len(calls) == 6 and sleeps.calls == [60.0]
    assert [_status(conn, f"t{i}") for i in range(5)] == ["present"] * 5


async def test_low_space_is_a_hard_stop_until_room_appears(tmp_path):
    conn = _db(tmp_path)
    state = {"free": 10}
    fetched: list = []

    def on_sleep(n):
        assert fetched == []
        state["free"] = 10**12

    sleeps = Sleeps(on_sleep)
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch(fetched),
                      reserve_bytes=1000, gates=Gates(free_bytes=lambda: state["free"]), sleep=sleeps)
    q.enqueue("t0")
    await q.drain()
    assert sleeps.calls == [15.0] and len(fetched) == 1
    assert q.snapshot()["paused"] is None


async def test_cancel_drops_queued_and_in_flight_finishes(tmp_path):
    conn = _db(tmp_path, n=3)
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch(url, params, dest):
        started.set()
        await release.wait()
        dest.write_bytes(b"x")

    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 1, fetch)
    for i in range(3):
        q.enqueue(f"t{i}")
    await asyncio.wait_for(started.wait(), 1)
    assert q.snapshot() == {"queued": 2, "in_flight": ["t0"], "paused": None}
    assert q.cancel(["t0", "t1", "t2"]) == 2
    release.set()
    await q.drain()
    assert _status(conn, "t0") == "present"
    assert _status(conn, "t1") is None and _status(conn, "t2") is None


async def test_enqueue_is_idempotent_and_skips_present(tmp_path):
    conn = _db(tmp_path, n=2)
    conn.execute("INSERT INTO cache_state(track_id,status,local_path) VALUES('t1','present','/x')")
    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, _ok_fetch([]))
    assert q.enqueue("t0") is True
    assert q.enqueue("t0") is False
    assert q.enqueue("t1") is False
    await q.drain()


async def test_failed_download_is_not_retried_by_the_queue(tmp_path):
    conn = _db(tmp_path)
    calls: list = []

    async def fetch(url, params, dest):
        calls.append(url)
        raise OSError("disk says no")

    q = DownloadQueue(conn, FakeStreamingClient(b""), _cache(tmp_path), 2, fetch)
    q.enqueue("t0")
    await q.drain()
    await asyncio.sleep(0.05)
    assert calls == ["http://nav/t0"] and _status(conn, "t0") == "error"


async def test_queue_start_sweeps_partials_and_stale_rows(tmp_path):
    conn = _db(tmp_path, n=2)
    root = _cache(tmp_path)
    (root / "tmp" / "t0.part").write_bytes(b"half")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t0','downloading')")
    conn.execute("INSERT INTO cache_state(track_id,status) VALUES('t1','queued')")
    DownloadQueue(conn, FakeStreamingClient(b""), root)
    assert not (root / "tmp" / "t0.part").exists()
    assert _status(conn, "t0") == "absent" and _status(conn, "t1") == "absent"
