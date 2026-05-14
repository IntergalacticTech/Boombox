"""Scheduler decision: should we run an install right now?

Pure function — the caller injects the clock and the playback status. The
scheduler doesn't care how those were obtained, which makes it trivially
testable and free of timing flakiness.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .config import UpdaterConfig
from .version import compare_edge, compare_stable


class SkipReason(str, enum.Enum):
    AUTO_DISABLED = "auto_disabled"
    UP_TO_DATE = "up_to_date"
    OUTSIDE_WINDOW = "outside_window"
    PLAYBACK_ACTIVE = "playback_active"


@dataclass(frozen=True)
class InstallDecision:
    install: bool
    reason: Optional[SkipReason]


def _in_window(now: datetime, start: str, duration_min: int) -> bool:
    """Window is inclusive of start, exclusive of end. Wraps over midnight."""
    sh, sm = (int(x) for x in start.split(":"))
    window_start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=duration_min)
    if now >= window_start and now < window_end:
        return True
    # Handle wrap: window_end may be tomorrow; "now" may be this morning.
    if window_end.day != window_start.day:
        # The window spans midnight. Re-anchor to "today's window started yesterday".
        ws_yesterday = window_start - timedelta(days=1)
        we_yesterday = ws_yesterday + timedelta(minutes=duration_min)
        if now >= ws_yesterday and now < we_yesterday:
            return True
    return False


def should_attempt_install(
    *,
    now: datetime,
    config: UpdaterConfig,
    installed_version: str,
    available_version: str,
    playback_status: str,  # "playing" | "paused" | "stopped"
) -> InstallDecision:
    if not config.auto:
        return InstallDecision(install=False, reason=SkipReason.AUTO_DISABLED)
    if not available_version:
        return InstallDecision(install=False, reason=SkipReason.UP_TO_DATE)
    cmp_fn = compare_stable if config.channel == "stable" else compare_edge
    try:
        diff = cmp_fn(installed=installed_version, available=available_version)
    except ValueError:
        # An unparseable available version is treated as "no update".
        return InstallDecision(install=False, reason=SkipReason.UP_TO_DATE)
    if diff is None:
        return InstallDecision(install=False, reason=SkipReason.UP_TO_DATE)
    if not _in_window(now, config.window_start, config.window_duration_min):
        return InstallDecision(install=False, reason=SkipReason.OUTSIDE_WINDOW)
    if playback_status == "playing":
        return InstallDecision(install=False, reason=SkipReason.PLAYBACK_ACTIVE)
    return InstallDecision(install=True, reason=None)
