"""Catalog sync — pull Navidrome's Subsonic state into the local SQLite
cache. Full sync iterates the catalog from scratch (used on first boot
or after corruption recovery). Incremental sync (Task 7) is the steady
state.

Sync is upsert-based and keeps the FTS5 search index in lockstep.
"""
from __future__ import annotations

import asyncio
import logging
import time
from sqlite3 import Connection
from typing import Protocol

from .db import fts_rowid

log = logging.getLogger("boombox-library.catalog")

_ALBUM_PAGE_SIZE = 500

# Prune guard. A sync that would reap more than this fraction of the local
# albums AND more than this many albums is treated as suspect (a truncated
# album listing from a flaky remote, a Navidrome rescan in progress, a
# library folder temporarily unmounted on the server) and skipped for the
# round — the next healthy sync prunes normally. Small deltas always prune.
PRUNE_MAX_FRACTION = 0.10
PRUNE_MIN_ALBUMS = 50


class SubsonicProto(Protocol):
    async def get_artists(self) -> list[dict]: ...
    async def get_album_list(self, offset: int = 0, size: int = 500) -> list[dict]: ...
    async def get_album(self, album_id: str) -> dict: ...
    async def get_starred(self) -> dict: ...
    async def get_playlists(self) -> list[dict]: ...
    async def get_playlist(self, playlist_id: str) -> dict: ...


def _upsert_artist(conn: Connection, a: dict, now: float) -> None:
    conn.execute(
        """INSERT INTO artists(id, name, sort_name, album_count, art_id, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name,
             sort_name=excluded.sort_name,
             album_count=excluded.album_count,
             art_id=excluded.art_id,
             updated_at=excluded.updated_at""",
        (a["id"], a["name"], a.get("sortName", a["name"]).lower(),
         int(a.get("albumCount", 0)), a.get("coverArt"), now),
    )
    _reindex(conn, "artist", a["id"], a["name"], a["name"])


def _reindex(conn: Connection, content_type: str, id_: str,
             title: str, body: str) -> None:
    """Replace one search_index row. Keyed by fts_rowid so the delete is an
    O(log n) rowid lookup — the column-predicate form was a full FTS scan
    per row (see db.fts_rowid)."""
    rid = fts_rowid(content_type, id_)
    conn.execute("DELETE FROM search_index WHERE rowid=?", (rid,))
    conn.execute(
        "INSERT INTO search_index(rowid, content_type, id, title, body) "
        "VALUES (?,?,?,?,?)",
        (rid, content_type, id_, title, body),
    )


def _upsert_album(conn: Connection, al: dict, now: float, starred_ids: set[str]) -> None:
    conn.execute(
        """INSERT INTO albums(id, name, sort_name, artist_id, year, genre,
                              song_count, duration_s, art_id,
                              is_compilation, navidrome_starred, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name,
             sort_name=excluded.sort_name,
             artist_id=excluded.artist_id,
             year=excluded.year,
             genre=excluded.genre,
             song_count=excluded.song_count,
             duration_s=excluded.duration_s,
             art_id=excluded.art_id,
             is_compilation=excluded.is_compilation,
             navidrome_starred=excluded.navidrome_starred,
             updated_at=excluded.updated_at""",
        (al["id"], al.get("name", ""),
         al.get("sortName", al.get("name", "")).lower(),
         al.get("artistId", ""), al.get("year"), al.get("genre"),
         int(al.get("songCount", 0)), int(al.get("duration", 0)),
         al.get("coverArt"), 1 if al.get("isCompilation") else 0,
         1 if al["id"] in starred_ids else 0, now),
    )
    body = " ".join(filter(None, [al.get("name"), al.get("artist"),
                                   str(al.get("year") or ""), al.get("genre")]))
    _reindex(conn, "album", al["id"], al.get("name", ""), body)


def _upsert_track(conn: Connection, tr: dict, album_id: str, now: float,
                  starred_ids: set[str]) -> None:
    conn.execute(
        """INSERT INTO tracks(id, album_id, title, track_no, disc_no,
                              duration_s, suffix, size_bytes, content_type,
                              navidrome_starred, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             album_id=excluded.album_id,
             title=excluded.title,
             track_no=excluded.track_no,
             disc_no=excluded.disc_no,
             duration_s=excluded.duration_s,
             suffix=excluded.suffix,
             size_bytes=excluded.size_bytes,
             content_type=excluded.content_type,
             navidrome_starred=excluded.navidrome_starred,
             updated_at=excluded.updated_at""",
        (tr["id"], album_id, tr.get("title", ""),
         tr.get("track"), tr.get("discNumber"),
         int(tr.get("duration", 0)), tr.get("suffix", ""),
         int(tr.get("size", 0)), tr.get("contentType", ""),
         1 if tr["id"] in starred_ids else 0, now),
    )
    _reindex(conn, "track", tr["id"], tr.get("title", ""), tr.get("title", ""))


