"""USB cache drive detection and symlink management.

A USB drive is treated as the boombox's audio cache drive iff it carries
a marker file at its root (default ".boombox-cache"). The service polls
the configured search paths (default /media) and adopts the first
matching mount, creating the required subdirs and updating a stable
symlink so Mopidy-Local can always read from /opt/boombox/cache-mount/audio.

This module is filesystem-side (plus the cache_state bookkeeping that
follows the drive coming and going) — async behavior (poll loop) lives
in the service entry point.

Drive loss: cache_state rows are NOT deleted when the drive vanishes —
the files are usually fine, just unplugged. Instead every 'present' row
on the lost drive is flipped to status 'missing' (local_path kept), so
the resolver, which only plays status='present', never hands Mopidy a
file:// path on a drive that isn't there, and pinned tracks are
re-downloaded if a different drive is adopted. When a drive is adopted
again, 'missing' rows whose file exists (same path, or the same
audio/<file> on a drive remounted at a new path) go back to 'present'.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import Iterable, Optional, Sequence

log = logging.getLogger("boombox-library.cache_drive")

DEFAULT_SYMLINK = Path("/opt/boombox/cache-mount")
_REQUIRED_SUBDIRS = ("audio", "meta", "tmp")

# cache_state.status for a row whose file lives on a cache drive that is
# not currently mounted. Never played; restored by restore_missing_rows().
STATUS_MISSING = "missing"


@dataclass(frozen=True)
class CacheDriveState:
    present: bool
    mount_path: Optional[Path]
    free_bytes: Optional[int]
    total_bytes: Optional[int]
    # True for the internal music storage (cache.internal_path).
    internal: bool = False


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


def ensure_internal_drive(path: Path, marker: str = ".boombox-cache") -> CacheDriveState:
    """The internal music store as an always-present cache drive: create it
    (0755), write the marker and audio/meta/tmp when missing. Cheap when
    everything is there (cache_poll calls it every few seconds — no write).
    Raises OSError when the path can't be created or written."""
    created = not path.exists()
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    if created:
        path.chmod(0o755)  # mkdir's mode is filtered by the umask
    if not (path / marker).exists() or any(
            not (path / sub).is_dir() for sub in _REQUIRED_SUBDIRS):
        adopt_drive(path, marker=marker)
    free, total = _disk_usage(path)
    return CacheDriveState(present=True, mount_path=path, free_bytes=free,
                           total_bytes=total, internal=True)


_warned_internal: set[str] = set()


