"""SQLite connection + schema migrations for boombox-library.

The catalog DB lives at /opt/boombox/state/library.db on production;
tests use tempdirs. FTS5 is built-in to SQLite (>= 3.9 with extension);
we rely on the system sqlite shipped with Python 3.11+ on Debian/Ubuntu.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("boombox-library.db")

SCHEMA_VERSION = 3


def fts_rowid(content_type: str, id_: str) -> int:
    """Stable, positive 63-bit rowid for a search_index row.

    FTS5 cannot index a plain column predicate, so
    `DELETE FROM search_index WHERE content_type=? AND id=?` is a full
    scan of the whole index — and sync_full ran one per artist and per
    album, every hour: O(rows²), minutes of a pinned core on the Pi (and
    the thermal/undervoltage spiral that goes with it). Keying rows by a
    rowid derived from (type, id) makes the delete an O(log n) lookup.
    """
    digest = hashlib.blake2b(f"{content_type}:{id_}".encode(), digest_size=8).digest()
    return (int.from_bytes(digest, "big") & 0x7FFF_FFFF_FFFF_FFFF) or 1


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
    # sync_full holds a single multi-minute write transaction; if any other
    # service (boombox-rfid) is also writing the DB, wait up to 10 s before
    # giving up rather than racing the long sync.
    conn.execute("PRAGMA busy_timeout = 10000")
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
    # v2 — sort_name indexes. /api/library/browse orders by sort_name on
    # ~8.7 k albums; without the index this is a full table scan + in-memory
    # sort on every browse. Indexed it's an index-ordered range scan.
    """
    CREATE INDEX IF NOT EXISTS idx_albums_sort_name ON albums(sort_name);
    CREATE INDEX IF NOT EXISTS idx_artists_sort_name ON artists(sort_name);
    """,
    # v3 — search_index rows are re-keyed to fts_rowid(content_type, id).
    # No DDL; the data rewrite lives in _rebuild_search_index_rowids below
    # because the rowid is computed in Python.
    "SELECT 1;",
]


def _rebuild_search_index_rowids(conn: sqlite3.Connection) -> None:
    """One-off for v3: rewrite every FTS row under its stable rowid.

    ~100 k rows on a full catalog; a few seconds once, versus minutes on
    every hourly sync before this."""
    rows = conn.execute(
        "SELECT content_type, id, title, body FROM search_index").fetchall()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM search_index")
        conn.executemany(
            "INSERT INTO search_index(rowid, content_type, id, title, body) "
            "VALUES (?,?,?,?,?)",
            [(fts_rowid(r[0], r[1]), r[0], r[1], r[2], r[3]) for r in rows],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    log.info("search_index re-keyed: %d rows", len(rows))


# Python-side data migrations that run right after the DDL of the same version.
_POST_MIGRATE = {3: _rebuild_search_index_rowids}


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
        hook = _POST_MIGRATE.get(i)
        if hook:
            hook(conn)
        conn.execute("DELETE FROM _schema_version")
        conn.execute("INSERT INTO _schema_version(version) VALUES (?)", (i,))
