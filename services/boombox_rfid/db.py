"""Schema additions for RFID bindings.

The rfid_bindings table lives in /opt/boombox/state/library.db alongside
the Phase 1 catalog. This module owns its own migration version namespace
(_schema_version_rfid) so it can be applied independently of the library
schema migrations.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS _schema_version_rfid (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS rfid_bindings (
    uid          TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,     -- 'album' | 'artist' | 'playlist' | 'track'
    target_id    TEXT NOT NULL,     -- Subsonic ID
    label        TEXT,              -- human-readable, populated at bind time
    added_at     REAL NOT NULL,
    last_tap_ts  REAL,
    tap_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rfid_target ON rfid_bindings(kind, target_id);
"""

SCHEMA_VERSION = 1


def connect(path: Path) -> sqlite3.Connection:
    """Open the shared library DB with row factory + WAL. Idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,
        check_same_thread=False,
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    # The library service holds long sync transactions that can monopolize
    # the writer lock. Wait up to 10 s for it to release rather than
    # erroring immediately on the first conflict.
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply RFID schema additions. Idempotent. Independent of library
    schema migrations so the order of service startup doesn't matter."""
    current = 0
    try:
        row = conn.execute("SELECT version FROM _schema_version_rfid").fetchone()
        if row:
            current = row[0]
    except sqlite3.OperationalError:
        current = 0

    if current >= SCHEMA_VERSION:
        return

    conn.executescript(_DDL)
    conn.execute("DELETE FROM _schema_version_rfid")
    conn.execute("INSERT INTO _schema_version_rfid(version) VALUES (?)",
                 (SCHEMA_VERSION,))
