"""Tests for boombox_library.db — schema, migrations, FTS5 setup."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from boombox_library.db import connect, migrate, SCHEMA_VERSION


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
