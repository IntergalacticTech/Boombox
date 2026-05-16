"""SQLite connection + schema migrations for boombox-library.

The catalog DB lives at /opt/boombox/state/library.db on production;
tests use tempdirs. FTS5 is built-in to SQLite (>= 3.9 with extension);
we rely on the system sqlite shipped with Python 3.11+ on Debian/Ubuntu.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("boombox-library.db")

SCHEMA_VERSION = 1


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with sane defaults: foreign keys ON, WAL mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,  # autocommit; we use explicit BEGIN where needed
        check_same_thread=False,
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


_MIGRATIONS = [
    # v1 — initial schema
    """
    CREATE TABLE IF NOT EXISTS _schema_version (
        version INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS artists (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        sort_name    TEXT NOT NULL,
        album_count  INTEGER NOT NULL DEFAULT 0,
        art_id       TEXT,
        updated_at   REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS albums (
        id                TEXT PRIMARY KEY,
        name              TEXT NOT NULL,
        sort_name         TEXT NOT NULL,
        artist_id         TEXT NOT NULL,
        year              INTEGER,
        genre             TEXT,
        song_count        INTEGER NOT NULL DEFAULT 0,
        duration_s        INTEGER NOT NULL DEFAULT 0,
        art_id            TEXT,
        is_compilation    INTEGER NOT NULL DEFAULT 0,
        navidrome_starred INTEGER NOT NULL DEFAULT 0,
        updated_at        REAL NOT NULL,
        FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_albums_artist ON albums(artist_id);

    CREATE TABLE IF NOT EXISTS tracks (
        id                TEXT PRIMARY KEY,
        album_id          TEXT NOT NULL,
        title             TEXT NOT NULL,
        track_no          INTEGER,
        disc_no           INTEGER,
        duration_s        INTEGER NOT NULL DEFAULT 0,
        suffix            TEXT NOT NULL DEFAULT '',
        size_bytes        INTEGER NOT NULL DEFAULT 0,
        content_type      TEXT NOT NULL DEFAULT '',
        navidrome_starred INTEGER NOT NULL DEFAULT 0,
        updated_at        REAL NOT NULL,
        FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_id);

    CREATE TABLE IF NOT EXISTS playlists (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        song_count  INTEGER NOT NULL DEFAULT 0,
        owner       TEXT NOT NULL DEFAULT '',
        public      INTEGER NOT NULL DEFAULT 0,
        updated_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS playlist_tracks (
        playlist_id TEXT NOT NULL,
        track_id    TEXT NOT NULL,
        position    INTEGER NOT NULL,
        PRIMARY KEY (playlist_id, position),
        FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);

    CREATE TABLE IF NOT EXISTS pins (
        target_kind TEXT NOT NULL,
        target_id   TEXT NOT NULL,
        source      TEXT NOT NULL,
        added_at    REAL NOT NULL,
        PRIMARY KEY (target_kind, target_id)
    );

    CREATE TABLE IF NOT EXISTS cache_state (
        track_id       TEXT PRIMARY KEY,
        status         TEXT NOT NULL,
        local_path     TEXT,
        size_bytes     INTEGER,
        downloaded_at  REAL,
        error_message  TEXT
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
        content_type, id UNINDEXED, title, body
    );
    """,
]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any missing schema migrations. Idempotent."""
    current = 0
    try:
        row = conn.execute("SELECT version FROM _schema_version").fetchone()
        if row:
            current = row[0]
    except sqlite3.OperationalError:
        current = 0

    for i, ddl in enumerate(_MIGRATIONS, start=1):
        if i <= current:
            continue
        log.info("applying schema migration %d", i)
        conn.executescript(ddl)
        conn.execute("DELETE FROM _schema_version")
        conn.execute("INSERT INTO _schema_version(version) VALUES (?)", (i,))
