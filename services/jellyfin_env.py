"""Shared Jellyfin endpoint resolution for the boombox services.

Everything that talks to Jellyfin must agree on WHERE Jellyfin is: the
transport proxy (``jellyfin_client``), the post-upload and USB-mount library
refresh triggers, and the WATCH-button kiosk navigation. Centralising that
here means a home user can point the whole device at either an on-device
Jellyfin (the default) or one running on a home server / VPS by editing a
single env var in ``/etc/boombox/jellyfin.env`` — no code change, no address
left hardcoded to loopback.

    BOOMBOX_JELLYFIN_BASE   e.g. https://video.example.com   (default local)
    BOOMBOX_JELLYFIN_KEY    path to the API-key file
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BASE = "http://127.0.0.1:8096"
DEFAULT_KEY_FILE = "/etc/boombox/jellyfin-api-key"


def jellyfin_base() -> str:
    """Base URL of the Jellyfin server, without a trailing slash.

    Read fresh each call so a service picks up an env change on restart
    without import-time caching surprises.
    """
    return os.environ.get("BOOMBOX_JELLYFIN_BASE", DEFAULT_BASE).rstrip("/")


def jellyfin_key_file() -> Path:
    return Path(os.environ.get("BOOMBOX_JELLYFIN_KEY", DEFAULT_KEY_FILE))


def jellyfin_token() -> str | None:
    """The stored Jellyfin API key, or None if unreadable/empty."""
    try:
        return jellyfin_key_file().read_text().strip() or None
    except (FileNotFoundError, OSError):
        return None
