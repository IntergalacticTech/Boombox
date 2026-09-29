"""Tests for services/boombox-library.py — reachability flag, sync retry
backoff and cache-drive loss handling in the ServiceContext loops.

The entry point is a hyphenated script, so it's loaded by path. Nothing
here touches the network, /opt or /etc: the Subsonic client, sync_full
and every filesystem location are swapped for fakes / tmp_path.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
from boombox_library.config import DEFAULT_CONFIG, LibraryConfig, SourceConfig
from boombox_library.subsonic import (
    SubsonicAuthError,
    SubsonicError,
    SubsonicUnreachable,
)

_SCRIPT = Path(__file__).resolve().parent.parent / "boombox-library.py"


def _load_service():
    spec = importlib.util.spec_from_file_location("boombox_library_service", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


svc = _load_service()


class FakeClient:
    """Stand-in for SubsonicClient; behaviour set per test via class attrs."""
    ping_exc: BaseException | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def ping(self) -> bool:
        if FakeClient.ping_exc is not None:
            raise FakeClient.ping_exc
        return True

    def download_url(self, track_id):
        return ("http://x/rest/download.view", {"id": track_id})


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch):
    cfg = LibraryConfig(
        source=SourceConfig(url="https://music.example", username="u", password="p"),
        sync=DEFAULT_CONFIG.sync,
        cache=DEFAULT_CONFIG.cache.__class__(search_paths=(str(tmp_path / "media"),)),
    )
    (tmp_path / "media").mkdir()
    monkeypatch.setattr(svc, "load_config", lambda: cfg)
    monkeypatch.setattr(svc, "DB_PATH", tmp_path / "library.db")
    monkeypatch.setattr(svc, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(svc, "ART_CACHE_DIR", tmp_path / "art")
    monkeypatch.setattr(svc, "DEFAULT_SYMLINK", tmp_path / "cache-mount")
    monkeypatch.setattr(svc, "SubsonicClient", FakeClient)
    FakeClient.ping_exc = None

    async def fake_sync_full(client, conn):
        return {}
    monkeypatch.setattr(svc, "sync_full", fake_sync_full)
    monkeypatch.setattr(svc, "write_snapshots", lambda conn, d: None)
    return svc.ServiceContext()


# ---- retry backoff ----

def test_retry_delay_backs_off_and_caps():
    assert svc.retry_delay(0, 3600) == 3600
    assert [svc.retry_delay(n, 3600) for n in range(1, 8)] == [
        60, 120, 240, 480, 960, 1920, 3600]
    assert svc.retry_delay(500, 3600) == 3600  # no overflow on long outages
    assert svc.retry_delay(1, 30) == 30  # never slower than the interval


# ---- reachability flag ----

@pytest.mark.asyncio
async def test_sync_once_success_sets_online(ctx):
    assert await ctx._sync_once() is True
    assert await ctx.is_online() is True
    assert ctx.last_sync_ts > 0
    assert ctx.syncing is False


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    SubsonicUnreachable("timeout"),
    SubsonicError("http 403"),         # generic error used to escape the task
    asyncio.TimeoutError(),
    RuntimeError("surprise"),
])
async def test_any_ping_failure_clears_stale_online(ctx, exc):
    ctx._online = True  # stale from a previous good sync
    FakeClient.ping_exc = exc
    assert await ctx._sync_once() is False  # returns, never raises
    assert await ctx.is_online() is False
    assert ctx.syncing is False


@pytest.mark.asyncio
async def test_unreachable_mid_sync_clears_online(ctx, monkeypatch):
    async def dropped(client, conn):
        raise SubsonicUnreachable("edge proxy page (http 403)")
    monkeypatch.setattr(svc, "sync_full", dropped)
    assert await ctx._sync_once() is False
    assert await ctx.is_online() is False


@pytest.mark.asyncio
async def test_triggered_sync_task_never_raises(ctx):
    FakeClient.ping_exc = RuntimeError("boom")
    await ctx.trigger_sync()
    assert ctx._sync_task is not None
    assert await ctx._sync_task is False
    assert ctx._sync_task.exception() is None


def _script_attempts(ctx, monkeypatch, outcomes):
    """Replace the ping+sync body with a scripted sequence of failures
    (None = success) so _sync_once's bookkeeping runs for real."""
    it = iter(outcomes)

    async def scripted():
        return next(it)
    monkeypatch.setattr(ctx, "_sync_attempt", scripted)


def _record_waits(ctx, monkeypatch, stop_after):
    delays: list[float] = []

    async def fake_wait(delay):
        delays.append(delay)
        if len(delays) == stop_after:
            raise asyncio.CancelledError
        return False  # the full delay elapsed
    monkeypatch.setattr(ctx, "_wait_or_woken", fake_wait)
    return delays


@pytest.mark.asyncio
async def test_sync_timer_retries_with_backoff_and_resets(ctx, monkeypatch):
    down = SubsonicUnreachable("timeout")
    _script_attempts(ctx, monkeypatch, [down, down, None, down, None])
    delays = _record_waits(ctx, monkeypatch, 5)
    with pytest.raises(asyncio.CancelledError):
        await ctx.sync_timer()
    interval = ctx.cfg.sync.interval_seconds
    assert delays == [60, 120, interval, 60, interval]


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    SubsonicAuthError("40: wrong username or password"),
    SubsonicError("70: not found"),
    RuntimeError("bug on one album"),
])
async def test_sync_timer_waits_full_interval_on_permanent_failure(ctx, monkeypatch, exc):
    """Bad credentials / local errors won't fix themselves in 60 s —
    no burst of full syncs and failed auths through the edge."""
    _script_attempts(ctx, monkeypatch, [exc, exc, exc])
    delays = _record_waits(ctx, monkeypatch, 3)
    with pytest.raises(asyncio.CancelledError):
        await ctx.sync_timer()
    interval = ctx.cfg.sync.interval_seconds
    assert delays == [interval, interval, interval]


