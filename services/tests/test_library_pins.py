"""Tests for boombox_library.pins — pin/unpin, cascade, reconciliation, sidecar."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from boombox_library.db import connect, migrate
from boombox_library.models import PinKind, PinSource
from boombox_library.pins import (
    expand_pin_to_tracks,
    pin,
    unpin,
    reconcile_starred,
    write_sidecar,
    load_sidecar,
)


def _seed_album(conn, album_id="al1", artist_id="ar1", track_ids=("t1", "t2")):
    conn.execute("INSERT OR IGNORE INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES (?,?,?,?,?)", (artist_id, "X", "x", 1, 0.0))
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (album_id, "A", "a", artist_id, len(track_ids), 100, 0, 0, 0.0))
    for tid in track_ids:
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                     "size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (tid, album_id, "T", 50, "mp3", 500_000, "audio/mpeg", 0, 0.0))


def test_expand_album_pin_to_tracks(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    tids = expand_pin_to_tracks(conn, PinKind.ALBUM, "al1")
    assert set(tids) == {"t1", "t2"}


def test_expand_artist_pin_to_tracks(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn, album_id="al1", artist_id="ar1", track_ids=("t1",))
    _seed_album(conn, album_id="al2", artist_id="ar1", track_ids=("t2", "t3"))
    tids = expand_pin_to_tracks(conn, PinKind.ARTIST, "ar1")
    assert set(tids) == {"t1", "t2", "t3"}


def test_pin_inserts_and_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)  # same again, no-op
    rows = list(conn.execute("SELECT * FROM pins"))
    assert len(rows) == 1


def test_unpin_removes(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    unpin(conn, PinKind.ALBUM, "al1")
    assert list(conn.execute("SELECT * FROM pins")) == []


def test_reconcile_starred_adds_pin_when_album_starred(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    conn.execute("UPDATE albums SET navidrome_starred=1 WHERE id='al1'")
    reconcile_starred(conn)
    pins_rows = list(conn.execute(
        "SELECT target_kind, target_id, source FROM pins"))
    assert ("album", "al1", "starred") in [tuple(r) for r in pins_rows]


def test_reconcile_starred_does_not_remove_user_pin_when_unstarred(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    # User pinned it; then it was un-starred upstream (or never starred).
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    conn.execute("UPDATE albums SET navidrome_starred=0 WHERE id='al1'")
    reconcile_starred(conn)
    pins_rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert pins_rows[0][0] == "user"  # user pin survives


def test_reconcile_removes_starred_pin_when_unstarred(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    conn.execute("UPDATE albums SET navidrome_starred=1 WHERE id='al1'")
    reconcile_starred(conn)
    # Then it gets un-starred upstream.
    conn.execute("UPDATE albums SET navidrome_starred=0 WHERE id='al1'")
    reconcile_starred(conn)
    assert list(conn.execute("SELECT * FROM pins")) == []


def test_sidecar_round_trip(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    sidecar = tmp_path / "pins.json"
    write_sidecar(conn, sidecar)
    text = sidecar.read_text()
    assert "al1" in text and "album" in text and "user" in text

    # Clear pins, load from sidecar
    conn.execute("DELETE FROM pins")
    load_sidecar(conn, sidecar)
    rows = list(conn.execute("SELECT target_id, source FROM pins"))
    assert rows[0]["target_id"] == "al1"
    assert rows[0]["source"] == "user"


def test_pin_source_has_favorite_value():
    """FAVORITE source represents auto-pins from the heart/favorites button."""
    assert PinSource.FAVORITE.value == "favorite"


def test_pin_user_upgrades_favorite(tmp_path: Path):
    """USER > FAVORITE: pinning with USER over an existing FAVORITE upgrades."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.FAVORITE)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert len(rows) == 1
    assert rows[0]["source"] == "user"


def test_pin_favorite_does_not_overwrite_user(tmp_path: Path):
    """FAVORITE < USER: favoriting after explicit pin leaves source=USER."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    pin(conn, PinKind.ALBUM, "al1", PinSource.FAVORITE)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "user"


def test_pin_user_upgrades_starred(tmp_path: Path):
    """USER > STARRED: pinning over a starred-source pin upgrades to user."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.STARRED)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "user"


def test_pin_starred_does_not_overwrite_favorite(tmp_path: Path):
    """STARRED is the weakest source — never upgrades over FAVORITE or USER."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.FAVORITE)
    pin(conn, PinKind.ALBUM, "al1", PinSource.STARRED)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "favorite"


def test_unpin_with_source_filter_only_deletes_matching(tmp_path: Path):
    """Unpinning with source='favorite' must not nuke a user pin."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    unpin(conn, PinKind.ALBUM, "al1", source=PinSource.FAVORITE)
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert len(rows) == 1 and rows[0]["source"] == "user"


def test_unpin_without_source_filter_deletes_any(tmp_path: Path):
    """Backwards compat: unpin(kind, id) without source still force-deletes."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_album(conn)
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    unpin(conn, PinKind.ALBUM, "al1")
    assert list(conn.execute("SELECT * FROM pins")) == []
