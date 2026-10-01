"""Home Library (boombox-library) routes for the LAN app: /api/remote/home/*.

GET routes pass boombox-library's JSON/images through unchanged — the phone
never talks to :6687 itself (loopback-only, no auth). POST /play resolves
track ids to playable URIs (cache file or the library's stream proxy), drops
offline misses, and plays or appends them through Mopidy the same way an
RFID card does: first track now, the rest in background chunks
(boombox_rfid.mopidy_client), with the full list recorded as the queue
intent so boombox-resume never snapshots a half-built queue.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Callable
from urllib.parse import quote

import aiohttp
from aiohttp import web
from boombox_rfid.mopidy_client import MopidyClient, PendingTail
from queue_intent import clear_intent, write_intent

log = logging.getLogger("boombox-remote")

LIBRARY_BASE = os.environ.get("BOOMBOX_LIBRARY_BASE", "http://127.0.0.1:6687")
MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
TIMEOUT = aiohttp.ClientTimeout(total=15)
BROWSE_TYPES = frozenset({"artists", "albums", "playlists"})
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MAX_PLAY_IDS = 1000           # boombox-library's RESOLVE_BATCH_MAX
SYNC_QUEUE_MAX = 10           # queue lists this short finish before we answer
MAX_QUERY = 200
_PASS_HEADERS = ("ETag", "Cache-Control")
KEEP_KINDS = frozenset({"album", "artist", "playlist"})
LIBRARY_DOWN = "library service not answering"
NOTHING_PLAYABLE = ("none of these tracks can play right now — they aren't cached "
                    "and the Home Library server is unreachable")
PLAYER_DOWN = "the music player isn't answering"


def _fail(status: int, error: str) -> web.Response:
    return web.json_response({"ok": False, "error": error}, status=status)


class HomePlayer:
    """Plays or appends resolved URIs, one operation at a time (a lock), so a
    double-tapped Play can't interleave two play_uris calls. A new play
    supersedes EVERYTHING still running in the background — the previous
    play's tail AND any long "Queue all" appends — and waits for them to
    stop before replacing the queue, so an old append can never land inside
    the new play's queue (as a new RFID tap does)."""

    def __init__(self, rpc_url: str = MOPIDY_RPC,
                 client_factory: Callable[[str], Any] = MopidyClient) -> None:
        self._rpc = rpc_url
        self._factory = client_factory
        self._lock = asyncio.Lock()
        self._tail_task: asyncio.Task | None = None
        self._queue_tasks: set[asyncio.Task] = set()

    async def _cancel_background(self) -> None:
        tasks = [t for t in (self._tail_task, *self._queue_tasks)
                 if t is not None and not t.done()]
        self._tail_task = None
        self._queue_tasks.clear()
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def play(self, uris: list[str]) -> None:
        async with self._lock:
            await self._cancel_background()
            clear_intent()
            async with self._factory(self._rpc) as m:
                tail = await m.play_uris(uris)
            if tail:
                token: str | None = None
                try:
                    token = write_intent(uris)
                except OSError as e:
                    log.warning("could not record queue intent: %s", e)
                self._tail_task = asyncio.create_task(self._append(tail, token))

    async def queue(self, uris: list[str]) -> None:
        async with self._lock:
            tail = PendingTail(uris=list(uris), after_tlid=None)
            if len(uris) <= SYNC_QUEUE_MAX:
                async with self._factory(self._rpc) as m:
                    await m.append_tail(tail)
                return
            task = asyncio.create_task(self._append(tail, None))
            self._queue_tasks.add(task)
            task.add_done_callback(self._queue_tasks.discard)

    async def _append(self, tail: PendingTail, token: str | None) -> None:
        try:
            async with self._factory(self._rpc) as m:
                n = await m.append_tail(tail)
            log.info("home library: queued %d/%d remaining tracks", n, len(tail.uris))
        except asyncio.CancelledError:
            log.info("home library: background queueing superseded")
            raise
        except Exception as e:
            log.warning("home library: background queueing failed: %s", e)
        if token is not None:
            clear_intent(token)


async def _proxy_get(session: aiohttp.ClientSession, url: str,
                     req: web.Request) -> web.Response:
    headers: dict[str, str] = {}
    inm = req.headers.get("If-None-Match")
    if inm:
        headers["If-None-Match"] = inm
    try:
        async with session.get(url, headers=headers, timeout=TIMEOUT) as r:
            body = await r.read()
            status = r.status
            ctype = r.content_type
            passthrough = {h: r.headers[h] for h in _PASS_HEADERS if h in r.headers}
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.warning("home library GET %s failed: %s", url, type(e).__name__)
        return _fail(502, LIBRARY_DOWN)
    if status >= 500:
        log.warning("home library GET %s → HTTP %s", url, status)
        return _fail(502, LIBRARY_DOWN)
    if status == 304:
        return web.Response(status=304, headers=passthrough)
    return web.Response(status=status, body=body, content_type=ctype, headers=passthrough)


async def _proxy_json(session: aiohttp.ClientSession, method: str, url: str,
                      body: dict | None = None) -> web.Response:
    """JSON call to boombox-library; its status and body pass through, its
    failures become 502."""
    try:
        async with session.request(method, url, json=body, timeout=TIMEOUT) as r:
            status = r.status
            try:
                data = await r.json(content_type=None)
            except ValueError:
                data = None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.warning("home library %s %s failed: %s", method, url, type(e).__name__)
        return _fail(502, LIBRARY_DOWN)
    if status >= 500 or not isinstance(data, dict):
        log.warning("home library %s %s → HTTP %s", method, url, status)
        return _fail(502, LIBRARY_DOWN)
    if status >= 400 and "ok" not in data:
        data = {"ok": False, "error": str(data.get("error") or "request refused")}
    return web.json_response(data, status=status)