def test_is_transient_classification():
    import aiohttp
    assert svc.is_transient(SubsonicUnreachable("x"))
    assert svc.is_transient(asyncio.TimeoutError())
    assert svc.is_transient(aiohttp.ClientConnectionError())
    assert not svc.is_transient(SubsonicAuthError("40"))
    assert not svc.is_transient(SubsonicError("http 404"))
    assert not svc.is_transient(RuntimeError("x"))


@pytest.mark.asyncio
async def test_sync_timer_survives_cycle_exception(ctx, monkeypatch):
    calls = {"n": 0}

    async def exploding_cycle():
        calls["n"] += 1
        raise RuntimeError("unexpected")

    monkeypatch.setattr(ctx, "_sync_cycle", exploding_cycle)
    delays = _record_waits(ctx, monkeypatch, 2)
    with pytest.raises(asyncio.CancelledError):
        await ctx.sync_timer()
    assert calls["n"] == 2
    assert delays == [60, 120]


@pytest.mark.asyncio
async def test_external_sync_failure_wakes_timer_into_backoff(ctx, monkeypatch):
    """First boot: no source → the timer sleeps a full interval. The wizard
    then saves a source and its trigger_sync fails transiently — the timer
    must wake and retry in 60 s, not after the rest of the hour."""
    _script_attempts(ctx, monkeypatch,
                     [None, SubsonicUnreachable("cloudflare blip")])
    delays: list[float] = []
    real_wait = ctx._wait_or_woken

    async def recording_wait(delay):
        delays.append(delay)
        return await real_wait(delay)
    monkeypatch.setattr(ctx, "_wait_or_woken", recording_wait)

    timer = asyncio.create_task(ctx.sync_timer())
    for _ in range(20):
        await asyncio.sleep(0)
    interval = ctx.cfg.sync.interval_seconds
    assert delays == [interval]

    await ctx.trigger_sync()  # e.g. PUT /api/library/source
    assert ctx._sync_task is not None
    assert await ctx._sync_task is False
    for _ in range(20):
        await asyncio.sleep(0)
    assert delays == [interval, 60]
    timer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await timer


@pytest.mark.asyncio
async def test_external_sync_success_resets_backoff(ctx, monkeypatch):
    _script_attempts(ctx, monkeypatch, [SubsonicUnreachable("down"), None])
    delays: list[float] = []
    real_wait = ctx._wait_or_woken

    async def recording_wait(delay):
        delays.append(delay)
        return await real_wait(delay)
    monkeypatch.setattr(ctx, "_wait_or_woken", recording_wait)

    timer = asyncio.create_task(ctx.sync_timer())
    for _ in range(20):
        await asyncio.sleep(0)
    assert delays == [60]
    await ctx.trigger_sync()  # "Sync now" succeeds
    assert ctx._sync_task is not None
    assert await ctx._sync_task is True
    for _ in range(20):
        await asyncio.sleep(0)
    assert delays == [60, ctx.cfg.sync.interval_seconds]
    timer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await timer


# ---- cache drive loss ----

async def _poll_once(ctx, monkeypatch):
    async def stop(seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(svc.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await ctx.cache_poll()


def _status(conn, track_id):
    return conn.execute("SELECT status, local_path FROM cache_state WHERE track_id=?",
                        (track_id,)).fetchone()["status"]


@pytest.mark.asyncio
async def test_cache_drive_loss_marks_missing_and_readopt_restores(ctx, tmp_path, monkeypatch):
    drive = tmp_path / "media" / "usb0"
    (drive / "audio").mkdir(parents=True)
    (drive / ".boombox-cache").touch()
    track = drive / "audio" / "t1.mp3"
    track.write_bytes(b"x")
    ctx.conn.execute("INSERT INTO cache_state(track_id, status, local_path) "
                     "VALUES ('t1', 'present', ?)", (str(track),))

    await _poll_once(ctx, monkeypatch)  # adopt
    assert ctx.cache_state.present
    assert _status(ctx.conn, "t1") == "present"

    (drive / ".boombox-cache").unlink()  # drive "yanked" (marker gone)
    await _poll_once(ctx, monkeypatch)
    assert not ctx.cache_state.present
    assert ctx._download_queue is None
    assert _status(ctx.conn, "t1") == "missing"

    (drive / ".boombox-cache").touch()  # plugged back in
    await _poll_once(ctx, monkeypatch)
    assert _status(ctx.conn, "t1") == "present"


@pytest.mark.asyncio
async def test_startup_without_drive_marks_dead_rows_missing(ctx, tmp_path, monkeypatch):
    ctx.conn.execute("INSERT INTO cache_state(track_id, status, local_path) "
                     "VALUES ('t1', 'present', '/media/usb0/audio/t1.mp3')")
    await _poll_once(ctx, monkeypatch)
    assert not ctx.cache_state.present
    assert _status(ctx.conn, "t1") == "missing"
