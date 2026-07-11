"""Tests for boombox_updater.scheduler — should_attempt_install()."""
from __future__ import annotations

from datetime import datetime

from boombox_updater.config import UpdaterConfig
from boombox_updater.scheduler import (
    InstallDecision,
    SkipReason,
    should_attempt_install,
)


def cfg(**overrides) -> UpdaterConfig:
    base = dict(auto=True, channel="stable",
                window_start="03:00", window_duration_min=60)
    base.update(overrides)
    return UpdaterConfig(**base)


def at(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 13, hh, mm)


def test_inside_window_with_update_available_and_idle() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out == InstallDecision(install=True, reason=None)


def test_outside_window_skips() -> None:
    out = should_attempt_install(
        now=at(8, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.OUTSIDE_WINDOW


def test_window_wraps_midnight() -> None:
    # Window 23:00 -> 02:00 (180 min). 00:30 must still be inside.
    c = cfg(window_start="23:00", window_duration_min=180)
    out = should_attempt_install(
        now=at(0, 30), config=c,
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is True


def test_wrap_window_boundaries() -> None:
    # Window 23:00 -> 02:00 (180 min), spanning midnight.
    # Inclusive start (23:00), exclusive end (02:00), and points just
    # outside on each side.
    c = cfg(window_start="23:00", window_duration_min=180)

    def decide(hh: int, mm: int):
        return should_attempt_install(
            now=at(hh, mm), config=c,
            installed_version="v0.4.1", available_version="v0.4.2",
            playback_status="paused",
        )

    assert decide(22, 59).install is False   # just before start
    assert decide(23, 0).install is True     # inclusive start
    assert decide(1, 59).install is True     # inside, after midnight
    assert decide(2, 0).install is False     # exclusive end
    assert decide(2, 1).install is False     # just after end


def test_auto_disabled_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(auto=False),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.AUTO_DISABLED


def test_no_update_available_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.2", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.UP_TO_DATE


def test_playing_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="playing",
    )
    assert out.install is False
    assert out.reason == SkipReason.PLAYBACK_ACTIVE


def test_window_boundary_inclusive_start_exclusive_end() -> None:
    # Window 03:00 -> 04:00. 03:00 inside, 04:00 outside.
    inside = should_attempt_install(
        now=at(3, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    outside = should_attempt_install(
        now=at(4, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert inside.install is True
    assert outside.install is False
