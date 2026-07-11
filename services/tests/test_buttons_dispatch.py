"""Action dispatcher: routes transport actions through Mopidy or state-API based on current source."""
from __future__ import annotations

import boombox_buttons as bb
import pytest


class FakeMopidy:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
    async def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if method == "core.playback.get_state":
            return {"result": "playing"}
        if method == "core.tracklist.get_length":
            return {"result": 1}
        return {"result": None}


class FakeStateApi:
    def __init__(self, source="mopidy", status="playing"):
        self.source = source
        self.status = status
        self.calls: list[tuple[str, dict]] = []
    async def current_source(self):
        return self.source
    async def active_external(self):
        # Mirrors StateApi.active_external: only returns non-Mopidy labels
        # when the player is actually playing or paused.
        if self.source in (None, "mopidy"):
            return None
        if self.status not in ("playing", "paused"):
            return None
        return self.source
    async def control(self, action):
        self.calls.append(("control", {"action": action}))


@pytest.mark.asyncio
async def test_play_pause_routes_to_mopidy_when_source_is_mopidy():
    m, s = FakeMopidy(), FakeStateApi(source="mopidy")
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None)
    await d.dispatch("play_pause", "short_press")
    assert any(c[0] in ("core.playback.play", "core.playback.pause") for c in m.calls)
    assert s.calls == []


@pytest.mark.asyncio
async def test_play_pause_routes_to_state_api_when_external_source_live():
    m, s = FakeMopidy(), FakeStateApi(source="airplay")
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None)
    await d.dispatch("play_pause", "short_press")
    assert s.calls == [("control", {"action": "play-pause"})]
    assert m.calls == []


@pytest.mark.asyncio
async def test_unknown_action_logs_and_does_nothing():
    m, s = FakeMopidy(), FakeStateApi()
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None)
    await d.dispatch("nonsense_action", "short_press")
    assert m.calls == [] and s.calls == []


@pytest.mark.asyncio
async def test_disabled_button_in_config_does_not_dispatch():
    """Dispatcher receives a 'stop' event but config marks it disabled -> drop."""
    m, s = FakeMopidy(), FakeStateApi()
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None,
                     disabled={"stop"})
    await d.dispatch("stop", "short_press")
    assert m.calls == []
