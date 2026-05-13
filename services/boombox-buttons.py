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
from pathlib import Path

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


# ---------- Service entry point -------------------------------------------
# Backend clients (Task 7), GPIO event loop (Task 8), action handlers
# (Tasks 6, 9-12), and HTTP API server (Task 14) land in subsequent commits.
# Until Task 8 rebuilds main(), running this file as a script is intentionally
# a no-op.

async def main() -> None:
    raise NotImplementedError(
        "boombox-buttons main() is rebuilt in Task 8 of "
        "docs/superpowers/plans/2026-05-12-gpio-buttons.md"
    )


if __name__ == "__main__":
    asyncio.run(main())
