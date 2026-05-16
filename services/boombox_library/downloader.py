"""Audio file downloader for boombox-library.

download_track() handles one track end-to-end: stream from Subsonic to
a .part tmp file, atomically rename to final, update cache_state. The
fetch coroutine is injected to keep network out of unit tests; the real
implementation uses aiohttp streaming.

The queue + concurrency layer (Task 10) wraps this.
"""
from __future__ import annotations

import enum
import logging
import os
import time
from pathlib import Path
from sqlite3 import Connection
from typing import Awaitable, Callable, Protocol

import aiohttp

log = logging.getLogger("boombox-library.downloader")


class DownloadResult(str, enum.Enum):
    OK = "ok"
    SKIPPED = "skipped"  # already present
    ERROR = "error"


class StreamingClient(Protocol):
    def download_url(self, track_id: str) -> tuple[str, dict]: ...


Fetcher = Callable[[str, dict, Path], Awaitable[None]]
"""(url, params, dest_path) → writes bytes to dest_path."""


async def default_fetch(url: str, params: dict, dest: Path) -> None:
    """Real aiohttp streaming fetch. Raises on non-2xx."""
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)


async def download_track(
    conn: Connection,
    client: StreamingClient,
    track_id: str,
    cache_root: Path,
    fetch: Fetcher = default_fetch,
) -> DownloadResult:
    """Download one track into cache_root/audio/<id>.<suffix> atomically.

    cache_root must contain pre-existing audio/ and tmp/ subdirs (caller's
    responsibility — usually adopt_drive() has created them).
    """
    # Skip if already present
    row = conn.execute(
        "SELECT status FROM cache_state WHERE track_id=?", (track_id,)
    ).fetchone()
    if row and row["status"] == "present":
        return DownloadResult.SKIPPED

    # Look up track metadata
    trow = conn.execute(
        "SELECT suffix, size_bytes FROM tracks WHERE id=?", (track_id,)
    ).fetchone()
    if trow is None:
        log.error("track %s not in catalog; skipping", track_id)
        return DownloadResult.ERROR
    suffix = trow["suffix"] or "bin"

    tmp_path = cache_root / "tmp" / f"{track_id}.part"
    final_path = cache_root / "audio" / f"{track_id}.{suffix}"

    # Mark downloading
    conn.execute(
        """INSERT INTO cache_state(track_id, status, downloaded_at)
           VALUES (?, 'downloading', ?)
           ON CONFLICT(track_id) DO UPDATE SET status='downloading',
                                                error_message=NULL""",
        (track_id, time.time()),
    )

    url, params = client.download_url(track_id)
    try:
        if tmp_path.exists():
            tmp_path.unlink()
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
    except Exception as e:
        # Clean up partial file
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        conn.execute(
            """INSERT INTO cache_state(track_id, status, error_message)
               VALUES (?, 'error', ?)
               ON CONFLICT(track_id) DO UPDATE SET
                  status='error', error_message=excluded.error_message""",
            (track_id, str(e)),
        )
        log.warning("download of %s failed: %s", track_id, e)
        return DownloadResult.ERROR
