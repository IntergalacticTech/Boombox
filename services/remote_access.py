"""Persistent 'remote access enabled' flag for boombox-remote.

The phone-facing remote surface is gated by a single on/off flag, default
off, persisted alongside peers.json. The touchscreen toggles it. The BLE
peripheral and the already-paired CYD hardware remote are NOT gated by it —
the flag is a privacy gate against arbitrary phones on the WiFi, not a
master kill switch for paired hardware.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_STATE = Path.home() / ".config" / "boombox-remote" / "state.json"


def _state_path() -> Path:
    """Resolve the state file path. Re-reads env on every call so tests can
    override BOOMBOX_REMOTE_STATE between calls."""
    return Path(os.environ.get("BOOMBOX_REMOTE_STATE", str(DEFAULT_STATE)))


def is_enabled() -> bool:
    """True when remote access is on. A missing or malformed file reads as
    off — the conservative default. This includes valid JSON that isn't an
    object (e.g. a bare list or number)."""
    try:
        data = json.loads(_state_path().read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("enabled", False))


def set_enabled(enabled: bool) -> None:
    """Persist the flag. Creates the parent directory if needed."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": bool(enabled)}, indent=2))
