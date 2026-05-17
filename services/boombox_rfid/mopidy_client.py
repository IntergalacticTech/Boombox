"""Thin Mopidy JSON-RPC client used by boombox-rfid to enqueue playback
on a bound tap. Independent of the kiosk's ui/src/lib/mopidy.ts WS client.
"""
from __future__ import annotations

import logging
from typing import Iterable

import aiohttp

log = logging.getLogger("boombox-rfid.mopidy")


class MopidyClient:
    def __init__(self, rpc_url: str) -> None:
        self.url = rpc_url
        self._id = 0
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "MopidyClient":
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
        )
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _call(self, method: str, params: dict | None = None) -> object:
        assert self._session is not None
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method,
                "params": params or {}}
        async with self._session.post(self.url, json=body) as r:
            data = await r.json()
        if "error" in data:
            raise RuntimeError(f"mopidy {method}: {data['error']}")
        return data.get("result")

    async def play_uris(self, uris: Iterable[str]) -> None:
        """Replace tracklist with the given URIs and start playing.

        Falls back to adding Track objects when the simple {uris} form
        returns empty — Mopidy 3.4.2 + recent GStreamer has a scanner
        bug that drops http:// URIs at scan time. Track-object form
        bypasses scanning since we already provide the metadata.

        After playing, also issues a resume — observed live: the play
        call sometimes left Mopidy in a 'paused' state with the right
        current track. Calling resume() is a no-op when already playing.
        """
        uri_list = list(uris)
        if not uri_list:
            return
        await self._call("core.tracklist.clear")
        added = await self._call("core.tracklist.add", {"uris": uri_list})
        if isinstance(added, list) and len(added) == 0 and uri_list:
            # Scan failed; retry as bare Track objects so Mopidy skips scanning.
            tracks = [{"__model__": "Track", "uri": u, "name": "Streaming"}
                      for u in uri_list]
            added = await self._call("core.tracklist.add", {"tracks": tracks})
        # Play the first track explicitly via tlid so Mopidy doesn't have to
        # guess what to resume — explicit selection also reliably moves us
        # out of 'stopped'/'paused' into 'playing'.
        if isinstance(added, list) and added:
            first = added[0]
            tlid = first.get("tlid") if isinstance(first, dict) else None
            if tlid is not None:
                await self._call("core.playback.play", {"tlid": tlid})
            else:
                await self._call("core.playback.play")
        else:
            await self._call("core.playback.play")
        # Belt and suspenders: if Mopidy somehow landed in paused state,
        # explicitly resume.
        state = await self._call("core.playback.get_state")
        if state == "paused":
            await self._call("core.playback.resume")
