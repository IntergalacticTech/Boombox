"""Appliance-style power state for the boombox.

One small state machine — `awake` or `asleep` — owned by boombox-state and
driven from three places: the physical power button (short press), the
kiosk UI's Off tile, and the Settings drawer. "Asleep" means audio stopped,
kiosk parked on Home and the panel dark; after a grace period the Pi halts,
so an idle boombox draws no power but a mistaken press is recoverable by
touching the screen.

Everything that touches hardware is an injected coroutine (`stop_audio`,
`display_off`, `display_on`, `kiosk_home`, `poweroff`), which keeps this
module unit-testable and lets a partially-wired device run: every callback
is optional and best-effort. A failing `wlr-randr` is logged and the
sequence continues — a dark screen with a stuck timer is worse than a
missed backlight call.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("boombox-state")

Hook = Callable[[], Awaitable[None]] | Callable[[], None] | None

AWAKE = "awake"
ASLEEP = "asleep"

DEFAULT_GRACE_S = 180.0


def default_state_file() -> Path:
    """`$XDG_STATE_HOME/boombox/power.json`, or the XDG default under $HOME."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    return Path(base) / "boombox" / "power.json"


class PowerManager:
    """Tracks awake/asleep and runs the transition sequences.

    `grace_s` is the delay between falling asleep and halting the Pi; `0`
    disables the auto-poweroff entirely (the panel still sleeps).
    """

    def __init__(
        self,
        stop_audio: Hook = None,
        display_off: Hook = None,
        display_on: Hook = None,
        kiosk_home: Hook = None,
        poweroff: Hook = None,
        grace_s: float = DEFAULT_GRACE_S,
        state_file: str | os.PathLike[str] | None = None,
    ):
        self._stop_audio = stop_audio
        self._display_off = display_off
        self._display_on = display_on
        self._kiosk_home = kiosk_home
        self._poweroff = poweroff
        self.grace_s = float(grace_s or 0)
        self.state_file = Path(state_file) if state_file else default_state_file()

        # Always boot awake: a crash mid-sleep must not leave the panel dark.
        self.state: str = AWAKE
        self.since: float = time.time()
        self.poweroff_at: float | None = None
        self._timer: asyncio.Task | None = None

    # ---------- public API ------------------------------------------------

    def snapshot(self) -> dict:
        return {"state": self.state, "since": self.since,
                "poweroff_at": self.poweroff_at}

    async def start(self) -> dict:
        """Startup reconciliation. We're awake by construction; if the last
        persisted snapshot said asleep, the panel is probably still off, so
        force it back on."""
        if self._persisted_state() == ASLEEP:
            log.info("power: last snapshot was asleep — forcing display on")
            await self._fire("display_on", self._display_on)
            self._persist()
        return self.snapshot()

    async def sleep(self) -> dict:
        """Stop audio, park the kiosk on Home, blank the panel, arm the halt.
        Idempotent: a second sleep() while asleep does not re-arm the timer."""
        if self.state == ASLEEP:
            return self.snapshot()
        # Flip state first so /state readers (and the UI) react immediately,
        # before the slower subprocess/HTTP hops below.
        self.state = ASLEEP
        self.since = time.time()
        self.poweroff_at = self.since + self.grace_s if self.grace_s > 0 else None
        self._persist()

        await self._fire("stop_audio", self._stop_audio)
        await self._fire("kiosk_home", self._kiosk_home)
        await self._fire("display_off", self._display_off)
        self._arm_timer()
        return self.snapshot()

    async def wake(self) -> dict:
        """Cancel the halt and bring the panel back. Never resumes playback."""
        if self.state == AWAKE:
            return self.snapshot()
        self._cancel_timer()
        await self._fire("display_on", self._display_on)
        self.state = AWAKE
        self.since = time.time()
        self._persist()
        return self.snapshot()

    async def toggle(self) -> dict:
        return await (self.wake() if self.state == ASLEEP else self.sleep())

    async def off(self) -> dict:
        """Sleep, then halt now instead of after the grace period."""
        await self.sleep()
        self._cancel_timer()
        await self._fire("poweroff", self._poweroff)
        return self.snapshot()

    # ---------- internals -------------------------------------------------

    async def _fire(self, name: str, hook: Hook) -> None:
        """Run an optional hook; log and swallow anything it throws."""
        if hook is None:
            return
        try:
            result = hook()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            log.warning("power: %s hook failed (continuing): %s", name, e)

    def _arm_timer(self) -> None:
        if self.poweroff_at is None:
            return
        delay = max(0.0, self.poweroff_at - time.time())

        async def _runner():
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if self.state != ASLEEP:      # woken between tick and wake-up
                return
            log.info("power: grace period elapsed — powering off")
            await self._fire("poweroff", self._poweroff)

        self._timer = asyncio.create_task(_runner())

    def _cancel_timer(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = None
        self.poweroff_at = None

    def _persisted_state(self) -> str | None:
        try:
            body = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return None
        state = body.get("state") if isinstance(body, dict) else None
        return state if state in (AWAKE, ASLEEP) else None

    def _persist(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.snapshot()))
        except OSError as e:
            log.warning("power: could not write %s: %s", self.state_file, e)
