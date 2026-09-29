"""Tests for boombox_updater.scheduler — should_attempt_install()."""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from boombox_updater.config import UpdaterConfig
from boombox_updater.scheduler import (
    FAILED_RESULTS,
    InstallDecision,
    SkipReason,
    should_attempt_install,
)
from boombox_updater.state import AttemptResult, LastAttempt, StateStore


def cfg(**overrides) -> UpdaterConfig:
    base = dict(auto=True, channel="stable",
                window_start="03:00", window_duration_min=60)
    base.update(overrides)
    return UpdaterConfig(**base)


def at(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 13, hh, mm)


def test_inside_window_with_update_available_and_idle() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out == InstallDecision(install=True, reason=None)


def test_outside_window_skips() -> None:
    out = should_attempt_install(
        now=at(8, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.OUTSIDE_WINDOW


def test_window_wraps_midnight() -> None:
    # Window 23:00 -> 02:00 (180 min). 00:30 must still be inside.
    c = cfg(window_start="23:00", window_duration_min=180)
    out = should_attempt_install(
        now=at(0, 30), config=c,
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is True


def test_wrap_window_boundaries() -> None:
    # Window 23:00 -> 02:00 (180 min), spanning midnight.
    # Inclusive start (23:00), exclusive end (02:00), and points just
    # outside on each side.
    c = cfg(window_start="23:00", window_duration_min=180)

    def decide(hh: int, mm: int):
        return should_attempt_install(
            now=at(hh, mm), config=c,
            installed_version="v0.4.1", available_version="v0.4.2",
            playback_status="paused",
        )

    assert decide(22, 59).install is False   # just before start
    assert decide(23, 0).install is True     # inclusive start
    assert decide(1, 59).install is True     # inside, after midnight
    assert decide(2, 0).install is False     # exclusive end
    assert decide(2, 1).install is False     # just after end


def test_auto_disabled_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(auto=False),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.AUTO_DISABLED


def test_no_update_available_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.2", available_version="v0.4.2",
        playback_status="paused",
    )
    assert out.install is False
    assert out.reason == SkipReason.UP_TO_DATE


def test_playing_skips() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="playing",
    )
    assert out.install is False
    assert out.reason == SkipReason.PLAYBACK_ACTIVE


def test_window_boundary_inclusive_start_exclusive_end() -> None:
    # Window 03:00 -> 04:00. 03:00 inside, 04:00 outside.
    inside = should_attempt_install(
        now=at(3, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    outside = should_attempt_install(
        now=at(4, 0), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
    )
    assert inside.install is True
    assert outside.install is False


# ---- R6: never AUTO-retry a ref whose last attempt failed -----------------

def attempt(ref: str, result: AttemptResult) -> LastAttempt:
    return LastAttempt(ts=1.0, ref=ref, result=result, error="x", log_path="")


@pytest.mark.parametrize("result", [
    AttemptResult.ROLLED_BACK, AttemptResult.SMOKE_FAILED,
    AttemptResult.FETCH_FAILED, AttemptResult.BUILD_FAILED,
    AttemptResult.BROKEN,
])
def test_failed_ref_is_not_auto_retried(result: AttemptResult) -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
        last_attempt=attempt("v0.4.2", result),
    )
    assert out == InstallDecision(install=False,
                                  reason=SkipReason.PREVIOUSLY_FAILED)


def test_newer_ref_after_failure_is_attempted() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.3",
        playback_status="paused",
        last_attempt=attempt("v0.4.2", AttemptResult.ROLLED_BACK),
    )
    assert out == InstallDecision(install=True, reason=None)


@pytest.mark.parametrize("result", [AttemptResult.OK,
                                    AttemptResult.SKIPPED_PLAYBACK])
def test_non_failure_results_do_not_block(result: AttemptResult) -> None:
    assert result not in FAILED_RESULTS
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.1", available_version="v0.4.2",
        playback_status="paused",
        last_attempt=attempt("v0.4.2", result),
    )
    assert out.install is True


def test_up_to_date_still_wins_over_failed_memory() -> None:
    out = should_attempt_install(
        now=at(3, 15), config=cfg(),
        installed_version="v0.4.2", available_version="v0.4.2",
        playback_status="paused",
        last_attempt=attempt("v0.4.2", AttemptResult.ROLLED_BACK),
    )
    assert out.reason == SkipReason.UP_TO_DATE


def _load_updater_module():
    path = Path(__file__).resolve().parents[1] / "boombox-updater.py"
    spec = importlib.util.spec_from_file_location("boombox_updater_main", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scheduler_loop_skips_previously_failed_ref(tmp_path, monkeypatch) -> None:
    """Wiring: the real scheduler loop passes the persisted last_attempt,
    so a rolled-back ref is not re-installed on the next tick."""
    mod = _load_updater_module()
    store = StateStore(state_dir=tmp_path)
    store.update(installed_version="v0.4.1", available_version="v0.4.2",
                 last_attempt=attempt("v0.4.2", AttemptResult.ROLLED_BACK))

    class Runner:
        _store = store
        installs = 0

        async def install_now(self, ref=None, force=False):
            Runner.installs += 1

    async def no_playback() -> bool:
        return False

    async def stop_sleep(_s: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(mod, "load_config", lambda: cfg())
    monkeypatch.setattr(mod, "_playback_active", no_playback)
    monkeypatch.setattr(mod, "datetime",
                        type("D", (), {"now": staticmethod(lambda: at(3, 15))}))
    monkeypatch.setattr(mod.asyncio, "sleep", stop_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mod._scheduler_loop(Runner()))
    assert Runner.installs == 0

    # Same tick with a successful last attempt DOES install.
    store.update(last_attempt=attempt("v0.4.2", AttemptResult.OK))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mod._scheduler_loop(Runner()))
    assert Runner.installs == 1