def refresh_starred(conn: Connection, album_ids: set[str],
                    song_ids: set[str]) -> None:
    """Rewrite navidrome_starred on every album + track from getStarred2.

    The album/track upserts only run for albums whose track count changed,
    so without this a star/unstar in Navidrome would never reach the local
    flags (and starred_auto_pin would act on stale data). Only rows whose
    flag actually differs are touched, so a steady-state sync writes
    nothing. One short transaction; no awaits inside.
    """
    conn.execute("BEGIN")
    try:
        for table, ids in (("albums", album_ids), ("tracks", song_ids)):
            tmp = f"_starred_{table}"
            conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {tmp} "
                         "(id TEXT PRIMARY KEY)")
            conn.execute(f"DELETE FROM {tmp}")
            conn.executemany(f"INSERT OR IGNORE INTO {tmp}(id) VALUES (?)",
                             ((i,) for i in ids))
            conn.execute(
                f"UPDATE {table} SET navidrome_starred=1 "
                f"WHERE navidrome_starred=0 AND id IN (SELECT id FROM {tmp})")
            conn.execute(
                f"UPDATE {table} SET navidrome_starred=0 "
                f"WHERE navidrome_starred=1 AND id NOT IN (SELECT id FROM {tmp})")
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except Exception: pass
        raise


def _prune_is_safe(existing: int, removing: int) -> bool:
    """False when a prune looks like a truncated listing, not real deletes."""
    if removing <= PRUNE_MIN_ALBUMS:
        return True
    return removing <= existing * PRUNE_MAX_FRACTION


def _upsert_playlist(conn: Connection, pl: dict, now: float) -> None:
    conn.execute(
        """INSERT INTO playlists(id, name, song_count, owner, public, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name,
             song_count=excluded.song_count,
             owner=excluded.owner,
             public=excluded.public,
             updated_at=excluded.updated_at""",
        (pl["id"], pl.get("name", ""), int(pl.get("songCount", 0)),
         pl.get("owner", ""), 1 if pl.get("public") else 0, now),
    )


_TXN_CHUNK = 100  # commit every N items so other writers (boombox-rfid) aren't starved


async def _write_chunked(conn: Connection, items, write) -> None:
    """Apply `write(item)` to every item in transactions of _TXN_CHUNK rows,
    yielding to the event loop after each commit so API handlers (and other
    SQLite writers) get a turn. A tiny non-zero sleep for the same reason as
    the track loop below: sleep(0) re-takes the write lock too fast."""
    for start in range(0, len(items), _TXN_CHUNK):
        conn.execute("BEGIN")
        try:
            for item in items[start:start + _TXN_CHUNK]:
                write(item)
            conn.execute("COMMIT")
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise
        await asyncio.sleep(0.005)


