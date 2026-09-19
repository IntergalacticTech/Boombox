"""Tests for boombox_library.db — schema, migrations, FTS5 setup."""
from __future__ import annotations

from pathlib import Path

from boombox_library.db import SCHEMA_VERSION, connect, migrate


def test_migrate_creates_all_tables(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {"artists", "albums", "tracks", "playlists",
                "playlist_tracks", "pins", "cache_state",
                "search_index", "search_index_data",
                "search_index_idx", "search_index_content",
                "search_index_docsize", "search_index_config",
                "_schema_version"}
    assert expected.issubset(tables)


def test_migrate_idempotent(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    migrate(conn)  # second time must not error
    v = conn.execute("SELECT version FROM _schema_version").fetchone()[0]
    assert v == SCHEMA_VERSION


def test_fts5_search_round_trip(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("album", "abc123", "Back in Black", "AC/DC Back in Black 1980 rock"),
    )
    conn.commit()
    rows = list(conn.execute(
        "SELECT id FROM search_index WHERE search_index MATCH 'back'"
    ))
    assert len(rows) == 1
    assert rows[0][0] == "abc123"


def test_foreign_keys_enabled(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_sort_name_indexes_present(tmp_path: Path):
    """Browse path orders by sort_name; without indexes it's a full scan."""
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    migrate(conn)
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}
    assert "idx_albums_sort_name" in indexes
    assert "idx_artists_sort_name" in indexes


def test_fts_rowid_is_stable_positive_and_type_scoped():
    from boombox_library.db import fts_rowid
    a = fts_rowid("album", "abc123")
    assert a == fts_rowid("album", "abc123")
    assert 0 < a < 2**63
    assert a != fts_rowid("track", "abc123")
    assert a != fts_rowid("album", "abc124")


def test_migration_v3_rebuilds_search_index_with_stable_rowids(tmp_path: Path):
    """A v2 DB has FTS rows at arbitrary rowids; v3 must re-key every row to
    fts_rowid(content_type, id) without losing any and with search intact."""
    from boombox_library import db as dbmod
    from boombox_library.db import fts_rowid

    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    # Build a v2 database the old way.
    for i, ddl in enumerate(dbmod._MIGRATIONS[:2], start=1):
        conn.executescript(ddl)
        conn.execute("DELETE FROM _schema_version")
        conn.execute("INSERT INTO _schema_version(version) VALUES (?)", (i,))
    rows = [("album", "al1", "Back in Black", "AC/DC Back in Black"),
            ("track", "tr1", "Hells Bells", "Hells Bells"),
            ("artist", "ar1", "AC/DC", "AC/DC")]
    conn.executemany(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)", rows)
    assert conn.execute("SELECT rowid FROM search_index WHERE id='al1'").fetchone()[0] \
        != fts_rowid("album", "al1")

    migrate(conn)

    assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM search_index").fetchone()[0] == 3
    for ctype, id_, *_ in rows:
        got = conn.execute(
            "SELECT rowid FROM search_index WHERE content_type=? AND id=?", (ctype, id_)
        ).fetchone()[0]
        assert got == fts_rowid(ctype, id_)
    hit = conn.execute(
        "SELECT id FROM search_index WHERE search_index MATCH 'hells'").fetchone()
    assert hit[0] == "tr1"
