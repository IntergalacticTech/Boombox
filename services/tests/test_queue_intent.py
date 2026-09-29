"""queue_intent: the RFID card list boombox-resume snapshots mid-tail."""
from __future__ import annotations

import json
import time

import queue_intent as qi


def test_write_read_clear_roundtrip():
    tok = qi.write_intent(["a", "b", "c"])
    assert qi.read_intent() == ["a", "b", "c"]
    qi.clear_intent("someone-else")
    assert qi.read_intent() == ["a", "b", "c"]  # not that writer's to clear
    qi.clear_intent(tok)
    assert qi.read_intent() is None
    qi.clear_intent(tok)  # already gone: no error


def test_stale_or_garbage_intent_ignored():
    path = qi.intent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": time.time() - qi.MAX_AGE_S - 1, "uris": ["a"]}))
    assert qi.read_intent() is None
    path.write_text("{nope")
    assert qi.read_intent() is None
    path.write_text(json.dumps({"ts": time.time(), "uris": [1, 2]}))
    assert qi.read_intent() is None


def test_merge_intent_only_while_queue_is_part_of_the_card():
    full = [f"u{i}" for i in range(10)]
    partial = {"track_uri": "u0", "tracklist": full[:3], "position_ms": 5}
    assert qi.merge_intent(partial, full)["tracklist"] == full
    assert qi.merge_intent(partial, None) == partial
    # Playing something else, or a foreign track in the queue: leave it.
    other = {"track_uri": "x", "tracklist": ["x"]}
    assert qi.merge_intent(other, full) == other
    mixed = {"track_uri": "u0", "tracklist": ["u0", "user.mp3"]}
    assert qi.merge_intent(mixed, full) == mixed
