"""Boombox-rfid configuration.

YAML at /etc/boombox/rfid.yml. Defaults are baked in so the service runs
on first boot without any operator setup — the only field worth setting
is `device_path` if udev didn't create a by-id alias, or to disable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path("/etc/boombox/rfid.yml")
LIBRARY_DB_PATH = Path("/opt/boombox/state/library.db")


@dataclass(frozen=True)
class RfidConfig:
    enabled: bool = True
    # If empty, auto-detect any /dev/input/by-id/*-event-kbd whose name
    # contains "IC_Reader" (covers the common cheap HID readers).
    device_path: str = ""
    # Time after a tap during which the same UID is debounced.
    debounce_ms: int = 1500
    # Time the last unbound UID stays available in /api/rfid/recent.
    recent_ttl_ms: int = 30_000
    # Mopidy JSON-RPC base URL.
    mopidy_rpc: str = "http://127.0.0.1:6680/mopidy/rpc"


def load_config(path: Path = CONFIG_PATH) -> RfidConfig:
    if not path.exists():
        return RfidConfig()
    raw = yaml.safe_load(path.read_text()) or {}
    return RfidConfig(
        enabled=bool(raw.get("enabled", True)),
        device_path=str(raw.get("device_path", "")),
        debounce_ms=int(raw.get("debounce_ms", 1500)),
        recent_ttl_ms=int(raw.get("recent_ttl_ms", 30_000)),
        mopidy_rpc=str(raw.get("mopidy_rpc", "http://127.0.0.1:6680/mopidy/rpc")),
    )
