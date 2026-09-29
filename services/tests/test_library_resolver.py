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


def _cached_file(tmp_path: Path, name: str = "t1.mp3") -> str:
    f = tmp_path / "audio" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"ID3")
    return str(f)


def test_cached_online_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    path = _cached_file(tmp_path)
    _seed_track(conn, "t1", path)
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == f"file://{path}"


def test_cached_offline_returns_local(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    path = _cached_file(tmp_path)
    _seed_track(conn, "t1", path)
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.CACHE
    assert r.uri == f"file://{path}"


def test_uncached_online_returns_local_proxy_url(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BOOMBOX_LIBRARY_STREAM_BASE", raising=False)
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(
        conn, "t1", online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert r.source == PlaybackSource.STREAM
    # Local stream proxy on boombox-library — Mopidy's stream backend plays
    # it; the proxy adds Subsonic auth server-side.
    assert r.uri == "http://127.0.0.1:6687/api/library/stream/t1"
    # No credential material of any kind in the URI.
    assert "nav:4533" not in r.uri
    assert "u=" not in r.uri and "t=" not in r.uri and "s=" not in r.uri


def test_stream_base_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BOOMBOX_LIBRARY_STREAM_BASE", "http://10.0.0.5:7000/s/")
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1")
    r = resolve_playback(
        conn, "t1", online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert r.uri == "http://10.0.0.5:7000/s/t1"


def test_proxy_url_quotes_track_id():
    from boombox_library.resolver import make_proxy_stream_url
    assert make_proxy_stream_url("a b/c?d", base="http://h/x") == "http://h/x/a%20b%2Fc%3Fd"


def test_make_stream_url_kept_for_back_compat():
    from boombox_library.resolver import make_stream_url
    u = make_stream_url("http://nav:4533/", "u", "p", "t1")
    assert u.startswith("http://nav:4533/rest/stream.view?")
    assert "id=t1" in u and "t=" in u and "s=" in u and "p=p" not in u


def test_cached_row_but_file_missing_streams_when_online(tmp_path: Path):
    """Cache drive yanked (or file deleted) while the row still says
    'present': never hand Mopidy a dead file:// URI — stream instead."""
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", str(tmp_path / "gone" / "t1.mp3"))
    r = resolve_playback(
        conn, "t1", online=True,
        source_url="http://nav:4533", source_username="u", source_password="p",
    )
    assert r.source == PlaybackSource.STREAM
    assert r.uri is not None and r.uri.endswith("/api/library/stream/t1")
    assert r.cache_status == "absent"


def test_cached_row_but_file_missing_offline_is_miss(tmp_path: Path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    _seed_track(conn, "t1", str(tmp_path / "gone" / "t1.mp3"))
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.OFFLINE_MISS
    assert r.uri is None


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
    path = _cached_file(tmp_path, "cool dudé.mp3")
    _seed_track(conn, "t1", path)
    r = resolve_playback(conn, "t1", online=True)
    assert r.source == PlaybackSource.CACHE
    assert r.uri is not None
    assert r.uri.endswith("/audio/cool%20dud%C3%A9.mp3")
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
    assert r_online.uri.endswith("/api/library/stream/t1")

    r_offline = resolve_playback(conn, "t1", online=False)
    assert r_offline.source == PlaybackSource.OFFLINE_MISS
    assert r_offline.uri is None
