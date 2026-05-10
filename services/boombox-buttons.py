#!/usr/bin/env python3
"""Boombox GPIO button driver.

Listens for button presses on configured BCM pins and dispatches Mopidy
transport actions over HTTP RPC. Drives:

  - Play / pause
  - Next / previous track
  - Volume up / volume down

Wiring assumption: each button shorts the GPIO pin to GND when pressed,
relying on the SoC's internal pull-up. So a "press" is a falling edge.

The pin map below is a *default* — override by writing JSON to
/etc/boombox/buttons.json. Example:

    {
      "play_pause": 17,
      "next":       27,
      "previous":   22,
      "volume_up":  23,
      "volume_down": 24
    }

Set a pin to null to disable that action.

Why the user-space HTTP path (and not direct DBus / Python control)? It
matches every other path in this project — UI, MPRIS aggregator, audio
visualizer all talk to Mopidy via /mopidy/rpc. Reusing it keeps the
button driver dead simple, decoupled from Mopidy's process lifecycle, and
trivially re-targetable to AirPlay / Spotify if we extend later.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp
import gpiod
from gpiod.line import Direction, Bias, Edge, Value  # noqa: F401  (Value reserved for future)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-buttons")

GPIO_CHIP = "/dev/gpiochip0"          # Pi 5 default for the 40-pin header
DEBOUNCE_MS = 30
MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
VOLUME_STEP = 5                       # %

# A blank default; the user wires whatever they have. Setting any value to
# null disables that action. The driver still runs cleanly with all-null.
DEFAULTS: dict[str, int | None] = {
    "play_pause":  None,
    "next":        None,
    "previous":    None,
    "volume_up":   None,
    "volume_down": None,
}


def load_pin_map() -> dict[str, int | None]:
    """Read /etc/boombox/buttons.json (or env BOOMBOX_BUTTONS_FILE) over the
    defaults. Missing keys keep their default (i.e. disabled)."""
    path = os.environ.get("BOOMBOX_BUTTONS_FILE", "/etc/boombox/buttons.json")
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        try:
            user = json.loads(p.read_text())
            if isinstance(user, dict):
                for k, v in user.items():
                    if k in cfg and (v is None or isinstance(v, int)):
                        cfg[k] = v
            log.info("loaded pin config from %s", p)
        except Exception as e:
            log.warning("could not read %s: %s — using defaults", path, e)
    else:
        log.info("no %s; running with empty pin map (driver idle until you create one)", path)
    return cfg


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
