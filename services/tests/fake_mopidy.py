"""In-process fake of Mopidy's JSON-RPC endpoint (tracklist + playback subset).

Enough semantics for the queueing tests: tlids, at_position inserts,
tracklist.index(tlid=...), and a record of every call made.
"""
from __future__ import annotations

from aiohttp import web


class FakeMopidy:
    def __init__(self) -> None:
        self.tl: list[tuple[int, str]] = []
        self.next_tlid = 1
        self.state = "stopped"
        self.current: int | None = None
        self.position = 0
        self.calls: list[tuple[str, dict]] = []
        # Hook: called before each tracklist.add is applied (lets a test
        # mutate the tracklist "concurrently").
        self.before_add = None

    def uris(self) -> list[str]:
        return [u for _t, u in self.tl]

    def _tl_track(self, tlid: int, uri: str) -> dict:
        return {"__model__": "TlTrack", "tlid": tlid,
                "track": {"__model__": "Track", "uri": uri}}

    def handle(self, method: str, p: dict):
        self.calls.append((method, p))
        if method == "core.tracklist.clear":
            self.tl = []
            self.current = None
            self.state = "stopped"
            return None
        if method == "core.tracklist.add":
            if self.before_add:
                self.before_add(self, p)
            uris = p.get("uris") or [t["uri"] for t in p.get("tracks") or []]
            new = []
            for u in uris:
                new.append((self.next_tlid, u))
                self.next_tlid += 1
            at = p.get("at_position")
            if at is None:
                self.tl.extend(new)
            else:
                self.tl[at:at] = new
            return [self._tl_track(t, u) for t, u in new]
        if method == "core.tracklist.remove":
            gone = set((p.get("criteria") or {}).get("tlid") or [])
            removed = [(t, u) for t, u in self.tl if t in gone]
            self.tl = [(t, u) for t, u in self.tl if t not in gone]
            return [self._tl_track(t, u) for t, u in removed]
        if method == "core.tracklist.index":
            for i, (t, _u) in enumerate(self.tl):
                if t == p.get("tlid"):
                    return i
            return None
        if method == "core.tracklist.get_tl_tracks":
            return [self._tl_track(t, u) for t, u in self.tl]
        if method == "core.tracklist.get_tracks":
            return [{"uri": u} for _t, u in self.tl]
        if method == "core.tracklist.get_length":
            return len(self.tl)
        if method == "core.playback.play":
            tlid = p.get("tlid")
            if tlid is None and self.tl:
                tlid = self.tl[0][0]
            self.current = tlid
            self.state = "playing" if tlid is not None else "stopped"
            return None
        if method == "core.playback.get_state":
            return self.state
        if method == "core.playback.get_current_track":
            for t, u in self.tl:
                if t == self.current:
                    return {"uri": u}
            return None
        if method == "core.playback.get_time_position":
            return self.position
        if method == "core.playback.seek":
            self.position = p.get("time_position", 0)
            return True
        if method == "core.playback.pause":
            self.state = "paused"
            return None
        if method == "core.playback.resume":
            self.state = "playing"
            return None
        raise KeyError(method)

    def app(self) -> web.Application:
        async def rpc(req: web.Request) -> web.Response:
            body = await req.json()
            try:
                result = self.handle(body["method"], body.get("params") or {})
            except KeyError as e:
                return web.json_response({"jsonrpc": "2.0", "id": body.get("id"),
                                          "error": {"message": f"no method {e}"}})
            return web.json_response({"jsonrpc": "2.0", "id": body.get("id"),
                                      "result": result})

        app = web.Application()
        app.router.add_post("/mopidy/rpc", rpc)
        return app

    def adds(self) -> list[dict]:
        return [p for m, p in self.calls if m == "core.tracklist.add"]
