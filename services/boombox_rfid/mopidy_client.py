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
        """Replace tracklist with the given URIs and start playing."""
        uri_list = list(uris)
        if not uri_list:
            return
        await self._call("core.tracklist.clear")
        await self._call("core.tracklist.add", {"uris": uri_list})
        await self._call("core.playback.play")
