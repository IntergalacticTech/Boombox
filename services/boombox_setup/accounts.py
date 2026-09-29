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
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

from . import jellyfin_signin as jf

log = logging.getLogger("boombox-setup.accounts")

PREFIX = "/api/accounts/"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BASE_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(/[A-Za-z0-9._~%/+-]*)?$")
CDP_BASE = os.environ.get("BOOMBOX_KIOSK_CDP", "http://127.0.0.1:9222")
_VIDEO_UNITS = ["boombox-remote.service", "boombox-kiosk-guard.service",
                "boombox-buttons.service"]


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


def kiosk_device_id(ctx: Any) -> str:
    return f"{ctx.read_identity()['id']}-kiosk"


def _jf(ctx: Any) -> tuple[str, str]:
    env = ctx.jellyfin_env()
    return (env.get("BOOMBOX_JELLYFIN_BASE") or "http://127.0.0.1:8096",
            env.get("JELLYFIN_API_KEY", ""))


def _bad_base() -> dict[str, Any]:
    return {"ok": False, "error": "Enter an http(s):// address"}


async def _video_get(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    env = ctx.jellyfin_env()
    base, key = _jf(ctx)
    dev = kiosk_device_id(ctx)
    user = None
    if key:
        try:
            user = await jf.device_user(await ctx.http(), base, key, dev)
        except Exception:
            user = None
    return web.json_response({
        "mode": "remote" if env.get("BOOMBOX_JELLYFIN_BASE") else "builtin",
        "base": base, "key_set": bool(key),
        "kiosk_device_id": dev, "kiosk_user": user,
    })


async def _video_test(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    base = str(b.get("base", "")).strip().rstrip("/")
    key = str(b.get("api_key") or "") or _jf(ctx)[1]
    if not _BASE_RE.match(base):
        return web.json_response(_bad_base())
    try:
        info = await jf.system_info(await ctx.http(), base, key)
    except jf.JellyfinError as e:
        return web.json_response({"ok": False, "error": str(e)})
    return web.json_response({"ok": True, "error": "",
                              "server_name": str(info.get("ServerName", ""))})


async def _video_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    mode = b.get("mode")
    payload: dict[str, Any] = {"action": "jellyfin", "mode": mode}
    if mode == "remote":
        base = str(b.get("base", "")).strip().rstrip("/")
        if not _BASE_RE.match(base):
            return web.json_response(_bad_base(), status=400)
        payload["base"] = base
        if b.get("api_key"):
            payload["api_key"] = str(b["api_key"])
        # Spec: validate → test → write; never overwrite a working config
        # with one that fails, unless the owner explicitly chose "Save anyway".
        if b.get("force") is not True:
            try:
                await jf.system_info(await ctx.http(), base,
                                     str(b.get("api_key") or "") or _jf(ctx)[1])
            except jf.JellyfinError as e:
                return web.json_response({"ok": False, "error": str(e),
                                          "can_force": True}, status=400)
    elif mode != "builtin":
        return web.json_response({"ok": False, "error": "unknown mode"}, status=400)
    r = await ctx.apply(payload)
    if not isinstance(r, dict) or not r.get("ok"):
        err = r.get("error") if isinstance(r, dict) else None
        return web.json_response({"ok": False, "error": err or "save failed"},
                                 status=400)
    await ctx.restart_units(_VIDEO_UNITS)
    return web.json_response({"ok": True})


async def _video_users(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    base, key = _jf(ctx)
    if not key:
        return web.json_response({"users": [], "error": "Save an API key first"})
    try:
        users = await jf.list_users(await ctx.http(), base, key)
    except jf.JellyfinError as e:
        return web.json_response({"users": [], "error": str(e)})
    return web.json_response({"users": users})


def _err(msg: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": msg}, status=status)


async def _kiosk_signin(req: web.Request) -> web.Response:
    """Sign the kiosk's Chromium into Jellyfin as the chosen user: server-side
    Quick Connect for DeviceId <id>-kiosk, inject the session over CDP, then pin
    that DeviceId in the Jellyfin env. A failed injection revokes the device so
    no orphaned token is left behind."""
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    user_id = str(b.get("user_id", ""))
    base, key = _jf(ctx)
    if not key:
        return _err("Save an API key first", 400)
    s = await ctx.http()
    try:
        users = {u["id"]: u for u in await jf.list_users(s, base, key)}
    except jf.JellyfinError as e:
        return _err(str(e), 502)
    if user_id not in users:
        return _err("unknown Jellyfin user", 400)
    ident = ctx.read_identity()
    dev = kiosk_device_id(ctx)
    try:
        pub = await jf.public_info(s, base)
        token = await jf.quick_connect_token(
            s, base, key, user_id, dev, f"{ident['name']} kiosk", "boombox")
    except jf.JellyfinError as e:
        return _err(str(e), 502)
    creds = jf.credentials_blob(base, str(pub.get("Id", "")),
                                str(pub.get("ServerName", "")),
                                user_id, token, int(time.time() * 1000))
    try:
        await jf.inject_kiosk(CDP_BASE, base, dev, creds)
    except jf.JellyfinError as e:
        try:
            await jf.revoke_device(s, base, key, dev)
        except jf.JellyfinError:
            log.warning("could not revoke kiosk device after failed injection")
        return _err(str(e), 502)
    env = ctx.jellyfin_env()
    mode = "remote" if env.get("BOOMBOX_JELLYFIN_BASE") else "builtin"
    pin: dict[str, Any] = {"action": "jellyfin", "mode": mode, "device_id": dev}
    if mode == "remote":
        pin["base"] = base
    r = await ctx.apply(pin)
    if not isinstance(r, dict) or not r.get("ok"):
        err = r.get("error") if isinstance(r, dict) else None
        return _err(err or "could not save the kiosk device id", 400)
    await ctx.restart_units(["boombox-remote.service"])
    return web.json_response({"ok": True, "user": users[user_id]["name"]})


async def _kiosk_signout(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    base, key = _jf(ctx)
    dev = kiosk_device_id(ctx)
    errors: list[str] = []
    if key:
        try:
            await jf.revoke_device(await ctx.http(), base, key, dev)
        except jf.JellyfinError as e:
            errors.append(str(e))
    try:
        await jf.inject_kiosk(CDP_BASE, base, dev, None)
    except jf.JellyfinError as e:
        errors.append(str(e))
    return web.json_response({"ok": not errors, "error": "; ".join(errors)})


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/accounts/summary", _summary)
    r.add_get("/api/accounts/music", _music_get)
    r.add_post("/api/accounts/music/test", _music_test)
    r.add_put("/api/accounts/music", _music_put)
    r.add_get("/api/accounts/video", _video_get)
    r.add_post("/api/accounts/video/test", _video_test)
    r.add_put("/api/accounts/video", _video_put)
    r.add_get("/api/accounts/video/users", _video_users)
    r.add_post("/api/accounts/video/kiosk-signin", _kiosk_signin)
    r.add_post("/api/accounts/video/kiosk-signout", _kiosk_signout)
