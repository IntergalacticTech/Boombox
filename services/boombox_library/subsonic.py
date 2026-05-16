"""Subsonic API client for boombox-library.

All requests use token+salt auth (no plain-password transmission). Each
call generates a fresh salt so request signatures are not replayable.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Optional

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_ID = "boombox-library"


def make_auth_params(
    username: str,
    password: str,
    salt: Optional[str] = None,
) -> dict:
    """Construct Subsonic auth params using the token+salt scheme.

    salt is generated per-call unless supplied (tests pin it).
    """
    if salt is None:
        salt = secrets.token_hex(8)
    token = hashlib.md5(f"{password}{salt}".encode("utf-8")).hexdigest()
    return {
        "u": username,
        "t": token,
        "s": salt,
        "v": SUBSONIC_API_VERSION,
        "c": SUBSONIC_CLIENT_ID,
        "f": "json",
    }