def _make_handlers(session: aiohttp.ClientSession, base: str, player: HomePlayer):
    async def browse(req: web.Request) -> web.Response:
        t = req.query.get("type", "")
        if t not in BROWSE_TYPES:
            return _fail(400, "type must be artists, albums or playlists")
        return await _proxy_get(session, f"{base}/api/library/browse?type={t}", req)

    async def search(req: web.Request) -> web.Response:
        q = req.query.get("q", "").strip()
        if not q:
            return web.json_response({"results": []})
        if len(q) > MAX_QUERY:
            return _fail(400, "search text is too long")
        return await _proxy_get(session, f"{base}/api/library/search?q={quote(q)}", req)

    async def detail(req: web.Request) -> web.Response:
        kind = req.match_info["kind"]
        item_id = req.match_info["item_id"]
        if not _ID_RE.match(item_id):
            return _fail(400, "bad id")
        return await _proxy_get(
            session, f"{base}/api/library/{kind}/{quote(item_id, safe='')}", req)

    async def art(req: web.Request) -> web.Response:
        art_id = req.match_info["art_id"]
        if not _ID_RE.match(art_id):
            return _fail(400, "bad id")
        size = req.query.get("size", "")
        qs = f"?size={int(size)}" if size.isdigit() and 0 < int(size) <= 2000 else ""
        return await _proxy_get(
            session, f"{base}/api/library/art/{quote(art_id, safe='')}{qs}", req)

    async def play(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return _fail(400, "invalid_json")
        if not isinstance(body, dict):
            return _fail(400, "expected a JSON object")
        ids = body.get("ids")
        mode = body.get("mode", "play")
        if (not isinstance(ids, list) or not ids or len(ids) > MAX_PLAY_IDS
                or not all(isinstance(i, str) and _ID_RE.match(i) for i in ids)):
            return _fail(400, f"ids must be 1-{MAX_PLAY_IDS} track ids")
        if mode not in ("play", "queue"):
            return _fail(400, "mode must be play or queue")
        try:
            async with session.post(f"{base}/api/library/resolve", json={"ids": ids},
                                    timeout=TIMEOUT) as r:
                if r.status != 200:
                    log.warning("home library resolve → HTTP %s", r.status)
                    return _fail(502, LIBRARY_DOWN)
                data = await r.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.warning("home library resolve failed: %s", type(e).__name__)
            return _fail(502, LIBRARY_DOWN)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return _fail(502, LIBRARY_DOWN)
        uris = [it["uri"] for it in items
                if isinstance(it, dict) and it.get("source") != "offline_miss"
                and isinstance(it.get("uri"), str) and it["uri"]]
        if not uris:
            return _fail(409, NOTHING_PLAYABLE)
        try:
            if mode == "play":
                await player.play(uris)
            else:
                await player.queue(uris)
        except Exception as e:
            log.warning("home library %s failed: %s", mode, e)
            return _fail(502, PLAYER_DOWN)
        return web.json_response({"ok": True, "count": len(uris),
                                  "skipped": len(ids) - len(uris)})

    async def keep(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return _fail(400, "invalid_json")
        if not isinstance(body, dict):
            return _fail(400, "expected a JSON object")
        kind, item_id = body.get("kind"), body.get("id")
        if kind not in KEEP_KINDS:
            return _fail(400, "kind must be album, artist or playlist")
        if not isinstance(item_id, str) or not _ID_RE.match(item_id):
            return _fail(400, "bad id")
        return await _proxy_json(session, req.method, f"{base}/api/library/keep",
                                 {"kind": kind, "id": item_id})

    async def status(req: web.Request) -> web.Response:
        try:
            async with session.get(f"{base}/api/library/health", timeout=TIMEOUT) as r:
                health = await r.json(content_type=None) if r.status == 200 else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.warning("home library health failed: %s", type(e).__name__)
            health = None
        if not isinstance(health, dict):
            return _fail(502, LIBRARY_DOWN)
        return web.json_response({"online": bool(health.get("navidrome_reachable")),
                                  "internal_storage": bool(health.get("internal_storage"))})

    async def offline(req: web.Request) -> web.Response:
        return await _proxy_get(session, f"{base}/api/library/offline", req)

    return {"browse": browse, "search": search, "detail": detail, "art": art,
            "play": play, "keep": keep, "status": status, "offline": offline}


def add_routes(app: web.Application, session: aiohttp.ClientSession,
               player: HomePlayer, base: str = LIBRARY_BASE) -> None:
    """Register /api/remote/home/*. `session` is the service's shared client
    session (per-request 15 s timeouts override its default)."""
    h = _make_handlers(session, base.rstrip("/"), player)
    app.router.add_get("/api/remote/home/browse", h["browse"])
    app.router.add_get("/api/remote/home/search", h["search"])
    app.router.add_get("/api/remote/home/status", h["status"])
    app.router.add_get("/api/remote/home/offline", h["offline"])
    app.router.add_get("/api/remote/home/art/{art_id}", h["art"])
    app.router.add_get("/api/remote/home/{kind:artist|album|playlist}/{item_id}", h["detail"])
    app.router.add_post("/api/remote/home/play", h["play"])
    app.router.add_post("/api/remote/home/keep", h["keep"])
    app.router.add_delete("/api/remote/home/keep", h["keep"])
