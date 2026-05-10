#!/usr/bin/env python3
"""Boombox source orchestrator — most-recent-wins auto-switch.

Watches PipeWire (via `pw-dump`) every 500 ms for which audio output streams
are in the `running` state, classifies each by source (Mopidy / Bluetooth /
Spotify Connect / AirPlay), and when a new source goes active alongside
existing ones, pauses everyone else. No auto-resume — once paused, stays
paused until the user starts that source again.

Why polling pw-dump rather than streaming pw-mon: pw-mon's event format has
shifted between PipeWire versions and individual events don't always carry the
props we need to classify the source. pw-dump is an atomic JSON snapshot —
cheap enough at 500 ms on a Pi 5 (~30 ms / call) and trivially robust.

Pause mechanisms:
  - Mopidy:        JSON-RPC core.playback.pause on http://127.0.0.1:6680/mopidy/rpc
  - Bluetooth:     playerctl pause on the BlueZ MPRIS player exposed by mpris-proxy
  - AirPlay:       playerctl pause on ShairportSync's MPRIS interface
  - Spotify:       playerctl pause on librespot's MPRIS interface (best-effort:
                   raspotify 0.48 / librespot 0.8 don't expose MPRIS by default,
                   in which case the stream keeps playing alongside the new
                   source until the user pauses from their phone)
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orchestrator")

POLL_INTERVAL_S = 0.5
MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"


def _run(*args: str) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        return ""


def get_running_audio_streams() -> list[dict]:
    raw = _run("pw-dump")
    if not raw:
        return []
    try:
        objs = json.loads(raw)
    except json.JSONDecodeError:
        return []
    results: list[dict] = []
    for o in objs:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") not in ("Stream/Output/Audio", "Audio/Source"):
            continue
        if info.get("state") != "running":
            continue
        results.append({
            "id": o.get("id"),
            "node_name": props.get("node.name", "") or "",
            "app_name": props.get("application.name", "") or "",
        })
    return results


_SOURCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^bluez_input\."),         "bluetooth"),
    (re.compile(r"librespot|raspotify", re.I), "spotify"),
    (re.compile(r"shairport",            re.I), "airplay"),
    (re.compile(r"mopidy",               re.I), "mopidy"),
]


def classify_source(stream: dict) -> str | None:
    n, a = stream["node_name"], stream["app_name"]
    for pat, name in _SOURCE_PATTERNS:
        if pat.search(n) or pat.search(a):
            return name
    return None


def _pause_mpris(player_substr: str) -> bool:
    out = _run("playerctl", "-l")
    sub = player_substr.lower()
    for line in out.splitlines():
        if sub in line.lower():
            _run("playerctl", "-p", line.strip(), "pause")
            return True
    return False


def pause_mopidy() -> None:
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                MOPIDY_RPC,
                data=b'{"jsonrpc":"2.0","id":1,"method":"core.playback.pause"}',
                headers={"Content-Type": "application/json"},
            ),
            timeout=2,
        )
    except Exception:
        _run("mpc", "pause")


# Known non-Bluetooth MPRIS player names — anything else surfaced by mpris-proxy
# is presumed to be a phone/laptop bridged via BlueZ.
_NON_BT_MPRIS = frozenset({
    "shairportsync", "shairport-sync",
    "librespot", "spotify", "spotifyd",
    "mopidy",
    "playerctld",
})


def pause_bluetooth() -> None:
    out = _run("playerctl", "-l")
    paused_any = False
    for line in out.splitlines():
        name = line.strip()
        if name and name.lower() not in _NON_BT_MPRIS:
            _run("playerctl", "-p", name, "pause")
            paused_any = True
    if not paused_any:
        log.debug("no BlueZ MPRIS player to pause")


def pause_airplay() -> None:
    if not _pause_mpris("ShairportSync"):
        _pause_mpris("Shairport")


def pause_spotify() -> None:
    if not _pause_mpris("librespot"):
        _pause_mpris("spotify")


PAUSE_FNS = {
    "mopidy":    pause_mopidy,
    "bluetooth": pause_bluetooth,
    "airplay":   pause_airplay,
    "spotify":   pause_spotify,
}


def main() -> None:
    log.info("starting orchestrator (poll=%.1fs)", POLL_INTERVAL_S)
    prev_active: dict[str, int] = {}  # source -> tick first seen

    tick = 0
    while True:
        tick += 1
        try:
            sources_now: dict[str, int] = {}
            for s in get_running_audio_streams():
                src = classify_source(s)
                if src:
                    sources_now[src] = s["id"]

            new_sources = [s for s in sources_now if s not in prev_active]
            if new_sources and len(sources_now) > 1:
                winner = max(new_sources, key=lambda s: sources_now[s])
                losers = [s for s in sources_now if s != winner]
                log.info("source %r took over (node %d); pausing %s",
                         winner, sources_now[winner], losers)
                for s in losers:
                    fn = PAUSE_FNS.get(s)
                    if not fn:
                        continue
                    try:
                        fn()
                    except Exception as e:
                        log.warning("pause(%s) failed: %s", s, e)

            prev_active = {s: prev_active.get(s, tick) for s in sources_now}
        except Exception as e:
            log.warning("tick failed: %s", e)

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
