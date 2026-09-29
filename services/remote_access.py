"""Persistent 'remote access enabled' flag for boombox-remote, plus the small
pieces of remote-access state shared by the HTTP and BLE transports.

The phone-facing remote surface is gated by a single on/off flag, default
off, persisted alongside peers.json. The touchscreen toggles it. The BLE
peripheral and the already-paired CYD hardware remote are NOT gated by it —
the flag is a privacy gate against arbitrary phones on the WiFi, not a
master kill switch for paired hardware.

Also here: `write_json_atomic` (peers.json holds bearer tokens — write it
0600 and never leave a torn file behind) and `redeem_pin`, the one PIN check
both pairing transports use, which burns the PIN after PAIR_MAX_ATTEMPTS
wrong guesses.
"""
from __future__ import annotations

import contextlib
import hmac
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("boombox-remote")

DEFAULT_STATE = Path.home() / ".config" / "boombox-remote" / "state.json"

# Wrong PINs allowed per pairing window before the PIN is burned and the
# kiosk must mint a fresh one (same idea as boombox_setup.session's
# CODE_MAX_ATTEMPTS). 5 guesses at a 6-digit PIN ⇒ a 1-in-200,000 chance per
# kiosk-issued window, instead of unlimited guesses for the whole TTL.
PAIR_MAX_ATTEMPTS = 5


def _state_path() -> Path:
    """Resolve the state file path. Re-reads env on every call so tests can
    override BOOMBOX_REMOTE_STATE between calls."""
    return Path(os.environ.get("BOOMBOX_REMOTE_STATE", str(DEFAULT_STATE)))


def write_json_atomic(path: Path, data: Any, mode: int = 0o600) -> None:
    """Write JSON via tmp file + fsync + rename, so a crash or power cut
    mid-write never leaves a truncated file (a torn peers.json reads as {}
    and would silently unpair every remote). The file is created `mode`
    (0600 by default — peers.json holds bearer tokens). Creates the parent
    directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def is_enabled() -> bool:
    """True when remote access is on. A missing or malformed file reads as
    off — the conservative default. This includes valid JSON that isn't an
    object (e.g. a bare list or number)."""
    try:
        data = json.loads(_state_path().read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("enabled", False))


def set_enabled(enabled: bool) -> None:
    """Persist the flag. Creates the parent directory if needed."""
    write_json_atomic(_state_path(), {"enabled": bool(enabled)})


def redeem_pin(state: dict, pin: str, hash_pin: Callable[[str], str],
               now: float | None = None) -> str | None:
    """Check `pin` against the shared pairing state ({pin_hash, expires_at,
    attempts}). Returns None on a match — consuming the PIN (single use) —
    or an error code: "no_active_pin" (none issued, expired, or burned) or
    "bad_pin". The PAIR_MAX_ATTEMPTS-th wrong guess burns the PIN."""
    now = time.time() if now is None else now
    if state.get("pin_hash") is None or now > state.get("expires_at", 0):
        return "no_active_pin"
    if not hmac.compare_digest(hash_pin(pin), state["pin_hash"]):
        state["attempts"] = state.get("attempts", 0) + 1
        if state["attempts"] >= PAIR_MAX_ATTEMPTS:
            state["pin_hash"] = None
            state["expires_at"] = 0
            log.warning("pairing PIN burned after %d wrong attempts",
                        state["attempts"])
        return "bad_pin"
    state["pin_hash"] = None
    state["expires_at"] = 0
    state["attempts"] = 0
    return None
