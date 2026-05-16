"""Tests for boombox_library.eviction — FIFO over streamed, pinned protected."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.db import connect, migrate
from boombox_library.eviction import compute_eviction_candidates, evict_until_fits
from boombox_library.models import PinKind, PinSource
from boombox_library.pins import pin


def _seed(conn, tracks):
    """tracks: list of (track_id, album_id, size_bytes, downloaded_at)."""
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    seen_albums = set()
    for tid, aid, size, dl in tracks:
        if aid not in seen_albums:
            conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,"
                         "song_count,duration_s,is_compilation,navidrome_starred,"
                         "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (aid, aid, aid, "ar", 1, 30, 0, 0, 0))
            seen_albums.add(aid)
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                     "size_bytes,content_type,navidrome_starred,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (tid, aid, "T", 30, "mp3", size, "audio/mpeg", 0, 0))
        conn.execute("INSERT INTO cache_state(track_id,status,local_path,"
                     "size_bytes,downloaded_at) VALUES(?,?,?,?,?)",
                     (tid, "present", f"/cache/audio/{tid}.mp3", size, dl))


def test_no_eviction_when_zero_needed(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [("t1", "al1", 100, 1.0)])
    freed, leftover = evict_until_fits(conn, need_bytes=0,
                                       delete_file=lambda p: None)
    assert freed == 0
    assert leftover == 0
    assert conn.execute("SELECT COUNT(*) FROM cache_state WHERE status='present'").fetchone()[0] == 1


def test_evicts_oldest_streamed_first(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [
        ("t1", "al1", 100, 1.0),  # oldest
        ("t2", "al2", 100, 2.0),
        ("t3", "al3", 100, 3.0),
    ])
    deleted = []
    freed, leftover = evict_until_fits(conn, need_bytes=150,
                                       delete_file=lambda p: deleted.append(p))
    assert leftover == 0
    assert freed >= 150
    # Should have evicted t1 + t2 (oldest first)
    statuses = dict(conn.execute("SELECT track_id, status FROM cache_state"))
    assert statuses["t1"] == "absent"
    assert statuses["t2"] == "absent"
    assert statuses["t3"] == "present"
    assert "/cache/audio/t1.mp3" in deleted
    assert "/cache/audio/t2.mp3" in deleted


def test_never_evicts_pinned_tracks(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [
        ("t1", "al1", 100, 1.0),  # oldest but pinned via album
        ("t2", "al2", 100, 2.0),
    ])
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    freed, leftover = evict_until_fits(conn, need_bytes=150,
                                       delete_file=lambda p: None)
    # Only t2 (100 bytes) could be evicted; deficit remains
    statuses = dict(conn.execute("SELECT track_id, status FROM cache_state"))
    assert statuses["t1"] == "present"  # protected by pin
    assert statuses["t2"] == "absent"
    assert freed == 100
    assert leftover == 50


def test_returns_zero_leftover_when_exact_fit(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [("t1", "al1", 100, 1.0)])
    freed, leftover = evict_until_fits(conn, need_bytes=100,
                                       delete_file=lambda p: None)
    assert freed == 100
    assert leftover == 0


def test_compute_candidates_excludes_pinned(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [("t1", "al1", 100, 1.0), ("t2", "al2", 100, 2.0)])
    pin(conn, PinKind.ALBUM, "al1", PinSource.USER)
    candidates = compute_eviction_candidates(conn)
    ids = [c["track_id"] for c in candidates]
    assert ids == ["t2"]


def test_eviction_continues_on_non_oserror_from_delete_callback(tmp_path: Path):
    """A delete_file callback raising a non-OSError (e.g., a custom wrapper
    exception) must NOT wedge eviction — it should log and continue."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed(conn, [
        ("t1", "al1", 100, 1.0),
        ("t2", "al2", 100, 2.0),
        ("t3", "al3", 100, 3.0),
    ])

    def bad_delete(path):
        if "t1" in path:
            raise RuntimeError("simulated callback bug")  # NOT an OSError

    freed, leftover = evict_until_fits(conn, need_bytes=300,
                                       delete_file=bad_delete)
    # All 3 should be marked absent — the first one's exception didn't wedge
    statuses = dict(conn.execute("SELECT track_id, status FROM cache_state"))
    assert statuses["t1"] == "absent"
    assert statuses["t2"] == "absent"
    assert statuses["t3"] == "absent"
    # freed accounts for all three by size (DB truth, even if t1's file may
    # still exist physically — DB is source of truth for cache state)
    assert freed == 300
    assert leftover == 0
