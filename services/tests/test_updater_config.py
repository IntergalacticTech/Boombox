"""Tests for boombox_updater.config — read/write/validate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from boombox_updater.config import (
    DEFAULT_CONFIG,
    UpdaterConfig,
    load_config,
    save_config,
    validate,
)


def test_default_when_file_absent(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "missing.json")
    assert cfg == DEFAULT_CONFIG
    assert cfg.auto is True
    assert cfg.channel == "stable"
    assert cfg.window_start == "03:00"
    assert cfg.window_duration_min == 60


def test_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "updater.json"
    cfg = UpdaterConfig(auto=False, channel="edge", window_start="02:30",
                       window_duration_min=120)
    save_config(target, cfg)
    assert load_config(target) == cfg


def test_save_is_atomic(tmp_path: Path) -> None:
    """save_config writes to a tmp file then renames — never leaves a
    half-written target."""
    target = tmp_path / "updater.json"
    save_config(target, DEFAULT_CONFIG)
    # No `.tmp` left behind.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "updater.json"]
    assert leftovers == []


def test_validate_window_start_format() -> None:
    with pytest.raises(ValueError, match="window_start"):
        validate({"auto": True, "channel": "stable",
                  "window_start": "3am", "window_duration_min": 60})


def test_validate_channel() -> None:
    with pytest.raises(ValueError, match="channel"):
        validate({"auto": True, "channel": "rolling",
                  "window_start": "03:00", "window_duration_min": 60})


def test_validate_duration_bounds() -> None:
    with pytest.raises(ValueError, match="window_duration_min"):
        validate({"auto": True, "channel": "stable",
                  "window_start": "03:00", "window_duration_min": 0})
    with pytest.raises(ValueError, match="window_duration_min"):
        validate({"auto": True, "channel": "stable",
                  "window_start": "03:00", "window_duration_min": 24 * 60 + 1})


def test_load_corrupt_file_returns_default(tmp_path: Path) -> None:
    target = tmp_path / "updater.json"
    target.write_text("not json {{{")
    assert load_config(target) == DEFAULT_CONFIG


def test_load_extra_keys_ignored(tmp_path: Path) -> None:
    target = tmp_path / "updater.json"
    target.write_text(json.dumps({
        "auto": True, "channel": "stable",
        "window_start": "03:00", "window_duration_min": 60,
        "future_field": "ignore me",
    }))
    cfg = load_config(target)
    assert cfg == DEFAULT_CONFIG


def test_load_unreadable_file_returns_default(tmp_path: Path) -> None:
    """A file that exists but raises OSError on read (e.g. permission
    denied, broken symlink) must fall through to DEFAULT_CONFIG rather
    than crash the service at startup."""
    broken = tmp_path / "broken.json"
    # Symlink pointing at a non-existent target raises OSError on read().
    broken.symlink_to(tmp_path / "does-not-exist.json")
    assert load_config(broken) == DEFAULT_CONFIG
