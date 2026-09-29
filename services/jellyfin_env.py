"""Shared Jellyfin endpoint resolution for the boombox services.

Everything that talks to Jellyfin must agree on WHERE Jellyfin is: the
transport proxy (``jellyfin_client``), the post-upload and USB-mount library
refresh triggers, the WATCH-button kiosk navigation, and the kiosk guard's
allow-list. Centralising that here means a home user can point the whole
device at either an on-device Jellyfin (the default) or one running on a home
server / VPS by editing a single env var in ``/etc/boombox/jellyfin.env`` — no
code change, no address left hardcoded to loopback.

    BOOMBOX_JELLYFIN_BASE   e.g. https://video.example.com   (default local)
    BOOMBOX_JELLYFIN_KEY    path to the API-key file
    BOOMBOX_JELLYFIN_ENV    path to jellyfin.env (default /etc/boombox/...)
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BASE = "http://127.0.0.1:8096"
DEFAULT_KEY_FILE = "/etc/boombox/jellyfin-api-key"
DEFAULT_ENV_FILE = "/etc/boombox/jellyfin.env"


def jellyfin_env_file() -> Path:
    return Path(os.environ.get("BOOMBOX_JELLYFIN_ENV", DEFAULT_ENV_FILE))


def jellyfin_base_from_file() -> str | None:
    """BOOMBOX_JELLYFIN_BASE as currently written in jellyfin.env, or None.

    Read fresh each call: the setup wizard rewrites the file at runtime, and
    a long-running service's inherited env (systemd EnvironmentFile=) only
    catches up on restart.
    """
    try:
        text = jellyfin_env_file().read_text()
    except (OSError, ValueError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line.startswith("BOOMBOX_JELLYFIN_BASE="):
            continue
        val = line.split("=", 1)[1].strip()
        # systemd's EnvironmentFile strips one layer of matching quotes.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1].strip()
        return val.rstrip("/") or None
    return None


def jellyfin_base() -> str:
    """Base URL of the Jellyfin server, without a trailing slash.

    Resolution: the ``BOOMBOX_JELLYFIN_BASE`` env var (systemd units load it
    from jellyfin.env), else the value in jellyfin.env itself (for processes
    whose unit doesn't load the file), else the on-device default. Read fresh
    each call so a service picks up a change without import-time caching
    surprises.
    """
    env = os.environ.get("BOOMBOX_JELLYFIN_BASE", "").strip()
    if env:
        return env.rstrip("/")
    return jellyfin_base_from_file() or DEFAULT_BASE


def jellyfin_key_file() -> Path:
    return Path(os.environ.get("BOOMBOX_JELLYFIN_KEY", DEFAULT_KEY_FILE))


def jellyfin_token() -> str | None:
    """The stored Jellyfin API key, or None if unreadable/empty."""
    try:
        return jellyfin_key_file().read_text().strip() or None
    except (FileNotFoundError, OSError):
        return None
