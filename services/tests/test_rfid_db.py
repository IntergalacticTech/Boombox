"""Schema migration for rfid_bindings."""
from __future__ import annotations

from pathlib import Path

from boombox_rfid.db import connect, migrate


def test_migrate_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "lib.db")
    migrate(conn)
    migrate(conn)  # again — no error
    rows = list(conn.execute("SELECT version FROM _schema_version_rfid"))
    assert rows[0][0] == 1


def test_migrate_creates_bindings_table(tmp_path: Path):
    conn = connect(tmp_path / "lib.db")
    migrate(conn)
    # Insert a row to confirm columns line up.
    conn.execute(
        "INSERT INTO rfid_bindings(uid, kind, target_id, added_at) "
        "VALUES ('0001', 'album', 'al1', 0)"
    )
    row = conn.execute("SELECT * FROM rfid_bindings").fetchone()
    assert row["uid"] == "0001"
    assert row["kind"] == "album"
    assert row["tap_count"] == 0  # default
