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
import io
import json
import logging
import os
import socket
import sys
from pathlib import Path

import aiohttp as aiohttp_client_lib
from aiohttp import web
from PIL import Image
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

import actions
import clients

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-remote")

PORT = int(os.environ.get("BOOMBOX_REMOTE_PORT", "6685"))
DEFAULT_PEERS = Path.home() / ".config" / "boombox-remote" / "peers.json"
DEFAULT_ART_CACHE = Path.home() / ".cache" / "boombox-remote" / "art"
ART_SIZE = (240, 240)


def _art_cache_dir() -> Path:
    """Resolve the art cache directory. Re-reads env on each call so tests
    can override BOOMBOX_REMOTE_ART_CACHE between calls. Directory is
    created lazily, not at import time.
    """
    path = Path(os.environ.get("BOOMBOX_REMOTE_ART_CACHE",
                                str(DEFAULT_ART_CACHE)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_mdns_service_info(port: int) -> ServiceInfo:
    """Build the ServiceInfo for our `_boombox._tcp.local` advertisement.

    Read on every call so tests can monkeypatch BOOMBOX_ID / BOOMBOX_NAME.
    TXT property values must be bytes — zeroconf treats str values as
    "raw" (no length prefix), which breaks record parsing on the client.
    """
    boombox_id = os.environ.get("BOOMBOX_ID", "boombox-default")
    boombox_name = os.environ.get("BOOMBOX_NAME", "Boombox")
    hostname = socket.gethostname()
    return ServiceInfo(
        type_="_boombox._tcp.local.",
        name=f"{boombox_id}._boombox._tcp.local.",
        port=port,
        properties={
            "id":      boombox_id.encode(),
            "name":    boombox_name.encode(),
            "version": b"1",
        },
        server=f"{hostname}.local.",
    )


def _ws_poll_seconds() -> float:
    """Poll interval for the WS state-diff loop.

    Read on every call so tests can monkeypatch BOOMBOX_REMOTE_WS_POLL_MS
    without forcing a module reimport.
    """
    return int(os.environ.get("BOOMBOX_REMOTE_WS_POLL_MS", "250")) / 1000


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
    """Bearer-token middleware. 401 on missing or unknown token.

    The WebSocket path /api/remote/ws bypasses this middleware because it
    authenticates via query string token before the handshake completes —
    aiohttp's WebSocketResponse can't return a JSON 401 (only a close code).
    """
    if request.path == "/api/remote/ws":
        return await handler(request)
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


def create_app(aggregator: "StateAggregator | None" = None,
               dispatcher: "actions.Dispatcher | None" = None) -> web.Application:
    """Build the aiohttp Application. Used by tests and main().

    Pass `aggregator` for state reads and `dispatcher` for command writes.
    When either is None, the corresponding endpoint returns 503.
    """
    app = web.Application(middlewares=[require_auth])
    app["aggregator"] = aggregator
    app["dispatcher"] = dispatcher
    app.router.add_get("/api/remote/state", _get_state)
    app.router.add_post("/api/remote/command", _post_command)
    app.router.add_get("/api/remote/ws", _ws_handler)
    app.router.add_get("/api/remote/art/{hash}.jpg", _get_art)
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


async def _post_command(request: web.Request) -> web.Response:
    """Dispatch a remote command through actions.fire().

    Accepts `{"action": "<name>", "value": <optional>}`. Returns the
    result dict from actions.fire(); status is 200 on ok, 502 on
    handler failure, 400 on malformed body, 503 when dispatcher unset.
    """
    dispatcher = request.app.get("dispatcher")
    if dispatcher is None:
        return web.json_response(
            {"ok": False, "error": "dispatcher_unavailable"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_json"}, status=400)

    action = body.get("action") if isinstance(body, dict) else None
    if not action or not isinstance(action, str):
        return web.json_response(
            {"ok": False, "error": "missing_action"}, status=400)

    value = body.get("value")
    label = request["peer"].get("label", "unknown")

    result = await actions.fire(dispatcher, action, value,
                                 source=f"remote:{label}")
    status = 200 if result.get("ok") else 502
    return web.json_response(result, status=status)


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Push consolidated state to a remote on connect and on every change.

    Auth happens here (not in the middleware) because aiohttp WS clients
    typically can't set Authorization headers on the handshake. We accept
    ?token=... and use custom close codes (4401/4503) to surface errors.
    """
    token = request.query.get("token", "")
    peers = _load_peers()
    if token not in peers:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4401, message=b"bad_token")
        return ws

    agg = request.app.get("aggregator")
    if agg is None:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4503, message=b"aggregator_unavailable")
        return ws

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    poll_s = _ws_poll_seconds()
    last_payload: str | None = None
    try:
        while not ws.closed:
            try:
                data = await agg.consolidated_state()
            except Exception as exc:
                log.warning("ws aggregator error: %s", exc)
                await asyncio.sleep(poll_s)
                continue
            payload = json.dumps({"ok": True, "data": data},
                                  sort_keys=True, default=str)
            if payload != last_payload:
                await ws.send_str(payload)
                last_payload = payload
            await asyncio.sleep(poll_s)
    except asyncio.CancelledError:
        pass
    return ws


async def _get_art(request: web.Request) -> web.Response:
    """Serve resized 240x240 album art keyed by sha1 hash.

    Phase 1 reads the raw source bytes from `<cache>/<hash>.src` (populated
    by a future Mopidy art-fetch task) and produces `<cache>/<hash>.jpg`
    on first request. Subsequent reads serve the cached file directly.
    ETag is the hash itself, so clients can revalidate cheaply.
    """
    art_hash = request.match_info["hash"]
    # Reject anything that isn't lowercase hex (defense in depth — caller
    # always passes a sha1).
    if not art_hash or not all(c in "0123456789abcdef" for c in art_hash):
        return web.Response(status=400)

    etag = f'"{art_hash}"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})

    cache = _art_cache_dir()
    resized_path = cache / f"{art_hash}.jpg"
    src_path     = cache / f"{art_hash}.src"

    if not resized_path.exists():
        if not src_path.exists():
            return web.Response(status=404)
        # Lazy-resize on first request.
        with Image.open(src_path) as img:
            img = img.convert("RGB")
            img.thumbnail(ART_SIZE, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            resized_path.write_bytes(buf.getvalue())

    return web.Response(
        body=resized_path.read_bytes(),
        content_type="image/jpeg",
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


async def main() -> None:
    timeout = aiohttp_client_lib.ClientTimeout(total=2)
    async with aiohttp_client_lib.ClientSession(timeout=timeout) as session:
        agg = StateAggregator(
            session,
            boombox_id=os.environ.get("BOOMBOX_ID", "boombox-default"),
            boombox_name=os.environ.get("BOOMBOX_NAME", "Boombox"),
        )
        dispatcher = actions.Dispatcher(
            mopidy=clients.MopidyRpc(session),
            state=clients.StateApi(session),
            kiosk=None,        # populated when KioskClient is wired in
            recorder=None,     # populated alongside boombox-buttons
            display=None,
            sleep=None,
            disabled=set(),
        )
        app = create_app(aggregator=agg, dispatcher=dispatcher)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", PORT)
        await site.start()

        # Advertise on the LAN so remotes can discover us. IPv4-only because
        # ESP32 firmware typically resolves A records, not AAAA.
        azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        info = build_mdns_service_info(PORT)
        await azc.async_register_service(info)
        log.info("boombox-remote on :%d, mDNS as %s", PORT, info.name)

        try:
            await asyncio.Event().wait()
        finally:
            await azc.async_unregister_service(info)
            await azc.async_close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
