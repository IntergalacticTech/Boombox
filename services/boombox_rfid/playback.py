"""Resolve a binding (kind + target_id) into a list of playable Mopidy URIs.

Reuses Phase 1's playback resolver: for each track in the bound target we
ask the boombox-library `resolver.resolve_playback` for the right URI form
(file:// when cached, subsonic:track:<id> when streaming).

Skips tracks the resolver marks 'offline_miss' (not cached + not online).
"""
from __future__ import annotations

import logging
from sqlite3 import Connection

from .models import BindingKind

log = logging.getLogger("boombox-rfid.playback")


def expand_to_track_ids(conn: Connection, kind: BindingKind, target_id: str) -> list[str]:
    """Return the ordered track IDs that a binding resolves to."""
    if kind == BindingKind.TRACK:
        return [target_id]
    if kind == BindingKind.ALBUM:
        return [r[0] for r in conn.execute(
            "SELECT id FROM tracks WHERE album_id=? "
            "ORDER BY disc_no, track_no", (target_id,))]
    if kind == BindingKind.ARTIST:
        return [r[0] for r in conn.execute(
            "SELECT t.id FROM tracks t "
            "JOIN albums a ON a.id = t.album_id "
            "WHERE a.artist_id=? "
            "ORDER BY a.year, a.sort_name, t.disc_no, t.track_no",
            (target_id,))]
    if kind == BindingKind.PLAYLIST:
        return [r[0] for r in conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id=? "
            "ORDER BY position", (target_id,))]
    raise ValueError(f"unknown BindingKind {kind}")


def resolve_uris(conn: Connection, track_ids: list[str], online: bool) -> list[str]:
    """Map each track id to its playable URI using Phase 1's resolver."""
    # Lazy import — boombox_library lives in a sibling package on sys.path.
    from boombox_library.resolver import resolve_playback, PlaybackSource

    out: list[str] = []
    for tid in track_ids:
        r = resolve_playback(conn, tid, online)
        if r.source == PlaybackSource.OFFLINE_MISS or not r.uri:
            log.debug("skipping offline-miss track %s", tid)
            continue
        out.append(r.uri)
    return out
