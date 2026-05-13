"""Press classifier: timestamps + edges -> short_press / long_press / long_hold events."""
from __future__ import annotations

import boombox_buttons as bb


def test_short_press_emits_short_on_release():
    """Press for 100 ms, release -> single short_press."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    events = list(pc.feed(t_ms=0, edge="down"))
    events += list(pc.feed(t_ms=100, edge="up"))
    assert events == [("short_press",)]


def test_long_press_emits_long_on_threshold():
    """Held past 600 ms -> long_press fires once at threshold."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    events = list(pc.feed(t_ms=0, edge="down"))
    events += list(pc.tick(t_ms=300))   # still under threshold
    assert events == []
    events += list(pc.tick(t_ms=600))   # at threshold
    assert events == [("long_press",)]


def test_long_hold_ticks_at_interval():
    """After long_press, every long_hold_tick_ms while still held emits a long_hold tick."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    list(pc.tick(t_ms=600))             # long_press fires
    events = list(pc.tick(t_ms=800))    # 200ms later
    assert events == [("long_hold",)]
    events = list(pc.tick(t_ms=1000))
    assert events == [("long_hold",)]


def test_release_after_long_press_does_not_emit_short():
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    list(pc.tick(t_ms=600))
    events = list(pc.feed(t_ms=900, edge="up"))
    assert events == [("long_release",)]


def test_release_before_threshold_is_short_even_after_multiple_ticks():
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    list(pc.tick(t_ms=300))
    list(pc.tick(t_ms=500))
    events = list(pc.feed(t_ms=599, edge="up"))
    assert events == [("short_press",)]


def test_duplicate_down_edge_does_not_restart():
    """A stray 'down' edge while already pressed is ignored (debounce safety)."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    events = list(pc.feed(t_ms=50, edge="down"))
    assert events == []
