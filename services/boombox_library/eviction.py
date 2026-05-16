"""FIFO eviction over streamed cache; pinned content is protected.

The set of "pinned-protected" track IDs is derived from the pins table
by expanding each pin (album→tracks, artist→tracks, playlist→tracks,
track→itself). We materialize this set in Python and query SQLite for
the rest, ordered by downloaded_at ASC.

Eviction is opportunistic: it never deletes more than needed to satisfy
the byte deficit; it deletes the FILE and marks cache_state status='absent'.
The caller (downloader / pin handler) decides what to do with any
leftover deficit.
"""
from __future__ import annotations

import logging
from sqlite3 import Connection
from typing import Callable

from .pins import all_pinned_track_ids

log = logging.getLogger("boombox-library.eviction")


def compute_eviction_candidates(conn: Connection) -> list[dict]:
    """Cached tracks that are NOT pin-protected, oldest first."""
    pinned = all_pinned_track_ids(conn)
    rows = list(conn.execute(
        """SELECT track_id, local_path, size_bytes, downloaded_at
           FROM cache_state
           WHERE status='present'
           ORDER BY downloaded_at ASC"""
    ))
    return [dict(r) for r in rows if r["track_id"] not in pinned]


def evict_until_fits(
    conn: Connection,
    need_bytes: int,
    delete_file: Callable[[str], None],
) -> tuple[int, int]:
    """Evict oldest streamed cache items FIFO until need_bytes is freed,
    or no more candidates exist.

    Returns (freed_bytes, leftover_deficit). leftover_deficit > 0 means
    we hit the bottom of the unpinned pool without satisfying the request.
    """
    if need_bytes <= 0:
        return (0, 0)

    candidates = compute_eviction_candidates(conn)
    freed = 0
    for c in candidates:
        if freed >= need_bytes:
            break
        try:
            delete_file(c["local_path"])
        except OSError as e:
            log.warning("could not delete %s: %s", c["local_path"], e)
        conn.execute(
            """UPDATE cache_state
               SET status='absent', local_path=NULL, size_bytes=NULL,
                   downloaded_at=NULL, error_message=NULL
               WHERE track_id=?""",
            (c["track_id"],),
        )
        freed += int(c["size_bytes"] or 0)

    leftover = max(0, need_bytes - freed)
    return (freed, leftover)
