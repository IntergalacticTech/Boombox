"""/api/accounts/storage* — Admin → Storage in the LAN app (spec 2A).

Behind the same admin-session gate as the Accounts cards (api._auth_mw runs
accounts.check_auth for every /api/accounts/ path). Drive / kept items /
downloads and their actions proxy boombox-library over loopback. The file
browser reuses remote_files' security-reviewed handlers, moved here from
the household tier so a paired phone can browse but not change files."""
from __future__ import annotations

import logging
from typing import Any

import remote_files
from aiohttp import web

from .accounts import STORAGE_UPLOAD_PATH

log = logging.getLogger("boombox-setup.storage")

LIBRARY_DOWN = "library service not answering"
_REMOVE_KINDS = frozenset({"album", "artist", "playlist", "starred_tracks", "card_tracks"})


async def _proxy(req: web.Request, method: str, path: str,
                 body: dict | None = None) -> web.Response:
    ctx: Any = req.app["ctx"]
    status, data = await ctx.library_call(method, path, body)
    if status == 0 or status >= 500 or not isinstance(data, dict):
        return web.json_response({"ok": False, "error": LIBRARY_DOWN}, status=502)
    return web.json_response(data, status=status)


async def _overview(req: web.Request) -> web.Response:
    return await _proxy(req, "GET", "/api/library/storage")


async def _remove(req: web.Request) -> web.Response:
    try:
        b = await req.json()
    except ValueError:
        b = None
    if not isinstance(b, dict):
        return web.json_response({"ok": False, "error": "expected a JSON object"}, status=400)
    kind, item_id = b.get("kind"), b.get("id")
    if kind not in _REMOVE_KINDS or not isinstance(item_id, str) or len(item_id) > 128:
        return web.json_response({"ok": False, "error": "kind and id are required"}, status=400)
    return await _proxy(req, "POST", "/api/library/storage/remove", {"kind": kind, "id": item_id})


async def _retry(req: web.Request) -> web.Response:
    return await _proxy(req, "POST", "/api/library/storage/retry", {})


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/accounts/storage", _overview)
    r.add_post("/api/accounts/storage/remove", _remove)
    r.add_post("/api/accounts/storage/retry", _retry)
    r.add_get("/api/accounts/storage/files/browse", remote_files.browse)
    r.add_post(STORAGE_UPLOAD_PATH, remote_files.upload)
    r.add_post("/api/accounts/storage/files/delete", remote_files.delete)
