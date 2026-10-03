"""Consolidated now-playing follows the boombox's live player.

When boombox-state reports an active external MPRIS player (a Jellyfin
movie in the kiosk, AirPlay, Spotify, Bluetooth) the consolidated state's
source/track/playing come from it, not from Mopidy's (often stale) current
track. Plus the kiosk view signal and its trip through the compact wire
form the BLE/USB remotes read."""
from __future__ import annotations

import json
import sys

import actions
import clients
import pytest
import remote_wire

# What boombox-state's GET /state said live on MarkII with a movie paused
# in the kiosk.
MOVIE = {
    "source": "chromium.instance118331", "label": "Browser",
    "status": "paused", "player": "chromium.instance118331",
    "track": {"title": "(500) Days of Summer", "artist": None, "album": None},
    "volume": 1.0, "position_ms": 1255463, "length_ms": 5704575, "ts": 1.0,
}

STALE_SONG = {
    "uri": "local:track:song.flac", "name": "Hey Jude",
    "artists": [{"name": "The Beatles"}], "album": {"name": "1967-1970"},
    "length": 431000,
}


def _impl():
    import boombox_remote  # noqa: F401 — loads the impl module
    return sys.modules["boombox_remote_impl"]


class FakeMopidy:
    def __init__(self, track=None, state="stopped", position_ms=0):
        self.track, self.state, self.position_ms = track, state, position_ms

    async def call(self, method, params=None):
        return {"result": {
            "core.playback.get_current_track": self.track,
            "core.playback.get_state": self.state,
            "core.playback.get_time_position": self.position_ms,
        }.get(method)}


class FakeState:
    def __init__(self, snap=None):
        self.snap = snap
        self.art_lookups: list[tuple] = []

    async def snapshot(self):
        return self.snap

    async def volume_get(self):
        return (0.5, False)

    async def karaoke_state(self):
        return False

    async def power(self):
        return "awake"

    async def album_art_url(self, artist, album, track):
        self.art_lookups.append((artist, album, track))
        return None


def _agg(snap=None, mopidy=None, clock=None):
    mod = _impl()
    agg = mod.StateAggregator(session=None, boombox_id="b", boombox_name="B")
    agg._mopidy = mopidy or FakeMopidy()
    agg._state = FakeState(snap)

    async def theme():
        return {}

    async def no_art(uri):
        return None

    agg._fetch_theme = theme
    agg._mopidy_art_url = no_art
    if clock is not None:
        agg.kiosk_view = mod.KioskView(clock=clock)
    return agg


def _ext(label, status="playing", title="Song", artist="Artist"):
    return {"source": label.lower(), "label": label, "status": status,
            "player": label.lower(),
            "track": {"title": title, "artist": artist, "album": "Album"},
            "position_ms": 61_500, "length_ms": 200_900}


# ---------------------------------------------------------------- source
@pytest.mark.asyncio
async def test_movie_in_kiosk_wins_over_stale_mopidy_track():
    agg = _agg(MOVIE, FakeMopidy(STALE_SONG, state="paused", position_ms=5000))
    d = await agg.consolidated_state()
    assert d["source"] == "movies"
    assert d["playing"] is False            # MPRIS says paused
    assert d["track"] == {
        "uri": None, "title": "(500) Days of Summer", "artist": None,
        "album": None, "duration_s": 5704, "position_s": 1255}
    assert d["art_url"] is None
    assert agg._state.art_lookups == []      # no iTunes lookup for a movie


@pytest.mark.asyncio
async def test_playing_movie_reports_playing():
    snap = dict(MOVIE, status="playing")
    d = await _agg(snap, FakeMopidy(STALE_SONG, state="stopped")).consolidated_state()
    assert d["source"] == "movies" and d["playing"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("label,kind", [("AirPlay", "airplay"),
                                        ("Spotify", "spotify"),
                                        ("Bluetooth", "bluetooth"),
                                        ("VLC", "vlc")])
async def test_external_labels_map_to_source_ids(label, kind):
    agg = _agg(_ext(label), FakeMopidy(STALE_SONG, state="stopped"))
    d = await agg.consolidated_state()
    assert d["source"] == kind
    assert d["playing"] is True
    assert d["track"]["title"] == "Song" and d["track"]["artist"] == "Artist"
    assert d["track"]["duration_s"] == 200 and d["track"]["position_s"] == 61
    # Music sources still get cover art from boombox-state's lookup.
    assert agg._state.art_lookups == [("Artist", "Album", "Song")]


@pytest.mark.asyncio
async def test_external_without_metadata_has_no_track():
    snap = _ext("Bluetooth")
    snap["track"] = None
    d = await _agg(snap, FakeMopidy(STALE_SONG, state="paused")).consolidated_state()
    assert d["source"] == "bluetooth" and d["track"] is None
    assert d["playing"] is True


@pytest.mark.asyncio
async def test_stopped_external_falls_back_to_mopidy():
    # A Browser MPRIS player that's merely listed (stopped) is not live.
    snap = dict(MOVIE, status="stopped")
    mop = FakeMopidy(STALE_SONG, state="playing", position_ms=12_345)
    d = await _agg(snap, mop).consolidated_state()
    assert d["source"] == "mopidy"
    assert d["playing"] is True
    assert d["track"]["title"] == "Hey Jude"
    assert d["track"]["artist"] == "The Beatles"
    assert d["track"]["duration_s"] == 431 and d["track"]["position_s"] == 12


@pytest.mark.asyncio
async def test_state_service_down_keeps_mopidy_behaviour():
    mop = FakeMopidy(STALE_SONG, state="paused")
    d = await _agg(None, mop).consolidated_state()
    assert d["source"] == "mopidy" and d["playing"] is False
    assert d["track"]["title"] == "Hey Jude"


@pytest.mark.asyncio
async def test_nothing_anywhere():
    d = await _agg({"source": None, "label": None, "status": "stopped",
                    "track": None}).consolidated_state()
    assert d["source"] is None and d["track"] is None and d["playing"] is False


# ------------------------------------------------------------ kiosk view
@pytest.mark.asyncio
async def test_view_defaults_to_player():
    d = await _agg().consolidated_state()
    assert d["view"] == "player"


@pytest.mark.asyncio
async def test_view_home_is_reported_and_expires_without_refresh():
    now = [100.0]
    agg = _agg(clock=lambda: now[0])
    agg.kiosk_view.set("home")
    assert (await agg.consolidated_state())["view"] == "home"
    now[0] += _impl().KioskView.HOME_TTL_S - 1
    assert (await agg.consolidated_state())["view"] == "home"
    now[0] += 2                     # the kiosk went quiet (left the SPA)
    assert (await agg.consolidated_state())["view"] == "player"
    agg.kiosk_view.set("player")
    assert (await agg.consolidated_state())["view"] == "player"


def test_kiosk_view_rejects_unknown_values():
    with pytest.raises(ValueError):
        _impl().KioskView().set("drawer")


@pytest.fixture
def view_app(tmp_path, monkeypatch):
    # Remote access off: the kiosk view must still work (the USB knob
    # reads it and isn't gated by the flag).
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"enabled": False}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(tmp_path / "peers.json"))
    import boombox_remote
    agg = _agg()
    return boombox_remote.create_app(aggregator=agg), agg


