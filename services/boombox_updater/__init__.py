"""Boombox auto-updater.

Subpackages are purposefully small and pure where possible so unit tests
can exercise version comparison, config IO, the scheduler decision, and
the install state machine without touching git, the network, or the
filesystem outside their own tempdirs.
"""
from __future__ import annotations

from pathlib import Path

# Where to look for the installed VERSION file at runtime. Falls back to the
# repo-root VERSION (the dev source tree) if the install layout isn't there.
_INSTALLED_VERSION_FILE = Path("/opt/boombox/current/VERSION")
_DEV_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def _read_version() -> str:
    for candidate in (_INSTALLED_VERSION_FILE, _DEV_VERSION_FILE):
        try:
            return candidate.read_text().strip()
        except FileNotFoundError:
            continue
    return "unknown"


__version__ = _read_version()
