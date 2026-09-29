"""Admin session for the LAN app's Admin sections (/api/accounts/*).

The boombox web password (BOOMBOX_WEB_PASSWORD in /etc/boombox/web-auth.env)
unlocks an in-memory bearer token: 32 random bytes as hex, 12 h idle expiry
refreshed on every use, gone when boombox-setup restarts. Tokens are kept
only as SHA-256 digests and never logged.

Lockout: LOCKOUT_ATTEMPTS failed logins within LOCKOUT_WINDOW_S refuse ALL
logins — the right password included — for LOCKOUT_S. Global, not per-IP:
the LAN is small and a per-IP limit is trivially sidestepped on it.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path
from typing import Callable

IDLE_TTL_S = 12 * 3600
LOCKOUT_ATTEMPTS = 5
LOCKOUT_WINDOW_S = 5 * 60
LOCKOUT_S = 5 * 60


def _digest(token: str) -> str:
    # surrogatepass: aiohttp decodes non-UTF-8 header bytes with
    # surrogateescape; such a token must hash (to nothing live), not raise.
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def password_matches(supplied: object, expected: str) -> bool:
    """Constant-time compare of UTF-8 bytes (compare_digest on str raises for
    non-ASCII). An empty stored password never matches anything, nor does a
    string that isn't valid UTF-8."""
    if not isinstance(supplied, str) or not expected:
        return False
    try:
        got, want = supplied.encode("utf-8"), expected.encode("utf-8")
    except UnicodeEncodeError:        # lone surrogate (e.g. JSON "\udcff")
        return False
    return hmac.compare_digest(got, want)


def read_web_password(path: Path) -> str | None:
    """BOOMBOX_WEB_PASSWORD from web-auth.env, read fresh on every call (the
    Accounts page can rotate it at runtime; the unit's EnvironmentFile copy
    goes stale), or None when unreadable/unset. Same parsing as the root
    helper: strip the line, split on the first '=', strip the value."""
    try:
        text = path.read_text()
    except (OSError, ValueError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("BOOMBOX_WEB_PASSWORD="):
            return line.split("=", 1)[1].strip() or None
    return None


class AdminSessions:
    """Live admin tokens (by digest → last use) and the login lockout."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._last_used: dict[str, float] = {}
        self._failures: list[float] = []
        self._locked_until = 0.0

    def _prune(self, now: float) -> None:
        for digest, last in list(self._last_used.items()):
            if now - last >= IDLE_TTL_S:
                del self._last_used[digest]

    def issue(self) -> tuple[str, float]:
        now = self._clock()
        self._prune(now)
        token = secrets.token_hex(32)
        self._last_used[_digest(token)] = now
        return token, now + IDLE_TTL_S

    def verify(self, token: str) -> bool:
        """True for a live token, refreshing its idle timer. The lookup is by
        SHA-256 of a 256-bit random token, so its timing reveals nothing."""
        if not token:
            return False
        now = self._clock()
        digest = _digest(token)
        last = self._last_used.get(digest)
        if last is None:
            return False
        if now - last >= IDLE_TTL_S:
            del self._last_used[digest]
            return False
        self._last_used[digest] = now
        return True

    def revoke(self, token: str) -> None:
        if token:
            self._last_used.pop(_digest(token), None)

    def locked_for(self) -> float:
        return max(0.0, self._locked_until - self._clock())

    def record_failure(self) -> bool:
        """Count a failed login; True when this failure started a lockout."""
        now = self._clock()
        self._failures = [t for t in self._failures if now - t < LOCKOUT_WINDOW_S]
        self._failures.append(now)
        if len(self._failures) >= LOCKOUT_ATTEMPTS:
            self._failures.clear()
            self._locked_until = now + LOCKOUT_S
            return True
        return False
