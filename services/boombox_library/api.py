"""HTTP surface for boombox-library (mounted at :6687, proxied via nginx
under /api/library/).

The app needs a Context object supplied by the service entry point.
Context exposes the DB connection, config, cache drive state, and a few
async hooks (test_source, trigger_sync, is_online) so the API doesn't
hard-depend on the runtime wiring (keeps tests fast).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Protocol

from aiohttp import web

from . import __version__
from .config import LibraryConfig, SourceConfig
from .models import PinKind, PinSource
from .pins import pin as _pin_fn, unpin as _unpin_fn
from .resolver import resolve_playback

log = logging.getLogger("boombox-library.api")


class Context(Protocol):
    conn: object  # sqlite3.Connection
    cfg: LibraryConfig
    # Phase 2 additions for /health, /cache/adopt, /cache/streamed, /cache/clear, /cache/candidates
    last_sync_ts: float
    syncing: bool

    async def is_online(self) -> bool: ...
    async def trigger_sync(self) -> None: ...
    def cache_drive_state(self): ...
    def save_config(self, cfg: LibraryConfig) -> None: ...
    async def test_source(self, url: str, username: str, password: str) -> tuple[bool, str]: ...
    async def adopt_cache(self, mount_path: str) -> None: ...
    def enqueue_streamed_download(self, track_id: str) -> None: ...
    async def clear_streamed_cache(self) -> int: ...
    def cache_candidates(self) -> list[dict]: ...


def build_app(ctx: Context) -> web.Application:
    app = web.Application()
    app["ctx"] = ctx
    app.router.add_get("/api/library/health", _health)
    app.router.add_get("/api/library/source", _source_get)
    app.router.add_put("/api/library/source", _source_put)
    app.router.add_post("/api/library/source/test", _source_test)
    app.router.add_get("/api/library/browse", _browse)
    app.router.add_get("/api/library/search", _search)
    app.router.add_post("/api/library/pin", _pin)
    app.router.add_post("/api/library/sync/run", _sync_run)
    app.router.add_get("/api/library/track/{track_id}/playback", _resolver)
    app.router.add_get("/api/library/cache/stats", _cache_stats)
    app.router.add_post("/api/library/cache/adopt", _cache_adopt)
    app.router.add_post("/api/library/cache/streamed", _cache_streamed)
    app.router.add_post("/api/library/cache/clear", _cache_clear)
    app.router.add_get("/api/library/cache/candidates", _cache_candidates)
    return app


async def _health(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    drive = ctx.cache_drive_state()
    return web.json_response({
        "service_version": __version__,
        "navidrome_reachable": await ctx.is_online(),
        "cache_present": bool(drive and drive.present) if drive else False,
        "cache_mount": str(drive.mount_path) if drive and drive.mount_path else None,
        "last_sync_ts": ctx.last_sync_ts,
        "syncing": ctx.syncing,
    })


async def _source_get(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    s = ctx.cfg.source
    return web.json_response({"url": s.url, "username": s.username})


async def _source_put(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    new_source = SourceConfig(
        url=body.get("url", ""),
        username=body.get("username", ""),
        password=body.get("password", ""),
    )
    ok, msg = await ctx.test_source(new_source.url, new_source.username, new_source.password)
    if not ok:
        # Defense in depth: never echo the submitted password back, even
        # if upstream test_source leaked it into its error message.
        safe_msg = msg.replace(new_source.password, "***") if new_source.password else msg
        return web.json_response({"ok": False, "error": safe_msg}, status=400)
    ctx.save_config(replace(ctx.cfg, source=new_source))
    await ctx.trigger_sync()
    return web.json_response({"ok": True})


async def _source_test(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    ok, msg = await ctx.test_source(
        body.get("url", ""), body.get("username", ""), body.get("password", ""),
    )
    return web.json_response({"ok": ok, "error": msg if not ok else ""})


_BROWSE_QUERIES = {
    "artists": "SELECT id, name, album_count, art_id FROM artists ORDER BY sort_name",
    "albums": "SELECT id, name, artist_id, year, art_id FROM albums ORDER BY sort_name",
    "playlists": "SELECT id, name, song_count FROM playlists ORDER BY name",
}


async def _browse(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    t = req.query.get("type", "artists")
    sql = _BROWSE_QUERIES.get(t)
    if not sql:
        return web.json_response({"error": f"unknown type {t}"}, status=400)
    rows = list(ctx.conn.execute(sql))
    return web.json_response({"items": [dict(r) for r in rows]})


async def _search(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    q = req.query.get("q", "").strip()
    if not q:
        return web.json_response({"results": []})
    # FTS5 MATCH; escape double-quote inside q
    safe = q.replace('"', '""')
    rows = list(ctx.conn.execute(
        "SELECT content_type, id, title FROM search_index "
        "WHERE search_index MATCH ? LIMIT 200",
        (f'"{safe}"',),
    ))
    return web.json_response({"results": [dict(r) for r in rows]})


async def _pin(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    try:
        kind = PinKind(body["kind"])
    except (KeyError, ValueError):
        return web.json_response({"error": "invalid kind"}, status=400)
    target_id = body.get("id")
    if not target_id:
        return web.json_response({"error": "missing id"}, status=400)
    mode = body.get("mode", "pin")
    # source defaults to USER for backwards compat with Phase 1 callers.
    raw_source = body.get("source", "user")
    try:
        source = PinSource(raw_source)
    except ValueError:
        return web.json_response({"error": "invalid source"}, status=400)
    if mode == "pin":
        _pin_fn(ctx.conn, kind, target_id, source)
        # Kick a sync so downloads start immediately rather than waiting
        # for the next hourly tick. Sync is no-op if NAS unreachable.
        await ctx.trigger_sync()
    elif mode == "unpin":
        # If a source was explicitly passed, filter by it; otherwise force-delete.
        if "source" in body:
            _unpin_fn(ctx.conn, kind, target_id, source=source)
        else:
            _unpin_fn(ctx.conn, kind, target_id)
    else:
        return web.json_response({"error": "invalid mode"}, status=400)
    return web.json_response({"ok": True})


async def _sync_run(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    await ctx.trigger_sync()
    return web.json_response({"ok": True})


async def _resolver(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    track_id = req.match_info["track_id"]
    online = await ctx.is_online()
    r = resolve_playback(ctx.conn, track_id, online)
    return web.json_response({
        "source": r.source.value,
        "uri": r.uri,
        "cache_status": r.cache_status,
    })


async def _cache_stats(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    drive = ctx.cache_drive_state()
    if not drive or not drive.present:
        return web.json_response({
            "present": False, "capacity": 0, "free": 0,
            "pinned_bytes": 0, "streamed_bytes": 0,
            "reserved": ctx.cfg.cache.reserve_bytes,
        })
    from .pins import all_pinned_track_ids
    pinned_ids = all_pinned_track_ids(ctx.conn)
    rows = list(ctx.conn.execute(
        "SELECT track_id, size_bytes FROM cache_state WHERE status='present'"
    ))
    pinned_bytes = sum(
        int(r["size_bytes"] or 0) for r in rows if r["track_id"] in pinned_ids
    )
    streamed_bytes = sum(
        int(r["size_bytes"] or 0) for r in rows if r["track_id"] not in pinned_ids
    )
    return web.json_response({
        "present": True,
        "mount_path": str(drive.mount_path),
        "capacity": drive.total_bytes or 0,
        "free": drive.free_bytes or 0,
        "pinned_bytes": pinned_bytes,
        "streamed_bytes": streamed_bytes,
        "reserved": ctx.cfg.cache.reserve_bytes,
    })


async def _cache_adopt(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    mount_path = body.get("mount_path")
    if not mount_path:
        return web.json_response({"error": "missing mount_path"}, status=400)
    await ctx.adopt_cache(mount_path)
    return web.json_response({"ok": True})


async def _cache_streamed(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    track_id = req.query.get("id", "").strip()
    if not track_id:
        return web.json_response({"error": "missing id"}, status=400)
    ctx.enqueue_streamed_download(track_id)
    return web.json_response({"ok": True})


async def _cache_clear(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    cleared = await ctx.clear_streamed_cache()
    return web.json_response({"ok": True, "cleared": cleared})


async def _cache_candidates(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response({"candidates": ctx.cache_candidates()})
