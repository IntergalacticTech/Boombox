#!/usr/bin/env python3
"""Boombox auto-resume.

Continuously snapshots Mopidy's playback state (current track URI + tracklist
URIs + position) to disk while music plays. On startup, after a brief grace
period, if Mopidy is idle and a recent snapshot exists, it restores it.

Why a separate process rather than a Mopidy extension? It keeps Mopidy itself
unmodified (fewer pieces to break on upgrades) and matches every other audio
control path in this project — HTTP RPC into mopidy:6680.

Snapshot file: /var/lib/boombox/last.json (or BOOMBOX_RESUME_FILE env var).

Long streamed queues: Mopidy scans every http(s) URI inside
core.tracklist.add (~0.2-0.5 s each over the internet), so replaying a
200-track queue in one call would blow the RPC timeout and delay the music
by a minute. Such a queue is restored current-track-first (position and
paused state restored as before), then the rest is re-queued around it in
small background chunks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-resume")

MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
SNAPSHOT_PATH = Path(os.environ.get("BOOMBOX_RESUME_FILE", "/var/lib/boombox/last.json"))
SNAPSHOT_EVERY_S = 5
RESUME_AGE_LIMIT_S = 24 * 60 * 60       # don't resume snapshots older than a day
STARTUP_GRACE_S = 5                     # let Mopidy finish booting before deciding
RPC_TIMEOUT_S = 4
# Queue-restore tuning (mirrors boombox_rfid.mopidy_client): lists this short,
# or with nothing Mopidy must scan over the network, keep the one-shot add.
RESTORE_SYNC_MAX = 5
RESTORE_CHUNK = 10                      # small: each add blocks Mopidy's core
RESTORE_HEAD_TIMEOUT_S = 15             # adding the one current track
RESTORE_CHUNK_TIMEOUT_S = 90            # chunk × worst-case scan, with margin
RESTORE_GAP_S = 0.25                    # let queued UI RPCs through between chunks
_SCANNED_PREFIXES = ("http://", "https://")


_id = 0
async def rpc(sess: aiohttp.ClientSession, method: str, params: dict | None = None,
              timeout: float = RPC_TIMEOUT_S):
    global _id
    _id += 1
    body = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}
    async with sess.post(MOPIDY_RPC, json=body, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        if r.status != 200:
            return None
        return (await r.json(content_type=None)).get("result")


async def take_snapshot(sess: aiohttp.ClientSession) -> dict | None:
    state = await rpc(sess, "core.playback.get_state")
    if state not in ("playing", "paused"):
        return None
    cur = await rpc(sess, "core.playback.get_current_track")
    if not cur:
        return None
    pos = await rpc(sess, "core.playback.get_time_position")
    tl = await rpc(sess, "core.tracklist.get_tracks")
    tl_uris = [t.get("uri") for t in (tl or []) if t.get("uri")]
    cur_uri = cur.get("uri")
    if not cur_uri:
        return None
    return {
        "ts": time.time(),
        "state": state,
        "track_uri": cur_uri,
        "tracklist": tl_uris,
        "position_ms": int(pos or 0),
    }


def write_snapshot(s: dict) -> None:
    try:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SNAPSHOT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(s))
        tmp.replace(SNAPSHOT_PATH)
    except Exception as e:
        log.warning("snapshot write failed: %s", e)


def read_snapshot() -> dict | None:
    try:
        if not SNAPSHOT_PATH.exists():
            return None
        s = json.loads(SNAPSHOT_PATH.read_text())
        if time.time() - float(s.get("ts", 0)) > RESUME_AGE_LIMIT_S:
            log.info("snapshot too old, ignoring")
            return None
        if not s.get("track_uri"):
            return None
        return s
    except Exception as e:
        log.warning("snapshot read failed: %s", e)
        return None


async def maybe_restore(sess: aiohttp.ClientSession) -> RestoreTail | None:
    """Restore the snapshot if Mopidy is idle. Returns the part of a long
    queue still to be re-queued (hand it to append_restore_tail), else None."""
    snap = read_snapshot()
    if not snap:
        log.info("no snapshot to restore")
        return None
    state = await rpc(sess, "core.playback.get_state")
    if state == "playing":
        log.info("Mopidy already playing — not restoring")
        return None

    # If the snapshot says the user paused us before shutdown, we restore the
    # tracklist + position but leave Mopidy paused. Otherwise the boombox
    # plays unexpectedly at boot, which is jarring on an appliance.
    was_paused = snap.get("state") == "paused"

    cur = await rpc(sess, "core.playback.get_current_track")
    if cur and cur.get("uri") == snap["track_uri"] and state in ("paused", "stopped"):
        # Looks like the same track; seek + play, then pause if appropriate.
        log.info("resuming current track at %d ms (was_paused=%s)",
                 snap["position_ms"], was_paused)
        await rpc(sess, "core.playback.seek", {"time_position": snap["position_ms"]})
        await rpc(sess, "core.playback.play")
        if was_paused:
            await rpc(sess, "core.playback.pause")
        return None

    # Otherwise rebuild tracklist + jump to snapshot track.
    uris = snap.get("tracklist") or []
    if not uris:
        uris = [snap["track_uri"]]
    if _needs_split(uris):
        return await _restore_current_first(sess, snap, uris, was_paused)
    log.info("restoring tracklist of %d, jumping to %s @ %d ms (was_paused=%s)",
             len(uris), snap["track_uri"], snap["position_ms"], was_paused)
    await rpc(sess, "core.tracklist.clear")
    await rpc(sess, "core.tracklist.add", {"uris": uris})
    # Find the tlid for the snapshot track and play it.
    tl = await rpc(sess, "core.tracklist.get_tl_tracks") or []
    tlid = None
    for t in tl:
        if t.get("track", {}).get("uri") == snap["track_uri"]:
            tlid = t.get("tlid")
            break
    if tlid is not None:
        await rpc(sess, "core.playback.play", {"tlid": tlid})
    else:
        await rpc(sess, "core.playback.play")
    # Seek shortly after play has actually started.
    await asyncio.sleep(0.6)
    await rpc(sess, "core.playback.seek", {"time_position": snap["position_ms"]})
    if was_paused:
        await rpc(sess, "core.playback.pause")
    return None


@dataclass
class RestoreTail:
    """What's left to re-queue around the already-playing current track."""
    before: list[str]        # snapshot tracks preceding the current one
    after: list[str]         # snapshot tracks following it
    current_tlid: int        # the restored current track
    full: list[str]          # the whole snapshot tracklist, in order


