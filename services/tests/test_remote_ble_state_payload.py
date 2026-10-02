"""ble_peripheral.ble_state_payload — the BLE copy of the consolidated state
must fit one GATT value / notify (BlueZ truncates past MTU-3, and an ATT value
caps at 512 bytes), or remotes get cut-off JSON they can't parse."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

if "bless" not in sys.modules:
    try:
        import bless  # noqa: F401
    except ImportError:
        sys.modules["bless"] = MagicMock()

import ble_peripheral  # noqa: E402


def _state(**track_over) -> dict:
    track = {
        "uri": "local:track:Some%20Artist/Some%20Album/01%20A%20Song.flac",
        "title": "A Song", "artist": "Some Artist", "album": "Some Album",
        "duration_s": 245, "position_s": 12,
    }
    track.update(track_over)
    return {
        "boombox": {"id": "bb-1234abcd", "name": "MarkII", "version": 1},
        "source": "mopidy", "playing": True, "track": track,
        "art_hash": None, "art_url": "/local/" + "f" * 64 + ".jpeg",
        "volume": 0.42, "muted": False, "shuffle": True, "repeat": "all",
        "sources_available": ["mopidy", "airplay", "spotify", "bluetooth",
                              "movies"],
        "sleep_timer_s": None, "recording": False, "mic_on": False,
        "skin": "pocketlcd",
        "theme": {"bg": "#B9C3A5", "panel": "#2B2D29", "ink": "#1A2015",
                  "ink2": "#3E4836", "accent": "#C9502F",
                  "accent2": "#8C2F1F", "rule": "rgba(255,255,255,0.08)",
                  "font": "'Chakra Petch', 'Barlow Condensed', system-ui",
                  "mono": "'Share Tech Mono', 'JetBrains Mono', monospace"},
    }


def test_fits_and_keeps_what_remotes_read():
    out = ble_peripheral.ble_state_payload(_state())
    assert len(out) <= ble_peripheral.BLE_STATE_MAX
    doc = json.loads(out)
    assert doc["ok"] is True
    d = doc["data"]
    assert d["track"]["title"] == "A Song"
    assert d["track"]["duration_s"] == 245
    assert d["volume"] == 0.42 and d["shuffle"] is True and d["repeat"] == "all"
    assert d["skin"] == "pocketlcd"
    assert d["theme"]["accent"] == "#C9502F"
    assert d["theme"]["ink2"] == "#3E4836"
    # Dropped: nothing a remote reads over BLE.
    for k in ("art_url", "art_hash", "sources_available", "boombox"):
        assert k not in d
    assert "uri" not in d["track"]
    for k in ("font", "mono", "rule"):
        assert k not in d["theme"]


def test_long_strings_are_shortened_to_fit():
    out = ble_peripheral.ble_state_payload(_state(
        title="T" * 400, artist="Ä" * 200, album="A" * 300))
    assert len(out) <= ble_peripheral.BLE_STATE_MAX
    t = json.loads(out)["data"]["track"]
    # The cut is shared: every field keeps a readable prefix.
    for k, ch in (("title", "T"), ("artist", "Ä"), ("album", "A")):
        assert t[k].startswith(ch * 4) and t[k].endswith("…"), (k, t[k])


def test_typical_track_is_untouched():
    out = ble_peripheral.ble_state_payload(_state(
        title="Once in a Lifetime (2005 Remaster)", artist="Talking Heads",
        album="Remain in Light (Deluxe Version)"))
    t = json.loads(out)["data"]["track"]
    assert t["title"] == "Once in a Lifetime (2005 Remaster)"
    assert t["album"] == "Remain in Light (Deluxe Version)"


def test_typical_long_title_keeps_artist():
    out = ble_peripheral.ble_state_payload(_state(
        title="Kärlekens tunga — a much longer title than fits on one line",
        artist="Eldkvarn", album="Kärlekens tunga"))
    assert len(out) <= ble_peripheral.BLE_STATE_MAX
    t = json.loads(out)["data"]["track"]
    assert t["artist"] == "Eldkvarn"
    assert t["title"].startswith("Kärlekens tunga")


def test_falsy_flags_are_dropped_but_set_ones_kept():
    s = _state()
    d = json.loads(ble_peripheral.ble_state_payload(s))["data"]
    assert "recording" not in d and "mic_on" not in d and "sleep_timer_s" not in d
    s.update(mic_on=True, sleep_timer_s=900)
    d = json.loads(ble_peripheral.ble_state_payload(s))["data"]
    assert d["mic_on"] is True and d["sleep_timer_s"] == 900


def test_multibyte_text_is_cut_on_a_character_boundary():
    out = ble_peripheral.ble_state_payload(_state(title="日本語" * 120,
                                                  artist="", album=""))
    assert len(out) <= ble_peripheral.BLE_STATE_MAX
    title = json.loads(out.decode("utf-8"))["data"]["track"]["title"]
    assert title.endswith("…") and "日本語" in title


def test_no_track_and_no_theme():
    s = _state()
    s["track"] = None
    s["theme"] = {}
    d = json.loads(ble_peripheral.ble_state_payload(s))["data"]
    assert d["track"] is None and d["theme"] == {}


def test_does_not_mutate_the_input():
    s = _state(title="x" * 600)
    before = json.dumps(s, sort_keys=True)
    ble_peripheral.ble_state_payload(s)
    assert json.dumps(s, sort_keys=True) == before


def test_push_loop_resends_unchanged_state(monkeypatch):
    """A remote's initial read of a long value is unreliable (bless drops the
    ReadValue offset), so unchanged state is re-notified every STATE_RESEND_S."""
    import asyncio

    class Agg:
        async def consolidated_state(self):
            return _state()

    class Server:
        def __init__(self):
            self.pushes = 0

        def get_characteristic(self, uuid):
            return MagicMock()

        def update_value(self, service, uuid):
            self.pushes += 1

    p = ble_peripheral.BoomboxBlePeripheral.__new__(ble_peripheral.BoomboxBlePeripheral)
    p._aggregator = Agg()
    p._server = Server()
    p._last_state_json = b'{"ok":false}'
    now = [0.0]
    ticks = [0]
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        now[0] += s
        ticks[0] += 1
        if ticks[0] >= 24:          # 24 polls × 0.5 s = 12 s simulated
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def run():
        try:
            await p._push_state_loop(interval_s=0.5, resend_s=5.0,
                                     clock=lambda: now[0])
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    # First poll sends (changed), then the unchanged state goes out again at
    # t=5 s and t=10 s — 3 notifies in 12 s, not 24 and not 1.
    assert p._server.pushes == 3
