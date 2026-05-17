"""Playback resolver — decides which Mopidy URI form to play for a given
Subsonic track ID, given current cache state and online reachability.

For streaming (uncached + online), the resolver emits a direct HTTPS URL
to the Subsonic `stream.view` endpoint with token+salt auth baked in.
Mopidy's built-in `stream:` backend pipes the HTTP body through GStreamer
without needing Mopidy-Subsonic — that plugin is Python-2 bit-rotten and
fails to initialize on modern Python 3.

Side effects (the streamed-cache trigger) are not in this module — the
HTTP handler in api.py orchestrates them after consulting the resolver.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from sqlite3 import Connection
from typing import Optional
from urllib.parse import quote, urlencode

from .subsonic import make_auth_params


class PlaybackSource(str, Enum):
    CACHE = "cache"
    STREAM = "stream"
    OFFLINE_MISS = "offline_miss"


@dataclass(frozen=True)
class PlaybackResolution:
    source: PlaybackSource
    uri: Optional[str]
    cache_status: str  # 'present' | 'absent' | etc.


def make_stream_url(
    base_url: str, username: str, password: str, track_id: str,
) -> str:
    """Construct a direct Subsonic stream.view URL with token+salt auth.
    Mopidy's stream backend can play this directly via GStreamer."""
    params = make_auth_params(username=username, password=password)
    params["id"] = track_id
    return f"{base_url.rstrip('/')}/rest/stream.view?{urlencode(params)}"


def resolve_playback(
    conn: Connection,
    track_id: str,
    online: bool,
    *,
    source_url: str = "",
    source_username: str = "",
    source_password: str = "",
) -> PlaybackResolution:
    """Decide which URI form to play.

    Rules (from spec):
      cached + (online or offline)  → file://<path>,             source=CACHE
      not cached + online + cfg     → https://.../stream.view?…, source=STREAM
      not cached + online + no cfg  → uri=None,                  source=OFFLINE_MISS
      not cached + offline          → uri=None,                  source=OFFLINE_MISS
      unknown track                 → uri=None,                  source=OFFLINE_MISS
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

    if online and source_url and source_username and source_password:
        return PlaybackResolution(
            source=PlaybackSource.STREAM,
            uri=make_stream_url(source_url, source_username, source_password, track_id),
            cache_status=cache_status,
        )

    return PlaybackResolution(
        source=PlaybackSource.OFFLINE_MISS, uri=None,
        cache_status=cache_status,
    )
