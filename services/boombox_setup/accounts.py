"""/api/accounts/* — the LAN Accounts page backend.

Auth is NOT the wizard's token/code: nginx Basic auth on the LAN port is the
admin gate. nginx forwards `X-Boombox-User: $remote_user` (empty on the
loopback kiosk server, which has no auth) and `X-Real-IP`; we require a user
AND a non-loopback client, so a page open in the kiosk can never change
accounts. Mutations also need JSON and, when the browser sends Origin, a
same-origin match against `X-Boombox-Host` ($http_host). Secrets are
write-only: no response ever carries a password, API key or token.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

log = logging.getLogger("boombox-setup.accounts")

PREFIX = "/api/accounts/"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def check_auth(req: web.Request) -> web.Response | None:
    """None when the request may proceed, else the refusal response."""
    if not req.headers.get("X-Boombox-User", "").strip():
        return web.json_response({"error": "sign in to the boombox web UI"}, status=401)
    if req.headers.get("X-Real-IP", "127.0.0.1") in _LOOPBACK:
        return web.json_response(
            {"error": "accounts can only be changed from another device"}, status=403)
    if req.method in _MUTATING:
        if req.content_type != "application/json":
            return web.json_response(
                {"error": "Content-Type must be application/json"}, status=415)
        origin = req.headers.get("Origin")
        if origin and urlsplit(origin).netloc != req.headers.get("X-Boombox-Host", ""):
            return web.json_response({"error": "cross-origin request refused"}, status=403)
    return None


def _state(state: str, detail: str = "") -> dict[str, str]:
    return {"state": state, "detail": detail}


async def _summary(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    out: dict[str, dict[str, str]] = {}
    try:
        m = await ctx.music_get()
        out["music"] = (_state("unset") if not m.get("configured") else
                        _state("ok") if m.get("reachable") else
                        _state("problem", "music server not reachable"))
    except Exception:
        out["music"] = _state("problem", "library service not answering")
    out["video"] = await _video_state(ctx)
    out["streaming"] = await _streaming_state(ctx)
    out["web"] = _state("ok")
    return web.json_response(out)


async def _video_state(ctx: Any) -> dict[str, str]:
    env = ctx.jellyfin_env()
    if env.get("BOOMBOX_JELLYFIN_BASE") and not env.get("JELLYFIN_API_KEY"):
        return _state("problem", "API key missing")
    return _state("ok")


async def _streaming_state(ctx: Any) -> dict[str, str]:
    r = await ctx.apply({"action": "streaming-status"})
    if not r.get("ok"):
        return _state("problem", r.get("error", "status unavailable"))
    installed = [k for k in ("airplay", "spotify") if r.get(k, {}).get("installed")]
    return _state("ok" if installed else "absent", ", ".join(installed))


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/accounts/summary", _summary)
