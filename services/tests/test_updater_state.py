"""Tests for boombox_updater.state — persisted runtime state."""
from __future__ import annotations

from pathlib import Path

import pytest
from boombox_updater.state import (
    EMPTY_STATE,
    AttemptResult,
    LastAttempt,
    State,
    StateStore,
)


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(state_dir=tmp_path)


def test_initial_state_is_empty(store: StateStore) -> None:
    assert store.load() == EMPTY_STATE


def test_round_trip(store: StateStore) -> None:
    new = State(
        installed_version="v0.4.1",
        available_version="v0.4.2",
        available_published_at="2026-05-13T01:23:45Z",
        last_check_ts=1747100000.0,
        last_attempt=LastAttempt(
            ts=1747103600.0, ref="v0.4.2",
            result=AttemptResult.OK, error=None, log_path="logs/2026-05-13.log",
        ),
        state_machine="idle",
    )
    store.save(new)
    assert store.load() == new


def test_partial_update(store: StateStore) -> None:
    """update() merges only the named fields."""
    store.save(EMPTY_STATE)
    store.update(installed_version="v0.4.1", state_machine="building")
    out = store.load()
    assert out.installed_version == "v0.4.1"
    assert out.state_machine == "building"
    assert out.available_version == EMPTY_STATE.available_version  # untouched


def test_log_dir_is_under_state(store: StateStore, tmp_path: Path) -> None:
    p = store.new_log_path(ref="v0.4.2")
    assert p.parent == tmp_path / "logs"
    assert "v0.4.2" in p.name
    # Must not exist yet — caller opens it.
    assert not p.exists()


def test_prune_logs_keeps_newest_n(store: StateStore, tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for i in range(15):
        (logs_dir / f"2026-05-{i:02d}-vX.log").write_text("x")
    store.prune_logs(keep=10)
    remaining = sorted(p.name for p in logs_dir.iterdir())
    assert len(remaining) == 10
    # Newest (highest day number) survive.
    assert remaining[0] == "2026-05-05-vX.log"


def test_atomic_save_no_leftover_tmp(store: StateStore, tmp_path: Path) -> None:
    store.save(EMPTY_STATE)
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.is_file() and p.name != "updater.json"]
    assert leftovers == []


def test_load_unreadable_file_returns_empty(store: StateStore, tmp_path: Path) -> None:
    """Broken symlink / permission errors fall through to EMPTY_STATE
    instead of crashing the service."""
    broken = tmp_path / "updater.json"
    broken.symlink_to(tmp_path / "does-not-exist" / "VERSION")
    assert store.load() == EMPTY_STATE