def _needs_split(uris: list[str]) -> bool:
    return len(uris) > RESTORE_SYNC_MAX and any(u.startswith(_SCANNED_PREFIXES) for u in uris)


def _tlids(added) -> list[int]:
    if not isinstance(added, list):
        return []
    return [t["tlid"] for t in added
            if isinstance(t, dict) and isinstance(t.get("tlid"), int)]


async def _restore_current_first(sess: aiohttp.ClientSession, snap: dict,
                                 uris: list[str], was_paused: bool) -> RestoreTail | None:
    """Queue + play just the snapshot's current track (same position / pause
    semantics as the one-shot path); return the rest for the background."""
    try:
        idx = uris.index(snap["track_uri"])
    except ValueError:
        idx = 0  # like the one-shot path: no match → start from the top
    log.info("restoring long tracklist of %d current-first: %s @ %d ms (was_paused=%s)",
             len(uris), uris[idx], snap["position_ms"], was_paused)
    await rpc(sess, "core.tracklist.clear")
    added = await rpc(sess, "core.tracklist.add", {"uris": [uris[idx]]},
                      timeout=RESTORE_HEAD_TIMEOUT_S)
    tlids = _tlids(added)
    if tlids:
        await rpc(sess, "core.playback.play", {"tlid": tlids[0]})
    else:
        await rpc(sess, "core.playback.play")
    # Seek shortly after play has actually started.
    await asyncio.sleep(0.6)
    await rpc(sess, "core.playback.seek", {"time_position": snap["position_ms"]})
    if was_paused:
        await rpc(sess, "core.playback.pause")
    if not tlids:
        log.warning("current track didn't queue; not restoring the rest")
        return None
    return RestoreTail(before=uris[:idx], after=uris[idx + 1:],
                       current_tlid=tlids[0], full=list(uris))


async def _index(sess: aiohttp.ClientSession, tlid: int | None) -> int | None:
    if tlid is None:
        return None
    idx = await rpc(sess, "core.tracklist.index", {"tlid": tlid})
    return idx if isinstance(idx, int) else None


