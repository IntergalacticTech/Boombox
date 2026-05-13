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
from typing import Any

from aiohttp import web

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


def create_app() -> web.Application:
    """Build the aiohttp Application. Used by tests and main()."""
    app = web.Application(middlewares=[require_auth])
    app.router.add_get("/api/remote/state", _stub_state)
    return app


async def _stub_state(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "data": {}})


async def main() -> None:
    app = create_app()
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
