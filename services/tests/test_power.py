"""Tests for the PowerManager state machine (services/power.py).

Everything the manager touches — audio, backlight, kiosk, poweroff — is an
injected coroutine, so these run with no hardware and no subprocesses.
"""
from __future__ import annotations

import asyncio
import json

import power
import pytest


class Calls:
    """Records which callbacks fired, in order, and can be told to explode."""

    def __init__(self, raising: set[str] | None = None):
        self.seen: list[str] = []
        self.raising = raising or set()

    def cb(self, name: str):
        async def _cb():
            self.seen.append(name)
            if name in self.raising:
                raise RuntimeError(f"{name} boom")
        return _cb


def _manager(tmp_path, calls: Calls, grace_s: float = 0.0) -> power.PowerManager:
    return power.PowerManager(
        stop_audio=calls.cb("stop_audio"),
        display_off=calls.cb("display_off"),
        display_on=calls.cb("display_on"),
        kiosk_home=calls.cb("kiosk_home"),
        poweroff=calls.cb("poweroff"),
        grace_s=grace_s,
        state_file=tmp_path / "power.json",
    )


@pytest.mark.asyncio
async def test_starts_awake(tmp_path):
    m = _manager(tmp_path, Calls())
    snap = m.snapshot()
    assert snap["state"] == "awake"
    assert snap["poweroff_at"] is None
    assert snap["since"] > 0


@pytest.mark.asyncio
async def test_sleep_runs_the_full_sequence(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls)
    snap = await m.sleep()
    assert snap["state"] == "asleep"
    # state flips first, then audio → kiosk → backlight (spec order).
    assert calls.seen == ["stop_audio", "kiosk_home", "display_off"]


@pytest.mark.asyncio
async def test_wake_turns_the_panel_back_on_without_resuming_audio(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls)
    await m.sleep()
    calls.seen.clear()
    snap = await m.wake()
    assert snap["state"] == "awake"
    assert calls.seen == ["display_on"]


@pytest.mark.asyncio
async def test_sleep_and_wake_are_idempotent(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls)
    await m.sleep()
    since = m.snapshot()["since"]
    calls.seen.clear()
    snap = await m.sleep()
    assert calls.seen == []                      # no second sequence
    assert snap["since"] == since                # and no clock reset

    await m.wake()
    calls.seen.clear()
    await m.wake()
    assert calls.seen == []


@pytest.mark.asyncio
async def test_toggle_alternates(tmp_path):
    m = _manager(tmp_path, Calls())
    assert (await m.toggle())["state"] == "asleep"
    assert (await m.toggle())["state"] == "awake"


@pytest.mark.asyncio
async def test_timer_arms_and_fires_poweroff_after_the_grace_period(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls, grace_s=0.01)
    snap = await m.sleep()
    assert snap["poweroff_at"] is not None
    await asyncio.sleep(0.08)
    assert "poweroff" in calls.seen


@pytest.mark.asyncio
async def test_wake_cancels_the_pending_poweroff(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls, grace_s=0.05)
    await m.sleep()
    await m.wake()
    assert m.snapshot()["poweroff_at"] is None
    await asyncio.sleep(0.12)
    assert "poweroff" not in calls.seen


@pytest.mark.asyncio
async def test_second_sleep_does_not_rearm_the_timer(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls, grace_s=0.05)
    await m.sleep()
    first = m.snapshot()["poweroff_at"]
    await asyncio.sleep(0.02)
    await m.sleep()
    assert m.snapshot()["poweroff_at"] == first


@pytest.mark.asyncio
async def test_grace_zero_disables_auto_poweroff(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls, grace_s=0)
    snap = await m.sleep()
    assert snap["poweroff_at"] is None
    await asyncio.sleep(0.05)
    assert "poweroff" not in calls.seen


@pytest.mark.asyncio
async def test_off_sleeps_then_powers_off_immediately(tmp_path):
    calls = Calls()
    m = _manager(tmp_path, calls, grace_s=999)
    snap = await m.off()
    assert snap["state"] == "asleep"
    assert calls.seen == ["stop_audio", "kiosk_home", "display_off", "poweroff"]
    # The grace timer must not also be pending after an explicit off().
    assert snap["poweroff_at"] is None


@pytest.mark.asyncio
async def test_a_raising_callback_does_not_abort_the_sequence(tmp_path):
    calls = Calls(raising={"stop_audio"})
    m = _manager(tmp_path, calls)
    snap = await m.sleep()
    assert snap["state"] == "asleep"
    assert calls.seen == ["stop_audio", "kiosk_home", "display_off"]


@pytest.mark.asyncio
async def test_missing_callbacks_are_tolerated(tmp_path):
    """Every hook is optional — an unwired boombox still tracks power state."""
    m = power.PowerManager(grace_s=0, state_file=tmp_path / "power.json")
    assert (await m.sleep())["state"] == "asleep"
    assert (await m.wake())["state"] == "awake"


@pytest.mark.asyncio
async def test_snapshot_is_persisted_on_every_transition(tmp_path):
    path = tmp_path / "nested" / "power.json"
    m = power.PowerManager(grace_s=0, state_file=path)
    await m.sleep()
    assert json.loads(path.read_text())["state"] == "asleep"
    await m.wake()
    assert json.loads(path.read_text())["state"] == "awake"


@pytest.mark.asyncio
async def test_startup_forces_display_on_when_the_file_says_asleep(tmp_path):
    path = tmp_path / "power.json"
    path.write_text(json.dumps({"state": "asleep", "since": 1.0, "poweroff_at": None}))
    calls = Calls()
    m = power.PowerManager(
        display_on=calls.cb("display_on"), grace_s=0, state_file=path,
    )
    await m.start()
    assert m.snapshot()["state"] == "awake"   # never resumes asleep
    assert calls.seen == ["display_on"]


@pytest.mark.asyncio
async def test_startup_is_quiet_when_the_file_says_awake(tmp_path):
    path = tmp_path / "power.json"
    path.write_text(json.dumps({"state": "awake", "since": 1.0, "poweroff_at": None}))
    calls = Calls()
    m = power.PowerManager(
        display_on=calls.cb("display_on"), grace_s=0, state_file=path,
    )
    await m.start()
    assert calls.seen == []


@pytest.mark.asyncio
async def test_startup_tolerates_a_missing_or_corrupt_file(tmp_path):
    calls = Calls()
    corrupt = tmp_path / "power.json"
    corrupt.write_text("{not json")
    m = power.PowerManager(display_on=calls.cb("display_on"), grace_s=0,
                           state_file=corrupt)
    await m.start()
    assert m.snapshot()["state"] == "awake"
    assert calls.seen == []


def test_default_state_file_honours_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    m = power.PowerManager(grace_s=0)
    assert m.state_file == tmp_path / "xdg" / "boombox" / "power.json"


def test_default_state_file_falls_back_to_local_state(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    m = power.PowerManager(grace_s=0)
    assert m.state_file == tmp_path / ".local" / "state" / "boombox" / "power.json"
