"""/api/accounts/* — the LAN Accounts page backend.

Auth is NOT the wizard's token/code: nginx Basic auth on the LAN port is the
admin gate. nginx forwards `X-Boombox-User: $remote_user` and `X-Real-IP`;
we require a user AND a non-loopback client. The loopback `X-Real-IP` check is
what refuses the kiosk: `$remote_user` is not a reliable gate there, since any
client that sends Basic credentials (including a page open in the kiosk, on the
unauthenticated loopback server) populates it. Mutations also need JSON and, when the browser sends Origin, a
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
_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")
_BUILTIN_BASE = "http://127.0.0.1:8096"
_DEFAULT_PORTS = {"http": 80, "https": 443}
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
    return (env.get("BOOMBOX_JELLYFIN_BASE") or _BUILTIN_BASE,
            env.get("JELLYFIN_API_KEY", ""))


def _origin(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of an http(s) URL — lowercased, default port
    filled in — or None when it has no usable origin."""
    try:
        u = urlsplit(url.strip())
        scheme = u.scheme.lower()
        port = u.port
    except ValueError:
        return None
    if scheme not in _DEFAULT_PORTS or not u.hostname:
        return None
    return scheme, u.hostname.lower(), port or _DEFAULT_PORTS[scheme]


def _same_origin(a: str, b: str) -> bool:
    oa = _origin(a)
    return oa is not None and oa == _origin(b)


_NEED_KEY = "Enter the API key for this server"
_BAD_KEY = "The API key may only contain letters and digits"


def _key_for(ctx: Any, base: str, submitted: str) -> str:
    """The key to use against `base`: the submitted one, else the stored one —
    but only when `base` is the stored server's origin, so a saved key is
    never sent to a different host. "" when there is none."""
    if submitted:
        return submitted
    stored_base, stored_key = _jf(ctx)
    return stored_key if _same_origin(base, stored_base) else ""


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
    submitted = str(b.get("api_key") or "")
    if not _BASE_RE.match(base):
        return web.json_response(_bad_base())
    if submitted and not _KEY_RE.match(submitted):
        return _err(_BAD_KEY, 400)
    key = _key_for(ctx, base, submitted)
    if not key:
        return web.json_response({"ok": False, "error": _NEED_KEY})
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
    env = ctx.jellyfin_env()
    old_mode = "remote" if env.get("BOOMBOX_JELLYFIN_BASE") else "builtin"
    old_base = _jf(ctx)[0]
    if mode == "remote":
        base = str(b.get("base", "")).strip().rstrip("/")
        if not _BASE_RE.match(base):
            return web.json_response(_bad_base(), status=400)
        payload["base"] = base
        submitted = str(b.get("api_key") or "")
        if submitted and not _KEY_RE.match(submitted):
            return _err(_BAD_KEY, 400)
        key = _key_for(ctx, base, submitted)
        if not key:
            # A stored key is kept only for the same server; a new host
            # needs its own (even with "Save anyway").
            return _err(_NEED_KEY, 400)
        if submitted:
            payload["api_key"] = submitted
        # Spec: validate → test → write; never overwrite a working config
        # with one that fails, unless the owner explicitly chose "Save anyway".
        if b.get("force") is not True:
            try:
                await jf.system_info(await ctx.http(), base, key)
            except jf.JellyfinError as e:
                return web.json_response({"ok": False, "error": str(e),
                                          "can_force": True}, status=400)
    elif mode != "builtin":
        return web.json_response({"ok": False, "error": "unknown mode"}, status=400)
    new_base = payload.get("base", _BUILTIN_BASE)
    if mode != old_mode or not _same_origin(new_base, old_base):
        # The kiosk's pinned DeviceId belongs to the old server's session.
        payload["device_id"] = ""
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
    if not ctx.jellyfin_env().get("BOOMBOX_JELLYFIN_BASE"):
        # The built-in server needs no picker: the kiosk opens it at
        # localhost, a different origin than the one we could sign in to.
        return _err("Kiosk sign-in is only needed for a remote Jellyfin server", 400)
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
    r = await _apply_pin(ctx, dev)
    if not isinstance(r, dict) or not r.get("ok"):
        err = r.get("error") if isinstance(r, dict) else None
        return _err(err or "could not save the kiosk device id", 400)
    await ctx.restart_units(["boombox-remote.service"])
    return web.json_response({"ok": True, "user": users[user_id]["name"]})


async def _apply_pin(ctx: Any, device_id: str) -> Any:
    """Set (or, with "", remove) BOOMBOX_JELLYFIN_DEVICE_ID, keeping the mode."""
    base = ctx.jellyfin_env().get("BOOMBOX_JELLYFIN_BASE")
    pin: dict[str, Any] = {"action": "jellyfin", "mode": "remote" if base else "builtin",
                           "device_id": device_id}
    if base:
        pin["base"] = base
    return await ctx.apply(pin)


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
    # Unpin so phone control falls back to finding the kiosk's session.
    r = await _apply_pin(ctx, "")
    if not isinstance(r, dict) or not r.get("ok"):
        errors.append(_helper_error(r, "could not clear the kiosk device id"))
    else:
        await ctx.restart_units(["boombox-remote.service"])
    return web.json_response({"ok": not errors, "error": "; ".join(errors)})


_STREAMING_FIELDS = ("airplay_name", "airplay_password", "airplay_password_clear",
                     "spotify_name")


def _helper_error(r: Any, default: str) -> str:
    err = r.get("error") if isinstance(r, dict) else None
    return err if isinstance(err, str) and err else default


async def _streaming_get(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    r = await ctx.apply({"action": "streaming-status"})
    if not isinstance(r, dict) or not r.get("ok"):
        return web.json_response({"error": _helper_error(r, "status unavailable")},
                                 status=502)
    return web.json_response({k: v for k, v in r.items() if k != "ok"})


async def _streaming_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    clear = b.get("airplay_password_clear")
    if clear is not None and not isinstance(clear, bool):
        return _err("airplay_password_clear must be true or false", 400)
    # Only whitelisted fields reach the root helper, which does the validation.
    # The clear flag is forwarded only when it is exactly true.
    payload = {"action": "streaming", **{k: b[k] for k in _STREAMING_FIELDS
                                         if k in b and k != "airplay_password_clear"}}
    if clear is True:
        payload["airplay_password_clear"] = True
    r = await ctx.apply(payload)
    if not isinstance(r, dict) or not r.get("ok"):
        return _err(_helper_error(r, "save failed"), 400)
    return web.json_response({"ok": True, "changed": r.get("changed", [])})


async def _web_login_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await _json_body(req)
    if b is None:
        return _bad_body()
    cur = str(b.get("current_password", ""))
    new = str(b.get("new_password", ""))
    r = await ctx.apply({"action": "web-password",
                         "current_password": cur, "new_password": new})
    if not isinstance(r, dict) or not r.get("ok"):
        err = _helper_error(r, "not changed")
        for secret in (cur, new):
            if secret:
                err = err.replace(secret, "***")
        return _err(err, 400)
    return web.json_response({"ok": True, "updated": r.get("updated", [])})


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
    r.add_get("/api/accounts/streaming", _streaming_get)
    r.add_put("/api/accounts/streaming", _streaming_put)
    r.add_put("/api/accounts/web-login", _web_login_put)
