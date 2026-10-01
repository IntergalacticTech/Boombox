"""'Keep offline' (spec 2A): user pins on albums / artists / playlists,
their download progress, and the offline facts the LAN app dims rows with.

Pure functions over the catalog connection plus a queue-like object (the
service's DownloadQueue, or None when there is no music storage / source).

The pins table holds ONE row per target (pins.py ranks sources user >
favorite > rfid > starred), so keeping a starred or card-bound album
*replaces* its pin. Unkeeping therefore restores the weaker pin at once —
otherwise the album's files would be unprotected (evictable, removable)
until the next hourly reconcile.
"""
from __future__ import annotations

import logging
from sqlite3 import Connection
from typing import Iterable, Iterator, Optional, Protocol

from .models import PinKind, PinSource
from .pins import all_pinned_track_ids, expand_pin_to_tracks, pin, unpin

log = logging.getLogger("boombox-library.keep")

KEEP_KINDS = frozenset({PinKind.ALBUM, PinKind.ARTIST, PinKind.PLAYLIST})
_TABLE = {PinKind.ALBUM: "albums", PinKind.ARTIST: "artists",
          PinKind.PLAYLIST: "playlists", PinKind.TRACK: "tracks"}


class QueueLike(Protocol):
    def enqueue(self, track_id: str) -> bool: ...
    def cancel(self, track_ids: Iterable[str]) -> int: ...
    def snapshot(self) -> dict: ...


def _chunks(ids: list[str], n: int = 500) -> Iterator[list[str]]:
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def target_exists(conn: Connection, kind: PinKind, target_id: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {_TABLE[kind]} WHERE id=?",
                        (target_id,)).fetchone() is not None


def track_ids(conn: Connection, kind: PinKind, target_id: str) -> list[str]:
    """The target's tracks, de-duplicated (a playlist can repeat one)."""
    return list(dict.fromkeys(expand_pin_to_tracks(conn, kind, target_id)))


def present_sizes(conn: Connection, ids: list[str]) -> dict[str, int]:
    """track_id → size of every id that is on disk ('present')."""
    out: dict[str, int] = {}
    for chunk in _chunks(ids):
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT track_id, size_bytes FROM cache_state "
                f"WHERE status='present' AND track_id IN ({marks})", chunk):
            out[r[0]] = int(r[1] or 0)
    return out


def _pin_source(conn: Connection, kind: PinKind, target_id: str) -> Optional[str]:
    row = conn.execute("SELECT source FROM pins WHERE target_kind=? AND target_id=?",
                       (kind.value, target_id)).fetchone()
    return None if row is None else str(row["source"])


def keep_state(conn: Connection, kind: PinKind, target_id: str) -> dict:
    source = _pin_source(conn, kind, target_id)
    state = ("kept" if source == PinSource.USER.value
             else "starred" if source == PinSource.STARRED.value else "none")
    ids = track_ids(conn, kind, target_id)
    return {"state": state, "tracks_total": len(ids),
            "tracks_present": len(present_sizes(conn, ids))}


def keep(conn: Connection, queue: Optional[QueueLike], kind: PinKind,
         target_id: str) -> dict:
    """pin(source=user) + enqueue the target's tracks. Idempotent."""
    pin(conn, kind, target_id, PinSource.USER)
    queued = 0
    if queue is not None:
        queued = sum(1 for tid in track_ids(conn, kind, target_id) if queue.enqueue(tid))
    return {"ok": True, "queued": queued, "keep": keep_state(conn, kind, target_id)}


def _card_bound(conn: Connection, kind: PinKind, target_id: str) -> bool:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='rfid_bindings'").fetchone() is None:
        return False
    return conn.execute("SELECT 1 FROM rfid_bindings WHERE kind=? AND target_id=?",
                        (kind.value, target_id)).fetchone() is not None


def _starred(conn: Connection, kind: PinKind, target_id: str) -> bool:
    if kind not in (PinKind.ALBUM, PinKind.TRACK):
        return False  # reconcile_starred pins albums and tracks only
    row = conn.execute(f"SELECT navidrome_starred FROM {_TABLE[kind]} WHERE id=?",
                       (target_id,)).fetchone()
    return bool(row and row[0])


def unkeep(conn: Connection, queue: Optional[QueueLike], kind: PinKind,
           target_id: str, *, starred_auto_pin: bool) -> dict:
    """Drop the user pin; restore the card's or the star's pin it replaced;
    cancel queued downloads of tracks no pin protects any more (in-flight
    ones finish). Idempotent."""
    unpin(conn, kind, target_id, source=PinSource.USER)
    if _pin_source(conn, kind, target_id) is None:
        if _card_bound(conn, kind, target_id):
            pin(conn, kind, target_id, PinSource.RFID)
        elif starred_auto_pin and _starred(conn, kind, target_id):
            pin(conn, kind, target_id, PinSource.STARRED)
    cancelled = 0
    if queue is not None:
        protected = all_pinned_track_ids(conn)
        cancelled = queue.cancel(
            [t for t in track_ids(conn, kind, target_id) if t not in protected])
    return {"ok": True, "cancelled": cancelled, "keep": keep_state(conn, kind, target_id)}


_OFFLINE_IDS = {
    "album_ids": "SELECT DISTINCT t.album_id FROM tracks t "
                 "JOIN cache_state cs ON cs.track_id = t.id WHERE cs.status='present'",
    "artist_ids": "SELECT DISTINCT al.artist_id FROM albums al "
                  "JOIN tracks t ON t.album_id = al.id "
                  "JOIN cache_state cs ON cs.track_id = t.id WHERE cs.status='present'",
    "playlist_ids": "SELECT DISTINCT pt.playlist_id FROM playlist_tracks pt "
                    "JOIN cache_state cs ON cs.track_id = pt.track_id WHERE cs.status='present'",
}

_OFFLINE_FLAG_SQL = {
    "track": "SELECT track_id FROM cache_state WHERE status='present' AND track_id IN ({})",
    "album": "SELECT DISTINCT t.album_id FROM tracks t JOIN cache_state cs ON cs.track_id = t.id "
             "WHERE cs.status='present' AND t.album_id IN ({})",
    "artist": "SELECT DISTINCT al.artist_id FROM albums al JOIN tracks t ON t.album_id = al.id "
              "JOIN cache_state cs ON cs.track_id = t.id "
              "WHERE cs.status='present' AND al.artist_id IN ({})",
}


def offline_ids(conn: Connection) -> dict[str, list[str]]:
    """Albums / artists / playlists with at least one track on disk."""
    return {key: sorted(r[0] for r in conn.execute(sql)) for key, sql in _OFFLINE_IDS.items()}


def offline_flags(conn: Connection, results: list[dict]) -> list[dict]:
    """Search results (content_type, id, ...) + "offline": on disk (a track)
    or with at least one track on disk (an album / artist)."""
    by_type: dict[str, list[str]] = {}
    for r in results:
        by_type.setdefault(str(r.get("content_type", "")), []).append(str(r["id"]))
    have: set[tuple[str, str]] = set()
    for ctype, ids in by_type.items():
        sql = _OFFLINE_FLAG_SQL.get(ctype)
        if sql is None:
            continue
        for chunk in _chunks(list(dict.fromkeys(ids))):
            for row in conn.execute(sql.format(",".join("?" * len(chunk))), chunk):
                have.add((ctype, row[0]))
    return [{**r, "offline": (str(r.get("content_type", "")), str(r["id"])) in have}
            for r in results]
