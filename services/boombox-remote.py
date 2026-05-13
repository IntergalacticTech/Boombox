#!/usr/bin/env python3
"""boombox-remote — wireless-remote-facing HTTP API.

Exposes a consolidated REST + WebSocket interface aimed at ESP32-based
remotes (and any HTTP client). Routes commands through actions.fire()
so the GPIO buttons service and the wireless remotes share one code
path.

Auth: bearer tokens stored in ~/.config/boombox-remote/peers.json.
Phase 1 has no pairing UI — tokens are added by hand for testing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import aiohttp as aiohttp_client_lib
from aiohttp import web

import clients

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-remote")

PORT = int(os.environ.get("BOOMBOX_REMOTE_PORT", "6685"))
DEFAULT_PEERS = Path.home() / ".config" / "boombox-remote" / "peers.json"


def _load_peers() -> dict[str, dict]:
    """Read peers.json. Returns {} if the file is missing or malformed.

    The path is resolved on every call so tests can override
    BOOMBOX_REMOTE_PEERS between calls.
    """
    path = Path(os.environ.get("BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)))
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("peers.json malformed at %s: %s", path, e)
        return {}


@web.middleware
async def require_auth(request: web.Request, handler):
    """Bearer-token middleware. 401 on missing or unknown token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"ok": False, "error": "missing_token"},
                                 status=401)
    token = auth[len("Bearer "):]
    peers = _load_peers()
    if token not in peers:
        return web.json_response({"ok": False, "error": "bad_token"},
                                 status=401)
    request["peer"] = peers[token]
    request["peer_token"] = token
    return await handler(request)


class StateAggregator:
    """Reads upstream services and produces the consolidated payload.

    Phase 1: pulls from Mopidy (track + state + position) and boombox-state
    (source, volume, mute, karaoke). In-memory bits (sleep_timer, recording,
    skin) return None for now; they get wired in Phase 2 when there's a
    real consumer.
    """

    def __init__(self, session: aiohttp_client_lib.ClientSession,
                 boombox_id: str = "boombox", boombox_name: str = "Boombox"):
        self._sess = session
        self._boombox_id = boombox_id
        self._boombox_name = boombox_name
        self._mopidy = clients.MopidyRpc(session)
        self._state = clients.StateApi(session)

    async def consolidated_state(self) -> dict:
        # Pull from upstream services in parallel for snappiness.
        source, track_info, state_info, position_info, vol_info, karaoke = (
            await asyncio.gather(
                self._state.current_source(),
                self._mopidy.call("core.playback.get_current_track"),
                self._mopidy.call("core.playback.get_state"),
                self._mopidy.call("core.playback.get_time_position"),
                self._state.volume_get(),
                self._state.karaoke_state(),
            )
        )

        track = (track_info or {}).get("result") or {}
        playing_state = (state_info or {}).get("result")
        position_ms = (position_info or {}).get("result") or 0

        return {
            "boombox": {
                "id": self._boombox_id,
                "name": self._boombox_name,
                "version": 1,
            },
            "source": source,
            "playing": playing_state == "playing",
            "track": {
                "title":      track.get("name"),
                "artist":     ", ".join(a.get("name", "") for a in
                                         track.get("artists") or []) or None,
                "album":      (track.get("album") or {}).get("name"),
                "duration_s": (track.get("length") or 0) // 1000,
                "position_s": position_ms // 1000,
            } if track else None,
            "art_hash": None,   # populated in Task 10 (album-art endpoint)
            "art_url":  None,
            "volume":   vol_info[0] if vol_info else None,
            "muted":    vol_info[1] if vol_info else False,
            "sources_available": ["mopidy", "airplay", "spotify",
                                   "bluetooth", "movies"],
            "sleep_timer_s": None,  # in-memory; Phase 2 wires it
            "recording":     False,
            "mic_on":        karaoke,
            "skin":          None,
        }


def create_app(aggregator: "StateAggregator | None" = None) -> web.Application:
    """Build the aiohttp Application. Used by tests and main().

    Pass an `aggregator` (real `StateAggregator` in production, a stub in
    tests). When `aggregator` is None, /api/remote/state returns 503.
    """
    app = web.Application(middlewares=[require_auth])
    app["aggregator"] = aggregator
    app.router.add_get("/api/remote/state", _get_state)
    return app


async def _get_state(request: web.Request) -> web.Response:
    agg = request.app.get("aggregator")
    if agg is None:
        return web.json_response(
            {"ok": False, "error": "aggregator_unavailable"}, status=503)
    try:
        data = await agg.consolidated_state()
    except Exception as exc:
        log.warning("state aggregation failed: %s", exc)
        return web.json_response({"ok": False, "error": "upstream"},
                                 status=502)
    return web.json_response({"ok": True, "data": data})


async def main() -> None:
    timeout = aiohttp_client_lib.ClientTimeout(total=2)
    async with aiohttp_client_lib.ClientSession(timeout=timeout) as session:
        agg = StateAggregator(
            session,
            boombox_id=os.environ.get("BOOMBOX_ID", "boombox-default"),
            boombox_name=os.environ.get("BOOMBOX_NAME", "Boombox"),
        )
        app = create_app(aggregator=agg)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", PORT)
        await site.start()
        log.info("boombox-remote listening on 127.0.0.1:%d", PORT)
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
