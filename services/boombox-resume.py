#!/usr/bin/env python3
"""Boombox auto-resume.

Continuously snapshots Mopidy's playback state (current track URI + tracklist
URIs + position) to disk while music plays. On startup, after a brief grace
period, if Mopidy is idle and a recent snapshot exists, it restores it.

Why a separate process rather than a Mopidy extension? It keeps Mopidy itself
unmodified (fewer pieces to break on upgrades) and matches every other audio
control path in this project — HTTP RPC into mopidy:6680.

Snapshot file: /var/lib/boombox/last.json (or BOOMBOX_RESUME_FILE env var).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-resume")

MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
SNAPSHOT_PATH = Path(os.environ.get("BOOMBOX_RESUME_FILE", "/var/lib/boombox/last.json"))
SNAPSHOT_EVERY_S = 5
RESUME_AGE_LIMIT_S = 24 * 60 * 60       # don't resume snapshots older than a day
STARTUP_GRACE_S = 5                     # let Mopidy finish booting before deciding


_id = 0
async def rpc(sess: aiohttp.ClientSession, method: str, params: dict | None = None):
    global _id
    _id += 1
    body = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}
    async with sess.post(MOPIDY_RPC, json=body, timeout=aiohttp.ClientTimeout(total=4)) as r:
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


async def maybe_restore(sess: aiohttp.ClientSession) -> None:
    snap = read_snapshot()
    if not snap:
        log.info("no snapshot to restore")
        return
    state = await rpc(sess, "core.playback.get_state")
    if state == "playing":
        log.info("Mopidy already playing — not restoring")
        return

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
        return

    # Otherwise rebuild tracklist + jump to snapshot track.
    uris = snap.get("tracklist") or []
    if not uris:
        uris = [snap["track_uri"]]
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


async def main() -> None:
    log.info("snapshot path: %s", SNAPSHOT_PATH)
    async with aiohttp.ClientSession() as sess:
        # Wait for Mopidy to settle, then attempt the cold-start restore.
        await asyncio.sleep(STARTUP_GRACE_S)
        try:
            await maybe_restore(sess)
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
                        await maybe_restore(sess)
                    except Exception as e:
                        log.warning("mid-session restore failed: %s", e)

            prev_was_active = reachable and tl_len > 0

            if reachable:
                try:
                    snap = await take_snapshot(sess)
                    if snap:
                        write_snapshot(snap)
                except Exception as e:
                    log.debug("snapshot cycle: %s", e)

            await asyncio.sleep(SNAPSHOT_EVERY_S)


if __name__ == "__main__":
    asyncio.run(main())
