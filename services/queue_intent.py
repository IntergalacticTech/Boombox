"""The full queue boombox-rfid is still streaming into Mopidy.

A long streamed RFID card starts with only its first track queued; the rest
is appended in background chunks over a minute or more (see
``boombox_rfid.mopidy_client``). boombox-resume snapshots Mopidy's *live*
tracklist every few seconds, so a reboot or Mopidy restart in that window
would save — and later restore — a partial queue.

boombox-rfid therefore records the card's intended full URI list here while
its tail is in flight, and boombox-resume snapshots that list instead of the
partial one (same idea as resume's own ``merge_in_flight``). Both services
run as the kiosk user, so the file lives next to resume's snapshot.

    BOOMBOX_QUEUE_INTENT_FILE   default ~/.local/state/boombox/queue-intent.json
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Long enough for any card's tail (1000 tracks × 0.5 s scan ≈ 8 min); a file
# left behind by a crashed boombox-rfid is ignored after this.
MAX_AGE_S = 60 * 60


def intent_path() -> Path:
    env = os.environ.get("BOOMBOX_QUEUE_INTENT_FILE")
    if env:
        return Path(env)
    return Path.home() / ".local" / "state" / "boombox" / "queue-intent.json"


def write_intent(uris: list[str]) -> str:
    """Record `uris` as the queue being built. Returns a token for
    `clear_intent` so a superseded writer can't delete a newer intent."""
    token = f"{os.getpid()}-{time.time_ns()}"
    path = intent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"token": token, "ts": time.time(), "uris": list(uris)}))
    tmp.replace(path)
    return token


def clear_intent(token: str | None = None) -> None:
    """Remove the intent; with `token`, only if it is still that write's."""
    path = intent_path()
    try:
        if token is not None:
            if json.loads(path.read_text()).get("token") != token:
                return
        path.unlink()
    except (OSError, ValueError):
        pass


def read_intent() -> list[str] | None:
    try:
        data = json.loads(intent_path().read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if time.time() - float(data.get("ts") or 0) > MAX_AGE_S:
        return None
    uris = data.get("uris")
    if not isinstance(uris, list) or not all(isinstance(u, str) for u in uris):
        return None
    return uris


def merge_intent(snap: dict, uris: list[str] | None) -> dict:
    """Swap a partial tracklist in `snap` for the intended full one — only
    while the live queue is still a piece of that card (current track in it,
    nothing foreign queued), so a stale intent can't resurrect an old card."""
    if not uris or snap.get("track_uri") not in uris:
        return snap
    wanted = set(uris)
    if not all(u in wanted for u in snap.get("tracklist") or []):
        return snap
    return dict(snap, tracklist=list(uris))
