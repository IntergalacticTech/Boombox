"""Playback resolver — decides which Mopidy URI form to play for a given
Subsonic track ID, given current cache state and online reachability.

This is a pure function over (catalog state, cache state, online bool).
Side effects (the streamed-cache trigger) are not in this module — the
HTTP handler in api.py orchestrates them after consulting the resolver.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from sqlite3 import Connection
from typing import Optional
from urllib.parse import quote


class PlaybackSource(str, Enum):
    CACHE = "cache"
    STREAM = "stream"
    OFFLINE_MISS = "offline_miss"


@dataclass(frozen=True)
class PlaybackResolution:
    source: PlaybackSource
    uri: Optional[str]
    cache_status: str  # 'present' | 'absent' | etc.


def resolve_playback(conn: Connection, track_id: str, online: bool) -> PlaybackResolution:
    """Decide which URI form to play.

    Rules (from spec):
      cached + (online or offline)  → local:<path>,    source=CACHE
      not cached + online           → subsonic:track:<id>, source=STREAM
      not cached + offline          → uri=None,        source=OFFLINE_MISS
      unknown track                 → uri=None,        source=OFFLINE_MISS
    """
    row = conn.execute(
        "SELECT status, local_path FROM cache_state WHERE track_id=?",
        (track_id,),
    ).fetchone()

    if row is not None and row["status"] == "present" and row["local_path"]:
        # file:// URI plays through Mopidy's bundled stream backend (GStreamer
        # filesrc) — independent of Mopidy-Local's index. urllib.parse.quote
        # handles paths with spaces, unicode, #, ?, % correctly.
        quoted = quote(row["local_path"], safe="/")
        return PlaybackResolution(
            source=PlaybackSource.CACHE,
            uri=f"file://{quoted}",
            cache_status="present",
        )

    cache_status = row["status"] if row is not None else "absent"

    # Verify the track actually exists in the catalog before promising a stream
    exists = conn.execute(
        "SELECT 1 FROM tracks WHERE id=?", (track_id,)
    ).fetchone() is not None

    if not exists:
        return PlaybackResolution(
            source=PlaybackSource.OFFLINE_MISS, uri=None,
            cache_status=cache_status,
        )

    if online:
        return PlaybackResolution(
            source=PlaybackSource.STREAM,
            uri=f"subsonic:track:{track_id}",
            cache_status=cache_status,
        )

    return PlaybackResolution(
        source=PlaybackSource.OFFLINE_MISS, uri=None,
        cache_status=cache_status,
    )
