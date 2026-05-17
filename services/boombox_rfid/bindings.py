"""CRUD over the rfid_bindings table + bookkeeping for taps."""
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
    """Insert or replace a binding. Idempotent over (uid)."""
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
