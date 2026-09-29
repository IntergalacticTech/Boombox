"""Tests for boombox_library.cache_drive — marker detection + symlink mgmt."""
from __future__ import annotations

from pathlib import Path

from boombox_library.cache_drive import (
    adopt_drive,
    detect_cache_drive,
    remove_symlink,
    update_symlink,
)


def _make_drive(parent: Path, name: str, has_marker: bool, marker=".boombox-cache") -> Path:
    d = parent / name
    d.mkdir()
    if has_marker:
        (d / marker).touch()
    return d


def test_detect_no_drives(tmp_path: Path):
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    assert state.mount_path is None
    assert state.present is False


def test_detect_ignores_drives_without_marker(tmp_path: Path):
    _make_drive(tmp_path, "ad-hoc-1", has_marker=False)
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    assert state.present is False


def test_detect_picks_drive_with_marker(tmp_path: Path):
    d = _make_drive(tmp_path, "cache", has_marker=True)
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    assert state.present is True
    assert state.mount_path == d


def test_detect_first_wins_on_multiple_markers(tmp_path: Path):
    a = _make_drive(tmp_path, "a-cache", has_marker=True)
    _make_drive(tmp_path, "b-cache", has_marker=True)  # second marked drive; "a" should still win
    state = detect_cache_drive(search_paths=[tmp_path], marker=".boombox-cache")
    # Sorted iteration → "a-cache" wins
    assert state.mount_path == a


def test_adopt_drive_writes_marker(tmp_path: Path):
    d = _make_drive(tmp_path, "fresh", has_marker=False)
    adopt_drive(d, marker=".boombox-cache")
    assert (d / ".boombox-cache").exists()


def test_adopt_creates_required_subdirs(tmp_path: Path):
    d = _make_drive(tmp_path, "fresh", has_marker=False)
    adopt_drive(d, marker=".boombox-cache")
    assert (d / "audio").is_dir()
    assert (d / "meta").is_dir()
    assert (d / "tmp").is_dir()


def test_update_symlink_creates_then_swaps(tmp_path: Path):
    d1 = _make_drive(tmp_path, "drive-a", has_marker=True)
    d2 = _make_drive(tmp_path, "drive-b", has_marker=True)
    sym = tmp_path / "cache-mount"
    update_symlink(sym, target=d1)
    assert sym.is_symlink() and sym.resolve() == d1
    update_symlink(sym, target=d2)
    assert sym.is_symlink() and sym.resolve() == d2


def test_remove_symlink_idempotent(tmp_path: Path):
    sym = tmp_path / "cache-mount"
    remove_symlink(sym)  # no-op
    sym.symlink_to(tmp_path)
    remove_symlink(sym)
    assert not sym.exists() and not sym.is_symlink()


def test_list_candidate_drives_returns_unadopted(tmp_path: Path):
    """Drives that are mounted but lack the marker file appear as candidates."""
    from boombox_library.cache_drive import list_candidate_drives
    _make_drive(tmp_path, "DRIVE_A", has_marker=True)
    _make_drive(tmp_path, "DRIVE_B", has_marker=False)
    out = list_candidate_drives([tmp_path], marker=".boombox-cache")
    paths = [c["mount_path"] for c in out]
    assert str(tmp_path / "DRIVE_B") in paths
    assert str(tmp_path / "DRIVE_A") not in paths


def test_list_candidate_drives_includes_disk_usage(tmp_path: Path):
    """Each candidate has free_bytes + total_bytes (best-effort)."""
    from boombox_library.cache_drive import list_candidate_drives
    _make_drive(tmp_path, "DRIVE", has_marker=False)
    out = list_candidate_drives([tmp_path])
    assert out[0]["free_bytes"] is not None
    assert out[0]["total_bytes"] is not None
    assert out[0]["label"] == "DRIVE"


def test_list_candidate_drives_skips_missing_search_root(tmp_path: Path):
    """Non-existent search paths are silently skipped."""
    from boombox_library.cache_drive import list_candidate_drives
    out = list_candidate_drives([tmp_path / "does-not-exist"])
    assert out == []


# ---- cache_state bookkeeping across drive loss / re-adopt ----

