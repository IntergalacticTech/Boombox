"""Thin Mopidy JSON-RPC client used by boombox-rfid to enqueue playback
on a bound tap. Independent of the kiosk's ui/src/lib/mopidy.ts WS client.

Queueing strategy: Mopidy's stream backend scans every http(s) URI during
``core.tracklist.add`` (~0.2-0.5 s each over the internet), and the whole
call — plus Mopidy's HTTP server — is blocked meanwhile. An artist card with
200 streamed tracks would take over a minute and blow the RPC timeout before
a note played. So a long streamed list is split: the first track is added
and started immediately (``play_uris``), and the tail is appended in small
chunks afterwards (``append_tail``), normally from a background task.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterable

import aiohttp

log = logging.getLogger("boombox-rfid.mopidy")

# URIs Mopidy has to scan over the network when added.
_SCANNED_PREFIXES = ("http://", "https://")
# Lists this short (or with nothing to scan, e.g. all file://) keep the
# original single tracklist.add — they're quick enough as is.
SYNC_ADD_MAX = 5
# Tracks added before playback starts on a long streamed list.
HEAD_COUNT = 1
# Tail chunk size. Small on purpose: each add blocks Mopidy's core + HTTP
# server for chunk × scan time, so short chunks keep the UI's controls
# responsive between them.
TAIL_CHUNK = 10
# Per-call timeout for a tail chunk (chunk × worst-case scan, with margin).
TAIL_CALL_TIMEOUT_S = 90.0
# Breather between chunks so queued UI RPCs get a turn.
TAIL_GAP_S = 0.25
# Timeout for the head path (clear + head add) of a tap. Mopidy's core runs
# one call at a time, and cancelling the previous card's tail only drops our
# side of it: a chunk already sent keeps scanning, and this tap's clear
# queues behind it. So wait out one worst-case chunk, not the 10 s default.
HEAD_CALL_TIMEOUT_S = TAIL_CALL_TIMEOUT_S


def needs_split(uris: list[str]) -> bool:
    """True when adding `uris` in one call would stall on network scans."""
    return len(uris) > SYNC_ADD_MAX and any(u.startswith(_SCANNED_PREFIXES) for u in uris)


@dataclass
class PendingTail:
    """URIs still to be queued after the head, and where they go: right
    after tlid `after_tlid` (None = end of the tracklist)."""
    uris: list[str]
    after_tlid: int | None


def _tlids(added: object) -> list[int]:
    if not isinstance(added, list):
        return []
    return [t["tlid"] for t in added
            if isinstance(t, dict) and isinstance(t.get("tlid"), int)]


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

    async def _call(self, method: str, params: dict | None = None,
                    timeout: float | None = None) -> object:
        assert self._session is not None
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method,
                "params": params or {}}
        kw = {"timeout": aiohttp.ClientTimeout(total=timeout)} if timeout else {}
        async with self._session.post(self.url, json=body, **kw) as r:
            data = await r.json()
        if "error" in data:
            raise RuntimeError(f"mopidy {method}: {data['error']}")
        return data.get("result")

    async def _add(self, uris: list[str], at_position: int | None = None,
                   timeout: float | None = None) -> object:
        """tracklist.add with the Track-object fallback.

        Mopidy 3.4.2 + recent GStreamer has a scanner bug that drops
        http:// URIs at scan time, returning an empty list. The Track-object
        form bypasses scanning since we already provide the metadata.
        """
        params: dict = {"uris": uris}
        if at_position is not None:
            params["at_position"] = at_position
        added = await self._call("core.tracklist.add", params, timeout=timeout)
        if isinstance(added, list) and len(added) == 0 and uris:
            tracks = [{"__model__": "Track", "uri": u, "name": "Streaming"}
                      for u in uris]
            params = {"tracks": tracks}
            if at_position is not None:
                params["at_position"] = at_position
            added = await self._call("core.tracklist.add", params, timeout=timeout)
        return added

    async def play_uris(self, uris: Iterable[str]) -> PendingTail | None:
        """Replace tracklist with the given URIs and start playing.

        Short or non-streamed lists are added in one call, as always. A long
        streamed list only has its first HEAD_COUNT tracks added before play
        starts; the rest is returned as a PendingTail for the caller to hand
        to `append_tail` (typically in a background task, so an RFID tap
        doesn't block on it). Returns None when everything is queued.

        After playing, also issues a resume — observed live: the play
        call sometimes left Mopidy in a 'paused' state with the right
        current track. Calling resume() is a no-op when already playing.
        """
        uri_list = list(uris)
        if not uri_list:
            return None
        if needs_split(uri_list):
            head, tail = uri_list[:HEAD_COUNT], uri_list[HEAD_COUNT:]
        else:
            head, tail = uri_list, []
        await self._call("core.tracklist.clear", timeout=HEAD_CALL_TIMEOUT_S)
        added = await self._add(head, timeout=HEAD_CALL_TIMEOUT_S)
        # Play the first track explicitly via tlid so Mopidy doesn't have to
        # guess what to resume — explicit selection also reliably moves us
        # out of 'stopped'/'paused' into 'playing'.
        tlids = _tlids(added)
        if tlids:
            await self._call("core.playback.play", {"tlid": tlids[0]})
        else:
            await self._call("core.playback.play")
        # Belt and suspenders: if Mopidy somehow landed in paused state,
        # explicitly resume.
        state = await self._call("core.playback.get_state")
        if state == "paused":
            await self._call("core.playback.resume")
        if not tail:
            return None
        return PendingTail(uris=tail, after_tlid=tlids[-1] if tlids else None)

    async def _index(self, tlid: int | None) -> int | None:
        if tlid is None:
            return None
        idx = await self._call("core.tracklist.index", {"tlid": tlid})
        return idx if isinstance(idx, int) else None

    async def append_tail(self, tail: PendingTail, *,
                          chunk: int = TAIL_CHUNK,
                          call_timeout: float = TAIL_CALL_TIMEOUT_S,
                          gap_s: float = TAIL_GAP_S) -> int:
        """Queue `tail` in chunks, each placed right after the previous one.

        Anchoring on the last tlid we added (rather than appending at the
        end) keeps album order even if someone queues a track meanwhile. If
        the queue stops being ours — the user started something else, or
        another tap replaced it — we stop: the rest of this list no longer
        belongs anywhere. "Ours" means both the anchor and the anchor before
        it are still present; if only the newest chunk survives, it landed in
        somebody else's queue mid-replace, so it is removed again. Returns
        the number of tracks left queued.
        """
        anchor = tail.after_tlid
        prev: int | None = None      # anchor before the last chunk
        last_chunk: list[int] = []   # tlids the last add created
        queued = 0
        uris = tail.uris

        async def still_ours() -> tuple[bool, int | None]:
            idx = await self._index(anchor)
            if idx is None:
                return False, None
            if prev is not None and await self._index(prev) is None:
                return False, idx
            return True, idx

        for i in range(0, len(uris), chunk):
            at: int | None = None
            if anchor is not None:
                ok, idx = await still_ours()
                if not ok:
                    return queued - await self._drop_stray(last_chunk, idx, len(uris) - i)
                assert idx is not None
                at = idx + 1
            added = await self._add(uris[i:i + chunk], at_position=at,
                                    timeout=call_timeout)
            tlids = _tlids(added)
            if tlids:
                prev, anchor, last_chunk = anchor, tlids[-1], tlids
                queued += len(tlids)
            if gap_s and i + chunk < len(uris):
                await asyncio.sleep(gap_s)
        if prev is not None and last_chunk:
            ok, idx = await still_ours()
            if not ok:
                queued -= await self._drop_stray(last_chunk, idx, 0)
        return queued

    async def _drop_stray(self, last_chunk: list[int], anchor_idx: int | None,
                          unqueued: int) -> int:
        """Log why queueing stopped; remove a chunk that landed in a foreign
        queue (its anchor is present but the chain before it is gone).
        Returns how many tracks were removed."""
        removed = 0
        if anchor_idx is not None and last_chunk:
            await self._call("core.tracklist.remove", {"criteria": {"tlid": last_chunk}})
            removed = len(last_chunk)
        log.info("tracklist changed; dropping %d unqueued tracks%s", unqueued,
                 f" (and {removed} stray)" if removed else "")
        return removed
