"""Tests for boombox_library.snapshots — precomputed browse responses."""
from __future__ import annotations

import json
from pathlib import Path

from boombox_library.db import connect, migrate
from boombox_library.snapshots import (
    compute_etag,
    snapshot_path,
    write_snapshots,
)


def test_write_snapshots_materialises_three_files(tmp_path: Path):
    conn = connect(tmp_path / "lib.db"); migrate(conn)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','ABBA','abba',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,art_id,"
                 "updated_at) VALUES('al1','Arrival','arrival','ar1',9,2400,"
                 "0,0,'cov1',0)")
    conn.execute("INSERT INTO playlists(id,name,song_count,owner,public,"
                 "updated_at) VALUES('pl1','My Mix',5,'jwc',0,0)")

    counts = write_snapshots(conn, tmp_path / "snap")

    assert counts == {"albums": 1, "artists": 1, "playlists": 1}
    albums = json.loads((tmp_path / "snap" / "albums.json").read_text())
    assert albums["items"][0]["name"] == "Arrival"
    assert albums["items"][0]["art_id"] == "cov1"
    artists = json.loads((tmp_path / "snap" / "artists.json").read_text())
    assert artists["items"][0]["name"] == "ABBA"
    playlists = json.loads((tmp_path / "snap" / "playlists.json").read_text())
    assert playlists["items"][0]["name"] == "My Mix"


def test_write_snapshots_is_atomic(tmp_path: Path):
    """Snapshot writes use .tmp + os.replace so a partial write can't be
    observed as a half-valid JSON file by a concurrent /browse reader."""
    conn = connect(tmp_path / "lib.db"); migrate(conn)
    write_snapshots(conn, tmp_path / "snap")
    # No stray .tmp files left behind on a clean run.
    leftovers = list((tmp_path / "snap").glob("*.tmp"))
    assert leftovers == []


def test_compute_etag_changes_when_snapshot_changes(tmp_path: Path):
    conn = connect(tmp_path / "lib.db"); migrate(conn)
    write_snapshots(conn, tmp_path / "snap")
    p = snapshot_path(tmp_path / "snap", "albums")
    etag1 = compute_etag(p)

    # Mutate the snapshot — content + mtime both shift.
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',1,30,0,0,0)")
    # Bump mtime explicitly in case the test runs on a filesystem with
    # coarse 1 s mtime granularity (HFS+, some NFS) — content alone
    # would otherwise give the same etag.
    import os
    new_mtime = p.stat().st_mtime + 5
    os.utime(p, (new_mtime, new_mtime))
    write_snapshots(conn, tmp_path / "snap")
    etag2 = compute_etag(p)

    assert etag1 != etag2
