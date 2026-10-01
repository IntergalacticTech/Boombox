"""HTTP surface for boombox-library (mounted at :6687, proxied via nginx
under /api/library/).

The app needs a Context object supplied by the service entry point.
Context exposes the DB connection, config, cache drive state, and a few
async hooks (test_source, trigger_sync, is_online) so the API doesn't
hard-depend on the runtime wiring (keeps tests fast).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from aiohttp import web

from . import __version__, stream_proxy
from . import keep as keep_mod
from .art import fetch_art
from .catalog import prune_deferred_status, request_forced_prune
from .config import LibraryConfig
from .models import PinKind, PinSource
from .pins import pin as _pin_fn
from .pins import unpin as _unpin_fn
from .resolver import PlaybackResolution, cached_local_paths, resolve_playback
from .snapshots import compute_etag, snapshot_path
from .subsonic import make_auth_params

log = logging.getLogger("boombox-library.api")


class Context(Protocol):
    conn: sqlite3.Connection
    cfg: LibraryConfig
    # Phase 2 additions for /health, /cache/adopt, /cache/streamed, /cache/clear, /cache/candidates
    last_sync_ts: float
    syncing: bool
    # Album-art proxy/disk cache (Phase 3). Tests supply a tmp_path; the
    # service entry point sets it to /opt/boombox/state/art-cache.
    art_cache_dir: Path
    # Precomputed browse-response JSON snapshots. The service writes them
    # after every sync; the API serves them with ETag in lieu of querying
    # SQLite on every browse.
    snapshot_dir: Path

    # True while reachability is unknown (before the first probe answers):
    # callers treat unknown as online. reachability_known says which it is.
    async def is_online(self) -> bool: ...
    def reachability_known(self) -> bool: ...
    async def trigger_sync(self) -> None: ...
    def cache_drive_state(self): ...
    def save_config(self, cfg: LibraryConfig) -> None: ...
    async def test_source(self, url: str, username: str, password: str) -> tuple[bool, str]: ...
    async def adopt_cache(self, mount_path: str) -> None: ...
    def enqueue_streamed_download(self, track_id: str) -> None: ...
    async def clear_streamed_cache(self) -> int: ...
    def cache_candidates(self) -> list[dict]: ...
    # The live DownloadQueue (keep / storage routes), None without storage or source.
    def download_queue(self) -> keep_mod.QueueLike | None: ...


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
    app.router.add_post("/api/library/sync/prune", _sync_prune)
    app.router.add_get("/api/library/track/{track_id}/playback", _resolver)
    app.router.add_post("/api/library/resolve", _resolve_batch)
    app.router.add_get("/api/library/artist/{artist_id}", _artist_detail)
    app.router.add_get("/api/library/album/{album_id}", _album_detail)
    app.router.add_get("/api/library/playlist/{playlist_id}", _playlist_detail)
    app.router.add_get("/api/library/cache/stats", _cache_stats)
    app.router.add_post("/api/library/cache/adopt", _cache_adopt)
    app.router.add_post("/api/library/cache/streamed", _cache_streamed)
    app.router.add_post("/api/library/cache/clear", _cache_clear)
    app.router.add_get("/api/library/cache/candidates", _cache_candidates)
    app.router.add_get("/api/library/art/{art_id}", _art)
    app.router.add_post("/api/library/keep", _keep_post)
    app.router.add_delete("/api/library/keep", _keep_delete)
    app.router.add_get("/api/library/offline", _offline)
    app.router.add_get("/api/library/storage", _storage)
    app.router.add_post("/api/library/storage/remove", _storage_remove)
    app.router.add_post("/api/library/storage/retry", _storage_retry)
    stream_proxy.setup(app)  # GET/HEAD /api/library/stream/{track_id}
    return app


async def _health(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    drive = ctx.cache_drive_state()
    return web.json_response({
        "service_version": __version__,
        # Boolean-compatible: true until the first probe answers (unknown
        # counts as online for RFID and the apps); reachability_known
        # tells the two apart.
        "navidrome_reachable": await ctx.is_online(),
        "reachability_known": ctx.reachability_known(),
        "cache_present": bool(drive and drive.present) if drive else False,
        "cache_mount": str(drive.mount_path) if drive and drive.mount_path else None,
        "internal_storage": bool(drive and getattr(drive, "internal", False)),
        "last_sync_ts": ctx.last_sync_ts,
        "syncing": ctx.syncing,
        # A large album removal the prune guard is holding off, or null.
        "prune_deferred": prune_deferred_status(ctx.conn),
    })


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) lowercased with default ports filled, or None."""
    try:
        u = urlsplit(url.strip())
        port = u.port
    except ValueError:
        return None
    scheme = u.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not u.hostname:
        return None
    return scheme, u.hostname.lower(), port or _DEFAULT_PORTS[scheme]


