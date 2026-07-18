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

# Long enough that stepping away mid-setup never logs you out. The token is
# only mintable with physical access to the kiosk, only authorizes setup
# actions, and is cleared the moment setup completes.
TOKEN_TTL_S = 24 * 3600


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


CODE_MAX_ATTEMPTS = 10  # then the code is burned until the kiosk re-mints


@dataclass
class SetupSession:
    """Holds the one active setup token (hashed) and its expiry, plus a short
    numeric code so the kiosk can show a *typable* URL: a phone that can't
    scan the QR visits the base URL and enters the code to redeem the token
    (the same PIN→token shape boombox-remote uses for pairing)."""

    _token_hash: str | None = None
    _expires_at: float = 0.0
    _code_hash: str | None = None
    _code_attempts: int = 0
    # Kept in the clear only so redeem/idempotent-mint can return them;
    # never logged.
    _token: str | None = None
    _code: str | None = None

    def mint(self, now: float | None = None) -> tuple[str, str, float]:
        """Returns (token, code, expires_at).

        Idempotent while a session is live: the kiosk mints on every Welcome
        render, and re-minting there must NOT invalidate a token a phone is
        already using — a kiosk reload used to log the phone out. A fresh
        session is only minted when none exists or the current one expired."""
        now = time.time() if now is None else now
        # (_code_hash None ⇒ the code was burned by too many bad attempts —
        # treat that as no session so the kiosk shows a fresh code.)
        if (self._token is not None and self._code is not None
                and self._code_hash is not None and now < self._expires_at):
            return self._token, self._code, self._expires_at
        token = secrets.token_urlsafe(24)
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._token = token
        self._code = code
        self._token_hash = _hash(token)
        self._code_hash = _hash(code)
        self._code_attempts = 0
        self._expires_at = now + TOKEN_TTL_S
        return token, code, self._expires_at

    def verify(self, token: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if not token or not self._token_hash:
            return False
        if now >= self._expires_at:
            return False
        return hmac.compare_digest(_hash(token), self._token_hash)

    def redeem_code(self, code: str, now: float | None = None) -> str | None:
        """Exchange the on-screen code for the setup token. Constant-time
        compare; burns the code after CODE_MAX_ATTEMPTS bad tries so it can't
        be brute-forced within the session TTL."""
        now = time.time() if now is None else now
        if (not code or not self._code_hash or self._token is None
                or now >= self._expires_at):
            return None
        if self._code_attempts >= CODE_MAX_ATTEMPTS:
            return None
        if not hmac.compare_digest(_hash(code), self._code_hash):
            self._code_attempts += 1
            if self._code_attempts >= CODE_MAX_ATTEMPTS:
                self._code_hash = None
            return None
        return self._token

    def clear(self) -> None:
        self._token_hash = None
        self._expires_at = 0.0
        self._code_hash = None
        self._code_attempts = 0
        self._token = None
        self._code = None
