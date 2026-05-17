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

log = logging.getLogger("boombox-library.catalog")

_ALBUM_PAGE_SIZE = 500


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
    # FTS index for artist
    conn.execute("DELETE FROM search_index WHERE content_type='artist' AND id=?",
                 (a["id"],))
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("artist", a["id"], a["name"], a["name"]),
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
    conn.execute("DELETE FROM search_index WHERE content_type='album' AND id=?",
                 (al["id"],))
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("album", al["id"], al.get("name", ""), body),
    )


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
    conn.execute("DELETE FROM search_index WHERE content_type='track' AND id=?",
                 (tr["id"],))
    conn.execute(
        "INSERT INTO search_index(content_type, id, title, body) VALUES (?,?,?,?)",
        ("track", tr["id"], tr.get("title", ""), tr.get("title", "")),
    )


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


def _chunk_commit(conn: Connection, counter: int) -> int:
    """Commit + reopen the txn every _TXN_CHUNK items. Returns counter+1."""
    counter += 1
    if counter % _TXN_CHUNK == 0:
        conn.execute("COMMIT")
        conn.execute("BEGIN")
    return counter


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

    # Artists: HTTP first, then a single short transaction.
    artists = await client.get_artists()
    conn.execute("BEGIN")
    try:
        for a in artists:
            _upsert_artist(conn, a, now)
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except Exception: pass
        raise

    # Albums: each HTTP page → one short txn.
    offset = 0
    album_count = 0
    all_album_ids: list[str] = []
    while True:
        page = await client.get_album_list(offset=offset, size=_ALBUM_PAGE_SIZE)
        if not page:
            break
        conn.execute("BEGIN")
        try:
            for al in page:
                _upsert_album(conn, al, now, starred_album_ids)
                all_album_ids.append(al["id"])
            conn.execute("COMMIT")
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise
        album_count += len(page)
        if len(page) < _ALBUM_PAGE_SIZE:
            break
        offset += _ALBUM_PAGE_SIZE

    # Tracks: one HTTP call per album → one short txn per album.
    # Bumped from sleep(0) to a tiny non-zero sleep so the kernel actually
    # schedules other processes (notably boombox-rfid bind INSERTs). At
    # sleep(0) the asyncio loop yielded but the writer lock got reacquired
    # so fast on the next iteration that rfid still starved out its
    # 10 s busy_timeout — caught when a card bind took 9 s on the kiosk.
    track_count = 0
    for aid in all_album_ids:
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
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise

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

    log.info("sync_full done: %d artists, %d albums, %d tracks, %d playlists",
             len(artists), album_count, track_count, len(playlists))
    return {"artists": len(artists), "albums": album_count,
            "tracks": track_count, "playlists": len(playlists)}
