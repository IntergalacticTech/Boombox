"""Playback resolver — decides which Mopidy URI form to play for a given
Subsonic track ID, given current cache state and online reachability.

For streaming (uncached + online), the resolver emits a URL on
boombox-library's own local stream proxy
(http://127.0.0.1:6687/api/library/stream/<id>, see stream_proxy.py),
which adds the Subsonic token+salt auth server-side. The URI Mopidy holds
— and that leaks into last.json, the phone remote and the screen — thus
carries no reusable credential. Mopidy's built-in `stream:` backend pipes
the HTTP body through GStreamer without needing Mopidy-Subsonic — that
plugin is Python-2 bit-rotten and fails to initialize on modern Python 3.

Side effects (the streamed-cache trigger) are not in this module — the
HTTP handler in api.py orchestrates them after consulting the resolver.
"""
from __future__ import annotations

import os
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


# Mopidy talks to the proxy directly (not via nginx, which puts basic auth
# in front of /api/library/). Override for tests or a non-default port.
DEFAULT_STREAM_BASE = "http://127.0.0.1:6687/api/library/stream"
STREAM_BASE_ENV = "BOOMBOX_LIBRARY_STREAM_BASE"


def stream_base() -> str:
    return (os.environ.get(STREAM_BASE_ENV) or DEFAULT_STREAM_BASE).rstrip("/")


def make_proxy_stream_url(track_id: str, base: Optional[str] = None) -> str:
    """URL of the local stream proxy for track_id — credential-free."""
    return f"{(base or stream_base()).rstrip('/')}/{quote(track_id, safe='')}"


def make_stream_url(
    base_url: str, username: str, password: str, track_id: str,
) -> str:
    """Construct a direct Subsonic stream.view URL with token+salt auth.

    Back-compat only — playback goes through make_proxy_stream_url so the
    token+salt never leaves boombox-library."""
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
    stream_base_url: Optional[str] = None,
) -> PlaybackResolution:
    """Decide which URI form to play.

    Rules (from spec):
      cached + file on disk         → file://<path>,                  source=CACHE
      not cached + online + cfg     → http://127.0.0.1:6687/api/library/stream/<id>,
                                                                       source=STREAM
      not cached + online + no cfg  → uri=None,                       source=OFFLINE_MISS
      not cached + offline          → uri=None,                       source=OFFLINE_MISS
      unknown track                 → uri=None,                       source=OFFLINE_MISS

    "Cached" requires the file to actually exist: a row still saying
    'present' after the cache drive was yanked (or the file deleted) is
    treated as not cached rather than handing Mopidy a dead file:// URI.
    The source credentials only gate STREAM (the proxy needs a configured
    source); they never appear in the URI.
    """
    row = conn.execute(
        "SELECT status, local_path FROM cache_state WHERE track_id=?",
        (track_id,),
    ).fetchone()

    cached = (row is not None and row["status"] == "present"
              and row["local_path"] and os.path.exists(row["local_path"]))
    if cached:
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
    if cache_status == "present":
        # DB says present but the file is gone — report what's true.
        cache_status = "absent"

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
            uri=make_proxy_stream_url(track_id, stream_base_url),
            cache_status=cache_status,
        )

    return PlaybackResolution(
        source=PlaybackSource.OFFLINE_MISS, uri=None,
        cache_status=cache_status,
    )
