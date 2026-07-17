"""Setup-session token — physical-presence proof for the LAN wizard.

Mirrors the boombox-remote pairing model: the kiosk (localhost) mints a
short-lived token that it renders as a QR code on the touchscreen. A phone
that scanned that QR presents the token to authorize setup writes, proving
the person is physically at the device. Kiosk (localhost) requests are
trusted directly and skip the token.

One token at a time, stored hashed. Tokens are bearer secrets, so we compare
in constant time and never log or echo them.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

TOKEN_TTL_S = 1800  # 30 min — first-run setup is unhurried.


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class SetupSession:
    """Holds the one active setup token (hashed) and its expiry."""

    _token_hash: str | None = None
    _expires_at: float = 0.0

    def mint(self, now: float | None = None) -> tuple[str, float]:
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(24)
        self._token_hash = _hash(token)
        self._expires_at = now + TOKEN_TTL_S
        return token, self._expires_at

    def verify(self, token: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if not token or not self._token_hash:
            return False
        if now >= self._expires_at:
            return False
        return hmac.compare_digest(_hash(token), self._token_hash)

    def clear(self) -> None:
        self._token_hash = None
        self._expires_at = 0.0
