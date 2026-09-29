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
    try:
        out["video"] = await _video_state(ctx)
    except Exception:
        log.exception("accounts summary: video status failed")
        out["video"] = _state("problem", "video settings unreadable")
    try:
        out["streaming"] = await _streaming_state(ctx)
    except Exception:
        log.exception("accounts summary: streaming status failed")
        out["streaming"] = _state("problem", "streaming status unavailable")
    out["web"] = _state("ok")
    return web.json_response(out)


async def _video_state(ctx: Any) -> dict[str, str]:
    env = ctx.jellyfin_env()
    if env.get("BOOMBOX_JELLYFIN_BASE") and not env.get("JELLYFIN_API_KEY"):
        return _state("problem", "API key missing")
    return _state("ok")


async def _streaming_state(ctx: Any) -> dict[str, str]:
    r = await ctx.apply({"action": "streaming-status"})
    if not isinstance(r, dict) or not r.get("ok"):
        err = r.get("error") if isinstance(r, dict) else None
        return _state("problem", err if isinstance(err, str) and err else
                      "status unavailable")
    installed = [k for k in ("airplay", "spotify")
                 if isinstance(r.get(k), dict) and r[k].get("installed")]
    return _state("ok" if installed else "absent", ", ".join(installed))


async def _music_get(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    try:
        m = await ctx.music_get()
    except Exception:
        log.exception("accounts music: library source unreadable")
        return web.json_response({
            "url": "", "username": "", "configured": False, "reachable": False,
            "last_sync_ts": None, "syncing": False, "prune_deferred": None,
            "error": "library service not answering"})
    h = await ctx.library_health()
    return web.json_response({
        "url": m.get("url", ""), "username": m.get("username", ""),
        "configured": bool(m.get("configured")), "reachable": bool(m.get("reachable")),
        "last_sync_ts": h.get("last_sync_ts"), "syncing": bool(h.get("syncing")),
        "prune_deferred": h.get("prune_deferred"),
    })


async def _json_body(req: web.Request) -> dict | None:
    """The request's JSON object, or None when the body isn't one."""
    try:
        b = await req.json()
    except ValueError:
        return None
    return b if isinstance(b, dict) else None


def _bad_body() -> web.Response:
    return web.json_response({"ok": False, "error": "expected a JSON object"}, status=400)


def _music_fields(b: dict) -> tuple[str, str, str]:
    # Blank password is passed through: the library keeps the stored one.
    return (str(b.get("url", "")).strip(), str(b.get("username", "")).strip(),
            str(b.get("password") or ""))


async def _music_test(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    ok, err = await ctx.music_test(*_music_fields(b))
    return web.json_response({"ok": ok, "error": "" if ok else err})


async def _music_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    url, user, pw = _music_fields(b)
    if not url.startswith(("http://", "https://")) or not user:
        return web.json_response({"ok": False, "error": "URL and username are required"},
                                 status=400)
    ok, err = await ctx.music_save(url, user, pw)
    if not ok:
        return web.json_response(
            {"ok": False, "error": err.replace(pw, "***") if pw else err}, status=400)
    return web.json_response({"ok": True})


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/accounts/summary", _summary)
    r.add_get("/api/accounts/music", _music_get)
    r.add_post("/api/accounts/music/test", _music_test)
    r.add_put("/api/accounts/music", _music_put)
