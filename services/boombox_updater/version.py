"""Channel-aware version comparison for the auto-updater.

Stable channel: PEP 440 versions (`v0.5.0`, `v0.5.0-rc1`, `0.5.0-dev`).
Edge channel: git short shas. Equal-prefix match counts as same commit so
that the locally-stored short sha can be compared to GitHub's long sha.

`installed` may be the literal `"legacy"` (migrated installs) or
`"unknown"` (read failure) — both treated as definitely outdated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class UpdateAvailable:
    """Returned when the available version differs from installed."""
    available: str
    installed: str


_SENTINELS_ALWAYS_OUTDATED = {"legacy", "unknown", ""}


def parse_stable(s: str) -> Version:
    """Parse a stable-channel version string. Strips a leading 'v'."""
    cleaned = s.lstrip("v")
    return Version(cleaned)  # raises InvalidVersion (a ValueError subclass)


def compare_stable(*, installed: str, available: str) -> Optional[UpdateAvailable]:
    """Return UpdateAvailable if `available` is newer than `installed`."""
    avail = parse_stable(available)
    if installed in _SENTINELS_ALWAYS_OUTDATED:
        return UpdateAvailable(available=available, installed=installed)
    try:
        inst = parse_stable(installed)
    except InvalidVersion:
        # Anything we can't parse is treated as outdated rather than crash.
        return UpdateAvailable(available=available, installed=installed)
    if avail > inst:
        return UpdateAvailable(available=available, installed=installed)
    return None


def compare_edge(*, installed: str, available: str) -> Optional[UpdateAvailable]:
    """Return UpdateAvailable if the available sha differs from installed.

    A short sha matches a long sha if it's a prefix of it (or vice versa).
    """
    if not installed or not available:
        return UpdateAvailable(available=available, installed=installed)
    a, b = installed.lower(), available.lower()
    if a == b or a.startswith(b) or b.startswith(a):
        return None
    return UpdateAvailable(available=available, installed=installed)