def select_cache_drive(
    internal_path: str,
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> CacheDriveState:
    """The cache drive for this poll: the internal storage when configured
    and usable (it always wins over /media), else the first marker-carrying
    drive under search_paths — the removable-drive fallback."""
    paths = [Path(p) for p in search_paths]
    if internal_path:
        try:
            state = ensure_internal_drive(Path(internal_path), marker)
            _warned_internal.discard(internal_path)
            return state
        except OSError as e:
            if internal_path not in _warned_internal:
                _warned_internal.add(internal_path)
                log.warning("internal music storage %s is unusable (%s); "
                            "falling back to a marked drive under %s",
                            internal_path, e, [str(p) for p in paths])
    return detect_cache_drive(paths, marker)


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


def _is_writable(path: Path) -> bool:
    """Probe whether we can create files under `path`. Many auto-mounted
    USB drives land read-only; the adopt path would fail anyway, so we
    pre-filter them out."""
    try:
        return os.access(str(path), os.W_OK)
    except OSError:
        return False


def list_candidate_drives(
    search_paths: Iterable[Path],
    marker: str = ".boombox-cache",
) -> list[dict]:
    """Mounted directories that look like USB drives but lack the marker.

    The UI uses this to prompt the user to adopt a fresh drive as the cache.
    Already-adopted drives (marker present) are excluded so the prompt
    doesn't re-fire after the user has chosen. Read-only mounts (common
    for vfat USB drives auto-mounted by udisks) are also excluded — the
    adopt path would fail to write the marker file on them.
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
            if not _is_writable(child):
                continue
            free, total = _disk_usage(child)
            out.append({
                "mount_path": str(child),
                "label": child.name,
                "free_bytes": free,
                "total_bytes": total,
            })
    return out


def _is_under(path: str, root: Path) -> bool:
    prefix = str(root).rstrip("/") + "/"
    return path.startswith(prefix)


def mark_rows_missing(conn: Connection, lost_mount: Optional[Path]) -> int:
    """Flip 'present' cache_state rows whose file is gone to 'missing'.

    With `lost_mount` (the drive just vanished) every present row under
    that mount is flipped without touching the filesystem — a yanked USB
    mountpoint can stall or error on stat. Without it (startup with no
    drive attached) each present row is checked for its file instead.
    Returns the number of rows flipped.
    """
    rows = present_rows(conn)
    gone: list[tuple[str, Optional[str]]]
    if lost_mount is not None:
        gone = [(tid, path) for tid, path in rows
                if path and _is_under(path, lost_mount)]
    else:
        gone = find_gone_rows(rows)
    return apply_rows_missing(conn, gone)


def restore_missing_rows(conn: Connection, mount: Path) -> int:
    """Re-adopt 'missing' rows whose file is present on `mount`.

    Tries the recorded path first (same drive, same mountpoint), then
    `mount/audio/<basename>` (same drive, remounted elsewhere). Rows whose
    file isn't found stay 'missing'. Returns the number restored.
    """
    return apply_rows_restored(
        conn, find_restorable_rows(missing_rows(conn), mount))


# The reconcile above in three phases, so an asyncio caller can run the
# filesystem half (a stat per row — slow on a big or sleepy USB drive)
# in a worker thread while every SQLite read/write stays on its own
# thread: read the rows, check the files off-thread, apply the result.

def present_rows(conn: Connection) -> list[tuple[str, Optional[str]]]:
    """(track_id, local_path) of every 'present' cache_state row."""
    return [(r["track_id"], r["local_path"]) for r in conn.execute(
        "SELECT track_id, local_path FROM cache_state WHERE status='present'"
    )]


def missing_rows(conn: Connection) -> list[tuple[str, Optional[str]]]:
    """(track_id, local_path) of every 'missing' cache_state row."""
    return [(r["track_id"], r["local_path"]) for r in conn.execute(
        "SELECT track_id, local_path FROM cache_state WHERE status=?",
        (STATUS_MISSING,),
    )]


def find_gone_rows(
    rows: Iterable[tuple[str, Optional[str]]],
) -> list[tuple[str, Optional[str]]]:
    """Filesystem-only: the (track_id, local_path) rows whose local_path
    is empty or absent."""
    return [(tid, path) for tid, path in rows
            if not path or not os.path.exists(path)]


def find_restorable_rows(
    rows: Iterable[tuple[str, Optional[str]]], mount: Path,
) -> list[tuple[str, str, int]]:
    """Filesystem-only: (track_id, found_path, size) for each row whose
    file exists on `mount` — at its recorded path, else audio/<basename>."""
    found: list[tuple[str, str, int]] = []
    for tid, path in rows:
        if not path:
            continue
        for c in (Path(path), mount / "audio" / Path(path).name):
            if not _is_under(str(c), mount):
                continue
            try:
                size = c.stat().st_size
            except OSError:
                continue
            found.append((tid, str(c), size))
            break
    return found


def apply_rows_missing(conn: Connection,
                       rows: Sequence[tuple[str, Optional[str]]]) -> int:
    """Flip these (track_id, local_path) rows 'present' -> 'missing'. A
    row whose status or path changed since it was read (e.g. re-downloaded
    to a new file meanwhile) is left alone. Returns len(rows)."""
    if rows:
        conn.executemany(
            "UPDATE cache_state SET status=? WHERE track_id=? "
            "AND status='present' AND local_path IS ?",
            ((STATUS_MISSING, tid, path) for tid, path in rows),
        )
    return len(rows)


def apply_rows_restored(conn: Connection,
                        found: list[tuple[str, str, int]]) -> int:
    """Flip these rows 'missing' -> 'present' at the found path/size.
    Rows that changed status since they were read are left alone."""
    for tid, path, size in found:
        conn.execute(
            "UPDATE cache_state SET status='present', local_path=?, "
            "size_bytes=? WHERE track_id=? AND status=?",
            (path, size, tid, STATUS_MISSING),
        )
    return len(found)
