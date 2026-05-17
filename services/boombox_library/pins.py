"""Pin manager — pin/unpin, cascade rules, starred reconciliation,
write-ahead JSON sidecar.

Pin semantics:
- Pin an album    → track-level downloads are scheduled for its tracks.
                    The `pins` row is at the album level; tracks are not
                    individually pinned in the DB. expand_pin_to_tracks()
                    is the resolver.
- Pin an artist   → snapshot of the artist's *current* albums; new
                    releases later are NOT auto-pinned.
- Pin a playlist  → its constituent tracks are scheduled.
- Pin a track     → just that track.

A track is "pinned-protected" (cache-wise) iff any pin row resolves to it.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from sqlite3 import Connection

from .models import PinKind, PinSource


def expand_pin_to_tracks(conn: Connection, kind: PinKind, target_id: str) -> list[str]:
    """Return the list of track IDs that a pin resolves to."""
    if kind == PinKind.TRACK:
        return [target_id]
    if kind == PinKind.ALBUM:
        return [r[0] for r in conn.execute(
            "SELECT id FROM tracks WHERE album_id=?", (target_id,))]
    if kind == PinKind.ARTIST:
        return [r[0] for r in conn.execute(
            "SELECT t.id FROM tracks t "
            "JOIN albums a ON a.id = t.album_id "
            "WHERE a.artist_id=?", (target_id,))]
    if kind == PinKind.PLAYLIST:
        return [r[0] for r in conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id=? "
            "ORDER BY position", (target_id,))]
    raise ValueError(f"unknown PinKind {kind}")


# Precedence (high → low): USER > FAVORITE > RFID > STARRED.
# When inserting over an existing pin we upgrade source iff the new source
# outranks the stored one; we never downgrade. STARRED is weakest so it
# only takes effect when no pin exists.
_SOURCE_RANK = {
    PinSource.USER: 4,
    PinSource.FAVORITE: 3,
    PinSource.RFID: 2,
    PinSource.STARRED: 1,
}


def pin(conn: Connection, kind: PinKind, target_id: str, source: PinSource) -> None:
    """Insert or upgrade a pin row.

    Idempotent. If an existing pin's source ranks lower than the new one, the
    row's source is upgraded; otherwise the existing source is preserved.
    """
    existing = conn.execute(
        "SELECT source FROM pins WHERE target_kind=? AND target_id=?",
        (kind.value, target_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO pins(target_kind, target_id, source, added_at) "
            "VALUES (?, ?, ?, ?)",
            (kind.value, target_id, source.value, time.time()),
        )
        return
    try:
        existing_src = PinSource(existing["source"])
    except ValueError:
        existing_src = PinSource.STARRED  # unknown → lowest rank
    if _SOURCE_RANK[source] > _SOURCE_RANK[existing_src]:
        conn.execute(
            "UPDATE pins SET source=? WHERE target_kind=? AND target_id=?",
            (source.value, kind.value, target_id),
        )


def unpin(
    conn: Connection,
    kind: PinKind,
    target_id: str,
    source: PinSource | None = None,
) -> None:
    """Delete a pin row. If `source` is given, only rows with that source are
    deleted — so removing a favorite-driven pin doesn't nuke a parallel
    user-driven pin. Without `source`, force-deletes any pin for (kind, id).
    """
    if source is None:
        conn.execute(
            "DELETE FROM pins WHERE target_kind=? AND target_id=?",
            (kind.value, target_id),
        )
    else:
        conn.execute(
            "DELETE FROM pins WHERE target_kind=? AND target_id=? AND source=?",
            (kind.value, target_id, source.value),
        )


def all_pinned_track_ids(conn: Connection) -> set[str]:
    """Union of every track ID protected by any pin."""
    out: set[str] = set()
    for row in conn.execute("SELECT target_kind, target_id FROM pins"):
        out.update(expand_pin_to_tracks(conn, PinKind(row[0]), row[1]))
    return out


def reconcile_starred(conn: Connection) -> None:
    """Two-way reconcile between Navidrome's starred state and pins.source='starred'.

    - For each album/artist/track marked navidrome_starred=1, INSERT a
      starred-source pin (no-op if any pin already exists).
    - For each starred-source pin whose target is no longer starred,
      DELETE the pin. User/RFID-source pins are untouched.
    """
    # Add starred pins for currently starred items
    for row in conn.execute("SELECT id FROM albums WHERE navidrome_starred=1"):
        pin(conn, PinKind.ALBUM, row[0], PinSource.STARRED)
    for row in conn.execute("SELECT id FROM tracks WHERE navidrome_starred=1"):
        pin(conn, PinKind.TRACK, row[0], PinSource.STARRED)
    # (Subsonic also reports starred artists; we represent these as artist pins.)
    # No artists table column for starred yet — Subsonic-side starred artists
    # arrive via reconcile path in catalog.sync_full's getStarred; for v1 we
    # do NOT auto-pin starred artists (they pull in an artist's whole catalog,
    # which is rarely what the user means by "starred"). Documented decision.

    # Remove starred-source pins whose target lost its star
    conn.execute("""
        DELETE FROM pins
        WHERE source='starred'
          AND target_kind='album'
          AND target_id NOT IN (SELECT id FROM albums WHERE navidrome_starred=1)
    """)
    conn.execute("""
        DELETE FROM pins
        WHERE source='starred'
          AND target_kind='track'
          AND target_id NOT IN (SELECT id FROM tracks WHERE navidrome_starred=1)
    """)


def write_sidecar(conn: Connection, path: Path) -> None:
    """Write pins to a JSON sidecar (write-ahead) — survives SQLite corruption.

    Atomic write: write to .tmp, fsync, then os.replace. Matches the
    write-ahead pattern used for the config file (Task 4 fix).
    """
    pins_list = [dict(r) for r in conn.execute(
        "SELECT target_kind, target_id, source, added_at FROM pins")]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps({"version": 1, "pins": pins_list},
                         indent=2, sort_keys=True)
    with tmp.open("w") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_sidecar(conn: Connection, path: Path) -> int:
    """Load pins from sidecar into an empty DB. Returns count loaded.
    No-op if sidecar missing. Skips entries whose target_kind is unknown."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    loaded = 0
    for p in data.get("pins", []):
        try:
            kind = PinKind(p["target_kind"])
            src = PinSource(p["source"])
        except ValueError:
            continue
        conn.execute(
            """INSERT INTO pins(target_kind, target_id, source, added_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(target_kind, target_id) DO NOTHING""",
            (kind.value, p["target_id"], src.value, float(p.get("added_at", 0))),
        )
        loaded += 1
    return loaded
