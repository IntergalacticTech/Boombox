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
import hmac
import io
import json
import logging
import os
import secrets
import socket
import sys
import time
from pathlib import Path

import aiohttp as aiohttp_client_lib
from aiohttp import web
from PIL import Image
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

import actions
import clients
import remote_access
import remote_files

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-remote")

PORT = int(os.environ.get("BOOMBOX_REMOTE_PORT", "6685"))
DEFAULT_PEERS = Path.home() / ".config" / "boombox-remote" / "peers.json"
DEFAULT_ART_CACHE = Path.home() / ".cache" / "boombox-remote" / "art"
ART_SIZE = (240, 240)

# Process-local pairing state. One active PIN at a time; resets if the
# service restarts mid-pairing. PIN is stored as a SHA-256 hex digest so
# memory inspection doesn't leak it; comparison uses hmac.compare_digest.
_PAIR_STATE: dict = {"pin_hash": None, "expires_at": 0}
PAIR_PIN_TTL_S = int(os.environ.get("BOOMBOX_REMOTE_PAIR_TTL_S", "120"))


def _make_pin() -> str:
    """Cryptographically random 6-digit numeric PIN."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_pin(pin: str) -> str:
    """SHA-256 hex digest. Used for hmac.compare_digest comparison."""
    import hashlib
    return hashlib.sha256(pin.encode()).hexdigest()


def _art_cache_dir() -> Path:
    """Resolve the art cache directory. Re-reads env on each call so tests
    can override BOOMBOX_REMOTE_ART_CACHE between calls. Directory is
    created lazily, not at import time.
    """
    path = Path(os.environ.get("BOOMBOX_REMOTE_ART_CACHE",
                                str(DEFAULT_ART_CACHE)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_mdns_service_info(port: int | None = None) -> ServiceInfo:
    """Build the ServiceInfo for our `_boombox._tcp.local` advertisement.

    Read on every call so tests can monkeypatch BOOMBOX_ID / BOOMBOX_NAME.
    TXT property values must be bytes — zeroconf treats str values as
    "raw" (no length prefix), which breaks record parsing on the client.

    The advertised port is the LAN-facing nginx port (`BOOMBOX_LAN_PORT`,
    default 8090), NOT the loopback aiohttp port — clients off-host must
    reach the service via nginx. The `path` TXT record tells clients to
    prepend `/api/remote/` to discover the API surface.
    """
    boombox_id = os.environ.get("BOOMBOX_ID", "boombox-default")
    boombox_name = os.environ.get("BOOMBOX_NAME", "Boombox")
    lan_port = port if port is not None else int(
        os.environ.get("BOOMBOX_LAN_PORT", "8090"))
    hostname = socket.gethostname()
    return ServiceInfo(
        type_="_boombox._tcp.local.",
        name=f"{boombox_id}._boombox._tcp.local.",
        port=lan_port,
        properties={
            "id":      boombox_id.encode(),
            "name":    boombox_name.encode(),
            "version": b"1",
            "path":    b"/api/remote/",
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

    /api/remote/pair/start and /api/remote/pair bypass auth too — they
    predate any token (PIN-based pairing is how tokens are minted in the
    first place). /pair/start is gated to localhost in the handler; /pair
    is open to the LAN so the CYD can redeem the PIN.
    """
    if request.path in ("/api/remote/ws", "/api/remote/pair/start",
                          "/api/remote/pair", "/api/remote/admin/status",
                          "/api/remote/admin/enable",
                          "/api/remote/admin/disable",
                          "/api/remote/admin/unpair"):
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


@web.middleware
async def require_remote_enabled(request: web.Request, handler):
    """403 every phone-facing route when the remote_enabled flag is off.

    Exempt: /api/remote/admin/* (that's how the flag gets turned on; those
    handlers are localhost-gated) and /api/remote/ws (a WebSocket can't
    return a JSON 403 — the ws handler checks the flag itself and closes
    with code 4403).
    """
    path = request.path
    if path == "/api/remote/ws" or path.startswith("/api/remote/admin/"):
        return await handler(request)
    if not remote_access.is_enabled():
        return web.json_response(
            {"ok": False, "error": "remote_disabled"}, status=403)
    return await handler(request)


