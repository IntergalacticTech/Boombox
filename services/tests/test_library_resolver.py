"""Tests for boombox_library.resolver — playback decision logic."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.db import connect, migrate
from boombox_library.resolver import resolve_playback, PlaybackSource


def _seed_track(conn, track_id="t1", cached_path=None):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)",
                 (track_id, "al", "T", 30, "mp3", 1000, "audio/mpeg", 0, 0))
    if cached_path:
        conn.execute("INSERT INTO cache_state(track_id,status,local_path,"
                     "size_bytes,downloaded_at) VALUES(?,?,?,?,?)",
                     (track_id, "present", cached_path, 1000, 0))


def test_cached_online_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", "/cache/audio/t1.mp3")
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == "local:track:/cache/audio/t1.mp3"


def test_cached_offline_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", "/cache/audio/t1.mp3")
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == "local:track:/cache/audio/t1.mp3"


def test_uncached_online_returns_subsonic_stream(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.STREAM
    # Mopidy-Subsonic URI scheme
    assert r.uri == "subsonic:track:t1"


def test_uncached_offline_returns_offline_miss(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.OFFLINE_MISS
    assert r.uri is None


def test_unknown_track_returns_offline_miss(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    r = resolve_playback(conn, "does-not-exist", online=True)
    assert r.source == PlaybackSource.OFFLINE_MISS
