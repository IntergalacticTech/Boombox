"""HTTP surface for boombox-setup (mounted at :6689, proxied via nginx under
/api/setup/ with `auth_basic off`).

Auth model: mutating routes require the caller to be **localhost** (the kiosk,
identified by nginx's X-Real-IP) OR to carry a valid **setup token** (minted on
the kiosk, scanned via QR onto a phone) in an `Authorization: Bearer` header —
never a URL query param, which would land in logs/history. `session` minting
is localhost-only.

Once setup is **complete**, everything but `status`/`session` is refused
until setup is re-opened, i.e. until the kiosk mints a fresh session (Settings
→ Setup wizard opens the wizard's Welcome step, which does exactly that);
POST /complete closes it again, as does POST /session/close (the kiosk player
calls it on load, i.e. when the wizard was left without finishing) or
REOPEN_TTL_S without an authenticated request. `status` is open, but once complete an
unauthenticated caller only gets `complete`/`identity`/`skin` — no Wi-Fi/IP,
music username, video base or remote peer names.

Every POST/PUT/DELETE must be `Content-Type: application/json`. A cross-site
page can only send that after a CORS preflight (which this app never grants),
so a plain form post or no-cors fetch from a page the kiosk browser opens can't
ride the kiosk's localhost trust.

The route handlers are thin — all side effects live behind the Context
protocol so the entry point owns runtime wiring (sudo helper, HTTP proxying to
library/remote, user-unit restarts) and tests can supply a fake.
"""
from __future__ import annotations

import logging
from typing import Protocol

from aiohttp import web

from . import __version__, accounts, storage
from .session import REOPEN_TTL_S, TOKEN_TTL_S, SetupSession

log = logging.getLogger("boombox-setup.api")


class Context(Protocol):
    lan_port: int

    # identity / state reads (local, cheap)
    def read_identity(self) -> dict: ...
    def wifi_status(self) -> dict: ...
    def video_status(self) -> dict: ...
    def is_complete(self) -> bool: ...
    def mark_complete(self) -> None: ...
    def lan_host(self) -> str: ...
    def get_skin(self) -> str | None: ...
    def set_skin(self, skin_id: str) -> bool: ...
    # the boombox web password (Admin unlock), read fresh; None when unset
    def web_password(self) -> str | None: ...

    # privileged helper (sudo) + post-apply user-unit restarts
    async def apply(self, payload: dict) -> dict: ...
    async def restart_units(self, units: list[str]) -> None: ...

    # proxied to boombox-library / boombox-remote over loopback
    async def music_get(self) -> dict: ...
    async def music_test(self, url: str, username: str, password: str) -> tuple[bool, str]: ...
    async def music_save(self, url: str, username: str, password: str) -> tuple[bool, str]: ...
    async def remote_status(self) -> dict: ...
    async def remote_enable(self) -> dict: ...
    async def remote_pair_start(self) -> dict: ...
    # one JSON call to boombox-library: (status, body); (0, None) = no answer
    async def library_call(self, method: str, path: str,
                           body: dict | None = None) -> tuple[int, dict | None]: ...


def _client_is_localhost(req: web.Request) -> bool:
    # nginx sets X-Real-IP on /api/setup/. Absent header ⇒ a direct loopback
    # call (tests / on-box curl) ⇒ trusted. Present ⇒ trust only loopback.
    xri = req.headers.get("X-Real-IP")
    if xri is None:
        return True
    return xri in ("127.0.0.1", "::1", "localhost")


def _token_from(req: web.Request) -> str:
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def _authenticated(req: web.Request) -> bool:
    sess: SetupSession = req.app["session"]
    return _client_is_localhost(req) or sess.verify(_token_from(req))


