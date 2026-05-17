"""CRUD over the rfid_bindings table + bookkeeping for taps.

Binding a card also creates a Phase 1 pin (source='rfid'), so the bound
content gets pre-cached for offline play and tap-to-play is fast.
"""
from __future__ import annotations

import time
from sqlite3 import Connection
from typing import Optional

from .models import Binding, BindingKind


def get_binding(conn: Connection, uid: str) -> Optional[Binding]:
    row = conn.execute(
        "SELECT uid, kind, target_id, label, added_at, last_tap_ts, tap_count "
        "FROM rfid_bindings WHERE uid=?",
        (uid,),
    ).fetchone()
    if row is None:
        return None
    return Binding(
        uid=row["uid"],
        kind=BindingKind(row["kind"]),
        target_id=row["target_id"],
        label=row["label"],
        added_at=row["added_at"],
        last_tap_ts=row["last_tap_ts"],
        tap_count=row["tap_count"],
    )


def list_bindings(conn: Connection) -> list[Binding]:
    rows = conn.execute(
        "SELECT uid, kind, target_id, label, added_at, last_tap_ts, tap_count "
        "FROM rfid_bindings ORDER BY added_at DESC"
    ).fetchall()
    return [
        Binding(
            uid=r["uid"], kind=BindingKind(r["kind"]),
            target_id=r["target_id"], label=r["label"],
            added_at=r["added_at"], last_tap_ts=r["last_tap_ts"],
            tap_count=r["tap_count"],
        )
        for r in rows
    ]


def bind(
    conn: Connection,
    uid: str,
    kind: BindingKind,
    target_id: str,
    label: Optional[str] = None,
) -> None:
    """Insert or replace a binding. Idempotent over (uid).

    Also creates a Phase 1 pin (source='rfid') for the bound target so the
    library service downloads the audio to the offline cache. Pins are
    additive: a parallel user pin / favorite pin is unaffected.
    """
    now = time.time()
    conn.execute(
        """INSERT INTO rfid_bindings(uid, kind, target_id, label, added_at, tap_count)
           VALUES (?, ?, ?, ?, ?, 0)
           ON CONFLICT(uid) DO UPDATE SET
             kind=excluded.kind,
             target_id=excluded.target_id,
             label=excluded.label""",
        (uid, kind.value, target_id, label, now),
    )
    # Auto-pin so the bound album/artist/playlist/track is pre-cached. RFID
    # is the lowest writer rank — explicit user pins survive a same-target
    # rebind, and the auto-pin gives way later if the user explicitly pins
    # USER. Lazy-imported to keep boombox_rfid's hot path independent of
    # the library package if we ever split the install.
    try:
        from boombox_library.models import PinKind, PinSource
        from boombox_library.pins import pin as _pin
        _pin(conn, PinKind(kind.value), target_id, PinSource.RFID)
    except Exception:
        pass  # if library tables aren't present, the binding still works


def unbind_with_pin(conn: Connection, uid: str) -> bool:
    """Delete a binding AND its rfid-source pin if any. Returns True if
    the binding existed. The pin is removed source-filtered so a parallel
    user pin survives."""
    existing = get_binding(conn, uid)
    if existing is None:
        return unbind(conn, uid)  # idempotent false
    unbind(conn, uid)
    try:
        from boombox_library.models import PinKind, PinSource
        from boombox_library.pins import unpin
        unpin(conn, PinKind(existing.kind.value), existing.target_id,
              source=PinSource.RFID)
    except Exception:
        pass
    return True


def unbind(conn: Connection, uid: str) -> bool:
    """Delete a binding. Returns True if a row was removed."""
    cur = conn.execute("DELETE FROM rfid_bindings WHERE uid=?", (uid,))
    return cur.rowcount > 0


def record_tap(conn: Connection, uid: str) -> None:
    """Bump tap_count + last_tap_ts for a bound UID. No-op for unbound."""
    conn.execute(
        "UPDATE rfid_bindings SET last_tap_ts=?, tap_count=tap_count+1 "
        "WHERE uid=?",
        (time.time(), uid),
    )
