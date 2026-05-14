"""Tests for the action dispatcher's high-level fire() entry point."""
from __future__ import annotations

import pytest

import actions


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
