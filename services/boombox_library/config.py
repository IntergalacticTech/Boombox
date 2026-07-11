"""User-editable boombox-library config: /etc/boombox/library.yml.

Defaults are baked in for first-boot. The HTTP API's PUT validates input
before calling save_config(). All writes are atomic (.tmp + rename) so
a crashed write never corrupts the file. The Subsonic password is
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

import yaml
from cryptography.fernet import Fernet, InvalidToken

CONFIG_PATH = Path("/etc/boombox/library.yml")
_MACHINE_ID_PATH = Path("/etc/machine-id")
_KEY_SALT = b"boombox-library-v1"


@dataclass(frozen=True)
class SourceConfig:
    url: str = ""
    username: str = ""
    # plaintext in-memory; encrypted on disk. repr=False so accidental
    # log.debug(cfg) or print() can never leak the password.
    password: str = field(default="", repr=False)


@dataclass(frozen=True)
class SyncConfig:
    interval_seconds: int = 3600
    starred_auto_pin: bool = True
    max_concurrent_downloads: int = 2


@dataclass(frozen=True)
class CacheConfig:
    marker_filename: str = ".boombox-cache"
    search_paths: tuple = ("/media",)
    reserve_bytes: int = 1_073_741_824  # 1 GB


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


def load_config(path: Path = CONFIG_PATH) -> LibraryConfig:
    if not path.exists():
        return DEFAULT_CONFIG
    raw = yaml.safe_load(path.read_text()) or {}

    src = raw.get("source", {})
    source = SourceConfig(
        url=src.get("url", ""),
        username=src.get("username", ""),
        password=_decrypt_password(src.get("password_encrypted", "")),
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
        reserve_bytes=int(ca.get("reserve_bytes", 1_073_741_824)),
    )

    return LibraryConfig(source=source, sync=sync, cache=cache)


def save_config(cfg: LibraryConfig, path: Path = CONFIG_PATH) -> None:
    out = {
        "source": {
            "url": cfg.source.url,
            "username": cfg.source.username,
            "password_encrypted": _encrypt_password(cfg.source.password),
        },
        "sync": {
            "interval_seconds": cfg.sync.interval_seconds,
            "starred_auto_pin": cfg.sync.starred_auto_pin,
            "max_concurrent_downloads": cfg.sync.max_concurrent_downloads,
        },
        "cache": {
            "marker_filename": cfg.cache.marker_filename,
            "search_paths": list(cfg.cache.search_paths),
            "reserve_bytes": cfg.cache.reserve_bytes,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = yaml.safe_dump(out, sort_keys=False)
    with tmp.open("w") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