async def append_restore_tail(sess: aiohttp.ClientSession, tail: RestoreTail,
                              gap_s: float = RESTORE_GAP_S) -> int:
    """Re-queue the rest of a restored queue around the current track.

    The following tracks go first (they're what plays next), each chunk
    right after the previous one; then the preceding tracks, each chunk
    inserted just before the current track so their order holds. Stops —
    taking back a chunk that landed in a foreign queue — as soon as the
    restored current track has left the tracklist (the user started
    something else). Returns the number of tracks re-queued.
    """
    queued = 0
    anchor = tail.current_tlid
    for kind, uris in (("after", tail.after), ("before", tail.before)):
        for i in range(0, len(uris), RESTORE_CHUNK):
            at = await _index(sess, tail.current_tlid)
            if at is not None and kind == "after":
                a_idx = await _index(sess, anchor)
                at = None if a_idx is None else a_idx + 1
            if at is None:
                log.info("tracklist changed during restore; stopping after %d", queued)
                return queued
            added = await rpc(sess, "core.tracklist.add",
                              {"uris": uris[i:i + RESTORE_CHUNK], "at_position": at},
                              timeout=RESTORE_CHUNK_TIMEOUT_S)
            tlids = _tlids(added)
            if tlids and await _index(sess, tail.current_tlid) is None:
                # Replaced while this chunk was in flight: take it back out.
                await rpc(sess, "core.tracklist.remove", {"criteria": {"tlid": tlids}})
                log.info("tracklist changed during restore; stopping after %d", queued)
                return queued
            if tlids:
                queued += len(tlids)
                if kind == "after":
                    anchor = tlids[-1]
            if gap_s:
                await asyncio.sleep(gap_s)
    log.info("restore re-queued %d/%d tracks", queued, len(tail.after) + len(tail.before))
    return queued


class _Restorer:
    """Runs maybe_restore and owns the background re-queue it may leave."""

    def __init__(self, sess: aiohttp.ClientSession) -> None:
        self._sess = sess
        self._task: asyncio.Task | None = None
        self._tail: RestoreTail | None = None

    def in_flight(self) -> RestoreTail | None:
        if self._task is not None and not self._task.done():
            return self._tail
        return None

    async def restore(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        tail = await maybe_restore(self._sess)
        if tail and (tail.before or tail.after):
            self._tail = tail
            self._task = asyncio.create_task(self._run(tail))

    async def _run(self, tail: RestoreTail) -> None:
        try:
            await append_restore_tail(self._sess, tail)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("background re-queue failed: %s", e)


def merge_in_flight(snap: dict, tail: RestoreTail | None) -> dict:
    """While a restore is still re-queueing, Mopidy's tracklist is partial;
    snapshot the intended full list instead so a reboot mid-restore doesn't
    lose the rest of the queue."""
    if tail and snap.get("track_uri") in tail.full:
        snap = dict(snap, tracklist=list(tail.full))
    return snap


async def main() -> None:
    log.info("snapshot path: %s", SNAPSHOT_PATH)
    async with aiohttp.ClientSession() as sess:
        restorer = _Restorer(sess)
        # Wait for Mopidy to settle, then attempt the cold-start restore.
        await asyncio.sleep(STARTUP_GRACE_S)
        try:
            await restorer.restore()
        except Exception as e:
            log.warning("startup restore failed: %s", e)

        # Steady-state loop: snapshot live state, AND detect a Mopidy
        # mid-session restart by watching for the tracklist evaporating
        # while we still have a recent snapshot. That covers `apt upgrade`,
        # crashes, etc. — not just the in-app RESTART button.
        prev_was_active = False  # last poll had a non-empty tracklist
        while True:
            try:
                state = await rpc(sess, "core.playback.get_state")
                tl_len = await rpc(sess, "core.tracklist.get_length") or 0
                reachable = state is not None
            except Exception:
                reachable = False
                state = None
                tl_len = 0

            # Restart-mid-session signal: we had an active session a moment
            # ago (tl_len > 0), now tracklist is empty, state is stopped, and
            # the snapshot file is fresh — that's almost certainly a fresh
            # Mopidy after a restart.
            is_fresh_idle = reachable and state == "stopped" and tl_len == 0
            if prev_was_active and is_fresh_idle:
                snap = read_snapshot()
                age = time.time() - float(snap.get("ts", 0)) if snap else 1e9
                if snap and age < 60:
                    log.info("Mopidy mid-session restart detected (snapshot %.0f s old) — restoring", age)
                    try:
                        await restorer.restore()
                    except Exception as e:
                        log.warning("mid-session restore failed: %s", e)

            prev_was_active = reachable and tl_len > 0

            if reachable:
                try:
                    snap = await take_snapshot(sess)
                    if snap:
                        write_snapshot(merge_in_flight(snap, restorer.in_flight()))
                except Exception as e:
                    log.debug("snapshot cycle: %s", e)

            await asyncio.sleep(SNAPSHOT_EVERY_S)


if __name__ == "__main__":
    asyncio.run(main())
