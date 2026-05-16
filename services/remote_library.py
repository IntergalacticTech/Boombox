"""Library + playlist + queue surface for boombox-remote.

Thin server-side wrappers over Mopidy JSON-RPC so the PWA talks only to
/api/remote/* with one bearer token and never reaches Mopidy directly.
The Mopidy client is injected (clients.MopidyRpc) so it is trivially
mockable in tests.
"""
from __future__ import annotations

import asyncio
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
    # Mopidy field aliases. "track" is the user-facing label but Mopidy
    # wants "track_name"; we accept either for forgiveness.
    _SEARCH_FIELDS = {
        "any":   "any",
        "artist": "artist",
        "album":  "album",
        "track":  "track_name",
        "track_name": "track_name",
    }

    async def search(request: web.Request) -> web.Response:
        q = (request.query.get("q") or "").strip()
        if not q:
            return web.json_response({"ok": False, "error": "missing_q"},
                                     status=400)
        raw_field = (request.query.get("field") or "any").strip().lower()
        field = _SEARCH_FIELDS.get(raw_field)
        if field is None:
            return web.json_response({"ok": False, "error": "bad_field"},
                                     status=400)
        res = await mopidy.call("core.library.search",
                                {"query": {field: [q]}})
        results = res.get("result") or []
        tracks = [_track_summary(t) for group in results
                  for t in (group.get("tracks") or [])][:80]
        return web.json_response({"ok": True, "tracks": tracks})

    async def browse(request: web.Request) -> web.Response:
        """List children of a Mopidy library URI. Empty/missing uri lists
        the root (the backends, e.g. local: and m3u:). Each ref is the
        Mopidy shape: {uri, name, type} where type is one of directory,
        album, artist, track, playlist."""
        uri = request.query.get("uri") or None
        res = await mopidy.call("core.library.browse", {"uri": uri})
        refs = res.get("result") or []
        return web.json_response({"ok": True, "refs": refs})

    async def lookup(request: web.Request) -> web.Response:
        """Resolve a non-track URI (album, artist, directory) into a flat
        list of tracks. Mopidy's core.library.lookup returns one track for
        track URIs, the album's tracks for album URIs, and the artist's
        full discography for artist URIs — exactly what the PWA needs to
        queue a "Play this album" button."""
        uri = (request.query.get("uri") or "").strip()
        if not uri:
            return web.json_response({"ok": False, "error": "missing_uri"},
                                     status=400)
        res = await mopidy.call("core.library.lookup", {"uris": [uri]})
        by_uri = res.get("result") or {}
        tracks: list[dict] = []
        for ts in by_uri.values():
            for t in ts or []:
                tracks.append(_track_summary(t))
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
        # Resolve to track summaries so the playlist detail view can render
        # title/artist/album without a second round-trip.
        uris = [it.get("uri") for it in items if it.get("uri")]
        if not uris:
            return web.json_response({"ok": True, "uris": [], "tracks": []})
        lookups = await mopidy.call("core.library.lookup", {"uris": uris})
        by_uri = lookups.get("result") or {}
        tracks: list[dict] = []
        for u in uris:
            ts = by_uri.get(u) or []
            if ts:
                tracks.append(_track_summary(ts[0]))
            else:
                # Mopidy doesn't always resolve URIs (e.g. a stale m3u
                # entry whose file went missing). Surface a stub so the
                # row still renders and the user can remove it.
                tracks.append({"uri": u, "title": None, "artist": None,
                               "album": None, "duration_s": 0})
        return web.json_response({
            "ok": True, "uris": uris, "tracks": tracks,
        })

    async def playlist_append(request: web.Request) -> web.Response:
        """Append URIs to an existing playlist. Mopidy doesn't expose an
        atomic append — we lookup, splice, and save. Lossy under concurrent
        edits from another client, but that's a rare two-remote race."""
        target = request.match_info["uri"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        new_uris = (body or {}).get("uris") if isinstance(body, dict) else None
        if not isinstance(new_uris, list) or not new_uris:
            return web.json_response({"ok": False, "error": "uris_required"},
                                     status=400)
        looked = await mopidy.call("core.playlists.lookup", {"uri": target})
        playlist = looked.get("result")
        if not playlist:
            return web.json_response({"ok": False, "error": "not_found"},
                                     status=404)
        existing = playlist.get("tracks") or []
        playlist["tracks"] = existing + [{"uri": u} for u in new_uris]
        saved = (await mopidy.call(
            "core.playlists.save", {"playlist": playlist})).get("result")
        if not saved:
            return web.json_response({"ok": False, "error": "save_failed"},
                                     status=502)
        return web.json_response({"ok": True, "added": len(new_uris)})

    async def playlist_delete(request: web.Request) -> web.Response:
        """Delete a playlist by URI. Mopidy's delete returns True if a
        backend owned the playlist and removed it; we surface that as
        ok/error."""
        target = request.match_info["uri"]
        res = await mopidy.call("core.playlists.delete", {"uri": target})
        ok = bool(res.get("result"))
        if not ok:
            return web.json_response({"ok": False, "error": "delete_failed"},
                                     status=502)
        return web.json_response({"ok": True})

    async def playlist_rename(request: web.Request) -> web.Response:
        """Rename a playlist. Mopidy's playlist URI for m3u is path-derived,
        so a "rename" is really save-as-new + delete-old. We try the
        cleaner path first: save the same playlist with a new name (some
        backends update in place). If that yields a fresh URI, the old
        one is removed to keep the list clean."""
        target = request.match_info["uri"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        new_name = (body or {}).get("name") if isinstance(body, dict) else None
        if not isinstance(new_name, str) or not new_name.strip():
            return web.json_response({"ok": False, "error": "name_required"},
                                     status=400)
        new_name = new_name.strip()

        looked = await mopidy.call("core.playlists.lookup", {"uri": target})
        playlist = looked.get("result")
        if not playlist:
            return web.json_response({"ok": False, "error": "not_found"},
                                     status=404)
        old_uri = playlist.get("uri")
        tracks = playlist.get("tracks") or []

        # Saving with the new name + the same URI may either rename in
        # place (older Mopidy) or coin a new URI (m3u backend, where the
        # filename derives from the name). Either way we end up with a
        # playlist of the new name. Use create + save to be backend-safe.
        created = (await mopidy.call(
            "core.playlists.create",
            {"name": new_name, "uri_scheme": "m3u"})).get("result")
        if not created:
            return web.json_response({"ok": False, "error": "create_failed"},
                                     status=502)
        created["tracks"] = tracks
        saved = (await mopidy.call(
            "core.playlists.save", {"playlist": created})).get("result")
        if not saved:
            return web.json_response({"ok": False, "error": "save_failed"},
                                     status=502)
        new_uri = saved.get("uri")
        if new_uri and new_uri != old_uri:
            # best-effort cleanup of the old shell — ignore failures so a
            # half-success still leaves the user with the renamed copy
            try:
                await mopidy.call("core.playlists.delete", {"uri": old_uri})
            except Exception:
                pass
        await mopidy.call("core.playlists.refresh", {"uri_scheme": "m3u"})
        return web.json_response({"ok": True, "uri": new_uri,
                                  "name": saved.get("name")})

    async def playlist_remove_item(request: web.Request) -> web.Response:
        """Remove a single track URI from a playlist. Same lookup-splice-save
        pattern as append. Removes ALL occurrences of the URI."""
        target = request.match_info["uri"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        drop_uri = (body or {}).get("uri") if isinstance(body, dict) else None
        if not isinstance(drop_uri, str) or not drop_uri:
            return web.json_response({"ok": False, "error": "uri_required"},
                                     status=400)
        looked = await mopidy.call("core.playlists.lookup", {"uri": target})
        playlist = looked.get("result")
        if not playlist:
            return web.json_response({"ok": False, "error": "not_found"},
                                     status=404)
        existing = playlist.get("tracks") or []
        playlist["tracks"] = [t for t in existing if t.get("uri") != drop_uri]
        saved = (await mopidy.call(
            "core.playlists.save", {"playlist": playlist})).get("result")
        if not saved:
            return web.json_response({"ok": False, "error": "save_failed"},
                                     status=502)
        return web.json_response(
            {"ok": True, "removed": len(existing) - len(playlist["tracks"])})

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

    async def queue_list(_request: web.Request) -> web.Response:
        """Current tracklist with stable tlid handles + currently-playing
        index. Frontend renders this as "Up next" inline on Now Playing.
        tlid is Mopidy's per-tracklist identity — survives reorders, dies
        on tracklist.clear; we use it for jump / remove instead of array
        indices which shift under us. `index` is also surfaced so the
        UI can render position-aware controls (reorder up/down) without
        a separate ordinal-lookup round-trip."""
        items, idx = await asyncio.gather(
            mopidy.call("core.tracklist.get_tl_tracks"),
            mopidy.call("core.tracklist.index"),
        )
        rows = items.get("result") or []
        playing_index = idx.get("result")
        out = []
        for i, it in enumerate(rows):
            t = it.get("track") or {}
            summary = _track_summary(t)
            summary["tlid"] = it.get("tlid")
            summary["index"] = i
            summary["playing"] = (i == playing_index)
            out.append(summary)
        return web.json_response({"ok": True, "tracks": out})

    async def queue_move(request: web.Request) -> web.Response:
        """Move a single tracklist entry. Body: {tlid, to_position}.
        Mopidy's core.tracklist.move operates on a slice [start, end)
        and shifts it to to_position. We resolve tlid → current index
        server-side so the client doesn't race with another remote's
        reorder. `to_position` is clamped to the valid range."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        tlid = (body or {}).get("tlid") if isinstance(body, dict) else None
        to_pos = (body or {}).get("to_position") \
            if isinstance(body, dict) else None
        if not isinstance(tlid, int) or not isinstance(to_pos, int):
            return web.json_response({"ok": False, "error": "bad_args"},
                                     status=400)
        items = (await mopidy.call(
            "core.tracklist.get_tl_tracks")).get("result") or []
        cur_idx = next((i for i, it in enumerate(items)
                         if it.get("tlid") == tlid), None)
        if cur_idx is None:
            return web.json_response({"ok": False, "error": "tlid_not_found"},
                                     status=404)
        # Clamp to_position; Mopidy is strict about end > length.
        n = len(items)
        target = max(0, min(n - 1, to_pos))
        if target == cur_idx:
            return web.json_response({"ok": True, "noop": True})
        await mopidy.call("core.tracklist.move",
                          {"start": cur_idx, "end": cur_idx + 1,
                           "to_position": target})
        return web.json_response({"ok": True,
                                   "from": cur_idx, "to": target})

    async def queue_jump(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        tlid = (body or {}).get("tlid") if isinstance(body, dict) else None
        if not isinstance(tlid, int):
            return web.json_response({"ok": False, "error": "tlid_required"},
                                     status=400)
        await mopidy.call("core.playback.play", {"tlid": tlid})
        return web.json_response({"ok": True})

    async def queue_remove(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        tlid = (body or {}).get("tlid") if isinstance(body, dict) else None
        if not isinstance(tlid, int):
            return web.json_response({"ok": False, "error": "tlid_required"},
                                     status=400)
        await mopidy.call("core.tracklist.remove",
                          {"criteria": {"tlid": [tlid]}})
        return web.json_response({"ok": True})

    async def queue_clear(_request: web.Request) -> web.Response:
        await mopidy.call("core.tracklist.clear")
        return web.json_response({"ok": True})

    async def rescan(_request: web.Request) -> web.Response:
        """Trigger a full Mopidy library rescan via boombox-state. Heavier
        than core.library.refresh — runs `mopidyctl local scan` server-side
        which actually re-indexes new files dropped over Samba / USB.
        Fires the scan and returns immediately; the rescan can take minutes
        on a large library and there's no streaming progress channel yet."""
        import aiohttp
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=4)) as s:
                async with s.post(
                        "http://127.0.0.1:6681/library/scan") as r:
                    if r.status != 200:
                        return web.json_response(
                            {"ok": False, "error": f"upstream_{r.status}"},
                            status=502)
                    body = await r.json()
        except Exception as e:
            return web.json_response(
                {"ok": False, "error": str(e)}, status=502)
        return web.json_response({"ok": bool(body.get("ok"))})

    return (search, list_playlists, create_playlist, playlist_items, queue,
            rescan, browse, lookup, queue_list, queue_jump, queue_remove,
            queue_clear, playlist_append, playlist_remove_item,
            playlist_delete, playlist_rename, queue_move)


def add_routes(app: web.Application, mopidy) -> None:
    """Register library/playlist/queue routes. `mopidy` is a
    clients.MopidyRpc (or any object with an async .call(method, params))."""
    (search, list_pls, create_pl, pl_items, queue, rescan, browse, lookup,
     queue_list, queue_jump, queue_remove, queue_clear,
     playlist_append, playlist_remove_item,
     playlist_delete, playlist_rename, queue_move) = _make_handlers(mopidy)
    app.router.add_get("/api/remote/library/search", search)
    app.router.add_get("/api/remote/library/browse", browse)
    app.router.add_get("/api/remote/library/lookup", lookup)
    app.router.add_post("/api/remote/library/rescan", rescan)
    app.router.add_get("/api/remote/playlists", list_pls)
    app.router.add_post("/api/remote/playlists", create_pl)
    app.router.add_get("/api/remote/playlists/{uri}/items", pl_items)
    app.router.add_post("/api/remote/playlists/{uri}/append", playlist_append)
    app.router.add_post("/api/remote/playlists/{uri}/remove_item",
                        playlist_remove_item)
    app.router.add_post("/api/remote/playlists/{uri}/rename", playlist_rename)
    app.router.add_post("/api/remote/playlists/{uri}/delete", playlist_delete)
    app.router.add_post("/api/remote/queue", queue)
    app.router.add_get("/api/remote/queue", queue_list)
    app.router.add_post("/api/remote/queue/jump", queue_jump)
    app.router.add_post("/api/remote/queue/remove", queue_remove)
    app.router.add_post("/api/remote/queue/clear", queue_clear)
    app.router.add_post("/api/remote/queue/move", queue_move)
