"""Tests for the action dispatcher's high-level fire() entry point."""
from __future__ import annotations

import actions
import pytest


def _make_dispatcher(mopidy=None, state=None, kiosk=None,
                     recorder=None, display=None, sleep=None,
                     disabled=None):
    """Construct a Dispatcher with whatever clients the test supplies.
    Any client left None makes its handler a no-op (handlers null-guard).
    """
    return actions.Dispatcher(
        mopidy=mopidy, state=state, kiosk=kiosk,
        recorder=recorder, display=display, sleep=sleep,
        disabled=disabled or set(),
    )


@pytest.mark.asyncio
async def test_fire_unknown_action_returns_error():
    """Unknown action names produce {ok: False, error: 'unknown_action:<name>'}."""
    d = _make_dispatcher()
    result = await actions.fire(d, "no_such_action")
    assert result == {"ok": False, "error": "unknown_action:no_such_action"}


@pytest.mark.asyncio
async def test_fire_disabled_action_returns_disabled():
    """Actions listed in the dispatcher's `disabled` set are silently rejected
    with {ok: False, error: 'disabled'} before any handler runs."""
    d = _make_dispatcher(disabled={"play_pause"})
    result = await actions.fire(d, "play_pause")
    assert result == {"ok": False, "error": "disabled"}


@pytest.mark.asyncio
async def test_fire_known_action_returns_ok_when_handler_succeeds():
    """A known action whose handler runs to completion returns {ok: True}.
    `stop` is the simplest handler: it just calls mopidy.call() when mopidy
    is non-None. We pass a stub that records the call and returns {}."""
    calls = []

    class StubMopidy:
        async def call(self, method, params=None):
            calls.append((method, params))
            return {}

    d = _make_dispatcher(mopidy=StubMopidy())
    result = await actions.fire(d, "stop")
    assert result == {"ok": True}
    assert calls == [("core.playback.stop", None)]


@pytest.mark.asyncio
async def test_fire_handler_exception_returns_error():
    """If a handler raises, fire() catches it and returns
    {ok: False, error: 'handler_raised'} — the exception does not propagate."""
    class ExplodingMopidy:
        async def call(self, *a, **kw):
            raise RuntimeError("boom")

    d = _make_dispatcher(mopidy=ExplodingMopidy())
    result = await actions.fire(d, "stop")
    assert result == {"ok": False, "error": "handler_raised"}


@pytest.mark.asyncio
async def test_fire_passes_value_to_volume_handler():
    """fire(d, 'volume', 70) interprets 70 as a percent and forwards 0.7 to
    StateApi.volume_set (which uses a 0..1.5 fraction). 100 → 1.0."""
    calls = []

    class StubState:
        async def volume_set(self, v):
            calls.append(v)

    d = _make_dispatcher(state=StubState())
    result = await actions.fire(d, "volume", 70)
    assert result == {"ok": True}
    assert calls == [pytest.approx(0.7)]


@pytest.mark.asyncio
async def test_fire_mute_toggles_via_state_api():
    """fire(d, 'mute') calls StateApi.mute_toggle()."""
    calls = []

    class StubState:
        async def mute_toggle(self):
            calls.append("toggle")

    d = _make_dispatcher(state=StubState())
    result = await actions.fire(d, "mute")
    assert result == {"ok": True}
    assert calls == ["toggle"]


@pytest.mark.asyncio
async def test_source_action_routes_to_movies(monkeypatch):
    import actions
    calls = []

    async def fake_movies(d):
        calls.append("movies")

    monkeypatch.setitem(actions._HANDLERS, ("movies", "short_press"),
                        fake_movies)
    d = actions.Dispatcher(mopidy=None, state=None, kiosk=None,
                           recorder=None, display=None, sleep=None)
    result = await actions.fire(d, "source", "movies", source="test")
    assert result == {"ok": True}
    assert calls == ["movies"]


@pytest.mark.asyncio
async def test_source_action_aliases_library_to_mopidy(monkeypatch):
    import actions
    calls = []

    async def fake_library(d):
        calls.append("library")

    monkeypatch.setitem(actions._HANDLERS, ("library", "short_press"),
                        fake_library)
    d = actions.Dispatcher(mopidy=None, state=None, kiosk=None,
                           recorder=None, display=None, sleep=None)
    # both "library" and "mopidy" must route to the library handler
    await actions.fire(d, "source", "mopidy", source="test")
    await actions.fire(d, "source", "library", source="test")
    assert calls == ["library", "library"]


