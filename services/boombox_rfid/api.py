"""HTTP API for boombox-rfid (mounted at :6688, proxied via nginx under
/api/rfid/).

Context (injected by the entry point) exposes the DB connection plus a
small surface for recording taps and querying the last unbound UID.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Protocol

from aiohttp import web

from . import __version__
from .bindings import bind as _bind_fn
from .bindings import list_bindings
from .bindings import unbind as _unbind_fn
from .models import BindingKind

log = logging.getLogger("boombox-rfid.api")


class Context(Protocol):
    conn: sqlite3.Connection
    last_unbound_uid: str
    last_unbound_ts: float
    last_tap_uid: str
    last_tap_ts: float

    def device_path(self) -> str: ...


def build_app(ctx: Context) -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.router.add_get("/api/rfid/status", _status)
    app.router.add_get("/api/rfid/bindings", _list)
    app.router.add_post("/api/rfid/bind", _bind)
    app.router.add_delete("/api/rfid/bind/{uid}", _unbind)
    app.router.add_get("/api/rfid/recent", _recent)
    return app


async def _status(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response({
        "service_version": __version__,
        "device_path": ctx.device_path(),
        "last_tap_uid": ctx.last_tap_uid,
        "last_tap_ts": ctx.last_tap_ts,
    })


async def _list(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    items = [
        {
            "uid": b.uid, "kind": b.kind.value, "target_id": b.target_id,
            "label": b.label, "added_at": b.added_at,
            "last_tap_ts": b.last_tap_ts, "tap_count": b.tap_count,
        }
        for b in list_bindings(ctx.conn)
    ]
    return web.json_response({"bindings": items})


async def _bind(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    uid = (body.get("uid") or "").strip()
    target_id = (body.get("target_id") or "").strip()
    try:
        kind = BindingKind(body.get("kind", ""))
    except ValueError:
        return web.json_response({"error": "invalid kind"}, status=400)
    if not uid:
        return web.json_response({"error": "missing uid"}, status=400)
    if not target_id:
        return web.json_response({"error": "missing target_id"}, status=400)
    label = body.get("label")
    _bind_fn(ctx.conn, uid, kind, target_id, label)
    # A bind clears any pending unbound notification for that uid.
    if ctx.last_unbound_uid == uid:
        ctx.last_unbound_uid = ""
    return web.json_response({"ok": True})


async def _unbind(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    uid = req.match_info["uid"]
    removed = _unbind_fn(ctx.conn, uid)
    if not removed:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"ok": True})


async def _recent(req: web.Request) -> web.Response:
    """Last unbound UID + timestamp. Used by the touchscreen + PWA to
    show a 'New card detected — bind it' prompt. Empty uid means no
    unbound card pending."""
    ctx: Context = req.app["ctx"]
    return web.json_response({
        "uid": ctx.last_unbound_uid,
        "ts": ctx.last_unbound_ts,
    })
