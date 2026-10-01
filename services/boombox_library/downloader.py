"""Audio file downloader + download scheduler for boombox-library.

download_track() handles one track end-to-end: stream from Subsonic to a
.part tmp file, atomically rename to final, update cache_state. The fetch
coroutine is injected to keep network out of unit tests; the real one
(make_fetch) streams with aiohttp and aborts if free space falls below the
reserve mid-transfer.

DownloadQueue schedules downloads (spec 2A, "never starve the Pi"): at most
`max_concurrent` at a time, and before EACH start it checks, in order —
  offline    Navidrome unreachable, or a download just lost the link: idle,
             re-check every OFFLINE_RECHECK_S (no retry storm). A track
             that drops MAX_LINK_RETRIES times in a row goes to 'error';
  low_space  free space below the reserve: hard stop until there is room;
  hot        SoC >= THERMAL_LIMIT_C: wait THERMAL_RECHECK_S, re-check;
  streaming  Mopidy is playing a stream-proxy URI: leave it the link.
In-flight downloads always finish. A failed download keeps status 'error'
with its reason and is NOT retried by the queue — the hourly sync
re-enqueues it (ServiceContext._enqueue_pinned_downloads). The queue is
in memory: the sync re-derives what to download from the pins.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import Awaitable, Callable, Iterable, Optional, Protocol

import aiohttp

from .download_gates import free_bytes

log = logging.getLogger("boombox-library.downloader")

THERMAL_LIMIT_C = 70.0
THERMAL_RECHECK_S = 60.0
OFFLINE_RECHECK_S = 60.0
PAUSE_RECHECK_S = 15.0
SPACE_CHECK_EVERY = 16 * 1024 * 1024
# Idle timeouts, no total cap: a big file over a slow tunnel that keeps
# making progress completes; a stalled connection fails within a minute.
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60)
# A track whose transfer drops the link this many times in a row is marked
# 'error' (the hourly sync retries it) so it cannot block the queue forever.
MAX_LINK_RETRIES = 3
_RECHECK_S = {"offline": OFFLINE_RECHECK_S, "low_space": PAUSE_RECHECK_S,
              "hot": THERMAL_RECHECK_S, "streaming": PAUSE_RECHECK_S}
# What a CDN / tunnel answers when the homelab behind it is down: the link
# failed, not the track. (503 stays a track error: Navidrome itself sends it.)
_LINK_DOWN_STATUSES = frozenset({502, 504, 520, 521, 522, 523, 524, 530})


class DownloadResult(str, enum.Enum):
    OK = "ok"
    SKIPPED = "skipped"    # already present
    ERROR = "error"        # this track failed: status 'error', reason kept
    OFFLINE = "offline"    # the link dropped: requeued, not failed
    NO_SPACE = "no_space"  # would cross the reserve: status 'no_space'


class OutOfSpace(Exception):
    """Free space fell below the reserve during a transfer."""


class StreamingClient(Protocol):
    def download_url(self, track_id: str) -> tuple[str, dict]: ...


Fetcher = Callable[[str, dict, Path], Awaitable[None]]
"""(url, params, dest_path) → writes bytes to dest_path."""


def _safe_error_message(e: Exception) -> str:
    """Format an exception for cache_state.error_message without leaking
    auth params from the request URL.

    aiohttp.ClientResponseError.__str__ includes the merged URL with
    `?u=USERNAME&t=TOKEN&s=SALT&id=...`. We strip the URL by formatting
    only type + status + message for that exception type.
    """
    if isinstance(e, aiohttp.ClientResponseError):
        return f"{type(e).__name__}: {e.status} {e.message}"
    if isinstance(e, aiohttp.ClientError):
        msg = str(e)
        return msg.split('?', 1)[0] if 'http' in msg else msg
    return f"{type(e).__name__}: {e}"


def is_link_failure(e: BaseException) -> bool:
    """The connection to the music server failed (vs. this track failing)."""
    if isinstance(e, aiohttp.ClientResponseError):
        return e.status in _LINK_DOWN_STATUSES
    return isinstance(e, (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError,
                          asyncio.TimeoutError, ConnectionError))


async def default_fetch(url: str, params: dict, dest: Path) -> None:
    """Plain aiohttp streaming fetch (no space guard). Raises on non-2xx."""
    async with aiohttp.ClientSession(timeout=FETCH_TIMEOUT) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)


def make_fetch(cache_root: Path, reserve_bytes: int) -> Fetcher:
    """The queue's fetch: default_fetch plus the disk-full hard stop —
    every SPACE_CHECK_EVERY bytes, abort with OutOfSpace when free space on
    cache_root has fallen below the reserve."""
    async def fetch(url: str, params: dict, dest: Path) -> None:
        async with aiohttp.ClientSession(timeout=FETCH_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                since_check = 0
                with dest.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        since_check += len(chunk)
                        if since_check >= SPACE_CHECK_EVERY:
                            since_check = 0
                            free = free_bytes(cache_root)
                            if free is not None and free < reserve_bytes:
                                raise OutOfSpace(f"{free} B free < {reserve_bytes} B reserve")
    return fetch


def _mark(conn: Connection, track_id: str, status: str,
          message: Optional[str] = None) -> None:
    conn.execute(
        """INSERT INTO cache_state(track_id, status, error_message) VALUES (?, ?, ?)
           ON CONFLICT(track_id) DO UPDATE SET status=excluded.status,
                                               error_message=excluded.error_message""",
        (track_id, status, message),
    )


def _drop_partial(tmp_path: Path) -> None:
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass


def sweep_partials(cache_root: Path) -> int:
    """Delete leftover tmp/*.part files (crash / power cut mid-download).
    Only call while no download runs on this cache_root."""
    try:
        parts = list((cache_root / "tmp").glob("*.part"))
    except OSError:
        return 0
    n = 0
    for p in parts:
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


async def download_track(
    conn: Connection,
    client: StreamingClient,
    track_id: str,
    cache_root: Path,
    fetch: Fetcher = default_fetch,
    *,
    reserve_bytes: int = 0,
) -> DownloadResult:
    """Download one track into cache_root/audio/<id>.<suffix> atomically.

    cache_root must contain audio/ and tmp/ (adopt_drive creates them).
    reserve_bytes: keep at least this much free (the service passes
    cache.reserve_bytes; 0 = none, for direct callers and tests). A track
    that would cross it — after evicting unpinned streamed cache — is
    skipped with status 'no_space'. A dropped link requeues the track
    (status 'queued', DownloadResult.OFFLINE) instead of failing it.
    """
    row = conn.execute(
        "SELECT status FROM cache_state WHERE track_id=?", (track_id,)
    ).fetchone()
    if row and row["status"] == "present":
        return DownloadResult.SKIPPED

    trow = conn.execute(
        "SELECT suffix, size_bytes FROM tracks WHERE id=?", (track_id,)
    ).fetchone()
    if trow is None:
        log.error("track %s not in catalog; skipping", track_id)
        return DownloadResult.ERROR
    suffix = trow["suffix"] or "bin"

    expected_size = int(trow["size_bytes"] or 0)
    free = free_bytes(cache_root)
    if free is not None:
        need = expected_size + reserve_bytes - free
        if need > 0:
            from .eviction import evict_until_fits
            freed, _left = evict_until_fits(
                conn, need, lambda p: os.unlink(p) if p else None)
            free += freed
        if expected_size + reserve_bytes > free:
            _mark(conn, track_id, "no_space",
                  f"no space: {expected_size} B needed, {free} B free, "
                  f"{reserve_bytes} B reserved")
            log.warning("skipping %s: it would cross the %d B reserve",
                        track_id, reserve_bytes)
            return DownloadResult.NO_SPACE

    tmp_path = cache_root / "tmp" / f"{track_id}.part"
    final_path = cache_root / "audio" / f"{track_id}.{suffix}"

    conn.execute(
        """INSERT INTO cache_state(track_id, status, downloaded_at)
           VALUES (?, 'downloading', ?)
           ON CONFLICT(track_id) DO UPDATE SET status='downloading',
                                                error_message=NULL""",
        (track_id, time.time()),
    )

    url, params = client.download_url(track_id)
    try:
        _drop_partial(tmp_path)
        await fetch(url, params, tmp_path)
        os.replace(tmp_path, final_path)
        size = final_path.stat().st_size
        conn.execute(
            """INSERT INTO cache_state(track_id, status, local_path,
                                       size_bytes, downloaded_at)
               VALUES (?, 'present', ?, ?, ?)
               ON CONFLICT(track_id) DO UPDATE SET
                  status='present',
                  local_path=excluded.local_path,
                  size_bytes=excluded.size_bytes,
                  downloaded_at=excluded.downloaded_at,
                  error_message=NULL""",
            (track_id, str(final_path), size, time.time()),
        )
        return DownloadResult.OK
    except asyncio.CancelledError:
        _drop_partial(tmp_path)
        _mark(conn, track_id, "absent")
        raise
    except OutOfSpace as e:
        _drop_partial(tmp_path)
        _mark(conn, track_id, "no_space", f"no space: {e}")
        log.warning("download of %s stopped: %s", track_id, e)
        return DownloadResult.NO_SPACE
    except Exception as e:
        _drop_partial(tmp_path)
        if is_link_failure(e):
            _mark(conn, track_id, "queued")
            log.info("download of %s interrupted, music server unreachable: %s",
                     track_id, _safe_error_message(e))
            return DownloadResult.OFFLINE
        _mark(conn, track_id, "error", _safe_error_message(e))
        log.warning("download of %s failed: %s", track_id, _safe_error_message(e))
        return DownloadResult.ERROR


async def _never_streaming() -> bool:
    return False


def _always_online() -> bool:
    return True


def _unknown() -> Optional[float]:
    return None


def _unknown_free() -> Optional[int]:
    return None


@dataclass
class Gates:
    """Inputs the scheduler checks before each start (defaults: all clear)."""
    is_online: Callable[[], bool] = _always_online
    is_streaming: Callable[[], Awaitable[bool]] = _never_streaming
    soc_temp_c: Callable[[], Optional[float]] = _unknown
    free_bytes: Callable[[], Optional[int]] = _unknown_free


class DownloadQueue:
    """In-memory download scheduler with bounded concurrency and gates."""

    def __init__(
        self,
        conn: Connection,
        client: StreamingClient,
        cache_root: Path,
        max_concurrent: int = 2,
        fetch: Optional[Fetcher] = None,
        *,
        reserve_bytes: int = 0,
        gates: Optional[Gates] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.conn = conn
        self.client = client
        self.cache_root = cache_root
        self.max_concurrent = max(1, max_concurrent)
        self.reserve_bytes = reserve_bytes
        self._fetch = fetch or make_fetch(cache_root, reserve_bytes)
        self._gates = gates or Gates()
        self._sleep = sleep
        self._clock = clock
        self._pending: dict[str, None] = {}          # insertion-ordered set
        self._in_flight: dict[str, asyncio.Task] = {}
        self._wake = asyncio.Event()
        self._runner: Optional[asyncio.Task] = None
        self._offline_until = 0.0
        self._link_failures: dict[str, int] = {}     # consecutive, per track
        self._cancelled: set[str] = set()            # cancel()ed while in flight
        self.paused: Optional[str] = None
        # A new queue owns this drive: whatever an earlier run left half
        # done (power cut) is not downloading any more.
        sweep_partials(cache_root)
        conn.execute("UPDATE cache_state SET status='absent' "
                     "WHERE status IN ('downloading', 'queued')")

    def enqueue(self, track_id: str) -> bool:
        """Schedule a download. False when it is already queued, in flight
        or present."""
        self._cancelled.discard(track_id)   # wanted again after all
        if track_id in self._pending or track_id in self._in_flight:
            return False
        row = self.conn.execute(
            "SELECT status FROM cache_state WHERE track_id=?", (track_id,)).fetchone()
        if row is not None and row["status"] == "present":
            return False
        self.conn.execute(
            """INSERT INTO cache_state(track_id, status) VALUES (?, 'queued')
               ON CONFLICT(track_id) DO UPDATE SET status='queued', error_message=NULL""",
            (track_id,),
        )
        self._pending[track_id] = None
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run())
        self._wake.set()
        return True

    def cancel(self, track_ids: Iterable[str]) -> int:
        """Drop queued (not yet started) downloads; in-flight ones finish.
        Returns how many were dropped."""
        n = 0
        for tid in track_ids:
            if tid in self._pending:
                del self._pending[tid]
                self.conn.execute(
                    "DELETE FROM cache_state WHERE track_id=? AND status='queued'", (tid,))
                n += 1
            elif tid in self._in_flight:
                self._cancelled.add(tid)   # let it finish; never requeue it
        return n

    def snapshot(self) -> dict:
        return {"queued": len(self._pending), "in_flight": list(self._in_flight),
                "paused": self.paused}

    async def pause_reason(self) -> Optional[str]:
        if not self._gates.is_online() or self._clock() < self._offline_until:
            return "offline"
        free = self._gates.free_bytes()
        if free is not None and free < self.reserve_bytes:
            return "low_space"
        temp = self._gates.soc_temp_c()
        if temp is not None and temp >= THERMAL_LIMIT_C:
            return "hot"
        try:
            if await self._gates.is_streaming():
                return "streaming"
        except Exception as e:  # a broken probe never blocks downloads
            log.debug("streaming probe failed: %s", e)
        return None

    async def _run(self) -> None:
        while True:
            if not self._pending or len(self._in_flight) >= self.max_concurrent:
                if not self._pending:
                    self.paused = None
                self._wake.clear()
                await self._wake.wait()
                continue
            reason = await self.pause_reason()
            if reason != self.paused:
                log.info("downloads %s", f"paused: {reason}" if reason else "resumed")
            self.paused = reason
            if reason is not None:
                await self._sleep(_RECHECK_S[reason])
                continue
            tid = next(iter(self._pending))
            del self._pending[tid]
            self._in_flight[tid] = asyncio.create_task(self._download(tid))

    async def _download(self, track_id: str) -> None:
        try:
            result = await download_track(
                self.conn, self.client, track_id, self.cache_root, self._fetch,
                reserve_bytes=self.reserve_bytes)
            if result is DownloadResult.OK:
                # The link works: earlier drops were outages, not the tracks.
                self._link_failures.clear()
            elif result is DownloadResult.OFFLINE:
                self._on_link_failure(track_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("download of %s crashed", track_id)
        finally:
            self._in_flight.pop(track_id, None)
            self._cancelled.discard(track_id)
            self._wake.set()

    def _on_link_failure(self, track_id: str) -> None:
        """A download lost the link: idle before the next start, and put the
        track back at the head of the line — unless it was cancelled while
        in flight, or it has now dropped MAX_LINK_RETRIES times in a row
        (then it is a track problem: 'error', retried by the hourly sync)."""
        self._offline_until = self._clock() + OFFLINE_RECHECK_S
        if track_id in self._cancelled:
            self._link_failures.pop(track_id, None)
            self.conn.execute(
                "DELETE FROM cache_state WHERE track_id=? AND status='queued'", (track_id,))
            return
        n = self._link_failures.get(track_id, 0) + 1
        if n >= MAX_LINK_RETRIES:
            self._link_failures.pop(track_id, None)
            _mark(self.conn, track_id, "error",
                  f"download kept dropping ({n} interrupted transfers in a row)")
            log.warning("giving up on %s for now: %d interrupted transfers", track_id, n)
            return
        self._link_failures[track_id] = n
        self._pending = {track_id: None, **self._pending}

    async def drain(self) -> None:
        """Wait until nothing is queued or in flight (tests)."""
        while self._pending or self._in_flight:
            await asyncio.sleep(0.005)

    def stop(self) -> None:
        """Cancel the scheduler and every in-flight download (drive lost,
        shutdown). Their .part files are removed by download_track."""
        if self._runner is not None:
            self._runner.cancel()
        for task in self._in_flight.values():
            task.cancel()
        self._pending.clear()
        self._link_failures.clear()
        self._cancelled.clear()