def _db(tmp_path: Path):
    from boombox_library.db import connect, migrate
    conn = connect(tmp_path / "library.db")
    migrate(conn)
    return conn


def _row(conn, track_id: str, status: str, path: str | None) -> None:
    conn.execute(
        "INSERT INTO cache_state(track_id, status, local_path, size_bytes) "
        "VALUES (?, ?, ?, 1)", (track_id, status, path))


def _status(conn, track_id: str):
    r = conn.execute("SELECT status, local_path FROM cache_state WHERE track_id=?",
                     (track_id,)).fetchone()
    return (r["status"], r["local_path"])


def test_mark_rows_missing_under_lost_mount_without_stat(tmp_path: Path):
    from boombox_library.cache_drive import mark_rows_missing
    conn = _db(tmp_path)
    mount = tmp_path / "media" / "usb0"
    _row(conn, "t1", "present", f"{mount}/audio/t1.mp3")
    _row(conn, "t2", "present", f"{tmp_path}/elsewhere/t2.mp3")
    _row(conn, "t3", "queued", None)
    # Prefix match must be on a path boundary: usb0 ≠ usb01.
    _row(conn, "t4", "present", f"{mount}1/audio/t4.mp3")
    assert mark_rows_missing(conn, mount) == 1
    assert _status(conn, "t1") == ("missing", f"{mount}/audio/t1.mp3")  # path kept
    assert _status(conn, "t2")[0] == "present"
    assert _status(conn, "t3")[0] == "queued"
    assert _status(conn, "t4")[0] == "present"


def test_mark_rows_missing_startup_checks_files(tmp_path: Path):
    from boombox_library.cache_drive import mark_rows_missing
    conn = _db(tmp_path)
    real = tmp_path / "t1.mp3"
    real.write_bytes(b"x")
    _row(conn, "t1", "present", str(real))
    _row(conn, "t2", "present", str(tmp_path / "gone.mp3"))
    assert mark_rows_missing(conn, None) == 1
    assert _status(conn, "t1")[0] == "present"
    assert _status(conn, "t2")[0] == "missing"


def test_restore_missing_rows_same_path_and_remounted(tmp_path: Path):
    from boombox_library.cache_drive import restore_missing_rows
    conn = _db(tmp_path)
    old = tmp_path / "usb0"
    new = tmp_path / "usb1"
    (old / "audio").mkdir(parents=True)
    (new / "audio").mkdir(parents=True)
    (old / "audio" / "t1.mp3").write_bytes(b"abc")
    (new / "audio" / "t2.flac").write_bytes(b"abcdef")
    _row(conn, "t1", "missing", str(old / "audio" / "t1.mp3"))
    _row(conn, "t2", "missing", str(old / "audio" / "t2.flac"))  # remounted
    _row(conn, "t3", "missing", str(old / "audio" / "t3.mp3"))   # really gone

    assert restore_missing_rows(conn, old) == 1
    assert _status(conn, "t1") == ("present", str(old / "audio" / "t1.mp3"))

    assert restore_missing_rows(conn, new) == 1
    assert _status(conn, "t2") == ("present", str(new / "audio" / "t2.flac"))
    size = conn.execute("SELECT size_bytes FROM cache_state WHERE track_id='t2'").fetchone()[0]
    assert size == 6
    assert _status(conn, "t3")[0] == "missing"


def test_missing_rows_are_never_resolved_to_a_file(tmp_path: Path):
    """The resolver only plays status='present' — a 'missing' row with a
    dead path falls through to stream/offline instead."""
    from boombox_library.resolver import PlaybackSource, resolve_playback
    conn = _db(tmp_path)
    conn.execute("INSERT INTO artists(id, name, sort_name, updated_at) VALUES ('ar','A','a',0)")
    conn.execute("INSERT INTO albums(id, name, sort_name, artist_id, updated_at) "
                 "VALUES ('al','B','b','ar',0)")
    conn.execute("INSERT INTO tracks(id, album_id, title, updated_at) VALUES ('t1','al','T',0)")
    _row(conn, "t1", "missing", "/media/gone/audio/t1.mp3")
    r = resolve_playback(conn, "t1", online=False)
    assert r.source == PlaybackSource.OFFLINE_MISS
    assert r.uri is None
