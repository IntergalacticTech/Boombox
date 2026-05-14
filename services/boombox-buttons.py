#!/usr/bin/env python3
"""Boombox GPIO button + rotary encoder driver.

Owns the physical control surface described in
docs/superpowers/specs/2026-05-12-gpio-buttons-design.md: 17 buttons + 1
rotary encoder with push. Every action is independently disable-able via
/etc/boombox/buttons.json. Pin assignments are user-editable via that file
or via the Settings drawer's Buttons panel (which writes the file).

Listens on aiohttp 127.0.0.1:6684 for /config, /learn, /test endpoints used
by the Settings panel (fronted as /api/buttons/ via nginx).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from copy import deepcopy
from pathlib import Path

import aiohttp

from clients import (
    MopidyRpc, StateApi, KioskClient, Display, SleepTimer, Recorder,
)
from actions import Dispatcher, _HANDLERS, fire, shutdown_sequence  # noqa: F401

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