_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@web.middleware
async def _auth_mw(req: web.Request, handler):
    if req.path.startswith(accounts.PREFIX):
        deny = accounts.check_auth(req)
        return deny if deny is not None else await handler(req)
    if req.method in _MUTATING and req.content_type != "application/json":
        return web.json_response(
            {"error": "Content-Type must be application/json"}, status=415)

    # Open routes: status (read-only; redacts itself when unauthenticated),
    # code→token redemption (gated by the on-screen code itself — and it can
    # only succeed while a session is live), and the OPTIONS preflight.
    open_paths = {"/api/setup/status", "/api/setup/session/redeem"}
    if req.method == "OPTIONS" or req.path in open_paths:
        return await handler(req)

    sess: SetupSession = req.app["session"]
    is_local = _client_is_localhost(req)

    # Minting a token requires physical access to the kiosk itself. After
    # completion this is also how setup is re-opened.
    if req.path == "/api/setup/session":
        if not is_local:
            return web.json_response({"error": "localhost only"}, status=403)
        return await handler(req)

    if not (is_local or sess.verify(_token_from(req))):
        return web.json_response({"error": "setup token required"}, status=401)

    # Closing is allowed even when nothing is open (idempotent no-op).
    if req.path == "/api/setup/session/close":
        return await handler(req)

    ctx: Context = req.app["ctx"]
    if ctx.is_complete():
        if not sess.active():
            return web.json_response(
                {"ok": False, "error": "setup is already complete — open "
                 "Settings → Setup wizard on the boombox to change it"},
                status=409)
        # Re-opened: activity keeps the short idle timeout from lapsing.
        sess.touch()
    return await handler(req)


def build_app(ctx: Context) -> web.Application:
    app = web.Application(middlewares=[_auth_mw])
    app["ctx"] = ctx
    app["session"] = SetupSession()
    r = app.router
    r.add_get("/api/setup/status", _status)
    r.add_post("/api/setup/session", _session_start)
    r.add_post("/api/setup/session/redeem", _session_redeem)
    r.add_post("/api/setup/session/close", _session_close)
    r.add_put("/api/setup/skin", _skin_put)
    r.add_put("/api/setup/identity", _identity)
    r.add_get("/api/setup/wifi/scan", _wifi_scan)
    r.add_put("/api/setup/wifi", _wifi_join)
    r.add_get("/api/setup/music", _music_get)
    r.add_post("/api/setup/music/test", _music_test)
    r.add_put("/api/setup/music", _music_put)
    r.add_get("/api/setup/remote", _remote_status)
    r.add_post("/api/setup/remote/enable", _remote_enable)
    r.add_post("/api/setup/remote/pair", _remote_pair)
    r.add_put("/api/setup/video", _video_put)
    r.add_post("/api/setup/complete", _complete)
    accounts.add_routes(app)
    storage.add_routes(app)
    return app


