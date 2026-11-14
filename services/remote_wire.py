"""Compact wire form of boombox-remote's consolidated state, shared by the
hardware-remote transports (BLE peripheral, USB knob bridge).

Remotes only read a subset of the consolidated state; `compact_state` drops
the rest (art URLs, the source list, the boombox id/name, the track URI, the
theme's rule colour and CSS font stacks, false/unset flags). Kept free of any
transport import (bless, termios…) so either transport works without the
other.
"""
from __future__ import annotations

import json
from typing import Any

# `boombox` (id/name) is also on BLE's device_info characteristic, which is
# what BLE remotes pair against; a USB knob doesn't pair at all.
DROP_KEYS = ("art_hash", "art_url", "sources_available", "boombox")
# Dropped only when falsy — remotes default them to off/unset.
DROP_IF_FALSY = ("recording", "mic_on", "sleep_timer_s")
THEME_KEYS = ("bg", "panel", "ink", "ink2", "accent", "accent2")


def compact_state(data: dict) -> dict:
    """Return a trimmed copy of `data` holding only what remotes read.
    The input is not modified (the nested track/theme dicts are copied)."""
    d: dict[str, Any] = {k: v for k, v in data.items()
                         if k not in DROP_KEYS
                         and not (k in DROP_IF_FALSY and not v)}
    track = d.get("track")
    if isinstance(track, dict):
        d["track"] = {k: v for k, v in track.items() if k != "uri"}
    theme = d.get("theme")
    if isinstance(theme, dict):
        d["theme"] = {k: theme[k] for k in THEME_KEYS if k in theme}
    return d


def dumps_compact(obj: Any) -> bytes:
    """Compact, deterministic UTF-8 JSON (sorted keys, so an unchanged state
    serialises to identical bytes and change detection is a byte compare)."""
    return json.dumps(obj, default=str, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()
