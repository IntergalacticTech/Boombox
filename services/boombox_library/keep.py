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
import os
from pathlib import Path
from sqlite3 import Connection
from typing import Callable, Iterable, Iterator, Optional, Protocol

from .cache_drive import CacheDriveState
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
        # This also cancels queued streamed-cache downloads of the target's
        # unprotected tracks (the queue doesn't tell the two apart).
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


STARRED_ONLY = "unstar in Navidrome to remove"
CARD_ONLY = "bound to an RFID card — unbind the card to remove"
# pins.source → the Storage page's "source" (an RFID pin shows as "card")
_LISTED_SOURCES = {PinSource.USER.value: "user", PinSource.STARRED.value: "starred",
                   PinSource.RFID.value: "card"}


def _name(conn: Connection, kind: PinKind, target_id: str) -> str:
    row = conn.execute(f"SELECT name FROM {_TABLE[kind]} WHERE id=?", (target_id,)).fetchone()
    return str(row[0]) if row else target_id


def _item(conn: Connection, kind: str, target_id: str, name: str, source: str,
          ids: list[str]) -> dict:
    sizes = present_sizes(conn, ids)
    return {"kind": kind, "id": target_id, "name": name, "source": source,
            "tracks_total": len(ids), "tracks_present": len(sizes),
            "bytes": sum(sizes.values())}


def kept_items(conn: Connection) -> list[dict]:
    """User, starred and card-bound (RFID, source "card") pins on albums /
    artists / playlists, oldest first, then one aggregate row each for
    starred single tracks and card-bound single tracks."""
    marks = ",".join("?" * len(_LISTED_SOURCES))
    rows = list(conn.execute(
        f"SELECT target_kind, target_id, source FROM pins WHERE source IN ({marks}) "
        "AND target_kind IN ('album', 'artist', 'playlist') ORDER BY added_at",
        tuple(_LISTED_SOURCES)))
    items: list[dict] = []
    for r in rows:
        kind = PinKind(r["target_kind"])
        items.append(_item(conn, kind.value, r["target_id"], _name(conn, kind, r["target_id"]),
                           _LISTED_SOURCES[r["source"]], track_ids(conn, kind, r["target_id"])))
    for source, kind_name, name in ((PinSource.STARRED, "starred_tracks", "Starred songs"),
                                    (PinSource.RFID, "card_tracks", "Songs on cards")):
        ids = [r[0] for r in conn.execute(
            "SELECT target_id FROM pins WHERE target_kind='track' AND source=? "
            "ORDER BY added_at", (source.value,))]
        if ids:
            items.append(_item(conn, kind_name, "", name, _LISTED_SOURCES[source.value], ids))
    return items


def storage_overview(conn: Connection, drive: Optional[CacheDriveState],
                     reserve_bytes: int, queue: Optional[QueueLike]) -> dict:
    """The Admin → Storage page. ``music_bytes`` is every track file on disk
    (kept or leftover streamed cache); ``kept_tracks`` and the ``failed`` /
    ``no_space`` counters cover pinned tracks only — the same set
    retry_failed re-enqueues, so the counters always match what Retry can do."""
    protected = all_pinned_track_ids(conn)
    total = count = 0
    for r in conn.execute(
            "SELECT track_id, size_bytes FROM cache_state WHERE status='present'"):
        total += int(r[1] or 0)
        if r[0] in protected:
            count += 1
    failed = {"error": 0, "no_space": 0}
    for r in conn.execute(
            "SELECT track_id, status FROM cache_state WHERE status IN ('error', 'no_space')"):
        if r[0] in protected:
            failed[r[1]] += 1
    snap = queue.snapshot() if queue is not None else {
        "queued": 0, "in_flight": [], "paused": None}
    in_flight = [str(t) for t in snap["in_flight"]]
    titles: dict[str, str] = {}
    for chunk in _chunks(in_flight):
        marks = ",".join("?" * len(chunk))
        titles.update((r[0], r[1]) for r in conn.execute(
            f"SELECT id, title FROM tracks WHERE id IN ({marks})", chunk))
    present = drive is not None and drive.present
    return {
        "drive": {
            "present": present,
            "internal": bool(drive is not None and drive.internal),
            "mount_path": str(drive.mount_path) if drive is not None and present and drive.mount_path else None,
            "total_bytes": drive.total_bytes if drive is not None and present else None,
            "free_bytes": drive.free_bytes if drive is not None and present else None,
            "reserve_bytes": reserve_bytes,
            "music_bytes": total,
            "kept_tracks": count,
        },
        "kept": kept_items(conn),
        "downloads": {
            "active": queue is not None,
            "queued": int(snap["queued"]),
            "in_flight": [{"id": t, "title": titles.get(t, t)} for t in in_flight],
            "paused": snap["paused"],
            "failed": failed["error"],
            "no_space": failed["no_space"],
        },
    }


def _inside(path: str, root: Optional[Path]) -> bool:
    if root is None:
        return False
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def remove_kept(conn: Connection, queue: Optional[QueueLike], kind: PinKind,
                target_id: str, *, starred_auto_pin: bool, cache_root: Optional[Path],
                delete_file: Callable[[str], None] = os.unlink) -> tuple[int, dict]:
    """Storage → Remove: unkeep, then delete at once the files of tracks no
    pin protects any more (the plain unkeep leaves them to eviction).
    Only files that resolve inside ``cache_root`` (the adopted music drive)
    are deleted; any other path is logged and its row left 'present' (none
    at all without a drive). Starred-only and card-only items can't be
    removed here (unstar / unbind the card instead).
    Idempotent."""
    source = _pin_source(conn, kind, target_id)
    if source == PinSource.STARRED.value:
        return 409, {"ok": False, "error": STARRED_ONLY}
    if source == PinSource.RFID.value:
        return 409, {"ok": False, "error": CARD_ONLY}
    unkeep(conn, queue, kind, target_id, starred_auto_pin=starred_auto_pin)
    protected = all_pinned_track_ids(conn)
    orphans = [t for t in track_ids(conn, kind, target_id) if t not in protected]
    removed = freed = 0
    for chunk in _chunks(orphans):
        marks = ",".join("?" * len(chunk))
        rows = list(conn.execute(
            f"SELECT track_id, local_path, size_bytes FROM cache_state "
            f"WHERE status='present' AND track_id IN ({marks})", chunk))
        for r in rows:
            if r["local_path"]:
                if not _inside(r["local_path"], cache_root):
                    log.warning("not deleting %s: outside the music storage %s",
                                r["local_path"], cache_root)
                    continue
                try:
                    delete_file(r["local_path"])
                except FileNotFoundError:
                    pass
                except OSError as e:
                    log.warning("could not delete %s: %s", r["local_path"], e)
                    continue
            conn.execute(
                "UPDATE cache_state SET status='absent', local_path=NULL, size_bytes=NULL, "
                "downloaded_at=NULL, error_message=NULL WHERE track_id=?", (r["track_id"],))
            removed += 1
            freed += int(r["size_bytes"] or 0)
    return 200, {"ok": True, "removed_tracks": removed, "freed_bytes": freed,
                 "keep": keep_state(conn, kind, target_id)}


def retry_failed(conn: Connection, queue: QueueLike) -> int:
    """Re-enqueue pinned tracks in 'error' / 'no_space' (Storage → Retry failed)."""
    protected = all_pinned_track_ids(conn)
    ids = [r[0] for r in conn.execute(
        "SELECT track_id FROM cache_state WHERE status IN ('error', 'no_space') "
        "ORDER BY track_id") if r[0] in protected]
    return sum(1 for t in ids if queue.enqueue(t))