@pytest.mark.asyncio
async def test_kiosk_posts_view_without_a_token(view_app, aiohttp_client):
    app, agg = view_app
    client = await aiohttp_client(app)
    r = await client.post("/api/remote/kiosk/view", json={"view": "home"})
    assert r.status == 200
    assert (await r.json()) == {"ok": True, "view": "home"}
    assert agg.kiosk_view.get() == "home"
    # sendBeacon's text/plain body works too.
    r = await client.post("/api/remote/kiosk/view",
                          data=json.dumps({"view": "player"}),
                          headers={"Content-Type": "text/plain"})
    assert r.status == 200
    assert agg.kiosk_view.get() == "player"


@pytest.mark.asyncio
async def test_kiosk_view_rejects_bad_bodies(view_app, aiohttp_client):
    app, agg = view_app
    client = await aiohttp_client(app)
    r = await client.post("/api/remote/kiosk/view", json={"view": "drawer"})
    assert r.status == 400
    r = await client.post("/api/remote/kiosk/view", data="not json")
    assert r.status == 400
    assert agg.kiosk_view.get() == "player"


@pytest.mark.asyncio
async def test_kiosk_view_is_localhost_only(view_app, aiohttp_client):
    app, agg = view_app
    client = await aiohttp_client(app)
    r = await client.post("/api/remote/kiosk/view", json={"view": "home"},
                          headers={"X-Real-IP": "192.168.1.50"})
    assert r.status == 403
    assert agg.kiosk_view.get() == "player"


# -------------------------------------------------------- compact payload
@pytest.mark.asyncio
async def test_compact_payload_carries_view_source_and_movie_track():
    agg = _agg(dict(MOVIE, status="playing"), FakeMopidy(STALE_SONG))
    agg.kiosk_view.set("home")
    d = remote_wire.compact_state(await agg.consolidated_state())
    assert d["view"] == "home"
    assert d["source"] == "movies" and d["playing"] is True
    assert d["track"] == {"title": "(500) Days of Summer", "artist": None,
                          "album": None, "duration_s": 5704,
                          "position_s": 1255}


# ------------------------------------------------------ transport routing
class SnapState(clients.StateApi):
    """The real StateApi routing logic over a canned /state body."""

    def __init__(self, snap):
        super().__init__(session=None)
        self.snap = snap
        self.controls: list[str] = []

    async def snapshot(self):
        return self.snap

    async def control(self, action):
        self.controls.append(action)


class RecordingMopidy:
    def __init__(self):
        self.calls: list[str] = []

    async def call(self, method, params=None):
        self.calls.append(method)
        if method == "core.playback.get_state":
            return {"result": "paused"}
        if method == "core.tracklist.get_length":
            return {"result": 3}
        return {"result": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["playing", "paused"])
@pytest.mark.parametrize("action,control", [("play_pause", "play-pause"),
                                            ("next", "next")])
async def test_knob_transport_goes_to_the_movie(status, action, control):
    state = SnapState(dict(MOVIE, status=status))
    mop = RecordingMopidy()
    d = actions.Dispatcher(mopidy=mop, state=state, kiosk=None,
                           recorder=None, display=None, sleep=None)
    res = await actions.fire(d, action, source="knob:usb")
    assert res["ok"] is True
    assert state.controls == [control]
    assert not any(c.startswith("core.playback.") and c != "core.playback.get_state"
                   for c in mop.calls)


@pytest.mark.asyncio
async def test_knob_play_pause_goes_to_mopidy_when_movie_stopped():
    state = SnapState(dict(MOVIE, status="stopped"))
    mop = RecordingMopidy()
    d = actions.Dispatcher(mopidy=mop, state=state, kiosk=None,
                           recorder=None, display=None, sleep=None)
    await actions.fire(d, "play_pause", source="knob:usb")
    assert state.controls == []
    assert "core.playback.play" in mop.calls
