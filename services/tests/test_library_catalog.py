"""Tests for boombox_library.catalog — full + delta sync."""
from __future__ import annotations

from pathlib import Path

import pytest
from boombox_library.catalog import sync_full
from boombox_library.db import connect, migrate


class FakeSubsonic:
    def __init__(self, artists, albums, tracks_per_album, starred=None, playlists=None):
        self._artists = artists
        self._albums = albums
        self._tracks = tracks_per_album  # {album_id: [track,...]}
        self._starred = starred or {"album": [], "song": [], "artist": []}
        self._playlists = playlists or []
        self._playlist_details = {}  # {playlist_id: {"id": ..., "entry": [...]}}

    async def get_artists(self):
        return self._artists

    async def get_album_list(self, offset=0, size=500):
        return self._albums[offset:offset + size]

    async def get_album(self, album_id):
        tracks = self._tracks.get(album_id, [])
        return {"id": album_id, "song": tracks}

    async def get_starred(self):
        return self._starred

    async def get_playlists(self):
        return self._playlists

    async def get_playlist(self, playlist_id):
        return self._playlist_details.get(playlist_id, {"id": playlist_id, "entry": []})


@pytest.mark.asyncio
async def test_sync_full_populates_catalog(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "ABBA", "albumCount": 1}],
        albums=[{"id": "al1", "name": "Arrival",
                 "artistId": "ar1", "year": 1976,
                 "songCount": 2, "duration": 100, "isCompilation": False}],
        tracks_per_album={"al1": [
            {"id": "t1", "title": "Dancing Queen", "track": 1,
             "duration": 60, "suffix": "mp3", "size": 1_000_000,
             "contentType": "audio/mpeg"},
            {"id": "t2", "title": "Money Money Money", "track": 2,
             "duration": 40, "suffix": "mp3", "size": 700_000,
             "contentType": "audio/mpeg"},
        ]},
    )
    await sync_full(client, db)

    assert db.execute("SELECT COUNT(*) FROM artists").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 2

    # FTS5 should also be populated
    rows = list(db.execute(
        "SELECT id FROM search_index WHERE search_index MATCH 'abba'"
    ))
    assert any(r[0] == "ar1" for r in rows)


@pytest.mark.asyncio
async def test_sync_full_idempotent(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 0}],
        albums=[],
        tracks_per_album={},
    )
    await sync_full(client, db)
    await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM artists").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_sync_full_marks_starred(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 1}],
        albums=[{"id": "al1", "name": "A", "artistId": "ar1",
                 "songCount": 1, "duration": 30}],
        tracks_per_album={"al1": [
            {"id": "t1", "title": "T", "duration": 30, "suffix": "mp3",
             "size": 100, "contentType": "audio/mpeg"},
        ]},
        starred={"album": [{"id": "al1"}], "song": [{"id": "t1"}], "artist": []},
    )
    await sync_full(client, db)
    starred_album = db.execute(
        "SELECT navidrome_starred FROM albums WHERE id='al1'"
    ).fetchone()[0]
    starred_track = db.execute(
        "SELECT navidrome_starred FROM tracks WHERE id='t1'"
    ).fetchone()[0]
    assert starred_album == 1
    assert starred_track == 1


