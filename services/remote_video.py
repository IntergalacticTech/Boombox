"""Jellyfin browsing for the LAN app: /api/remote/video/*.

Server-side only: the stored API key (jellyfin_env) goes out in an
X-Emby-Token header and never into a response, a client-visible URL or a log
line. Browsing is as the Jellyfin user the kiosk is signed in as — the
LastUserId of the pinned kiosk device (BOOMBOX_JELLYFIN_DEVICE_ID, set by
Admin → Accounts → Video server → Sign kiosk in). With no pin only an
on-device server falls back to the bootstrapped JELLYFIN_USER_ID; anything
else answers "kiosk not signed in".
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp
from aiohttp import web
from jellyfin_client import DEVICE_ID_ENV, server_is_loopback
from jellyfin_env import jellyfin_base, jellyfin_token

log = logging.getLogger("boombox-remote")

TICKS_PER_SECOND = 10_000_000
TIMEOUT = aiohttp.ClientTimeout(total=15)
USER_CACHE_S = 60.0
DEFAULT_IMAGE_CACHE = Path.home() / ".cache" / "boombox-remote" / "video"
ITEM_FIELDS = "ProductionYear,Overview"
DEFAULT_LIMIT = 60
MAX_LIMIT = 200
MAX_SEARCH = 100
_ITEM_ID_RE = re.compile(r"^[0-9A-Fa-f-]{1,64}$")
_TYPES_RE = re.compile(r"^[A-Za-z]{1,32}(,[A-Za-z]{1,32}){0,5}$")

NOT_CONFIGURED = "video server not configured"
NOT_SIGNED_IN = "kiosk not signed in"
UNREACHABLE = "video server unreachable"
KEY_REFUSED = "video server refused the stored API key"


class VideoError(Exception):
    """A user-facing failure; `status` is the HTTP status for the phone."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _image_cache_dir() -> Path:
    path = Path(os.environ.get("BOOMBOX_REMOTE_VIDEO_CACHE", str(DEFAULT_IMAGE_CACHE)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secs(ticks: object) -> int:
    return int(ticks) // TICKS_PER_SECOND if isinstance(ticks, (int, float)) else 0


def normalize_item(i: dict) -> dict:
    raw_ud, raw_tags = i.get("UserData"), i.get("ImageTags")
    ud: dict = raw_ud if isinstance(raw_ud, dict) else {}
    tags: dict = raw_tags if isinstance(raw_tags, dict) else {}
    pct = ud.get("PlayedPercentage")
    return {
        "id": i.get("Id"),
        "name": i.get("Name"),
        "type": i.get("Type"),
        "collection_type": i.get("CollectionType"),
        "is_folder": bool(i.get("IsFolder")),
        "year": i.get("ProductionYear"),
        "runtime_s": _secs(i.get("RunTimeTicks")),
        "series_name": i.get("SeriesName"),
        "season": i.get("ParentIndexNumber"),
        "episode": i.get("IndexNumber"),
        "overview": i.get("Overview"),
        "has_image": bool(tags.get("Primary")),
        "played": bool(ud.get("Played")),
        "progress": round(float(pct), 1) if isinstance(pct, (int, float)) else None,
        "resume_s": _secs(ud.get("PlaybackPositionTicks")),
    }


def _items_of(data: Any) -> list[dict]:
    items = data.get("Items") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def image_width(raw: str | None) -> int:
    """Clamp to 80..1280 and round UP to a multiple of 80, so the poster
    cache holds a handful of sizes per item instead of one per request."""
    try:
        w = int(raw) if raw else 320
    except ValueError:
        w = 320
    w = max(80, min(1280, w))
    return -(-w // 80) * 80


class JellyfinBrowser:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._sess = session
        self._user: tuple[str, str, float] | None = None   # (device, user, fetched)

    def _target(self) -> tuple[str, dict[str, str]]:
        key = jellyfin_token()
        if not key:
            raise VideoError(503, NOT_CONFIGURED)
        return jellyfin_base(), {"X-Emby-Token": key}

    async def _request(self, method: str, path: str,
                       params: dict[str, str] | None = None) -> tuple[int, bytes, str]:
        base, headers = self._target()
        try:
            async with self._sess.request(method, f"{base}{path}", params=params,
                                          headers=headers, timeout=TIMEOUT) as r:
                return r.status, await r.read(), r.content_type
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Type name only: some aiohttp errors echo request details.
            log.warning("jellyfin %s %s failed: %s", method, path, type(e).__name__)
            raise VideoError(502, UNREACHABLE) from None

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> Any | None:
        """Parsed JSON; None on 404; VideoError(502) on any other failure."""
        status, body, _ctype = await self._request("GET", path, params)
        if status == 404:
            return None
        if status in (401, 403):
            log.warning("jellyfin GET %s → HTTP %s (API key rejected?)", path, status)
            raise VideoError(502, KEY_REFUSED)
        if not 200 <= status < 300:
            log.warning("jellyfin GET %s → HTTP %s", path, status)
            raise VideoError(502, UNREACHABLE)
        try:
            return json.loads(body)
        except ValueError:
            raise VideoError(502, UNREACHABLE) from None

    async def kiosk_user(self) -> str:
        device_id = os.environ.get(DEVICE_ID_ENV, "").strip()
        if not device_id:
            self._target()                 # unconfigured → 503 before 409
            fallback = os.environ.get("JELLYFIN_USER_ID", "").strip()
            if fallback and server_is_loopback(jellyfin_base()):
                return fallback
            raise VideoError(409, NOT_SIGNED_IN)
        now = time.monotonic()
        if self._user and self._user[0] == device_id and now - self._user[2] < USER_CACHE_S:
            return self._user[1]
        info = await self._get_json("/Devices/Info", {"id": device_id})
        user_id = info.get("LastUserId") if isinstance(info, dict) else None
        if not isinstance(user_id, str) or not user_id:
            raise VideoError(409, NOT_SIGNED_IN)
        self._user = (device_id, user_id, now)
        return user_id

    async def _get_new_or_old(self, new_path: str, old_path: str,
                              params: dict[str, str]) -> Any | None:
        data = await self._get_json(new_path, params)
        if data is None:
            data = await self._get_json(old_path, params)
        return data

    async def views(self) -> list[dict]:
        uid = await self.kiosk_user()
        data = await self._get_new_or_old("/UserViews", f"/Users/{uid}/Views", {"userId": uid})
        return [normalize_item(i) for i in _items_of(data)]

    async def resume(self) -> list[dict]:
        uid = await self.kiosk_user()
        params = {"userId": uid, "limit": "24", "mediaTypes": "Video", "fields": ITEM_FIELDS}
        data = await self._get_new_or_old("/UserItems/Resume", f"/Users/{uid}/Items/Resume",
                                          params)
        return [normalize_item(i) for i in _items_of(data)]

    async def items(self, *, parent_id: str, types: str, search: str,
                    start: int, limit: int) -> dict:
        uid = await self.kiosk_user()
        params = {"userId": uid, "startIndex": str(start), "limit": str(limit),
                  "fields": ITEM_FIELDS, "sortBy": "ParentIndexNumber,IndexNumber,SortName",
                  "sortOrder": "Ascending"}
        if parent_id:
            params["parentId"] = parent_id
        if types:
            params["includeItemTypes"] = types
        if search:
            params["searchTerm"] = search
        if types or search:
            params["recursive"] = "true"
        data = await self._get_json("/Items", params)
        items = _items_of(data)
        total = data.get("TotalRecordCount") if isinstance(data, dict) else None
        return {"items": [normalize_item(i) for i in items],
                "total": total if isinstance(total, int) else len(items), "start": start}

    async def image(self, item_id: str, max_width: int) -> bytes | None:
        path = _image_cache_dir() / f"{item_id.lower()}-{max_width}.jpg"
        try:
            return path.read_bytes()
        except FileNotFoundError:
            pass
        status, body, ctype = await self._request(
            "GET", f"/Items/{item_id}/Images/Primary",
            {"maxWidth": str(max_width), "format": "Jpg", "quality": "85"})
        if status == 404:
            return None
        if not 200 <= status < 300 or not ctype.startswith("image/"):
            log.warning("jellyfin poster %s → HTTP %s %s", item_id, status, ctype)
            raise VideoError(502, UNREACHABLE)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return body


def _fail(status: int, message: str) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _guard(fn: Handler) -> Handler:
    """VideoError → its status + message; anything unexpected → 502, never 500."""
    @functools.wraps(fn)
    async def wrapper(req: web.Request) -> web.StreamResponse:
        try:
            return await fn(req)
        except VideoError as e:
            return _fail(e.status, e.message)
        except Exception:
            log.exception("video route %s failed", req.path)
            return _fail(502, UNREACHABLE)
    return wrapper


def _int_param(raw: str | None, default: int, lo: int, hi: int) -> int | None:
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        return None
    return v if lo <= v <= hi else None


def _make_handlers(browser: JellyfinBrowser) -> dict[str, Handler]:
    async def views(_req: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "items": await browser.views()})

    async def resume(_req: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "items": await browser.resume()})

    async def items(req: web.Request) -> web.StreamResponse:
        q = req.query
        parent_id = q.get("parent_id", "")
        types = q.get("type", "")
        search = q.get("search", "").strip()
        start = _int_param(q.get("start"), 0, 0, 1_000_000)
        limit = _int_param(q.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
        if ((parent_id and not _ITEM_ID_RE.match(parent_id))
                or (types and not _TYPES_RE.match(types))
                or len(search) > MAX_SEARCH or start is None or limit is None):
            return _fail(400, "bad query")
        page = await browser.items(parent_id=parent_id, types=types, search=search,
                                   start=start, limit=limit)
        return web.json_response({"ok": True, **page})

    async def image(req: web.Request) -> web.StreamResponse:
        item_id = req.match_info["item_id"]
        if not _ITEM_ID_RE.match(item_id):
            return _fail(400, "bad item id")
        data = await browser.image(item_id, image_width(req.query.get("max_width")))
        if data is None:
            return web.Response(status=404)
        return web.Response(body=data, content_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=86400"})

    return {"views": views, "resume": resume, "items": items, "image": image}


def add_routes(app: web.Application, browser: JellyfinBrowser) -> None:
    """Register the browse/poster routes. /video/state and /video/command stay
    in jellyfin_client.py."""
    h = {name: _guard(fn) for name, fn in _make_handlers(browser).items()}
    app.router.add_get("/api/remote/video/views", h["views"])
    app.router.add_get("/api/remote/video/resume", h["resume"])
    app.router.add_get("/api/remote/video/items", h["items"])
    app.router.add_get("/api/remote/video/image/{item_id}", h["image"])
