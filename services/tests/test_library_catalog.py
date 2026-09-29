"""Tests for boombox_library.catalog — full + delta sync."""
from __future__ import annotations

from pathlib import Path

import pytest
from boombox_library import catalog
from boombox_library.catalog import (
    prune_deferred_status,
    request_forced_prune,
    sync_full,
)
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


@pytest.mark.asyncio
async def test_resync_keeps_exactly_one_search_row_per_item(tmp_path: Path):
    """Each hourly sync re-upserts every artist/album; the FTS row must be
    replaced in place (keyed by rowid), never duplicated, and the old
    title must stop matching once it changes."""
    from boombox_library.db import fts_rowid
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums = [{"id": "al1", "name": "Old Name", "artistId": "ar1", "songCount": 1}]
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "Artist", "albumCount": 1}],
        albums=albums,
        tracks_per_album={"al1": [{"id": "tr1", "title": "Song"}]},
    )
    await sync_full(client, db)
    albums[0]["name"] = "New Name"
    await sync_full(client, db)
    await sync_full(client, db)

    assert db.execute("SELECT COUNT(*) FROM search_index").fetchone()[0] == 3
    assert db.execute("SELECT rowid FROM search_index WHERE id='al1'").fetchone()[0] \
        == fts_rowid("album", "al1")
    assert db.execute(
        "SELECT COUNT(*) FROM search_index WHERE search_index MATCH 'old'").fetchone()[0] == 0
    assert db.execute(
        "SELECT id FROM search_index WHERE search_index MATCH 'new'").fetchone()[0] == "al1"


@pytest.mark.asyncio
async def test_sync_full_yields_to_the_loop_during_album_pages(tmp_path: Path):
    """A 500-album page must not run as one uninterrupted block: another
    task on the loop has to get scheduled while the page is being written."""
    import asyncio
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums = [{"id": f"al{i}", "name": f"Album {i}", "artistId": "ar1", "songCount": 1}
              for i in range(500)]
    client = FakeSubsonic(
        artists=[{"id": f"ar{i}", "name": f"Artist {i}", "albumCount": 1} for i in range(300)],
        albums=albums,
        tracks_per_album={f"al{i}": [{"id": f"tr{i}", "title": f"Song {i}"}] for i in range(500)},
    )
    await sync_full(client, db)   # cold sync fetches every album (yields per fetch)
    # Steady state: every album short-circuits on track count, so the only
    # yields left are the ones the artist/album write loops make themselves.
    ticks = 0
    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)
    t = asyncio.create_task(ticker())
    before = ticks
    await sync_full(client, db)
    t.cancel()
    # Artists (300) + albums (500) = at least 8 chunk boundaries of 100.
    assert ticks - before >= 8


# ---- prune guard ----

def _many_albums(n: int) -> tuple[list[dict], dict]:
    albums = [{"id": f"al{i}", "name": f"A{i}", "artistId": "ar1",
               "songCount": 1, "duration": 30} for i in range(n)]
    tracks = {f"al{i}": [{"id": f"t{i}", "title": f"T{i}", "duration": 30,
                          "suffix": "mp3", "size": 1,
                          "contentType": "audio/mpeg"}]
              for i in range(n)}
    return albums, tracks


@pytest.mark.asyncio
async def test_sync_full_refuses_mass_prune(tmp_path: Path, caplog):
    """A truncated listing (flaky remote, server rescan) that would reap
    >10% AND >50 albums is skipped with a WARNING — nothing is deleted."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums, tracks = _many_albums(200)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 200}],
        albums=albums, tracks_per_album=tracks,
    )
    await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 200

    client._albums = albums[:100]  # half the catalog vanishes
    with caplog.at_level("WARNING", logger="boombox-library.catalog"):
        await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 200
    assert db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 200
    assert any("refusing to prune" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_sync_full_prunes_large_fraction_when_under_absolute_floor(tmp_path: Path):
    """A big fraction of a small library (<= 50 albums) still prunes."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums, tracks = _many_albums(60)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 60}],
        albums=albums, tracks_per_album=tracks,
    )
    await sync_full(client, db)
    client._albums = albums[:20]  # 40 removed: 66% but only 40 albums
    await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 20


