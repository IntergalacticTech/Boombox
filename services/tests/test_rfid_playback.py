"""Expansion of bindings → playable URIs via Phase 1 resolver."""
from __future__ import annotations

from pathlib import Path

from boombox_library.db import connect as lib_connect
from boombox_library.db import migrate as lib_migrate
from boombox_rfid.db import migrate as rfid_migrate
from boombox_rfid.models import BindingKind
from boombox_rfid.playback import expand_to_track_ids, resolve_uris


def _seed(conn):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','ABBA','abba',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,year,"
                 "song_count,duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','Arrival','arrival','ar1',1976,2,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,track_no,disc_no,duration_s,"
                 "suffix,size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al1','Dancing Queen',1,1,30,'mp3',1000,'audio/mpeg',0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,track_no,disc_no,duration_s,"
                 "suffix,size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t2','al1','Money Money Money',2,1,30,'mp3',1000,'audio/mpeg',0,0)")
    return conn


def test_expand_album_returns_track_ids_in_order(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    ids = expand_to_track_ids(conn, BindingKind.ALBUM, "al1")
    assert ids == ["t1", "t2"]


def test_expand_artist_returns_all_tracks(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    ids = expand_to_track_ids(conn, BindingKind.ARTIST, "ar1")
    assert set(ids) == {"t1", "t2"}


def test_expand_track_returns_self(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    ids = expand_to_track_ids(conn, BindingKind.TRACK, "t1")
    assert ids == ["t1"]


def test_resolve_uris_streams_when_online(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BOOMBOX_LIBRARY_STREAM_BASE", raising=False)
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    uris = resolve_uris(
        conn, ["t1", "t2"], online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    # Local stream-proxy URLs — no Navidrome host or auth params leak into
    # the tracklist.
    assert uris == [
        "http://127.0.0.1:6687/api/library/stream/t1",
        "http://127.0.0.1:6687/api/library/stream/t2",
    ]


def test_resolve_uris_returns_file_when_cached(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BOOMBOX_LIBRARY_STREAM_BASE", raising=False)
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    cached = tmp_path / "audio" / "t1.mp3"
    cached.parent.mkdir()
    cached.write_bytes(b"ID3")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present',?,1000,0)", (str(cached),))
    uris = resolve_uris(
        conn, ["t1", "t2"], online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert uris[0] == f"file://{cached}"
    assert uris[1] == "http://127.0.0.1:6687/api/library/stream/t2"


def test_resolve_uris_skips_offline_miss(tmp_path: Path):
    conn = lib_connect(tmp_path / "lib.db"); lib_migrate(conn); rfid_migrate(conn)
    _seed(conn)
    uris = resolve_uris(conn, ["t1", "t2"], online=False)
    assert uris == []  # neither cached + offline → both skipped
