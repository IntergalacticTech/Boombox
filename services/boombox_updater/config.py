"""User-editable updater config: /etc/boombox/updater.json.

Defaults are baked in for first-boot. The HTTP API's PUT validates input
through `validate()` before calling `save_config()`. All writes are
atomic (.tmp + rename) so a crashed write never corrupts the file.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/etc/boombox/updater.json")
ALLOWED_CHANNELS = ("stable", "edge")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class UpdaterConfig:
    auto: bool
    channel: str
    window_start: str       # "HH:MM" 24h
    window_duration_min: int


DEFAULT_CONFIG = UpdaterConfig(
    auto=True,
    channel="stable",
    window_start="03:00",
    window_duration_min=60,
)


def validate(raw: dict[str, Any]) -> UpdaterConfig:
    """Validate a dict and return an UpdaterConfig. Raises ValueError on
    any rule violation, with the offending key in the message."""
    if not isinstance(raw.get("auto"), bool):
        raise ValueError("auto must be a bool")
    channel = raw.get("channel")
    if channel not in ALLOWED_CHANNELS:
        raise ValueError(f"channel must be one of {ALLOWED_CHANNELS}")
    window_start = raw.get("window_start", "")
    if not isinstance(window_start, str) or not HHMM_RE.match(window_start):
        raise ValueError("window_start must be HH:MM (24h)")
    duration = raw.get("window_duration_min")
    if not isinstance(duration, int) or duration < 1 or duration > 24 * 60:
        raise ValueError("window_duration_min must be int in [1, 1440]")
    return UpdaterConfig(
        auto=raw["auto"],
        channel=channel,
        window_start=window_start,
        window_duration_min=duration,
    )


def load_config(path: Path = CONFIG_PATH) -> UpdaterConfig:
    """Load config, returning DEFAULT_CONFIG on missing/corrupt/unreadable
    files. Catches OSError broadly (covers FileNotFoundError,
    PermissionError, broken symlinks) so a startup-time read failure can
    never crash the service."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG
    try:
        return validate(raw)
    except ValueError:
        return DEFAULT_CONFIG


def save_config(path: Path, cfg: UpdaterConfig) -> None:
    """Atomically write config (.tmp + rename, fsync)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n"
    with tmp.open("w") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
