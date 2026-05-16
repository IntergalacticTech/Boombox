"""Tests for boombox_library.catalog — full + delta sync."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

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
