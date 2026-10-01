"""User-editable boombox-library config: /etc/boombox/library.yml.

Defaults are baked in for first-boot. The HTTP API's PUT validates input
before calling save_config(). All writes are atomic (.tmp + fsync +
rename) so a crashed write never corrupts the file, and the file is
always created 0600 — it holds the (encrypted) credentials. The Subsonic password is
encrypted at rest via Fernet, with a key derived from /etc/machine-id —
the file is unreadable on a different machine, mitigating disk-image
exfiltration.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from cryptography.fernet import Fernet, InvalidToken

CONFIG_PATH = Path("/etc/boombox/library.yml")
_MACHINE_ID_PATH = Path("/etc/machine-id")
_KEY_SALT = b"boombox-library-v1"
DEFAULT_INTERNAL_PATH = "/opt/boombox/storage/music"
DEFAULT_RESERVE_BYTES = 20 * 1024 ** 3  # 20 GiB
# The pre-2A default. A library.yml carrying exactly this value was written
# by the old template / a Settings save, not chosen by hand: upgrade it.
LEGACY_RESERVE_BYTES = 1_073_741_824


@dataclass(frozen=True)
class SourceConfig:
    url: str = ""
    username: str = ""
    # plaintext in-memory; encrypted on disk. repr=False so accidental
    # log.debug(cfg) or print() can never leak the password.
    password: str = field(default="", repr=False)
    # Cap for streamed audio, in kbps. 0 = original quality (no transcoding);
    # >0 asks the Subsonic server to transcode down (stream.view maxBitRate).
    max_bitrate_kbps: int = 0


@dataclass(frozen=True)
class SyncConfig:
    interval_seconds: int = 3600
    starred_auto_pin: bool = True
    max_concurrent_downloads: int = 2


@dataclass(frozen=True)
class CacheConfig:
    marker_filename: str = ".boombox-cache"
    search_paths: tuple = ("/media",)
    # Downloads stop while free space is below this.
    reserve_bytes: int = DEFAULT_RESERVE_BYTES
    # Internal music storage, adopted as an always-present cache drive and
    # preferred over /media drives. "" disables it (a marker-carrying drive
    # under search_paths is then adopted, as before).
    internal_path: str = DEFAULT_INTERNAL_PATH


@dataclass(frozen=True)
class LibraryConfig:
    source: SourceConfig
    sync: SyncConfig
    cache: CacheConfig


DEFAULT_CONFIG = LibraryConfig(
    source=SourceConfig(),
    sync=SyncConfig(),
    cache=CacheConfig(),
)


def _machine_id() -> str:
    """Read /etc/machine-id; falls back to a known dev string if absent
    (e.g., running tests on macOS). Monkeypatched in tests."""
    try:
        return _MACHINE_ID_PATH.read_text().strip()
    except OSError:
        return "00000000000000000000000000000000"


def _derive_key() -> bytes:
    """Derive a 32-byte Fernet key from machine-id + a fixed salt.

    Stable across reboots on the same machine; different across machines.
    """
    mid = _machine_id().encode("utf-8")
    digest = hashlib.sha256(_KEY_SALT + mid).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt_password(plain: str) -> str:
    if not plain:
        return ""
    f = Fernet(_derive_key())
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt_password(token: str) -> str:
    if not token:
        return ""
    f = Fernet(_derive_key())
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Wrong machine, corrupt token — treat as empty (forces re-entry).
        return ""


def _non_negative_int(value: Any) -> int:
    """Lenient int parse for optional numeric keys: junk or <0 → 0."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(n, 0)


def _reserve_bytes(value: Any) -> int:
    """Junk / negative → the default; the legacy 1 GiB default → 20 GiB."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RESERVE_BYTES
    if n < 0 or n == LEGACY_RESERVE_BYTES:
        return DEFAULT_RESERVE_BYTES
    return n


def _internal_path(value: Any) -> str:
    """None / "" (YAML `internal_path:` or `internal_path: ""`) disables it."""
    return str(value).strip() if value else ""


def load_config(path: Path = CONFIG_PATH) -> LibraryConfig:
    if not path.exists():
        return DEFAULT_CONFIG
    raw = yaml.safe_load(path.read_text()) or {}

    src = raw.get("source", {})
    source = SourceConfig(
        url=src.get("url", ""),
        username=src.get("username", ""),
        password=_decrypt_password(src.get("password_encrypted", "")),
        max_bitrate_kbps=_non_negative_int(src.get("max_bitrate_kbps", 0)),
    )

    sy = raw.get("sync", {})
    sync = SyncConfig(
        interval_seconds=int(sy.get("interval_seconds", 3600)),
        starred_auto_pin=bool(sy.get("starred_auto_pin", True)),
        max_concurrent_downloads=int(sy.get("max_concurrent_downloads", 2)),
    )

    ca = raw.get("cache", {})
    cache = CacheConfig(
        marker_filename=ca.get("marker_filename", ".boombox-cache"),
        search_paths=tuple(ca.get("search_paths", ["/media"])),
        reserve_bytes=_reserve_bytes(ca.get("reserve_bytes", DEFAULT_RESERVE_BYTES)),
        internal_path=_internal_path(ca.get("internal_path", DEFAULT_INTERNAL_PATH)),
    )

    return LibraryConfig(source=source, sync=sync, cache=cache)


def save_config(cfg: LibraryConfig, path: Path = CONFIG_PATH) -> None:
    out = {
        "source": {
            "url": cfg.source.url,
            "username": cfg.source.username,
            "password_encrypted": _encrypt_password(cfg.source.password),
            "max_bitrate_kbps": cfg.source.max_bitrate_kbps,
        },
        "sync": {
            "interval_seconds": cfg.sync.interval_seconds,
            "starred_auto_pin": cfg.sync.starred_auto_pin,
            "max_concurrent_downloads": cfg.sync.max_concurrent_downloads,
        },
        "cache": {
            "internal_path": cfg.cache.internal_path,
            "marker_filename": cfg.cache.marker_filename,
            "search_paths": list(cfg.cache.search_paths),
            "reserve_bytes": cfg.cache.reserve_bytes,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = yaml.safe_dump(out, sort_keys=False)
    # Create the tmp file 0600 from the start (never briefly world-readable),
    # and fchmod in case a stale .tmp survived with looser bits — O_CREAT's
    # mode only applies to a newly created file. os.replace carries the
    # tmp's mode over, so every save leaves library.yml at 0600.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fd = -1  # ownership moved to fh; it closes the descriptor
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself. Best-effort: not every FS supports it."""
    try:
        dfd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)
