"""Tests for boombox_library.resolver — playback decision logic."""
from __future__ import annotations

from pathlib import Path

from boombox_library.db import connect, migrate
from boombox_library.resolver import PlaybackSource, resolve_playback


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
    assert r.uri == "file:///cache/audio/t1.mp3"


def test_cached_offline_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", "/cache/audio/t1.mp3")
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == "file:///cache/audio/t1.mp3"


def test_uncached_online_returns_direct_stream_url(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(
        conn, "t1", online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert r.source == PlaybackSource.STREAM
    # Direct Navidrome /rest/stream.view URL — Mopidy's stream backend
    # plays this without needing Mopidy-Subsonic.
    assert r.uri is not None
    assert r.uri.startswith("http://nav:4533/rest/stream.view?")
    assert "id=t1" in r.uri
    assert "u=u" in r.uri
    # Token+salt auth means the URL contains t= and s= but NOT plaintext password.
    assert "p=p" not in r.uri
    assert "t=" in r.uri and "s=" in r.uri


def test_uncached_online_without_cfg_returns_offline_miss(tmp_path: Path):
    """When the source isn't configured, an uncached track can't stream."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.OFFLINE_MISS
    assert r.uri is None


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


def test_cached_path_with_spaces_and_unicode_is_quoted(tmp_path: Path):
    """file:// URI must be properly URL-encoded for paths with spaces / unicode."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", "/media/usb-music/audio/cool dudé.mp3")
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == "file:///media/usb-music/audio/cool%20dud%C3%A9.mp3"
    # Path separator must NOT be quoted
    assert "/audio/" in r.uri


def test_cached_status_with_null_local_path_falls_through_to_stream(tmp_path: Path):
    """Defensive: if cache_state.status='present' but local_path is NULL
    (DB inconsistency), the resolver must NOT emit a broken file:// URI.
    It falls through to STREAM (when online) or OFFLINE_MISS (when offline)."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")  # creates track row but no cache_state
    # Manually insert an inconsistent cache_state row
    conn.execute("INSERT INTO cache_state(track_id, status, local_path, "
                 "size_bytes, downloaded_at) VALUES ('t1', 'present', NULL, "
                 "NULL, NULL)")
    r_online = resolve_playback(
        conn, "t1", online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert r_online.source == PlaybackSource.STREAM
    assert r_online.uri is not None
    assert r_online.uri.startswith("http://nav:4533/rest/stream.view?")

    r_offline = resolve_playback(conn, "t1", online=False)
    assert r_offline.source == PlaybackSource.OFFLINE_MISS
    assert r_offline.uri is None