def _same_origin(a: str, b: str) -> bool:
    oa = _origin(a)
    return oa is not None and oa == _origin(b)


def _password_or_stored(ctx: Context, url: str, password: str | None) -> str:
    """Blank = keep the stored password, but only for the stored server's
    origin: the Accounts page never receives the stored password, so an
    unchanged field arrives empty. A different server must never receive
    the stored credential, so it gets the blank as-is and fails normally."""
    if password:
        return password
    if _same_origin(url, ctx.cfg.source.url):
        return ctx.cfg.source.password
    return ""


async def _source_get(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    s = ctx.cfg.source
    return web.json_response({"url": s.url, "username": s.username})


async def _source_put(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    # replace(), not a fresh SourceConfig: fields the form doesn't send
    # (max_bitrate_kbps, set by hand in library.yml) must survive a save.
    new_source = replace(
        ctx.cfg.source,
        url=body.get("url", ""),
        username=body.get("username", ""),
        password=_password_or_stored(ctx, body.get("url", ""), body.get("password")),
    )
    ok, msg = await ctx.test_source(new_source.url, new_source.username, new_source.password)
    if not ok:
        # Defense in depth: never echo the submitted password back, even
        # if upstream test_source leaked it into its error message.
        safe_msg = msg.replace(new_source.password, "***") if new_source.password else msg
        return web.json_response({"ok": False, "error": safe_msg}, status=400)
    # save_config writes mopidy.conf and RESTARTS Mopidy — seconds of
    # blocking subprocess work that must not stall the event loop (it froze
    # every in-flight request, including the setup wizard's, past their
    # client timeouts).
    try:
        await asyncio.to_thread(ctx.save_config,
                                replace(ctx.cfg, source=new_source))
    except Exception as e:  # noqa: BLE001 — always answer JSON, never a bare 500
        log.exception("source save failed")
        return web.json_response(
            {"ok": False, "error": f"save failed: {type(e).__name__}: {e}"},
            status=500)
    await ctx.trigger_sync()
    return web.json_response({"ok": True})


async def _source_test(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    body = await req.json()
    ok, msg = await ctx.test_source(
        body.get("url", ""), body.get("username", ""),
        _password_or_stored(ctx, body.get("url", ""), body.get("password")),
    )
    return web.json_response({"ok": ok, "error": msg if not ok else ""})


_BROWSE_QUERIES = {
    "artists": "SELECT id, name, album_count, art_id FROM artists ORDER BY sort_name",
    "albums": "SELECT id, name, artist_id, year, art_id FROM albums ORDER BY sort_name",
    "playlists": "SELECT id, name, song_count FROM playlists ORDER BY name",
}


async def _browse(req: web.Request) -> web.Response:
    """Serve the precomputed JSON snapshot when present, fall back to a
    live SQLite query otherwise.

    The snapshot is rewritten by ServiceContext._sync_once after every
    successful sync; on first boot (no sync yet) we still answer correctly
    via the SQL fallback, but the response is materialised on every call.
    """
    ctx: Context = req.app["ctx"]
    t = req.query.get("type", "artists")
    sql = _BROWSE_QUERIES.get(t)
    if not sql:
        return web.json_response({"error": f"unknown type {t}"}, status=400)

    snap = snapshot_path(ctx.snapshot_dir, t)
    if snap.exists():
        etag = compute_etag(snap)
        if req.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        body = snap.read_bytes()
        return web.Response(
            body=body,
            content_type="application/json",
            headers={
                "ETag": etag,
                # Browser revalidates on every navigation but the ETag
                # match returns a 304 with no body, so the round-trip is
                # cheap and the user always sees fresh post-sync data.
                "Cache-Control": "no-cache",
            },
        )

    rows = list(ctx.conn.execute(sql))
    return web.json_response({"items": [dict(r) for r in rows]})


def _fts_prefix_query(q: str) -> str | None:
    """Turn free text into a safe FTS5 prefix query over title/body.

    Each whitespace token becomes a double-quoted string (embedded quotes
    doubled, so FTS5 operators/punctuation in it are just text) with a
    trailing * — "beat" matches "Beat It" while typing. Tokens are ANDed.
    The {title body} filter keeps the indexed content_type column
    ('track', 'album', ...) from matching every row of that kind. Tokens
    with no letters/digits tokenize to nothing and are dropped; None
    means nothing searchable is left.
    """
    terms = [
        '"' + tok.replace('"', '""') + '"*'
        for tok in q.split()
        if any(ch.isalnum() for ch in tok)
    ]
    if not terms:
        return None
    return "{title body}: (" + " ".join(terms) + ")"


async def _search(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    match = _fts_prefix_query(req.query.get("q", ""))
    if match is None:
        return web.json_response({"results": []})
    try:
        rows = list(ctx.conn.execute(
            "SELECT content_type, id, title FROM search_index "
            "WHERE search_index MATCH ? ORDER BY rank LIMIT 200",
            (match,),
        ))
    except sqlite3.OperationalError:
        # Defensive: the quoting above should make every query valid, but
        # a malformed MATCH must never surface as a 500 while typing.
        log.warning("search query rejected by FTS5: %r", match)
        rows = []
    return web.json_response(
        {"results": keep_mod.offline_flags(ctx.conn, [dict(r) for r in rows])})


async def _pin(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    if (refused := _not_json(req)) is not None:
        return refused
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


async def _existing_cache_files(ctx: Context, track_ids: list[str]) -> frozenset[str]:
    """Stat the candidate cache files off the event loop. The loop also
    feeds every live stream relay (stream_proxy), so a slow/wedged cache
    mount must not stall it for a whole batch of stat() calls."""
    paths = cached_local_paths(ctx.conn, track_ids)
    if not paths:
        return frozenset()
    return await asyncio.to_thread(
        lambda: frozenset(p for p in paths if os.path.exists(p)))


def _resolve_one(
    ctx: Context, track_id: str, online: bool, existing: frozenset[str],
) -> PlaybackResolution:
    src = ctx.cfg.source
    return resolve_playback(
        ctx.conn, track_id, online,
        source_url=src.url, source_username=src.username, source_password=src.password,
        file_exists=existing.__contains__,
    )


async def _sync_prune(req: web.Request) -> web.Response:
    """Override the prune guard once: the next complete sync reaps every
    album Navidrome no longer lists, however many. Starts that sync."""
    ctx: Context = req.app["ctx"]
    request_forced_prune(ctx.conn)
    await ctx.trigger_sync()
    return web.json_response({"ok": True})


async def _resolver(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    track_id = req.match_info["track_id"]
    existing = await _existing_cache_files(ctx, [track_id])
    r = _resolve_one(ctx, track_id, await ctx.is_online(), existing)
    return web.json_response({
        "source": r.source.value,
        "uri": r.uri,
        "cache_status": r.cache_status,
    })


RESOLVE_BATCH_MAX = 1000


async def _resolve_batch(req: web.Request) -> web.Response:
    """POST {"ids": [...]} → {"items": [{id, source, uri, cache_status}]}
    in request order. One reachability check for the whole batch, so
    queueing an album is one round-trip instead of one per track."""
    ctx: Context = req.app["ctx"]
    try:
        body = await req.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    ids = body.get("ids") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return web.json_response({"error": "ids must be a list of strings"}, status=400)
    if len(ids) > RESOLVE_BATCH_MAX:
        return web.json_response(
            {"error": f"too many ids (max {RESOLVE_BATCH_MAX})"}, status=400)
    online = await ctx.is_online()
    existing = await _existing_cache_files(ctx, ids)
    items = []
    for tid in ids:
        r = _resolve_one(ctx, tid, online, existing)
        items.append({
            "id": tid,
            "source": r.source.value,
            "uri": r.uri,
            "cache_status": r.cache_status,
        })
    return web.json_response({"items": items})


# ----- detail endpoints (touch UI drill-down) -----
#
# Tracks have no artist column of their own; a track's artist is its
# album's artist (compilations therefore show the album artist). If a
# later schema adds tracks.artist, it wins when non-empty.

def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _track_columns(conn: sqlite3.Connection) -> str:
    """SELECT list for the shared track shape; expects aliases t (tracks),
    ar (album artist) and cs (cache_state)."""
    artist = ("COALESCE(NULLIF(t.artist, ''), ar.name)"
              if _has_column(conn, "tracks", "artist") else "ar.name")
    return (
        f"t.id, t.title, {artist} AS artist, t.album_id, "
        "t.disc_no AS disc, t.track_no AS track, t.duration_s AS duration, "
        "COALESCE(cs.status, 'absent') AS cache_status"
    )


_TRACK_JOINS = (
    "JOIN albums al ON al.id = t.album_id "
    "LEFT JOIN artists ar ON ar.id = al.artist_id "
    "LEFT JOIN cache_state cs ON cs.track_id = t.id "
)


def _not_found(what: str) -> web.Response:
    return web.json_response({"error": f"{what} not found"}, status=404)


def _with_offline(rows) -> list[dict]:
    """Track rows + "offline": the file is on the boombox."""
    out = [dict(t) for t in rows]
    for t in out:
        t["offline"] = t.get("cache_status") == "present"
    return out


async def _artist_detail(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    artist_id = req.match_info["artist_id"]
    row = ctx.conn.execute(
        "SELECT id, name, art_id FROM artists WHERE id=?", (artist_id,),
    ).fetchone()
    if row is None:
        return _not_found("artist")
    # Year ascending with undated albums last, then by sort name.
    albums = ctx.conn.execute(
        "SELECT id, name, year, art_id, song_count AS track_count FROM albums "
        "WHERE artist_id=? ORDER BY year IS NULL, year, sort_name",
        (artist_id,),
    )
    album_rows = [dict(a) for a in albums]
    flags = keep_mod.offline_flags(
        ctx.conn, [{"content_type": "album", "id": a["id"]} for a in album_rows])
    for a, f in zip(album_rows, flags):
        a["offline"] = f["offline"]
    return web.json_response({
        "artist": dict(row),
        "albums": album_rows,
        "keep": keep_mod.keep_state(ctx.conn, PinKind.ARTIST, artist_id),
    })


async def _album_detail(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    album_id = req.match_info["album_id"]
    row = ctx.conn.execute(
        "SELECT al.id, al.name, ar.name AS artist, al.artist_id, al.year, al.art_id "
        "FROM albums al LEFT JOIN artists ar ON ar.id = al.artist_id "
        "WHERE al.id=?", (album_id,),
    ).fetchone()
    if row is None:
        return _not_found("album")
    tracks = ctx.conn.execute(
        f"SELECT {_track_columns(ctx.conn)} FROM tracks t {_TRACK_JOINS}"
        "WHERE t.album_id=? ORDER BY t.disc_no, t.track_no, t.title",
        (album_id,),
    )
    track_rows = _with_offline(tracks)
    return web.json_response({
        "album": dict(row),
        "tracks": track_rows,
        "keep": keep_mod.keep_state(ctx.conn, PinKind.ALBUM, album_id),
    })


async def _playlist_detail(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    playlist_id = req.match_info["playlist_id"]
    row = ctx.conn.execute(
        "SELECT id, name FROM playlists WHERE id=?", (playlist_id,),
    ).fetchone()
    if row is None:
        return _not_found("playlist")
    # Entries pointing at tracks the catalog doesn't know (not yet synced,
    # or deleted upstream) are dropped — there's nothing to show or play.
    tracks = ctx.conn.execute(
        f"SELECT {_track_columns(ctx.conn)} FROM playlist_tracks pt "
        f"JOIN tracks t ON t.id = pt.track_id {_TRACK_JOINS}"
        "WHERE pt.playlist_id=? ORDER BY pt.position",
        (playlist_id,),
    )
    track_rows = _with_offline(tracks)
    return web.json_response({
        "playlist": dict(row),
        "tracks": track_rows,
        "keep": keep_mod.keep_state(ctx.conn, PinKind.PLAYLIST, playlist_id),
    })


def _bad(error: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": error}, status=status)


def _not_json(req: web.Request) -> web.Response | None:
    """415 unless the request says Content-Type: application/json. The
    mutating routes are reachable with only the web password (LAN) or no
    credential (kiosk loopback); requiring JSON makes a cross-site "simple"
    POST (text/plain, form) fail instead of running — browsers preflight a
    JSON one."""
    if req.content_type != "application/json":
        return _bad("expected application/json", 415)
    return None


async def _keep_target(req: web.Request) -> tuple[PinKind, str] | web.Response:
    """(kind, id) from a {kind, id} JSON body, or the 400 to answer."""
    try:
        body = await req.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _bad("expected a JSON object")
    try:
        kind = PinKind(body.get("kind"))
    except ValueError:
        return _bad("kind must be album, artist or playlist")
    if kind not in keep_mod.KEEP_KINDS:
        return _bad("kind must be album, artist or playlist")
    target_id = body.get("id")
    if not isinstance(target_id, str) or not target_id:
        return _bad("missing id")
    return kind, target_id


async def _keep_post(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    if (refused := _not_json(req)) is not None:
        return refused
    t = await _keep_target(req)
    if isinstance(t, web.Response):
        return t
    kind, target_id = t
    if not keep_mod.target_exists(ctx.conn, kind, target_id):
        return _bad(f"{kind.value} not found", 404)
    return web.json_response(keep_mod.keep(ctx.conn, ctx.download_queue(), kind, target_id))


async def _keep_delete(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    if (refused := _not_json(req)) is not None:
        return refused
    t = await _keep_target(req)
    if isinstance(t, web.Response):
        return t
    kind, target_id = t
    return web.json_response(keep_mod.unkeep(
        ctx.conn, ctx.download_queue(), kind, target_id,
        starred_auto_pin=ctx.cfg.sync.starred_auto_pin))


async def _offline(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(keep_mod.offline_ids(ctx.conn))


async def _storage(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response(keep_mod.storage_overview(
        ctx.conn, ctx.cache_drive_state(), ctx.cfg.cache.reserve_bytes, ctx.download_queue()))


async def _storage_remove(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    if (refused := _not_json(req)) is not None:
        return refused
    try:
        body = await req.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("kind") == "starred_tracks":
        return _bad(keep_mod.STARRED_ONLY, 409)
    t = await _keep_target(req)
    if isinstance(t, web.Response):
        return t
    kind, target_id = t
    drive = ctx.cache_drive_state()
    root = drive.mount_path if drive is not None and drive.present else None
    status, out = keep_mod.remove_kept(
        ctx.conn, ctx.download_queue(), kind, target_id,
        starred_auto_pin=ctx.cfg.sync.starred_auto_pin, cache_root=root)
    return web.json_response(out, status=status)


async def _storage_retry(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    if (refused := _not_json(req)) is not None:
        return refused
    queue = ctx.download_queue()
    if queue is None:
        return _bad("downloads aren't running — no music storage or no music server set up", 409)
    return web.json_response({"ok": True, "retried": keep_mod.retry_failed(ctx.conn, queue)})


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
    if (refused := _not_json(req)) is not None:
        return refused
    cleared = await ctx.clear_streamed_cache()
    return web.json_response({"ok": True, "cleared": cleared})


async def _cache_candidates(req: web.Request) -> web.Response:
    ctx: Context = req.app["ctx"]
    return web.json_response({"candidates": ctx.cache_candidates()})


async def _art(req: web.Request) -> web.Response:
    """Proxy + on-disk cache for Navidrome cover-art.

    Path: /api/library/art/<art_id> with optional ?size=N to request a
    thumbnail size. Once an (art_id, size) is on disk we never re-fetch —
    Subsonic art_ids are content-stable, so `immutable` Cache-Control is
    safe and lets the browser cache forever.

    404 when there's no source URL configured, when Navidrome doesn't
    have art for that id, AND the disk cache has no copy — the UI falls
    back to its colour-hash gradient.
    """
    ctx: Context = req.app["ctx"]
    art_id = req.match_info["art_id"]
    size_param = req.query.get("size")
    size: int | None = None
    if size_param and size_param.isdigit():
        size = int(size_param)

    src = ctx.cfg.source
    auth = make_auth_params(src.username, src.password) if src.username else {}
    result = await fetch_art(
        base_url=src.url,
        auth_params=auth,
        art_id=art_id,
        cache_dir=ctx.art_cache_dir,
        size=size,
    )
    if result is None:
        return web.Response(status=404, text="art unavailable")
    data, ctype = result
    etag_parts = [art_id]
    if size:
        etag_parts.append(str(size))
    etag = '"' + "-".join(etag_parts) + '"'
    if req.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})
    return web.Response(
        body=data,
        content_type=ctype,
        headers={
            # Subsonic art_ids change when the underlying art changes,
            # so we can mark these immutable and let the browser keep
            # them forever.
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": etag,
        },
    )
