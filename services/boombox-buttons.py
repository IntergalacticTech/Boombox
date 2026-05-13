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
from pathlib import Path
from typing import Awaitable, Callable, Iterable

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
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
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


def pin_conflicts(cfg: dict) -> list[tuple[str, str, int]]:
    """Return a list of (action_a, action_b, pin) triples that collide."""
    by_pin: dict[int, list[str]] = {}
    for name, pin in enabled_pins(cfg).items():
        by_pin.setdefault(pin, []).append(name)
    conflicts: list[tuple[str, str, int]] = []
    for pin, names in by_pin.items():
        if len(names) > 1:
            names.sort()
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    conflicts.append((names[i], names[j], pin))
    return conflicts


# ---------- Mopidy RPC helpers --------------------------------------------

class MopidyRpc:
    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session
        self._id = 0

    async def call(self, method: str, params: dict | None = None) -> dict | None:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        try:
            async with self._sess.post(MOPIDY_RPC, json=body, timeout=aiohttp.ClientTimeout(total=2)) as r:
                if r.status != 200:
                    log.warning("rpc %s → HTTP %s", method, r.status)
                    return None
                return await r.json(content_type=None)
        except Exception as e:
            log.warning("rpc %s failed: %s", method, e)
            return None


async def play_pause(rpc: MopidyRpc) -> None:
    res = await rpc.call("core.playback.get_state")
    state = (res or {}).get("result")
    if state == "playing":
        await rpc.call("core.playback.pause")
    else:
        await rpc.call("core.playback.play")


async def next_track(rpc: MopidyRpc) -> None:
    await rpc.call("core.playback.next")


async def previous_track(rpc: MopidyRpc) -> None:
    await rpc.call("core.playback.previous")


async def volume_up(rpc: MopidyRpc) -> None:
    res = await rpc.call("core.mixer.get_volume")
    cur = (res or {}).get("result") or 0
    await rpc.call("core.mixer.set_volume", {"volume": min(100, cur + VOLUME_STEP)})


async def volume_down(rpc: MopidyRpc) -> None:
    res = await rpc.call("core.mixer.get_volume")
    cur = (res or {}).get("result") or 0
    await rpc.call("core.mixer.set_volume", {"volume": max(0, cur - VOLUME_STEP)})


ACTIONS: dict[str, Callable[[MopidyRpc], Awaitable[None]]] = {
    "play_pause": play_pause,
    "next":       next_track,
    "previous":   previous_track,
    "volume_up":  volume_up,
    "volume_down": volume_down,
}


# ---------- GPIO event loop ------------------------------------------------

async def watch_pins(pin_map: dict[str, int | None], rpc: MopidyRpc) -> None:
    pins = [(action, pin) for action, pin in pin_map.items() if pin is not None]
    if not pins:
        log.info("no GPIO pins configured — sleeping; reload the service after editing the pin map")
        # Sleep forever rather than exiting; systemd would just restart us.
        await asyncio.Event().wait()
        return

    # Build line config: each pin pulls up + listens for falling edges, with
    # hardware debounce so we don't repeat-fire on contact bounce.
    config = {
        pin: gpiod.LineSettings(
            direction=Direction.INPUT,
            bias=Bias.PULL_UP,
            edge_detection=Edge.FALLING,
            debounce_period=DEBOUNCE_MS / 1000,
        )
        for _, pin in pins
    }
    by_pin = {pin: action for action, pin in pins}

    log.info("watching pins: %s", ", ".join(f"{a}=BCM{p}" for a, p in pins))

    with gpiod.request_lines(GPIO_CHIP, consumer="boombox-buttons", config=config) as req:
        loop = asyncio.get_running_loop()
        # gpiod's blocking read in a background thread; events feed an asyncio queue.
        queue: asyncio.Queue[gpiod.EdgeEvent] = asyncio.Queue()

        def reader() -> None:
            while True:
                # wait_edge_events blocks; read each batch when available.
                if req.wait_edge_events():
                    for ev in req.read_edge_events():
                        loop.call_soon_threadsafe(queue.put_nowait, ev)

        loop.run_in_executor(None, reader)

        while True:
            ev = await queue.get()
            action = by_pin.get(ev.line_offset)
            if not action:
                continue
            handler = ACTIONS.get(action)
            if handler is None:
                continue
            log.info("button %s pressed (BCM%s)", action, ev.line_offset)
            asyncio.create_task(handler(rpc))


async def main() -> None:
    pin_map = load_pin_map()
    async with aiohttp.ClientSession() as session:
        rpc = MopidyRpc(session)
        await watch_pins(pin_map, rpc)


if __name__ == "__main__":
    asyncio.run(main())