@pytest.mark.asyncio
async def test_source_action_unknown_value_returns_error():
    import actions
    d = actions.Dispatcher(mopidy=None, state=None, kiosk=None,
                           recorder=None, display=None, sleep=None)
    result = await actions.fire(d, "source", "nonsense", source="test")
    assert result == {"ok": False, "error": "handler_raised"}


# ---------- power button --------------------------------------------------

class PowerStateApi:
    """StateApi stub for the /power endpoints. `state` is what /power
    reports; `fail` makes every call raise (boombox-state down)."""

    def __init__(self, state="awake", fail=False, toggle_returns=True):
        self.state = state
        self.fail = fail
        self.toggle_returns = toggle_returns
        self.calls: list[str] = []
        self.polls = 0

    async def power_state(self):
        self.polls += 1
        if self.fail:
            raise RuntimeError("state api down")
        return {"state": self.state, "since": 1.0, "poweroff_at": None}

    async def power_toggle(self):
        self.calls.append("toggle")
        if self.fail:
            raise RuntimeError("state api down")
        return {"state": "asleep"} if self.toggle_returns else None

    async def power_wake(self):
        self.calls.append("wake")
        self.state = "awake"
        return {"state": "awake"}


class FakeDisplay:
    def __init__(self):
        self.calls: list[str] = []

    async def toggle(self):
        self.calls.append("toggle")


@pytest.mark.asyncio
async def test_power_short_press_toggles_via_state_api():
    s, disp = PowerStateApi(), FakeDisplay()
    d = _make_dispatcher(state=s, display=disp)
    await d.dispatch("power", "short_press")
    assert s.calls == ["toggle"]
    assert disp.calls == []


@pytest.mark.asyncio
async def test_power_short_press_falls_back_to_display_when_state_api_errors():
    s, disp = PowerStateApi(fail=True), FakeDisplay()
    d = _make_dispatcher(state=s, display=disp)
    await d.dispatch("power", "short_press")
    assert disp.calls == ["toggle"]


@pytest.mark.asyncio
async def test_power_short_press_falls_back_when_state_api_returns_nothing():
    """StateApi swallows HTTP errors and returns None — that's a failure too."""
    s, disp = PowerStateApi(toggle_returns=False), FakeDisplay()
    d = _make_dispatcher(state=s, display=disp)
    await d.dispatch("power", "short_press")
    assert disp.calls == ["toggle"]


@pytest.mark.asyncio
async def test_power_short_press_uses_display_when_there_is_no_state_client():
    disp = FakeDisplay()
    d = _make_dispatcher(state=None, display=disp)
    await d.dispatch("power", "short_press")
    assert disp.calls == ["toggle"]


@pytest.mark.asyncio
async def test_press_while_asleep_wakes_and_is_dropped():
    s = PowerStateApi(state="asleep")
    m_calls = []

    class StubMopidy:
        async def call(self, method, params=None):
            m_calls.append(method)
            return {}

    d = _make_dispatcher(state=s, mopidy=StubMopidy())
    await d.dispatch("stop", "short_press")
    assert s.calls == ["wake"]
    assert m_calls == []            # the press itself is swallowed


@pytest.mark.asyncio
async def test_power_press_while_asleep_is_not_swallowed():
    """The power button must still reach its own handler when asleep,
    otherwise it could never wake the unit through the normal path."""
    s = PowerStateApi(state="asleep")
    d = _make_dispatcher(state=s, display=FakeDisplay())
    await d.dispatch("power", "short_press")
    assert s.calls == ["toggle"]


@pytest.mark.asyncio
async def test_power_lookup_is_cached_across_a_burst_of_presses():
    s = PowerStateApi(state="awake")
    d = _make_dispatcher(state=s)
    for _ in range(5):
        await d.dispatch("next", "short_press")
    assert s.polls == 1


@pytest.mark.asyncio
async def test_state_client_without_power_support_is_treated_as_awake():
    """Older/foreign state stubs have no power_state(); don't drop presses."""
    m_calls = []

    class LegacyState:
        async def active_external(self):
            return None

    class StubMopidy:
        async def call(self, method, params=None):
            m_calls.append(method)
            return {}

    d = _make_dispatcher(state=LegacyState(), mopidy=StubMopidy())
    await d.dispatch("next", "short_press")
    assert m_calls == ["core.playback.next"]