async def sync_full(client: SubsonicProto, conn: Connection) -> dict:
    """Full sync — pulls all artists/albums/tracks/playlists from Navidrome.
    Returns counts dict. Idempotent (upserts).

    Critical: every BEGIN/COMMIT brackets ONLY local SQLite work; never
    holds the write lock across an `await` on the Subsonic HTTP client.
    Otherwise concurrent writers like boombox-rfid would have to wait the
    full sync duration (~30 min on a cold boot) for the lock to free.
    """
    now = time.time()
    starred = await client.get_starred()
    starred_album_ids = {a["id"] for a in starred.get("album", [])}
    starred_song_ids = {s["id"] for s in starred.get("song", [])}

    # Artists: HTTP first, then short transactions of _TXN_CHUNK rows with a
    # yield between them — the whole write phase used to run as one block on
    # the event loop, so the HTTP API stopped answering for its duration.
    artists = await client.get_artists()
    await _write_chunked(conn, artists, lambda a: _upsert_artist(conn, a, now))

    # Albums: each HTTP page → one short txn. We capture each album's
    # expected songCount so the next loop can skip the per-album HTTP
    # call when our local track count already matches.
    offset = 0
    album_count = 0
    all_albums_seen: list[tuple[str, int]] = []
    while True:
        page = await client.get_album_list(offset=offset, size=_ALBUM_PAGE_SIZE)
        if not page:
            break
        await _write_chunked(
            conn, page, lambda al: _upsert_album(conn, al, now, starred_album_ids))
        all_albums_seen.extend(
            (al["id"], int(al.get("songCount", 0))) for al in page)
        album_count += len(page)
        if len(page) < _ALBUM_PAGE_SIZE:
            break
        offset += _ALBUM_PAGE_SIZE

    # Tracks: one HTTP call per album → one short txn per album.
    # Skip the call when our existing track count for that album_id
    # already matches what getAlbumList2 reports. This is the steady-state
    # optimisation — on a hourly sync of an unchanged catalog, every
    # album short-circuits and we issue zero getAlbum requests. Only
    # albums whose song count drifted (new uploads, retag) — or are
    # entirely new — get the expensive detail fetch.
    #
    # Bumped from sleep(0) to a tiny non-zero sleep so the kernel actually
    # schedules other processes (notably boombox-rfid bind INSERTs). At
    # sleep(0) the asyncio loop yielded but the writer lock got reacquired
    # so fast on the next iteration that rfid still starved out its
    # 10 s busy_timeout — caught when a card bind took 9 s on the kiosk.
    existing_track_counts: dict[str, int] = {
        row[0]: row[1] for row in conn.execute(
            "SELECT album_id, COUNT(*) FROM tracks GROUP BY album_id"
        )
    }
    track_count = 0
    fetched_albums = 0
    for aid, expected in all_albums_seen:
        have = existing_track_counts.get(aid, 0)
        if expected > 0 and have == expected:
            track_count += have
            continue
        await asyncio.sleep(0.005)
        detail = await client.get_album(aid)
        songs = detail.get("song", [])
        if not songs:
            continue
        conn.execute("BEGIN")
        try:
            for tr in songs:
                _upsert_track(conn, tr, aid, now, starred_song_ids)
                track_count += 1
            conn.execute("COMMIT")
            fetched_albums += 1
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise

    # Starred flags: the per-album upserts above skip unchanged albums, so
    # re-derive every flag from the getStarred2 result fetched up front.
    refresh_starred(conn, starred_album_ids, starred_song_ids)

    # Playlists: HTTP then short txn.
    playlists = await client.get_playlists()
    conn.execute("BEGIN")
    try:
        for pl in playlists:
            _upsert_playlist(conn, pl, now)
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except Exception: pass
        raise

    # Playlist members: each playlist gets its own HTTP + txn pair.
    for pl in playlists:
        detail = await client.get_playlist(pl["id"])
        songs = detail.get("entry", []) or detail.get("song", [])
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=?",
                         (pl["id"],))
            for i, song in enumerate(songs):
                conn.execute(
                    """INSERT INTO playlist_tracks(playlist_id, track_id, position)
                       VALUES (?, ?, ?)""",
                    (pl["id"], song["id"], i),
                )
            conn.execute("COMMIT")
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise

    # Reap albums that disappeared from Navidrome since the last sync.
    # Tracks cascade via the FK. Only run after we've walked the full
    # source-of-truth list — if the walk above raised, the whole
    # sync_full caller catches it and we never reach here, so a partial
    # walk can never drive a destructive delete. A listing that completed
    # but came back suspiciously short is caught by _prune_is_safe.
    seen_album_ids = {aid for aid, _ in all_albums_seen}
    if seen_album_ids:
        conn.execute("BEGIN")
        try:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _seen_albums "
                         "(id TEXT PRIMARY KEY)")
            conn.execute("DELETE FROM _seen_albums")
            conn.executemany("INSERT INTO _seen_albums(id) VALUES (?)",
                             ((aid,) for aid in seen_album_ids))
            existing = conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
            removing = conn.execute(
                "SELECT COUNT(*) FROM albums "
                "WHERE id NOT IN (SELECT id FROM _seen_albums)"
            ).fetchone()[0]
            removed = 0
            if removing and not _prune_is_safe(existing, removing):
                log.warning(
                    "sync_full: refusing to prune %d of %d albums (> %d%% and "
                    "> %d) — listing looks truncated; skipping prune this round",
                    removing, existing, int(PRUNE_MAX_FRACTION * 100),
                    PRUNE_MIN_ALBUMS)
            elif removing:
                cursor = conn.execute(
                    "DELETE FROM albums WHERE id NOT IN (SELECT id FROM _seen_albums)"
                )
                removed = cursor.rowcount or 0
            conn.execute("COMMIT")
            if removed:
                log.info("sync_full reaped %d removed albums", removed)
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise

    log.info("sync_full done: %d artists, %d albums (%d fetched, %d skipped), "
             "%d tracks, %d playlists",
             len(artists), album_count, fetched_albums,
             album_count - fetched_albums, track_count, len(playlists))
    return {"artists": len(artists), "albums": album_count,
            "tracks": track_count, "playlists": len(playlists),
            "albums_fetched": fetched_albums}
