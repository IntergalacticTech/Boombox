"""Local audio stream proxy: GET /api/library/stream/<track_id>.

Mopidy plays uncached tracks from http://127.0.0.1:6687/api/library/stream/<id>
instead of a direct Navidrome /rest/stream.view URL. The Subsonic token+salt
auth is built here, per request, from the live config — so no reusable
credential ever lands in Mopidy's tracklist, /var/lib/boombox/last.json,
the phone remote, or the on-screen now-playing URI. It also means a
password change in Settings takes effect on the next request with no
Mopidy restart.

The body is relayed chunk-by-chunk (never buffered) and the client's
Range header is passed through, so GStreamer's seek-by-range keeps
working against the upstream.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import weakref
from typing import Any

import aiohttp
from aiohttp import web

from .downloader import LINK_DOWN_STATUSES, is_link_failure
from .subsonic import make_auth_params

log = logging.getLogger("boombox-library.stream")

# Subsonic ids are opaque strings; Navidrome's are 22-char base62 or hex
# UUIDs. Anything outside this charset (&, =, ?, /, %, whitespace…) is
# rejected before it can reach the upstream query string.
TRACK_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# Headers relayed from upstream to the client verbatim.
_RELAY_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges")
# Upstream statuses streamed through as-is (416 is relayed separately);
# anything else becomes a 502.
_RELAY_STATUSES = (200, 206)

# No total timeout: a track can legitimately stream for an hour. connect
# bounds the handshake, sock_read bounds a stalled upstream mid-stream.
UPSTREAM_TIMEOUT = aiohttp.ClientTimeout(
    total=None, connect=10, sock_connect=10, sock_read=30,
)
CHUNK_BYTES = 64 * 1024
# Subsonic errors come back as HTTP 200 + a small JSON/XML body; cap how
# much of one we read.
_ERROR_BODY_MAX = 16 * 1024

class _SessionHolder:
    """Mutable slot for the lazily-created session — the app mapping is
    frozen once the app starts, so the slot is registered in setup()."""
    session: aiohttp.ClientSession | None = None


_SESSION_KEY = web.AppKey("stream_proxy_http", _SessionHolder)
# Handler tasks of in-flight relays. A relay lives as long as Mopidy has
# the track loaded (playing *or* paused), so on shutdown they are cut
# rather than waited on — aiohttp's graceful shutdown would otherwise
# sit out its full shutdown_timeout per phase (~120 s by default, past
# systemd's 90 s stop timeout → SIGKILL on every restart).
_ACTIVE_KEY = web.AppKey("stream_proxy_active", weakref.WeakSet)


def _report_link_failure(req: web.Request) -> None:
    """The music server's link failed: tell the service (ctx.mark_offline)
    so it reports offline now instead of at its next reachability probe."""
    hook = getattr(req.app["ctx"], "mark_offline", None)
    if callable(hook):
        try:
            hook()
        except Exception:  # never turn a relay error into a 500
            log.exception("mark_offline failed")


def valid_track_id(track_id: str) -> bool:
    return bool(TRACK_ID_RE.fullmatch(track_id))


def upstream_params(
    username: str, password: str, track_id: str, max_bitrate_kbps: int = 0,
) -> dict[str, Any]:
    """Query params for /rest/stream.view. A positive max_bitrate_kbps asks
    Navidrome to transcode to mp3 at that ceiling; 0 streams the original."""
    params: dict[str, Any] = make_auth_params(username=username, password=password)
    params["id"] = track_id
    if max_bitrate_kbps > 0:
        params["maxBitRate"] = str(max_bitrate_kbps)
        params["format"] = "mp3"
    return params


def setup(app: web.Application) -> None:
    """Register the route and the cleanup hook for the lazily-created
    session. Called from api.build_app."""
    app.router.add_get("/api/library/stream/{track_id}", _stream)  # HEAD too
    app[_SESSION_KEY] = _SessionHolder()
    app[_ACTIVE_KEY] = weakref.WeakSet()
    app.on_shutdown.append(_abort_streams)
    app.on_cleanup.append(_close_session)


async def _abort_streams(app: web.Application) -> None:
    """on_shutdown: end every in-flight relay now. The player sees a
    truncated stream (restarting boombox-library interrupts a streamed
    track — Mopidy skips or stops, exactly as for a network drop)."""
    active: weakref.WeakSet[asyncio.Task[Any]] = app[_ACTIVE_KEY]
    tasks = [t for t in active if not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        log.info("shutdown: aborted %d active stream(s)", len(tasks))


async def _close_session(app: web.Application) -> None:
    session = app[_SESSION_KEY].session
    if session is not None and not session.closed:
        await session.close()


def _session_for(req: web.Request) -> aiohttp.ClientSession:
    """Prefer a service-wide session if the context exposes one (ctx.http);
    otherwise lazily create one owned by the app and closed on cleanup."""
    shared = getattr(req.app["ctx"], "http", None)
    if isinstance(shared, aiohttp.ClientSession) and not shared.closed:
        return shared
    holder = req.app[_SESSION_KEY]
    if holder.session is None or holder.session.closed:
        # auto_decompress off: we relay bytes and Content-Length verbatim.
        holder.session = aiohttp.ClientSession(auto_decompress=False)
    return holder.session


def _subsonic_error_status(body: bytes) -> tuple[int, str]:
    """Map a Subsonic error envelope to (status, short text). Code 70 is
    'data not found'; everything else (auth, server) is a bad gateway."""
    try:
        err = json.loads(body)["subsonic-response"]["error"]
        code = int(err.get("code", 0))
    except (ValueError, KeyError, TypeError, AttributeError):
        # AttributeError: a non-dict "error" (string/list) from a
        # non-Navidrome server.
        return 502, "upstream error"
    if code == 70:
        return 404, "track not found upstream"
    return 502, f"upstream error {code}"


async def _stream(req: web.Request) -> web.StreamResponse:
    ctx = req.app["ctx"]
    track_id = req.match_info["track_id"]
    if not valid_track_id(track_id):
        return web.Response(status=400, text="invalid track id")

    exists = ctx.conn.execute(
        "SELECT 1 FROM tracks WHERE id=?", (track_id,),
    ).fetchone() is not None
    if not exists:
        return web.Response(status=404, text="unknown track")

    src = ctx.cfg.source
    if not (src.url and src.username and src.password):
        return web.Response(status=503, text="library source not configured")

    max_kbps = getattr(src, "max_bitrate_kbps", 0) or 0
    try:
        max_kbps = int(max_kbps)
    except (TypeError, ValueError):
        max_kbps = 0
    params = upstream_params(src.username, src.password, track_id, max_kbps)
    url = f"{src.url.rstrip('/')}/rest/stream.view"
    headers = {"Accept-Encoding": "identity"}
    if "Range" in req.headers:
        headers["Range"] = req.headers["Range"]

    session = _session_for(req)
    # The handler runs on the connection's task (reused across keep-alive
    # requests), so register only for the relay's lifetime.
    active = req.app[_ACTIVE_KEY]
    task = asyncio.current_task()
    if task is not None:
        active.add(task)
    try:
        return await _fetch_and_relay(req, session, url, params, headers, track_id)
    finally:
        if task is not None:
            active.discard(task)


async def _fetch_and_relay(
    req: web.Request, session: aiohttp.ClientSession, url: str,
    params: dict[str, Any], headers: dict[str, str], track_id: str,
) -> web.StreamResponse:
    try:
        async with session.get(url, params=params, headers=headers,
                               timeout=UPSTREAM_TIMEOUT) as up:
            return await _relay(req, up, track_id)
    except asyncio.TimeoutError:
        # Only reachable before headers were sent — _relay swallows
        # mid-body failures itself.
        log.warning("stream %s: upstream timeout", track_id)
        _report_link_failure(req)
        return web.Response(status=504, text="upstream timeout")
    except aiohttp.ClientError as e:
        # Never log e itself: ClientResponseError's str() carries the
        # full URL, token and salt included.
        log.warning("stream %s: upstream unreachable (%s)", track_id, type(e).__name__)
        if is_link_failure(e):
            _report_link_failure(req)
        return web.Response(status=502, text="upstream unreachable")

async def _relay(
    req: web.Request, up: aiohttp.ClientResponse, track_id: str,
) -> web.StreamResponse:
    ctype = up.headers.get("Content-Type", "")
    if up.status == 200 and ctype.split(";")[0].strip() in (
        "application/json", "text/xml", "application/xml",
    ):
        body = await up.content.read(_ERROR_BODY_MAX)
        status, text = _subsonic_error_status(body)
        log.info("stream %s: upstream subsonic error -> %d", track_id, status)
        return web.Response(status=status, text=text)
    if up.status == 404:
        return web.Response(status=404, text="track not found upstream")
    if up.status == 416:
        # Range past EOF (e.g. a resume offset on a re-encoded file). No
        # body; relay Content-Range so the player learns the real size.
        cr = up.headers.get("Content-Range")
        return web.Response(status=416, headers={"Content-Range": cr} if cr else None)
    if up.status not in _RELAY_STATUSES:
        log.info("stream %s: upstream http %d", track_id, up.status)
        if up.status in LINK_DOWN_STATUSES:   # the tunnel / CDN, not Navidrome
            _report_link_failure(req)
        return web.Response(status=502, text=f"upstream http {up.status}")

    resp = web.StreamResponse(status=up.status)
    for h in _RELAY_HEADERS:
        if h in up.headers:
            resp.headers[h] = up.headers[h]
    await resp.prepare(req)
    if req.method == "HEAD":
        return resp

    try:
        async for chunk in up.content.iter_chunked(CHUNK_BYTES):
            await resp.write(chunk)
        await resp.write_eof()
    except ConnectionResetError:
        # The player hung up (seek, skip, Mopidy's scanner reading just
        # the tags). Normal; leaving the `async with` releases upstream.
        log.debug("stream %s: client disconnected", track_id)
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        # Headers are already out — all we can do is cut the body short
        # so the player sees a truncated stream rather than a hang.
        log.warning("stream %s: upstream failed mid-body (%s)", track_id, type(e).__name__)
        if is_link_failure(e):
            _report_link_failure(req)
        if req.transport is not None:
            req.transport.close()
    return resp