async def _status(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    ident = ctx.read_identity()
    complete = ctx.is_complete()
    # A token that no longer verifies (setup finished, service restarted)
    # gets a 401 rather than a silently-redacted body, so the wizard drops
    # the stale token and returns to code entry instead of rendering from
    # a status that's missing fields. The kiosk is trusted regardless.
    sess: SetupSession = req.app["session"]
    token = _token_from(req)
    if token and not _client_is_localhost(req) and not sess.verify(token):
        return web.json_response({"error": "setup token rejected"}, status=401)
    if complete and not _authenticated(req):
        # Enough for the kiosk gate (ui setupGate.ts: `complete`) and the
        # wizard's pre-auth screens; the name/hostname are already broadcast
        # over mDNS. Everything else waits for a token.
        return web.json_response({
            "service_version": __version__,
            "complete": True,
            "identity": ident,
            "skin": ctx.get_skin(),
        })
    try:
        music = await ctx.music_get()
    except Exception:
        music = {"configured": False, "reachable": False}
    try:
        remote = await ctx.remote_status()
    except Exception:
        remote = {"enabled": False, "peers": []}
    return web.json_response({
        "service_version": __version__,
        "complete": complete,
        "identity": ident,
        "wifi": ctx.wifi_status(),
        "music": music,
        "video": ctx.video_status(),
        "remote": remote,
        "skin": ctx.get_skin(),
    })


async def _session_start(req: web.Request) -> web.Response:
    sess: SetupSession = req.app["session"]
    ctx: Context = req.app["ctx"]
    # Re-opening a finished setup gets the short idle TTL; first-run setup
    # keeps the long one so stepping away mid-setup never logs you out.
    ttl = REOPEN_TTL_S if ctx.is_complete() else TOKEN_TTL_S
    token, code, expires_at = sess.mint(ttl=ttl)
    host = ctx.lan_host()
    base_url = f"http://{host}:{ctx.lan_port}/setup/"
    return web.json_response({
        "token": token,
        "code": code,
        "expires_at": expires_at,
        # Full URL (QR) and the typable base + code the kiosk displays.
        "url": f"{base_url}#t={token}",
        "base_url": base_url,
    })


async def _session_close(req: web.Request) -> web.Response:
    """Close a re-opened setup (kiosk left the wizard without finishing).
    A no-op during first-run setup: the kiosk can't reach the player then,
    and a phone may still be mid-flow on the live token."""
    ctx: Context = req.app["ctx"]
    if ctx.is_complete():
        sess: SetupSession = req.app["session"]
        sess.clear()
    return web.json_response({"ok": True})


async def _session_redeem(req: web.Request) -> web.Response:
    """Exchange the on-screen 6-digit code for the setup token — the typed-URL
    path for phones that can't scan the QR. Open route; the code is the gate."""
    sess: SetupSession = req.app["session"]
    body = await req.json()
    code = str(body.get("code", "")).strip()
    token = sess.redeem_code(code)
    if token is None:
        return web.json_response(
            {"ok": False, "error": "wrong or expired code — check the "
             "boombox screen and try again"}, status=403)
    return web.json_response({"ok": True, "token": token})


async def _skin_put(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    skin_id = str(body.get("id", "")).strip()
    if not ctx.set_skin(skin_id):
        return web.json_response({"ok": False, "error": "invalid skin id"},
                                 status=400)
    return web.json_response({"ok": True, "skin": skin_id})


async def _identity(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    result = await ctx.apply({
        "action": "identity",
        "name": body.get("name", ""),
        "rename_host": bool(body.get("rename_host", False)),
    })
    if not result.get("ok"):
        return web.json_response(result, status=400)
    # Re-register mDNS/BLE under the new name and refresh /info consumers.
    await ctx.restart_units(["boombox-remote"])
    return web.json_response(result)


async def _wifi_scan(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    result = await ctx.apply({"action": "wifi-scan"})
    status = 200 if result.get("ok") else 500
    return web.json_response(result, status=status)


async def _wifi_join(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    result = await ctx.apply({
        "action": "wifi-join",
        "ssid": body.get("ssid", ""),
        "psk": body.get("psk", ""),
    })
    return web.json_response(result, status=200 if result.get("ok") else 400)


async def _music_get(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(await ctx.music_get())


async def _music_test(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    b = await req.json()
    ok, err = await ctx.music_test(b.get("url", ""), b.get("username", ""), b.get("password", ""))
    return web.json_response({"ok": ok, "error": err if not ok else ""})


async def _music_put(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    b = await req.json()
    ok, err = await ctx.music_save(b.get("url", ""), b.get("username", ""), b.get("password", ""))
    if not ok:
        pw = b.get("password", "")
        safe = err.replace(pw, "***") if pw else err
        return web.json_response({"ok": False, "error": safe}, status=400)
    return web.json_response({"ok": True})


async def _remote_status(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(await ctx.remote_status())


async def _remote_enable(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(await ctx.remote_enable())


async def _remote_pair(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(await ctx.remote_pair_start())


async def _video_put(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    b = await req.json()
    payload = {"action": "jellyfin", "mode": b.get("mode", "")}
    if b.get("mode") == "remote":
        payload["base"] = b.get("base", "")
        payload["api_key"] = b.get("api_key", "")
    result = await ctx.apply(payload)
    if not result.get("ok"):
        return web.json_response(result, status=400)
    await ctx.restart_units(["boombox-remote"])
    return web.json_response(result)


async def _complete(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    ctx.mark_complete()
    # Setup is done — retire the session so the long-lived token can't
    # linger as an idle credential.
    sess: SetupSession = req.app["session"]
    sess.clear()
    return web.json_response({"ok": True})
