"""Shared action dispatcher for every control surface (GPIO buttons,
wireless remote, future API consumers).

The Dispatcher class holds references to backend clients; action handlers
registered with @_handler look up the right client and fire the action.
Routing decisions (Mopidy vs MPRIS-via-state-API) live in the handlers
themselves — callers only know the action name.

Public API:
    Dispatcher                - dataclass holding backend client refs.
    fire(dispatcher, action, value=None, *, source="unknown") -> dict
                              - High-level entry point. Returns
                                {"ok": True} on success or
                                {"ok": False, "error": "<reason>"} otherwise.
    shutdown_sequence(...)    - pause-then-poweroff coroutine, kept here
                                so the power-button handler can call it.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from clients import Display, KioskClient, MopidyRpc, StateApi

log = logging.getLogger("boombox-buttons")


# ---------- Dispatcher ----------------------------------------------------

@dataclass
class Dispatcher:
    """Routes (action, event) pairs to their target. Holds references to
    the four backend clients; each action handler picks the right one.

    `disabled` is a set of action names that should be silently dropped —
    populated from the config's enabled flag at startup and on hot-reload.
    """
    mopidy: object | None
    state:  object | None
    kiosk:  object | None
    recorder: object | None
    display: object | None
    sleep: object | None
    disabled: set[str] | None = None

    async def dispatch(self, action: str, event: str = "short_press") -> None:
        if self.disabled and action in self.disabled:
            return
        handler = _HANDLERS.get((action, event))
        if handler is None:
            log.debug("no handler for (%s, %s)", action, event)
            return
        try:
            await handler(self)
        except Exception as exc:
            log.warning("handler %s/%s raised: %s", action, event, exc)


# Action handlers register themselves below. We separate (short_press) from
# (long_press / long_hold / long_release) so the table is explicit.
_HANDLERS: dict[tuple[str, str], Callable[[Dispatcher], Awaitable[None]]] = {}


def _handler(action: str, event: str = "short_press"):
    def deco(fn):
        _HANDLERS[(action, event)] = fn
        return fn
    return deco


# Transport — short presses
@_handler("play_pause")
async def _h_play_pause(d: Dispatcher):
    source = await d.state.current_source() if d.state else "mopidy"
    if source in (None, "mopidy"):
        if d.mopidy is None:
            return
        state = (await d.mopidy.call("core.playback.get_state")).get("result")
        await d.mopidy.call("core.playback.pause" if state == "playing" else "core.playback.play")
    else:
        await d.state.control("play-pause")


@_handler("stop")
async def _h_stop(d: Dispatcher):
    if d.mopidy:
        await d.mopidy.call("core.playback.stop")


@_handler("previous")
async def _h_previous(d: Dispatcher):
    source = await d.state.current_source() if d.state else "mopidy"
    if source in (None, "mopidy"):
        if d.mopidy:
            await d.mopidy.call("core.playback.previous")
    else:
        await d.state.control("previous")


@_handler("next")
async def _h_next(d: Dispatcher):
    source = await d.state.current_source() if d.state else "mopidy"
    if source in (None, "mopidy"):
        if d.mopidy:
            await d.mopidy.call("core.playback.next")
    else:
        await d.state.control("next")


@_handler("shuffle")
async def _h_shuffle(d: Dispatcher):
    if d.mopidy is None:
        return
    cur = (await d.mopidy.call("core.tracklist.get_random")).get("result")
    await d.mopidy.call("core.tracklist.set_random", {"value": not cur})


@_handler("repeat")
async def _h_repeat(d: Dispatcher):
    if d.mopidy is None:
        return
    repeat = (await d.mopidy.call("core.tracklist.get_repeat")).get("result")
    single = (await d.mopidy.call("core.tracklist.get_single")).get("result")
    # Cycle off -> all -> one -> off
    if not repeat and not single:
        await d.mopidy.call("core.tracklist.set_repeat", {"value": True})
        await d.mopidy.call("core.tracklist.set_single", {"value": False})
    elif repeat and not single:
        await d.mopidy.call("core.tracklist.set_single", {"value": True})
    else:
        await d.mopidy.call("core.tracklist.set_repeat", {"value": False})
        await d.mopidy.call("core.tracklist.set_single", {"value": False})


@_handler("power", "short_press")
async def _h_power_short(d: Dispatcher):
    if d.display:
        await d.display.toggle()


@_handler("power", "long_press")
async def _h_power_long(d: Dispatcher):
    """Triggered at the 2-second threshold. Show a kiosk overlay with a
    short countdown so the user can release to abort. The actual shutdown
    fires on long_release if the press is still held when the countdown
    ends; we just emit the overlay event here."""
    if d.display:
        await d.display.wake()
    if d.kiosk:
        await d.kiosk.emit("shutdown-countdown", {"seconds": 2})


@_handler("power", "long_release")
async def _h_power_release(d: Dispatcher):
    """If the kiosk's countdown completed and the user is still holding,
    long_release fires after the full hold duration. The kiosk overlay
    polls release timing itself; here we treat any long_release as confirm."""
    if d.kiosk:
        await d.kiosk.emit("shutdown-confirm", {})
    await shutdown_sequence(d.mopidy, d.state, d.kiosk, d.display)


@_handler("sleep_timer", "short_press")
async def _h_sleep(d: Dispatcher):
    if d.sleep is None:
        return
    t_ms = int(asyncio.get_running_loop().time() * 1000)
    new_mins = await d.sleep.press(t_ms)
    if d.kiosk:
        await d.kiosk.emit("sleep-timer", {"minutes": new_mins})


@_handler("sleep_timer", "long_press")
async def _h_sleep_cancel(d: Dispatcher):
    if d.sleep is None:
        return
    await d.sleep.cancel()
    if d.kiosk:
        await d.kiosk.emit("sleep-timer", {"minutes": None})


@_handler("record", "short_press")
async def _h_record(d: Dispatcher):
    if d.recorder is None:
        return
    if d.recorder.recording:
        path = await d.recorder.stop()
        if d.kiosk:
            await d.kiosk.emit("record", {"on": False, "path": path})
    else:
        path = await d.recorder.start()
        if d.kiosk:
            await d.kiosk.emit("record", {"on": True, "path": path})


# Source switch handlers
@_handler("library", "short_press")
async def _h_library(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.navigate("http://localhost/")


@_handler("airplay", "short_press")
async def _h_airplay(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.emit("source-overlay", {"source": "airplay"})


@_handler("spotify", "short_press")
async def _h_spotify(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.emit("source-overlay", {"source": "spotify"})


@_handler("bluetooth", "short_press")
async def _h_bluetooth(d: Dispatcher):
    if d.state:
        await d.state.bluetooth_pair()
    if d.kiosk:
        await d.kiosk.emit("source-overlay", {"source": "bluetooth"})


@_handler("movies", "short_press")
async def _h_movies(d: Dispatcher):
    """Toggle between SPA and Jellyfin. The kiosk-guard service is already
    aware of Jellyfin via the SourceSwitcher SPA logic; we just navigate."""
    if d.mopidy:
        await d.mopidy.call("core.playback.pause")
    if d.kiosk:
        await d.kiosk.navigate("http://localhost:8096/web/index.html#/home")


@_handler("web", "short_press")
async def _h_web(d: Dispatcher):
    """Toggle the LAN web access state + show a QR overlay. The SPA owns
    the toggle bookkeeping; we just emit and let it call /upload/enable
    or /upload/disable."""
    if d.kiosk:
        await d.kiosk.emit("web-qr", {})


@_handler("skin_cycle", "short_press")
async def _h_skin(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.emit("skin-cycle", {})


# Microphone / karaoke
@_handler("mic_karaoke", "short_press")
async def _h_mic(d: Dispatcher):
    if d.state:
        await d.state.karaoke_toggle()


# Previous/Next long-press scrub. While held, each long_hold tick seeks 5s.
async def _scrub(d: Dispatcher, delta_ms: int) -> None:
    if d.mopidy is None:
        return
    res = await d.mopidy.call("core.playback.get_time_position")
    cur = (res or {}).get("result") or 0
    await d.mopidy.call("core.playback.seek", {"time_position": max(0, cur + delta_ms)})


_HANDLERS[("previous", "long_press")] = lambda d: _scrub(d, -5000)
_HANDLERS[("previous", "long_hold")]  = lambda d: _scrub(d, -5000)
_HANDLERS[("next",     "long_press")] = lambda d: _scrub(d, +5000)
_HANDLERS[("next",     "long_hold")]  = lambda d: _scrub(d, +5000)


# ---------- Shutdown sequence ---------------------------------------------

async def shutdown_sequence(mopidy: MopidyRpc, state: StateApi, kiosk: KioskClient,
                            display: Display) -> None:
    """Pause everything, then poweroff.

    Note: we do NOT call boombox-state's /mopidy/restart endpoint (the plan
    originally proposed that as a "nudge resume to snapshot" step, but
    inspection shows it actually restarts the Mopidy systemd unit — exactly
    the wrong thing during a shutdown). boombox-resume already polls and
    writes a fresh snapshot to disk every few seconds; pausing before
    poweroff gives that loop a chance to persist the paused state, and
    systemd's shutdown ordering takes it from there. If a more granular
    snapshot trigger becomes available later, wire it in here.
    """
    log.info("shutdown: pausing playback")
    try:
        await mopidy.call("core.playback.pause")
        await state.control("pause")
    except Exception as e:
        log.warning("shutdown: pause failed (continuing to poweroff): %s", e)
    log.info("shutdown: systemctl poweroff")
    proc = await asyncio.create_subprocess_exec(
        "sudo", "-n", "systemctl", "poweroff",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        log.error("systemctl poweroff failed (%s): %s",
                  proc.returncode, (err or out).decode(errors="replace").strip())


# ---------- Volume / mute — value-aware handlers --------------------------

@_handler("volume")
async def _h_volume(d: Dispatcher, value=None):
    """Set absolute volume (0-100). Requires `value` from the remote command."""
    if d.state is None or value is None:
        return
    await d.state.volume_set(float(value))


@_handler("mute")
async def _h_mute(d: Dispatcher, value=None):
    """Toggle mute. `value` ignored — semantics are toggle, not set."""
    if d.state is None:
        return
    await d.state.mute_toggle()


# ---------- High-level entry point ----------------------------------------

import inspect as _inspect  # noqa: E402 — registered handlers above


async def fire(dispatcher: "Dispatcher", action: str, value=None, *,
               source: str = "unknown") -> dict:
    """High-level dispatch entry. Returns {ok, error?}.

    Routes short_press handlers. Handlers that declare a `value` parameter
    receive the command's `value` (e.g. `_h_volume(d, value=70)`); handlers
    that take only the dispatcher are called as before.
    """
    event = "short_press"
    if dispatcher.disabled and action in dispatcher.disabled:
        return {"ok": False, "error": "disabled"}
    handler = _HANDLERS.get((action, event))
    if handler is None:
        return {"ok": False, "error": f"unknown_action:{action}"}
    try:
        if "value" in _inspect.signature(handler).parameters:
            await handler(dispatcher, value=value)
        else:
            await handler(dispatcher)
        log.info("fired %s/%s from %s", action, event, source)
        return {"ok": True}
    except Exception as exc:
        log.warning("handler %s/%s raised: %s", action, event, exc)
        return {"ok": False, "error": "handler_raised"}