class StateAggregator:
    """Reads upstream services and produces the consolidated payload.

    Phase 1: pulls from Mopidy (track + state + position) and boombox-state
    (source, volume, mute, karaoke, theme). In-memory bits (sleep_timer,
    recording) return None for now; they get wired in Phase 2 when there's
    a real consumer.
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
        (source, track_info, state_info, position_info, vol_info, karaoke,
         theme_payload) = await asyncio.gather(
            self._state.current_source(),
            self._mopidy.call("core.playback.get_current_track"),
            self._mopidy.call("core.playback.get_state"),
            self._mopidy.call("core.playback.get_time_position"),
            self._state.volume_get(),
            self._state.karaoke_state(),
            self._fetch_theme(),
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
            "skin":  theme_payload.get("skinId"),
            "theme": theme_payload.get("theme") or {},
        }

    async def _fetch_theme(self) -> dict:
        """Pull the active theme from boombox-state. Returns {} on failure —
        the PWA falls back to its built-in default styling."""
        try:
            async with self._sess.get(
                    "http://127.0.0.1:6681/theme",
                    timeout=aiohttp_client_lib.ClientTimeout(total=1.5)) as r:
                if r.status != 200:
                    return {}
                return await r.json()
        except Exception:
            return {}


def create_app(aggregator: "StateAggregator | None" = None,
               dispatcher: "actions.Dispatcher | None" = None) -> web.Application:
    """Build the aiohttp Application. Used by tests and main().

    Pass `aggregator` for state reads and `dispatcher` for command writes.
    When either is None, the corresponding endpoint returns 503.
    """
    app = web.Application(
        middlewares=[require_remote_enabled, require_auth])
    app["aggregator"] = aggregator
    app["dispatcher"] = dispatcher
    app.router.add_get("/api/remote/state", _get_state)
    app.router.add_post("/api/remote/command", _post_command)
    app.router.add_get("/api/remote/ws", _ws_handler)
    app.router.add_get("/api/remote/art/{hash}.jpg", _get_art)
    app.router.add_post("/api/remote/pair/start", _post_pair_start)
    app.router.add_post("/api/remote/pair", _post_pair)
    app.router.add_get("/api/remote/admin/status", _get_admin_status)
    app.router.add_post("/api/remote/admin/enable", _post_admin_enable)
    app.router.add_post("/api/remote/admin/disable", _post_admin_disable)
    app.router.add_post("/api/remote/admin/unpair", _post_admin_unpair)
    remote_files.add_routes(app)
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

    if not remote_access.is_enabled():
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4403, message=b"remote_disabled")
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


def _is_localhost(request: web.Request) -> bool:
    # nginx proxies /api/remote/ from 127.0.0.1:6685, so request.remote is
    # always loopback. The :6685 socket is loopback-bound, so the only way
    # in is via nginx — and nginx overwrites X-Real-IP with $remote_addr,
    # making it the trustworthy peer identity. Fall back to request.remote
    # for direct-loopback callers on the Pi (no proxy, no header).
    peer = request.headers.get("X-Real-IP") or request.remote
    return peer in ("127.0.0.1", "::1", "localhost")


async def _post_pair_start(request: web.Request) -> web.Response:
    """Mint a fresh 6-digit PIN. Localhost-only (kiosk on the Pi)."""
    # Localhost-only — the kiosk runs on the Pi and is the only legit caller.
    if not _is_localhost(request):
        log.warning("/pair/start from non-localhost: %s", request.remote)
        return web.json_response(
            {"ok": False, "error": "forbidden"}, status=403)

    pin = _make_pin()
    _PAIR_STATE["pin_hash"] = _hash_pin(pin)
    _PAIR_STATE["expires_at"] = time.time() + PAIR_PIN_TTL_S
    log.info("pairing PIN issued, expires in %ds", PAIR_PIN_TTL_S)
    return web.json_response({
        "ok": True,
        "pin": pin,
        "expires_at": _PAIR_STATE["expires_at"],
    })


async def _get_admin_status(request: web.Request) -> web.Response:
    """Report the enable flag + paired peers. Localhost-only (the kiosk)."""
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    peers = _load_peers()
    return web.json_response({
        "ok": True,
        "enabled": remote_access.is_enabled(),
        "peers": [{"label": p.get("label", "remote"),
                   "paired_at": p.get("paired_at", 0)}
                  for p in peers.values()],
    })


async def _post_admin_enable(request: web.Request) -> web.Response:
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    remote_access.set_enabled(True)
    log.info("remote access enabled")
    return web.json_response({"ok": True, "enabled": True})


async def _post_admin_disable(request: web.Request) -> web.Response:
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    remote_access.set_enabled(False)
    log.info("remote access disabled")
    return web.json_response({"ok": True, "enabled": False})


async def _post_admin_unpair(request: web.Request) -> web.Response:
    """Remove one peer by token. Authorization is otherwise durable — this
    is the only way a peer loses access."""
    if not _is_localhost(request):
        return web.json_response({"ok": False, "error": "forbidden"},
                                 status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"},
                                 status=400)
    token = body.get("token") if isinstance(body, dict) else None
    if not token or not isinstance(token, str):
        return web.json_response({"ok": False, "error": "missing_token"},
                                 status=400)
    peers = _load_peers()
    peers.pop(token, None)
    path = Path(os.environ.get("BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(peers, indent=2))
    log.info("unpaired one remote")
    return web.json_response({"ok": True})


async def _post_pair(request: web.Request) -> web.Response:
    """Redeem a PIN for a 32-byte hex auth token. Single-use, LAN-open."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response(
            {"ok": False, "error": "invalid_body"}, status=400)

    pin = body.get("pin", "")
    label = body.get("label", "remote")
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isdigit():
        return web.json_response(
            {"ok": False, "error": "bad_pin"}, status=403)

    if (_PAIR_STATE["pin_hash"] is None or
            time.time() > _PAIR_STATE["expires_at"]):
        return web.json_response(
            {"ok": False, "error": "no_active_pin"}, status=403)

    if not hmac.compare_digest(_hash_pin(pin), _PAIR_STATE["pin_hash"]):
        return web.json_response(
            {"ok": False, "error": "bad_pin"}, status=403)

    # PIN verified — invalidate it (single-use), mint a token, persist.
    _PAIR_STATE["pin_hash"] = None
    _PAIR_STATE["expires_at"] = 0

    token = secrets.token_hex(32)
    peers = _load_peers()
    peers[token] = {
        "label": str(label)[:40] or "remote",
        "paired_at": int(time.time()),
    }
    path = Path(os.environ.get("BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(peers, indent=2))
    log.info("paired remote label=%s", peers[token]["label"])

    return web.json_response({
        "ok": True,
        "auth_token": token,
        "boombox_id":   os.environ.get("BOOMBOX_ID", "boombox-default"),
        "boombox_name": os.environ.get("BOOMBOX_NAME", "Boombox"),
    })


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
        # Mopidy-backed routes — wired here, not in create_app, since they
        # need the live session.
        import remote_library
        remote_library.add_routes(app, clients.MopidyRpc(session))
        import jellyfin_client
        jellyfin_client.add_routes(
            app, jellyfin_client.JellyfinClient(session))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", PORT)
        await site.start()

        # Advertise on the LAN so remotes can discover us. IPv4-only because
        # ESP32 firmware typically resolves A records, not AAAA. The
        # advertised port is the nginx LAN port (BOOMBOX_LAN_PORT, default
        # 8090) — not the loopback aiohttp port — because off-host traffic
        # enters via nginx /api/remote/.
        azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        info = build_mdns_service_info()
        await azc.async_register_service(info)
        log.info("boombox-remote on :%d, mDNS as %s (port %d, path %s)",
                  PORT, info.name, info.port, "/api/remote/")

        # BLE peripheral — the primary remote transport per the design spec.
        # Runs concurrently with the HTTP/WS server; they share the same
        # PIN state, peers.json, aggregator, and dispatcher.
        ble_task = None
        if os.environ.get("BOOMBOX_REMOTE_BLE", "1") == "1":
            try:
                from ble_peripheral import run_ble_peripheral
                ble_task = asyncio.create_task(run_ble_peripheral(
                    pair_state=_PAIR_STATE,
                    peers_path_cb=lambda: os.environ.get(
                        "BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)),
                    hash_pin_cb=_hash_pin,
                    aggregator=agg,
                    dispatcher=dispatcher,
                    fire_cb=actions.fire,
                    boombox_id=os.environ.get("BOOMBOX_ID", "boombox-default"),
                    boombox_name=os.environ.get("BOOMBOX_NAME", "Boombox"),
                    pair_ttl_s=PAIR_PIN_TTL_S,
                ))
                log.info("BLE peripheral starting")
            except Exception as e:
                log.warning("BLE peripheral failed to start: %s "
                             "(continuing without BLE)", e)

        try:
            await asyncio.Event().wait()
        finally:
            if ble_task is not None:
                ble_task.cancel()
            await azc.async_unregister_service(info)
            await azc.async_close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