@pytest.mark.asyncio
async def test_sync_full_prunes_many_albums_under_fraction(tmp_path: Path):
    """>50 removed but <=10% of the library is a real delete — prune."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums, tracks = _many_albums(1000)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 1000}],
        albums=albums, tracks_per_album=tracks,
    )
    await sync_full(client, db)
    client._albums = albums[:920]  # 80 removed = 8%
    await sync_full(client, db)
    assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 920


def _albums_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM albums").fetchone()[0]


async def _seed_200(tmp_path: Path):
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums, tracks = _many_albums(200)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 200}],
        albums=albums, tracks_per_album=tracks,
    )
    await sync_full(client, db)
    return db, client, albums


@pytest.mark.asyncio
async def test_persistent_mass_removal_is_eventually_pruned(tmp_path: Path, monkeypatch):
    """The guard is a hold-off, not a permanent block: the same albums
    missing on 3 consecutive syncs spanning >= 30 min are a real delete."""
    db, client, albums = await _seed_200(tmp_path)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(catalog.time, "time", lambda: clock["t"])
    client._albums = albums[:100]

    await sync_full(client, db)  # round 1: deferred
    assert _albums_count(db) == 200
    st = prune_deferred_status(db)
    assert st is not None and st["albums"] == 100 and st["rounds"] == 1

    clock["t"] += 3600
    await sync_full(client, db)  # round 2: deferred
    assert _albums_count(db) == 200
    assert prune_deferred_status(db)["rounds"] == 2

    clock["t"] += 3600
    await sync_full(client, db)  # round 3: confirmed
    assert _albums_count(db) == 100
    assert db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 100
    assert prune_deferred_status(db) is None


@pytest.mark.asyncio
async def test_rapid_resyncs_do_not_confirm_a_mass_prune(tmp_path: Path, monkeypatch):
    """Three back-to-back "Sync now" taps during a server rescan must not
    count as confirmation — the rounds also need to span 30 min."""
    db, client, albums = await _seed_200(tmp_path)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(catalog.time, "time", lambda: clock["t"])
    client._albums = albums[:100]
    for _ in range(4):
        clock["t"] += 60
        await sync_full(client, db)
    assert _albums_count(db) == 200
    clock["t"] += 1800
    await sync_full(client, db)
    assert _albums_count(db) == 100


@pytest.mark.asyncio
async def test_prune_hold_off_restarts_when_missing_set_changes(tmp_path: Path, monkeypatch):
    db, client, albums = await _seed_200(tmp_path)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(catalog.time, "time", lambda: clock["t"])
    client._albums = albums[:100]
    await sync_full(client, db)
    clock["t"] += 3600
    await sync_full(client, db)
    assert prune_deferred_status(db)["rounds"] == 2
    client._albums = albums[:90]  # a different shortfall: not the same event
    clock["t"] += 3600
    await sync_full(client, db)
    assert _albums_count(db) == 200
    assert prune_deferred_status(db)["rounds"] == 1


@pytest.mark.asyncio
async def test_healthy_listing_clears_deferred_prune(tmp_path: Path):
    """A temporary truncation that recovers leaves no pending state."""
    db, client, albums = await _seed_200(tmp_path)
    client._albums = albums[:100]
    await sync_full(client, db)
    assert prune_deferred_status(db) is not None
    client._albums = albums
    await sync_full(client, db)
    assert prune_deferred_status(db) is None
    assert _albums_count(db) == 200


@pytest.mark.asyncio
async def test_forced_prune_is_one_shot(tmp_path: Path):
    db, client, albums = await _seed_200(tmp_path)
    request_forced_prune(db)
    client._albums = albums[:100]
    await sync_full(client, db)
    assert _albums_count(db) == 100
    assert prune_deferred_status(db) is None
    # Consumed: the next mass shortfall is guarded again.
    client._albums = albums[:10]
    await sync_full(client, db)
    assert _albums_count(db) == 100


# ---- starred refresh ----

@pytest.mark.asyncio
async def test_sync_full_picks_up_star_and_unstar_on_unchanged_albums(tmp_path: Path):
    """Albums whose track count didn't change skip the upsert path; the
    starred flags must still follow getStarred2 every sync."""
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums, tracks = _many_albums(3)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 3}],
        albums=albums, tracks_per_album=tracks,
        starred={"album": [{"id": "al0"}], "song": [{"id": "t0"}], "artist": []},
    )
    await sync_full(client, db)

    def starred(table):
        return {r[0] for r in db.execute(
            f"SELECT id FROM {table} WHERE navidrome_starred=1")}

    assert starred("albums") == {"al0"}
    assert starred("tracks") == {"t0"}

    # Star al1/t2, unstar al0/t0 upstream — no track-count change anywhere.
    client._starred = {"album": [{"id": "al1"}], "song": [{"id": "t2"}],
                       "artist": []}
    await sync_full(client, db)
    assert starred("albums") == {"al1"}
    assert starred("tracks") == {"t2"}

    # Everything unstarred.
    client._starred = {"album": [], "song": [], "artist": []}
    await sync_full(client, db)
    assert starred("albums") == set()
    assert starred("tracks") == set()


@pytest.mark.asyncio
async def test_starred_refresh_feeds_reconcile_starred(tmp_path: Path):
    """End to end: unstar upstream → starred-source pin is removed."""
    from boombox_library.pins import reconcile_starred
    db = connect(tmp_path / "library.db")
    migrate(db)
    albums, tracks = _many_albums(2)
    client = FakeSubsonic(
        artists=[{"id": "ar1", "name": "X", "albumCount": 2}],
        albums=albums, tracks_per_album=tracks,
        starred={"album": [{"id": "al1"}], "song": [], "artist": []},
    )
    await sync_full(client, db)
    reconcile_starred(db)
    assert db.execute("SELECT COUNT(*) FROM pins WHERE source='starred'").fetchone()[0] == 1

    client._starred = {"album": [], "song": [], "artist": []}
    await sync_full(client, db)
    reconcile_starred(db)
    assert db.execute("SELECT COUNT(*) FROM pins WHERE source='starred'").fetchone()[0] == 0
