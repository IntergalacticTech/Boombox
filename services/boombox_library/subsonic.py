"""Subsonic API client for boombox-library.

All requests use token+salt auth (no plain-password transmission). Each
call generates a fresh salt so request signatures are not replayable.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any, Optional

import aiohttp

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_ID = "boombox-library"

log = logging.getLogger("boombox-library.subsonic")


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


class SubsonicError(Exception):
    """Base for all Subsonic API errors."""


class SubsonicAuthError(SubsonicError):
    """Authentication failed (HTTP 401 or response code 40/41)."""


class SubsonicUnreachable(SubsonicError):
    """Network-level failure reaching the server (timeout, DNS, refused)."""


class SubsonicClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 10.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session = session  # injected for tests; lazily created otherwise
        self._own_session = session is None

    async def __aenter__(self) -> "SubsonicClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _call(self, endpoint: str, extra_params: dict | None = None) -> dict:
        """Issue a Subsonic call; return the parsed 'subsonic-response' body.

        Raises SubsonicUnreachable on network failure,
        SubsonicAuthError on auth rejection,
        SubsonicError on other API-reported failures.
        """
        params = make_auth_params(self.username, self.password)
        if extra_params:
            params.update(extra_params)
        url = f"{self.base_url}/rest/{endpoint}.view"
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status >= 500:
                    raise SubsonicUnreachable(f"server {resp.status}")
                if resp.status == 401:
                    # Fronting proxy / reverse-proxy auth, before any Subsonic
                    # JSON envelope is produced. Surface as an auth failure.
                    raise SubsonicAuthError("http 401")
                if resp.status >= 400:
                    # Other 4xx from something in front of (or instead of) the
                    # Subsonic API — body is likely HTML, not a Subsonic
                    # envelope. Fail before attempting json() to avoid
                    # masking the real cause as "unreachable".
                    raise SubsonicError(f"http {resp.status}")
                body = await resp.json()
        except aiohttp.ClientError as e:
            raise SubsonicUnreachable(str(e)) from e

        if "subsonic-response" not in body:
            raise SubsonicError("malformed response — not a Subsonic API")
        sub = body["subsonic-response"]
        status = sub.get("status")
        if status not in ("ok", "failed"):
            raise SubsonicError("malformed response — not a Subsonic API")
        if status == "failed":
            err = sub.get("error", {})
            code = err.get("code")
            msg = err.get("message", "unknown")
            if code in (40, 41):
                raise SubsonicAuthError(f"{code}: {msg}")
            raise SubsonicError(f"{code}: {msg}")
        return sub

    async def ping(self) -> bool:
        await self._call("ping")
        return True
