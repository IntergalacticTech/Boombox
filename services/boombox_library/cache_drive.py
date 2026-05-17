"""USB cache drive detection and symlink management.

A USB drive is treated as the boombox's audio cache drive iff it carries
a marker file at its root (default ".boombox-cache"). The service polls
the configured search paths (default /media) and adopts the first
matching mount, creating the required subdirs and updating a stable
symlink so Mopidy-Local can always read from /opt/boombox/cache-mount/audio.

This module is filesystem-side only — async behavior (poll loop) lives
in the service entry point.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("boombox-library.cache_drive")

DEFAULT_SYMLINK = Path("/opt/boombox/cache-mount")
_REQUIRED_SUBDIRS = ("audio", "meta", "tmp")


@dataclass(frozen=True)
class CacheDriveState:
    present: bool
    mount_path: Optional[Path]
    free_bytes: Optional[int]
    total_bytes: Optional[int]


def detect_cache_drive(
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> CacheDriveState:
    """Scan search paths for a directory containing the marker file. First
    one (sorted) wins. Returns CacheDriveState(present=False, ...) if none."""
    for root in search_paths:
        root = Path(root)
        if not root.exists():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError as e:
            log.warning("could not scan %s: %s", root, e)
            continue
        for child in entries:
            if not child.is_dir():
                continue
            if (child / marker).exists():
                free, total = _disk_usage(child)
                return CacheDriveState(
                    present=True,
                    mount_path=child,
                    free_bytes=free,
                    total_bytes=total,
                )
    return CacheDriveState(present=False, mount_path=None,
                           free_bytes=None, total_bytes=None)


def _disk_usage(path: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        stat = os.statvfs(path)
        free = stat.f_bavail * stat.f_frsize
        total = stat.f_blocks * stat.f_frsize
        return free, total
    except OSError:
        return None, None


def adopt_drive(mount_path: Path, marker: str = ".boombox-cache") -> None:
    """Bless a USB drive as the cache drive: write marker + create subdirs."""
    (mount_path / marker).touch(exist_ok=True)
    for sub in _REQUIRED_SUBDIRS:
        (mount_path / sub).mkdir(exist_ok=True)


def update_symlink(symlink_path: Path, target: Path) -> None:
    """Atomically update symlink_path to point at target. Replaces any
    existing symlink. Uses os.symlink + os.replace via a temp symlink."""
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = symlink_path.with_suffix(symlink_path.suffix + ".tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, symlink_path)


def remove_symlink(symlink_path: Path) -> None:
    """Remove the symlink if it exists. Idempotent."""
    try:
        if symlink_path.is_symlink() or symlink_path.exists():
            symlink_path.unlink()
    except FileNotFoundError:
        pass


def list_candidate_drives(
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> list[dict]:
    """Mounted directories that look like USB drives but lack the marker.

    The UI uses this to prompt the user to adopt a fresh drive as the cache.
    Already-adopted drives (marker present) are excluded so the prompt
    doesn't re-fire after the user has chosen.
    """
    out: list[dict] = []
    for root in search_paths:
        root = Path(root)
        if not root.exists():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError as e:
            log.warning("could not scan %s: %s", root, e)
            continue
        for child in entries:
            if not child.is_dir():
                continue
            if (child / marker).exists():
                continue
            free, total = _disk_usage(child)
            out.append({
                "mount_path": str(child),
                "label": child.name,
                "free_bytes": free,
                "total_bytes": total,
            })
    return out