@pytest.mark.asyncio
async def test_sync_full_skips_unchanged_albums_on_resync(tmp_path: Path):
    """Steady-state sync: when track counts already match, get_album is
    NOT called. This is the per-album HTTP fan-out that dominated the
    previous ~10 min full-sync wall clock."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 1}],
        albums=[{"id": "al1", "name": "A", "artistId": "ar1",
                 "songCount": 1, "duration": 30}],
        tracks_per_album={"al1": [
            {"id": "t1", "title": "T", "duration": 30, "suffix": "mp3",
             "size": 100, "contentType": "audio/mpeg"},
        ]},
    )

    # Wrap get_album so we can count calls without losing behaviour.
    real_get_album = client.get_album
    calls: list[str] = []
    async def counting_get_album(aid):
        calls.append(aid)
        return await real_get_album(aid)
    client.get_album = counting_get_album

    await sync_full(client, db)
    first_call_count = len(calls)
    assert first_call_count == 1  # first sync fetches the album detail
    calls.clear()

    # Second sync: the album hasn't changed; no detail fetch should fire.
    result = await sync_full(client, db)
    assert calls == []
    assert result.get("albums_fetched") == 0


@pytest.mark.asyncio
async def test_sync_full_refetches_when_song_count_changes(tmp_path: Path):
    """If Navidrome reports a different songCount, the per-album HTTP
    call is re-issued — picks up retags / new track uploads."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 1}],
        albums=[{"id": "al1", "name": "A", "artistId": "ar1",
                 "songCount": 1, "duration": 30}],
        tracks_per_album={"al1": [
            {"id": "t1", "title": "T", "duration": 30, "suffix": "mp3",
             "size": 100, "contentType": "audio/mpeg"},
        ]},
    )
    await sync_full(client, db)

    # Album grew from 1 → 2 tracks upstream.
    client._albums[0]["songCount"] = 2
    client._tracks["al1"].append({
        "id": "t2", "title": "T2", "duration": 30, "suffix": "mp3",
        "size": 100, "contentType": "audio/mpeg",
    })
    result = await sync_full(client, db)
    assert result.get("albums_fetched") == 1
    assert db.execute("SELECT COUNT(*) FROM tracks WHERE album_id='al1'").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_sync_full_reaps_removed_albums(tmp_path: Path):
    """An album removed from Navidrome between syncs is deleted locally
    (tracks cascade via the FK), so the UI doesn't show orphans."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 2}],
        albums=[
            {"id": "al1", "name": "A1", "artistId": "ar1",
             "songCount": 1, "duration": 30},
            {"id": "al2", "name": "A2", "artistId": "ar1",
             "songCount": 1, "duration": 30},
        ],
        tracks_per_album={
            "al1": [{"id": "t1", "title": "T1", "duration": 30,
                     "suffix": "mp3", "size": 1, "contentType": "audio/mpeg"}],
            "al2": [{"id": "t2", "title": "T2", "duration": 30,
                     "suffix": "mp3", "size": 1, "contentType": "audio/mpeg"}],
        },
    )
    await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 2

    # Drop al2 upstream.
    client._albums = [client._albums[0]]
    await sync_full(client, db)
    rows = [r["id"] for r in db.execute("SELECT id FROM albums")]
    assert rows == ["al1"]
    # Tracks cascaded.
    assert db.execute("SELECT COUNT(*) FROM tracks WHERE album_id='al2'").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_sync_full_populates_playlist_tracks(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    # Subsonic returns tracks under "entry" key in getPlaylist response
    client = FakeSubsonic(
        artists=[{"id": "ar", "name": "X", "albumCount": 1}],
        albums=[{"id": "al", "name": "A", "artistId": "ar",
                 "songCount": 2, "duration": 100}],
        tracks_per_album={"al": [
            {"id": "t1", "title": "T1", "duration": 30, "suffix": "mp3",
             "size": 100, "contentType": "audio/mpeg"},
            {"id": "t2", "title": "T2", "duration": 30, "suffix": "mp3",
             "size": 100, "contentType": "audio/mpeg"},
        ]},
        playlists=[{"id": "pl1", "name": "My Mix", "songCount": 2}],
    )
    # Extend FakeSubsonic for this test — add a get_playlist method
    async def get_playlist(playlist_id):
        return {"id": "pl1", "entry": [{"id": "t1"}, {"id": "t2"}]}
    client.get_playlist = get_playlist
    await sync_full(client, db)
    rows = list(db.execute(
        "SELECT track_id, position FROM playlist_tracks WHERE playlist_id='pl1' ORDER BY position"))
    assert len(rows) == 2
    assert rows[0]["track_id"] == "t1" and rows[0]["position"] == 0
    assert rows[1]["track_id"] == "t2" and rows[1]["position"] == 1
