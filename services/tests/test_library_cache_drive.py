"""Tests for boombox_library.cache_drive — marker detection + symlink mgmt."""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.cache_drive import (
    CacheDriveState,
    detect_cache_drive,
    adopt_drive,
    update_symlink,
    remove_symlink,
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
    b = _make_drive(tmp_path, "b-cache", has_marker=True)
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
