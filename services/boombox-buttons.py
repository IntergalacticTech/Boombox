#!/usr/bin/env python3
"""Boombox GPIO button + rotary encoder driver.

Owns the physical control surface described in
docs/superpowers/specs/2026-05-12-gpio-buttons-design.md: 17 buttons + 1
rotary encoder with push. Every action is independently disable-able via
/etc/boombox/buttons.json. Pin assignments are user-editable via that file
or via the Settings drawer's Buttons panel (which writes the file).

Listens on aiohttp 127.0.0.1:6683 for /config, /learn, /test endpoints used
by the Settings panel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-buttons")

CONFIG_PATH = Path(os.environ.get("BOOMBOX_BUTTONS_FILE", "/etc/boombox/buttons.json"))


# ---------- Config ---------------------------------------------------------

# Every action ships disabled-by-default? No — the design is "all wired by
# default, user nulls out what they didn't solder." That matches the "more
# the merrier" preference: ship the full inventory, users disable rather
# than enable. Pin assignments come from the spec.
_DEFAULT_PINS = {
    "play_pause":  {"pin": 4,  "enabled": True},
    "stop":        {"pin": 5,  "enabled": True},
    "previous":    {"pin": 6,  "enabled": True},
    "next":        {"pin": 12, "enabled": True},
    "shuffle":     {"pin": 13, "enabled": True},
    "repeat":      {"pin": 7,  "enabled": True},
    "sleep_timer": {"pin": 8,  "enabled": True},
    "skin_cycle":  {"pin": 9,  "enabled": True},
    "library":     {"pin": 10, "enabled": True},
    "airplay":     {"pin": 16, "enabled": True},
    "spotify":     {"pin": 17, "enabled": True},
    "bluetooth":   {"pin": 22, "enabled": True},
    "movies":      {"pin": 23, "enabled": True},
    "web":         {"pin": 24, "enabled": True},
    "mic_karaoke": {"pin": 25, "enabled": True},
    "record":      {"pin": 26, "enabled": True},
    "power":       {"pin": 27, "enabled": True},
}

_DEFAULT_ENCODER = {"pin_a": 14, "pin_b": 15, "pin_push": 11, "enabled": True}


def default_config() -> dict:
    return {
        "long_press_ms": 600,
        "power_hold_ms": 2000,
        "encoder_step": 5,
        "pins": deepcopy(_DEFAULT_PINS),
        "encoder": deepcopy(_DEFAULT_ENCODER),
    }


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        base_v = out.get(k)
        if isinstance(v, dict) and isinstance(base_v, dict):
            out[k] = _merge(base_v, v)
        elif v is None and isinstance(base_v, dict):
            # Reject `None` override of a default dict (e.g. {"pins": null}).
            # The default stays; the load_config caller would otherwise crash.
            continue
        else:
            out[k] = v
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        log.info("no %s; using defaults", path)
        return default_config()
    try:
        user = json.loads(path.read_text())
        if not isinstance(user, dict):
            raise ValueError("config root must be an object")
    except Exception as e:
        log.warning("could not read %s: %s — using defaults", path, e)
        return default_config()
    return _merge(default_config(), user)


def enabled_pins(cfg: dict) -> dict[str, int]:
    """Return {action_name: pin} for everything that is wired AND enabled.

    Encoder lines appear as `encoder_a`, `encoder_b`, `encoder_push`.
    """
    out: dict[str, int] = {}
    for name, entry in cfg["pins"].items():
        if entry.get("enabled") and entry.get("pin") is not None:
            out[name] = int(entry["pin"])
    enc = cfg.get("encoder") or {}
    if enc.get("enabled"):
        for k_in, k_out in (("pin_a", "encoder_a"), ("pin_b", "encoder_b"), ("pin_push", "encoder_push")):
            if enc.get(k_in) is not None:
                out[k_out] = int(enc[k_in])
    return out


def pin_conflicts(cfg: dict) -> list[tuple[int, list[str]]]:
    """Return (pin, [action_names_in_alpha_order]) for every pin used by more
    than one enabled action. Empty list = no conflicts.
    """
    by_pin: dict[int, list[str]] = {}
    for name, pin in enabled_pins(cfg).items():
        by_pin.setdefault(pin, []).append(name)
    return [(p, sorted(ns)) for p, ns in sorted(by_pin.items()) if len(ns) > 1]


# ---------- Press classifier ----------------------------------------------

class PressClassifier:
    """State machine: receives (timestamp_ms, edge) events plus periodic ticks,
    emits ("short_press",) / ("long_press",) / ("long_hold",) / ("long_release",).

    No GPIO awareness — pure logic, fully testable. The GPIO loop wires
    falling edges to feed(edge="down") and rising edges to feed(edge="up").
    """

    def __init__(self, long_press_ms: int, long_hold_tick_ms: int = 200):
        self._long_ms = long_press_ms
        self._tick_ms = long_hold_tick_ms
        self._down_at: int | None = None
        self._long_fired: bool = False
        self._last_hold_at: int | None = None

    def feed(self, t_ms: int, edge: str):
        if edge == "down":
            if self._down_at is not None:
                return  # already pressed; ignore duplicates
            self._down_at = t_ms
            self._long_fired = False
            self._last_hold_at = None
            return
        if edge == "up":
            if self._down_at is None:
                return
            held = t_ms - self._down_at
            self._down_at = None
            if self._long_fired:
                self._long_fired = False
                self._last_hold_at = None
                yield ("long_release",)
            else:
                if held < self._long_ms:
                    yield ("short_press",)

    def tick(self, t_ms: int):
        if self._down_at is None:
            return
        held = t_ms - self._down_at
        if not self._long_fired and held >= self._long_ms:
            self._long_fired = True
            self._last_hold_at = t_ms
            yield ("long_press",)
            return
        if self._long_fired:
            if self._last_hold_at is None:
                self._last_hold_at = t_ms
            if t_ms - self._last_hold_at >= self._tick_ms:
                self._last_hold_at = t_ms
                yield ("long_hold",)


# ---------- Rotary encoder decoder ----------------------------------------

class EncoderDecoder:
    """Decodes a two-phase quadrature encoder. Emits ("cw",) or ("ccw",)
    once per detent (full cycle returning to 11)."""

    # Transition table indexed by ((prev_a, prev_b), (a, b)) -> direction or 0.
    # Built from the canonical 4-state Gray code transitions: a CW detent
    # walks the sequence 11 -> 01 -> 00 -> 10 -> 11 (and CCW reversed).
    _TRANSITION = {
        ((1, 1), (0, 1)): +1, ((0, 1), (0, 0)): +1, ((0, 0), (1, 0)): +1, ((1, 0), (1, 1)): +1,
        ((1, 1), (1, 0)): -1, ((1, 0), (0, 0)): -1, ((0, 0), (0, 1)): -1, ((0, 1), (1, 1)): -1,
    }

    def __init__(self):
        self._state: tuple[int, int] = (1, 1)
        self._accum: int = 0

    def feed(self, a: int, b: int):
        new_state = (a, b)
        if new_state == self._state:
            return
        delta = self._TRANSITION.get((self._state, new_state), 0)
        self._state = new_state
        self._accum += delta
        # A complete detent traverses 4 sub-transitions = ±4 accumulated.
        while self._accum >= 4:
            self._accum -= 4
            yield ("cw",)
        while self._accum <= -4:
            self._accum += 4
            yield ("ccw",)


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


# ---------- Backend clients -----------------------------------------------

import aiohttp

MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
STATE_BASE = "http://127.0.0.1:6681"
KIOSK_DEBUG = "http://127.0.0.1:9222"


class MopidyRpc:
    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session
        self._id = 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        try:
            async with self._sess.post(MOPIDY_RPC, json=body,
                                       timeout=aiohttp.ClientTimeout(total=2)) as r:
                if r.status != 200:
                    return {}
                return await r.json(content_type=None)
        except Exception as e:
            log.warning("mopidy.%s failed: %s", method, e)
            return {}


class StateApi:
    """Thin client for the boombox-state aggregator at :6681.

    `current_source()` returns the lowercase friendly source name
    ('mopidy', 'airplay', 'spotify', 'bluetooth') or None when nothing is
    playing.
    """

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    async def current_source(self) -> str | None:
        try:
            async with self._sess.get(f"{STATE_BASE}/state",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                if r.status != 200:
                    return None
                body = await r.json()
        except Exception:
            return None
        label = (body.get("label") or "").lower()
        return label or None

    async def control(self, action: str) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/control/{action}",
                                   timeout=aiohttp.ClientTimeout(total=2))
        except Exception as e:
            log.warning("state.control(%s) failed: %s", action, e)

    async def volume_get(self) -> tuple[float, bool] | None:
        try:
            async with self._sess.get(f"{STATE_BASE}/volume",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                body = await r.json()
                if not body.get("ok"):
                    return None
                return float(body["volume"]), bool(body.get("muted"))
        except Exception:
            return None

    async def volume_set(self, volume: float) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/volume", json={"volume": volume},
                                  timeout=aiohttp.ClientTimeout(total=1))
        except Exception as e:
            log.warning("state.volume_set failed: %s", e)

    async def mute_toggle(self) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/volume/mute",
                                  timeout=aiohttp.ClientTimeout(total=1))
        except Exception as e:
            log.warning("state.mute_toggle failed: %s", e)

    async def karaoke_state(self) -> bool:
        try:
            async with self._sess.get(f"{STATE_BASE}/karaoke",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                body = await r.json()
                return bool(body.get("on"))
        except Exception:
            return False

    async def karaoke_toggle(self) -> None:
        on = await self.karaoke_state()
        path = "/karaoke/off" if on else "/karaoke/on"
        try:
            await self._sess.post(f"{STATE_BASE}{path}",
                                  timeout=aiohttp.ClientTimeout(total=2))
        except Exception as e:
            log.warning("state.karaoke_toggle failed: %s", e)

    async def bluetooth_pair(self) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/bluetooth/pair",
                                  timeout=aiohttp.ClientTimeout(total=5))
        except Exception as e:
            log.warning("state.bluetooth_pair failed: %s", e)


class KioskClient:
    """DevTools client for the Chromium kiosk on :9222. Drives navigation
    and runs JS in the kiosk tab. Used for source overlays, swap-to-Jellyfin,
    QR code, sleep OSD, etc."""

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    async def _tab(self) -> dict | None:
        try:
            async with self._sess.get(f"{KIOSK_DEBUG}/json",
                                       timeout=aiohttp.ClientTimeout(total=1)) as r:
                tabs = await r.json()
                for t in tabs:
                    if t.get("type") == "page":
                        return t
        except Exception:
            return None
        return None

    async def navigate(self, url: str) -> None:
        tab = await self._tab()
        if not tab:
            return
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        try:
            import websockets
            async with websockets.connect(ws_url, open_timeout=2, max_size=2**24) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Page.navigate",
                                           "params": {"url": url}}))
        except Exception as e:
            log.warning("kiosk.navigate(%s) failed: %s", url, e)

    async def emit(self, event: str, detail: dict | None = None) -> None:
        """Dispatch a custom DOM event on the kiosk page so the SPA can
        react (overlay mount/unmount). The SPA listens on
        window.addEventListener('boombox:<event>')."""
        tab = await self._tab()
        if not tab:
            return
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        script = (
            f"window.dispatchEvent(new CustomEvent('boombox:{event}', "
            f"{{detail: {json.dumps(detail or {})}}}))"
        )
        try:
            import websockets
            async with websockets.connect(ws_url, open_timeout=2, max_size=2**24) as ws:
                await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                          "params": {"expression": script}}))
        except Exception as e:
            log.warning("kiosk.emit(%s) failed: %s", event, e)


# ---------- Display backlight ---------------------------------------------

class Display:
    """Wayland backlight control via wlr-randr. Async subprocess calls.

    On the kiosk, `wlr-randr` returns the active output's name on its first
    line. We cache it after the first call."""

    def __init__(self):
        self._output: str | None = None
        self._on: bool = True

    async def _detect_output(self) -> str | None:
        """Return the cached Wayland output name; query wlr-randr on first call.

        We pick the first non-indented line of wlr-randr's output, which is the
        connected output's name. Assumes one panel (the kiosk's DSI-1 in this
        build). If multiple outputs are connected, the kiosk should still be on
        the first; multi-output is out of scope.
        """
        if self._output:
            return self._output
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("wlr-randr failed (%s): %s",
                        proc.returncode, err.decode(errors="replace").strip())
            return None
        for line in out.decode().splitlines():
            if line and not line.startswith(" "):
                self._output = line.split()[0]
                return self._output
        return None

    async def toggle(self) -> None:
        out = await self._detect_output()
        if not out:
            return
        new = "off" if self._on else "on"
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr", "--output", out, "--" + new,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("wlr-randr --%s failed (%s): %s", new, proc.returncode,
                        err.decode(errors="replace").strip())
            return
        self._on = not self._on

    async def wake(self) -> None:
        out = await self._detect_output()
        if not out:
            return
        # Always send --on. If the display is already on, wlr-randr is a no-op;
        # if our cached _on state is stale (external tooling toggled the panel),
        # this still does the right thing.
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr", "--output", out, "--on",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("wlr-randr --on failed (%s): %s", proc.returncode,
                        err.decode(errors="replace").strip())
            return
        self._on = True

    @property
    def is_on(self) -> bool:
        """Public read-only view of the cached backlight state. Used by the
        sleep-timer expire path so we only invoke toggle() when the screen is
        currently on (avoids waking an already-asleep panel)."""
        return self._on


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


# ---------- Sleep timer ---------------------------------------------------

class SleepTimer:
    """Cycles 15 -> 30 -> 60 -> off -> 15 (subsequent presses within 3s
    cycle the duration; otherwise the first press sets the next value).
    Long-press cancels.

    Fires by calling on_expire() (set externally). The dispatcher hooks
    in pause + display sleep + kiosk OSD events at startup."""

    _CYCLE = [15, 30, 60, None]

    def __init__(self, on_expire: Callable[[], Awaitable[None]]):
        self._on_expire = on_expire
        self._idx: int = -1            # -1 = inactive
        self._task: asyncio.Task | None = None
        self._last_press_ms: int | None = None

    @property
    def active_minutes(self) -> int | None:
        if self._idx < 0:
            return None
        return self._CYCLE[self._idx]

    async def press(self, t_ms: int) -> int | None:
        """Returns the new value in minutes, or None when cycled to off."""
        if self._last_press_ms is not None and (t_ms - self._last_press_ms) <= 3000:
            self._idx = (self._idx + 1) % len(self._CYCLE)
        else:
            self._idx = 0
        self._last_press_ms = t_ms
        await self._reschedule()
        return self.active_minutes

    async def cancel(self) -> None:
        self._idx = -1
        await self._reschedule()

    async def _reschedule(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        mins = self.active_minutes
        if mins is None:
            return
        async def _runner():
            try:
                await asyncio.sleep(mins * 60)
                await self._on_expire()
            except asyncio.CancelledError:
                return
        self._task = asyncio.create_task(_runner())


# ---------- Recorder ------------------------------------------------------

class Recorder:
    """Captures the current default PipeWire sink's monitor to FLAC.
    Start = spawn `parec | flac -`. Stop = SIGTERM the pipeline.

    Output: ~/Music/Recordings/YYYY-MM-DD-HHMMSS.flac
    """

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._flac: asyncio.subprocess.Process | None = None
        self._path: str | None = None

    @property
    def recording(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> str | None:
        if self.recording:
            return self._path
        rec_dir = Path.home() / "Music" / "Recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = rec_dir / f"{ts}.flac"
        self._path = str(out)
        # parec → flac via a real OS pipe. We can't use asyncio's PIPE here
        # because asyncio gives back a StreamReader for parec.stdout and
        # asyncio.create_subprocess_exec rejects non-fileno stdin.
        read_fd, write_fd = os.pipe()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "parec", "--device=@DEFAULT_MONITOR@",
                "--format=s16le", "--rate=44100", "--channels=2",
                stdout=write_fd, stderr=asyncio.subprocess.DEVNULL,
            )
            self._flac = await asyncio.create_subprocess_exec(
                "flac", "--silent",
                "--endian=little", "--sign=signed",
                "--channels=2", "--bps=16", "--sample-rate=44100",
                "-", "-o", str(out),
                stdin=read_fd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        finally:
            # Each subprocess inherits its end; close our parent-side copies.
            os.close(write_fd)
            os.close(read_fd)
        return self._path

    async def stop(self) -> str | None:
        path = self._path
        for p in (self._proc, self._flac):
            if p is not None and p.returncode is None:
                p.terminate()
                try:
                    await asyncio.wait_for(p.wait(), timeout=3)
                except asyncio.TimeoutError:
                    p.kill()
        self._proc = None
        self._flac = None
        self._path = None
        return path


# ---------- GPIO event loop -----------------------------------------------

# `gpiod` is Linux-only; import lazily so the module remains importable on
# dev machines (macOS) where the test suite runs.

GPIO_CHIP = "/dev/gpiochip0"
DEBOUNCE_MS = 30
ENCODER_DEBOUNCE_MS = 1
TICK_INTERVAL_S = 0.05  # 20Hz; resolves long-press windows precisely enough


async def gpio_loop(cfg: dict, dispatcher: Dispatcher, stop: asyncio.Event,
                    learn_state: dict | None = None) -> None:
    """Single-pass GPIO loop. Re-call to rebuild after config hot-reload.
    Returns when `stop` is set.

    `learn_state` is a shared dict (mutated by the HTTP API's /learn handler):
    when in learn mode it holds {"action": "<name>", "until": <t_ms>,
    "result": None|<pin>}. While `t_ms < until` and `action` is set, the next
    falling-edge button press is captured into `result` instead of dispatched.
    """
    import gpiod
    from datetime import timedelta
    from gpiod.line import Direction, Bias, Edge

    if learn_state is None:
        learn_state = {"action": None, "until": 0, "result": None}

    pins = enabled_pins(cfg)
    if not pins:
        log.info("no GPIO pins configured; idling")
        await stop.wait()
        return

    long_ms = int(cfg.get("long_press_ms", 600))
    power_hold_ms = int(cfg.get("power_hold_ms", 2000))

    # gpiod line config: encoder phases get fast debounce + both-edge so we
    # see every quadrature transition; buttons get falling-edge only.
    line_config: dict[int, gpiod.LineSettings] = {}
    by_pin: dict[int, str] = {}
    for action, pin in pins.items():
        by_pin[pin] = action
        if action in ("encoder_a", "encoder_b"):
            line_config[pin] = gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,
                debounce_period=timedelta(milliseconds=ENCODER_DEBOUNCE_MS),
            )
        else:
            line_config[pin] = gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,  # need both so we can detect release
                debounce_period=timedelta(milliseconds=DEBOUNCE_MS),
            )

    log.info("gpio pins: %s", ", ".join(f"{a}=BCM{p}" for a, p in pins.items()))

    # Press classifiers per button action. Power gets the longer threshold.
    classifiers: dict[str, PressClassifier] = {
        action: PressClassifier(
            long_press_ms=power_hold_ms if action == "power" else long_ms,
        )
        for action in pins if action not in ("encoder_a", "encoder_b", "encoder_push")
    }
    encoder = EncoderDecoder()
    enc_a_state = enc_b_state = 1

    with gpiod.request_lines(GPIO_CHIP, consumer="boombox-buttons", config=line_config) as req:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def reader():
            try:
                while not stop.is_set():
                    if req.wait_edge_events(timeout=0.5):
                        for ev in req.read_edge_events():
                            loop.call_soon_threadsafe(queue.put_nowait, ev)
            except Exception:
                # A dead reader is fatal — surface it loudly and tear down the loop so
                # systemd restarts us rather than silently going dead.
                log.exception("gpiod reader thread crashed; signalling stop")
                loop.call_soon_threadsafe(stop.set)

        reader_fut = loop.run_in_executor(None, reader)

        async def tick():
            while not stop.is_set():
                t_ms = int(loop.time() * 1000)
                for action, pc in classifiers.items():
                    for evt in pc.tick(t_ms):
                        await dispatcher.dispatch(action, evt[0])
                await asyncio.sleep(TICK_INTERVAL_S)

        ticker = asyncio.create_task(tick())

        try:
            while not stop.is_set():
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                t_ms = int(loop.time() * 1000)
                action = by_pin.get(ev.line_offset)
                if not action:
                    continue
                if action == "encoder_a":
                    enc_a_state = 0 if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else 1
                    for evt in encoder.feed(enc_a_state, enc_b_state):
                        await dispatcher.dispatch("encoder", evt[0])
                elif action == "encoder_b":
                    enc_b_state = 0 if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else 1
                    for evt in encoder.feed(enc_a_state, enc_b_state):
                        await dispatcher.dispatch("encoder", evt[0])
                elif action == "encoder_push":
                    if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE:
                        await dispatcher.dispatch("encoder_push", "short_press")
                else:
                    edge = "down" if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else "up"
                    if edge == "down" and learn_state.get("action") and t_ms < learn_state.get("until", 0):
                        learn_state["result"] = ev.line_offset
                        continue   # don't dispatch, just capture
                    for evt in classifiers[action].feed(t_ms, edge):
                        await dispatcher.dispatch(action, evt[0])
        finally:
            ticker.cancel()


# ---------- Main ----------------------------------------------------------

async def main() -> None:
    cfg = load_config()
    conflicts = pin_conflicts(cfg)
    for pin, names in conflicts:
        log.error("pin conflict: BCM%s used by %s — disable all but one", pin, names)

    async with aiohttp.ClientSession() as sess:
        mopidy = MopidyRpc(sess)
        state = StateApi(sess)
        kiosk = KioskClient(sess)
        # Subsystems wired in later tasks:
        recorder = Recorder()
        display = Display()

        async def _on_sleep_expire():
            try:
                await mopidy.call("core.playback.pause")
                await state.control("pause")
                if display and display.is_on:
                    await display.toggle()  # sleep the screen
                if kiosk:
                    await kiosk.emit("sleep-expired", {})
            except Exception as e:
                log.warning("sleep expire failed: %s", e)
        sleep_t = SleepTimer(on_expire=_on_sleep_expire)
        disabled = {a for a, e in cfg["pins"].items() if not e.get("enabled")}
        dispatcher = Dispatcher(mopidy=mopidy, state=state, kiosk=kiosk,
                                recorder=recorder, display=display, sleep=sleep_t,
                                disabled=disabled)

        cfg_ref = [cfg]
        # Encoder rotation handlers — these always go through volume. They
        # close over cfg_ref (not cfg) so a hot-reload's new encoder_step is
        # picked up on the next tick without restarting the service.
        async def _enc_cw(d: Dispatcher):
            cur = await d.state.volume_get()
            if cur is None:
                return
            step = (cfg_ref[0].get("encoder_step", 5)) / 100.0
            await d.state.volume_set(min(1.0, cur[0] + step))
        async def _enc_ccw(d: Dispatcher):
            cur = await d.state.volume_get()
            if cur is None:
                return
            step = (cfg_ref[0].get("encoder_step", 5)) / 100.0
            await d.state.volume_set(max(0.0, cur[0] - step))
        async def _enc_push(d: Dispatcher):
            await d.state.mute_toggle()
        _HANDLERS[("encoder", "cw")] = _enc_cw
        _HANDLERS[("encoder", "ccw")] = _enc_ccw
        _HANDLERS[("encoder_push", "short_press")] = _enc_push

        dispatcher_ref = [dispatcher]
        learn_state: dict = {"action": None, "until": 0, "result": None}
        api_runner = await _http_api(cfg_ref, dispatcher_ref, learn_state)

        # Wrap the loop so we can rebuild it on config change.
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        reload_event = asyncio.Event()
        loop_ref = asyncio.get_running_loop()

        class _Handler(FileSystemEventHandler):
            def _hit(self, path: str) -> bool:
                return Path(path) == CONFIG_PATH

            def on_modified(self, event):
                if self._hit(event.src_path):
                    loop_ref.call_soon_threadsafe(reload_event.set)

            def on_created(self, event):
                # `sudo mv tmp config` atomically replaces the inode and
                # surfaces as a CREATE on the destination, not a MODIFY.
                if self._hit(event.src_path):
                    loop_ref.call_soon_threadsafe(reload_event.set)

            def on_moved(self, event):
                # Some editors (vim, sed -i) rename a temp file into place.
                # Watchdog emits this as a MOVED event whose dest is our file.
                dest = getattr(event, "dest_path", None)
                if dest and self._hit(dest):
                    loop_ref.call_soon_threadsafe(reload_event.set)

        observer = Observer()
        observer.schedule(_Handler(), str(CONFIG_PATH.parent), recursive=False)
        observer.start()

        import signal
        loop = asyncio.get_running_loop()
        try:
            while True:
                stop = asyncio.Event()
                # Install signal handlers per loop iteration so SIGTERM still wins.
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, stop.set)
                loop_task = asyncio.create_task(
                    gpio_loop(cfg_ref[0], dispatcher, stop, learn_state=learn_state)
                )
                wait_reload = asyncio.create_task(reload_event.wait())
                done, _ = await asyncio.wait(
                    {loop_task, wait_reload}, return_when=asyncio.FIRST_COMPLETED
                )
                if wait_reload in done:
                    log.info("config changed; rebuilding gpio loop")
                    reload_event.clear()
                    stop.set()
                    await loop_task
                    cfg = load_config()
                    cfg_ref[0] = cfg
                    dispatcher.disabled = {a for a, e in cfg["pins"].items() if not e.get("enabled")}
                    continue
                # Otherwise: the gpio_loop returned (probably SIGTERM-driven stop).
                # Cancel the dangling reload waiter before exiting.
                wait_reload.cancel()
                try:
                    await wait_reload
                except asyncio.CancelledError:
                    pass
                break
        finally:
            observer.stop()
            observer.join()
            await api_runner.cleanup()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, ValueError):
                    pass


# ---------- Settings HTTP API ---------------------------------------------

from aiohttp import web

BUTTONS_API_PORT = 6684


async def _http_api(cfg_ref: list, dispatcher_ref: list, learn_state: dict) -> web.AppRunner:
    """cfg_ref and dispatcher_ref are single-element lists so the handlers
    can mutate them when the config hot-reloads.

    learn_state is a dict shared with the GPIO loop; when in learn mode it
    is {"action": "<name>", "until": <t_ms>, "result": None|<pin>}.
    """
    async def get_config(_req):
        return web.json_response(cfg_ref[0])

    async def post_config(req):
        body = await req.json()
        CONFIG_PATH.write_text(json.dumps(body, indent=2))
        return web.json_response({"ok": True})

    async def post_learn(req):
        body = await req.json()
        action = body.get("action")
        if not action:
            return web.json_response({"ok": False, "error": "action required"}, status=400)
        loop = asyncio.get_running_loop()
        learn_state["action"] = action
        learn_state["until"] = int(loop.time() * 1000) + 5000
        learn_state["result"] = None
        # Poll for up to 5s for a captured pin.
        for _ in range(50):
            await asyncio.sleep(0.1)
            if learn_state.get("result") is not None:
                pin = learn_state["result"]
                learn_state["action"] = None
                return web.json_response({"ok": True, "action": action, "pin": pin})
        learn_state["action"] = None
        return web.json_response({"ok": False, "error": "no press detected"}, status=408)

    async def post_test(req):
        body = await req.json()
        action = body.get("action")
        event = body.get("event", "short_press")
        if not action or dispatcher_ref[0] is None:
            return web.json_response({"ok": False, "error": "action required"}, status=400)
        await dispatcher_ref[0].dispatch(action, event)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/config", get_config)
    app.router.add_post("/config", post_config)
    app.router.add_post("/learn", post_learn)
    app.router.add_post("/test", post_test)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", BUTTONS_API_PORT)
    await site.start()
    log.info("buttons HTTP API listening on 127.0.0.1:%d", BUTTONS_API_PORT)
    return runner


if __name__ == "__main__":
    asyncio.run(main())
