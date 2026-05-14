"""Library + playlist + queue surface for boombox-remote.

Thin server-side wrappers over Mopidy JSON-RPC so the PWA talks only to
/api/remote/* with one bearer token and never reaches Mopidy directly.
The Mopidy client is injected (clients.MopidyRpc) so it is trivially
mockable in tests.
"""
from __future__ import annotations

import logging

from aiohttp import web

log = logging.getLogger("boombox-remote")


def _track_summary(t: dict) -> dict:
    """Flatten a Mopidy track into the shape the PWA renders."""
    return {
        "uri": t.get("uri"),
        "title": t.get("name"),
        "artist": ", ".join(a.get("name", "") for a in t.get("artists") or [])
                  or None,
        "album": (t.get("album") or {}).get("name"),
        "duration_s": (t.get("length") or 0) // 1000,
    }


def _make_handlers(mopidy):
    async def search(request: web.Request) -> web.Response:
        q = (request.query.get("q") or "").strip()
        if not q:
            return web.json_response({"ok": False, "error": "missing_q"},
                                     status=400)
        res = await mopidy.call("core.library.search",
                                {"query": {"any": [q]}})
        results = res.get("result") or []
        tracks = [_track_summary(t) for group in results
                  for t in (group.get("tracks") or [])][:80]
        return web.json_response({"ok": True, "tracks": tracks})

    async def list_playlists(request: web.Request) -> web.Response:
        res = await mopidy.call("core.playlists.as_list")
        refs = res.get("result") or []
        return web.json_response({
            "ok": True,
            "playlists": [{"name": r.get("name"), "uri": r.get("uri")}
                          for r in refs],
        })

    async def create_playlist(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        name = (body or {}).get("name") if isinstance(body, dict) else None
        uris = (body or {}).get("uris") if isinstance(body, dict) else None
        if not name or not isinstance(uris, list) or not uris:
            return web.json_response(
                {"ok": False, "error": "name_and_uris_required"}, status=400)
        created = (await mopidy.call(
            "core.playlists.create",
            {"name": name, "uri_scheme": "m3u"})).get("result")
        if not created:
            return web.json_response({"ok": False, "error": "create_failed"},
                                     status=502)
        created["tracks"] = [{"uri": u} for u in uris]
        saved = (await mopidy.call(
            "core.playlists.save", {"playlist": created})).get("result")
        if not saved:
            return web.json_response({"ok": False, "error": "save_failed"},
                                     status=502)
        # best-effort cache refresh; save already succeeded
        await mopidy.call("core.playlists.refresh", {"uri_scheme": "m3u"})
        return web.json_response({"ok": True, "uri": saved.get("uri"),
                                  "name": saved.get("name")})

    async def playlist_items(request: web.Request) -> web.Response:
        # {uri} matches a single path segment — fine for m3u:/spotify:
        # colon-delimited URIs; the client URL-encodes the value.
        uri = request.match_info["uri"]
        res = await mopidy.call("core.playlists.get_items", {"uri": uri})
        items = res.get("result") or []
        return web.json_response({
            "ok": True,
            "uris": [it.get("uri") for it in items if it.get("uri")],
        })

    async def queue(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        uris = (body or {}).get("uris") if isinstance(body, dict) else None
        if not isinstance(uris, list) or not uris:
            return web.json_response({"ok": False, "error": "uris_required"},
                                     status=400)
        play = bool((body or {}).get("play", True))
        await mopidy.call("core.tracklist.clear")
        await mopidy.call("core.tracklist.add", {"uris": uris})
        if play:
            await mopidy.call("core.playback.play")
        return web.json_response({"ok": True})

    return search, list_playlists, create_playlist, playlist_items, queue


def add_routes(app: web.Application, mopidy) -> None:
    """Register library/playlist/queue routes. `mopidy` is a
    clients.MopidyRpc (or any object with an async .call(method, params))."""
    search, list_pls, create_pl, pl_items, queue = _make_handlers(mopidy)
    app.router.add_get("/api/remote/library/search", search)
    app.router.add_get("/api/remote/playlists", list_pls)
    app.router.add_post("/api/remote/playlists", create_pl)
    app.router.add_get("/api/remote/playlists/{uri}/items", pl_items)
    app.router.add_post("/api/remote/queue", queue)
