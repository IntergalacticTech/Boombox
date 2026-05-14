# services/tests/test_updater_e2e.py
"""End-to-end: drive the Installer state machine against a synthetic
/opt/boombox/ in a tempdir, with real symlink-swap behaviour. The Steps
protocol is implemented by TempdirSteps — real symlink moves, fake
build/verify — so this runs anywhere (no git, no npm, no systemd).

This is the safety net for the state-machine + symlink-swap interaction
that the pure-logic unit tests in test_updater_installer.py can't exercise.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from boombox_updater.installer import Installer, StepResult
from boombox_updater.state import AttemptResult


class TempdirSteps:
    """Real symlink swap behaviour against a tempdir, fake build/verify."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._releases = root / "releases"
        self._current = root / "current"
        self._previous = root / "previous"
        self._releases.mkdir(parents=True, exist_ok=True)
        self.verify_outcomes: List[StepResult] = []  # mutated per test
        self.verify_calls = 0

    # ---- helpers used by tests ----

    def stage_release(self, ref: str) -> None:
        (self._releases / ref).mkdir(parents=True, exist_ok=True)
        (self._releases / ref / "VERSION").write_text(ref + "\n")

    def point_current_at(self, ref: str) -> None:
        if self._current.exists() or self._current.is_symlink():
            self._current.unlink()
        self._current.symlink_to(Path("releases") / ref)

    def point_previous_at(self, ref: str) -> None:
        if self._previous.exists() or self._previous.is_symlink():
            self._previous.unlink()
        self._previous.symlink_to(Path("releases") / ref)

    def current_target(self) -> str:
        return self._current.resolve().name

    def previous_target(self) -> Optional[str]:
        if not self._previous.is_symlink():
            return None
        return self._previous.resolve().name

    # ---- Steps protocol ----

    def do_fetch(self, ref: str) -> StepResult:
        self.stage_release(ref)
        return StepResult.OK

    def do_build(self, ref: str) -> StepResult:
        return StepResult.OK

    def do_preflight(self, ref: str) -> StepResult:
        return StepResult.OK

    def do_swap(self, ref: str) -> StepResult:
        # Capture current as the new previous, then point current at ref —
        # mirrors install/apply-release.sh's `swap` subcommand.
        if self._current.is_symlink():
            old = self._current.resolve().relative_to(self._root)
            if self._previous.exists() or self._previous.is_symlink():
                self._previous.unlink()
            self._previous.symlink_to(old)
        if self._current.exists() or self._current.is_symlink():
            self._current.unlink()
        self._current.symlink_to(Path("releases") / ref)
        return StepResult.OK

    def do_restart(self) -> StepResult:
        return StepResult.OK

    def do_verify(self) -> StepResult:
        self.verify_calls += 1
        if self.verify_outcomes:
            return self.verify_outcomes.pop(0)
        return StepResult.OK

    def do_revert(self) -> StepResult:
        # Swap current <-> previous — mirrors apply-release.sh's `revert`.
        prev = self._previous.resolve().relative_to(self._root)
        cur = self._current.resolve().relative_to(self._root)
        self._current.unlink()
        self._current.symlink_to(prev)
        self._previous.unlink()
        self._previous.symlink_to(cur)
        return StepResult.OK

    def do_revert_verify(self) -> StepResult:
        return StepResult.OK

    def do_cleanup_failed_release(self, ref: str) -> None:
        # Mirrors `apply-release.sh cleanup` — rm -rf the release dir.
        shutil.rmtree(self._releases / ref, ignore_errors=True)


def test_happy_path(tmp_path: Path) -> None:
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")

    out = Installer(steps=steps, current_ref="v0.4.0",
                    previous_ref=None).install("v0.4.1")

    assert out.result == AttemptResult.OK
    assert steps.current_target() == "v0.4.1"
    assert steps.previous_target() == "v0.4.0"


def test_smoke_failure_no_previous_stays_put(tmp_path: Path) -> None:
    """With no `previous` safety net, a smoke-test failure leaves the bad
    release as `current` — the Installer reports SMOKE_FAILED and does not
    call do_revert (there is nothing to revert to)."""
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")
    steps.verify_outcomes = [StepResult.FAIL]

    out = Installer(steps=steps, current_ref="v0.4.0",
                    previous_ref=None).install("v0.4.1")

    assert out.result == AttemptResult.SMOKE_FAILED
    assert steps.current_target() == "v0.4.1"  # bad release stays — no net


def test_smoke_failure_with_previous_rolls_back(tmp_path: Path) -> None:
    """With a `previous` safety net, a smoke-test failure rolls `current`
    back to the release that was active before this install."""
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.3.9")
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")
    steps.point_previous_at("v0.3.9")
    steps.verify_outcomes = [StepResult.FAIL]

    out = Installer(steps=steps, current_ref="v0.4.0",
                    previous_ref="v0.3.9").install("v0.4.1")

    assert out.result == AttemptResult.ROLLED_BACK
    # do_swap set previous=v0.4.0, current=v0.4.1; do_revert flipped current
    # back to v0.4.0 (the release active before this install).
    assert steps.current_target() == "v0.4.0"
    # do_revert is a true current<->previous swap: after rolling back,
    # `previous` holds the bad release that was just backed out.
    assert steps.previous_target() == "v0.4.1"


def test_two_bad_releases_lands_on_last_known_good(tmp_path: Path) -> None:
    """Two bad installs in a row, each with a `previous` safety net. Because
    do_swap always re-captures the current (good) release into `previous`
    before pointing `current` at the new release, each revert lands back on
    the release that was current when that install started. v0.4.0 stays
    good through both — even though after the first rollback `previous`
    points at the bad v0.4.1."""
    steps = TempdirSteps(tmp_path)
    steps.stage_release("v0.3.9")
    steps.stage_release("v0.4.0")
    steps.point_current_at("v0.4.0")
    steps.point_previous_at("v0.3.9")

    # First bad install — rolls back to v0.4.0.
    steps.verify_outcomes = [StepResult.FAIL]
    out1 = Installer(steps=steps, current_ref="v0.4.0",
                     previous_ref="v0.3.9").install("v0.4.1")
    assert out1.result == AttemptResult.ROLLED_BACK
    assert steps.current_target() == "v0.4.0"

    # Second bad install. On disk `previous` now points at the bad v0.4.1,
    # but do_swap re-captures the good v0.4.0 before the revert — so this
    # rolls back to v0.4.0 again.
    steps.verify_outcomes = [StepResult.FAIL]
    out2 = Installer(steps=steps, current_ref="v0.4.0",
                     previous_ref="v0.4.1").install("v0.4.2")
    assert out2.result == AttemptResult.ROLLED_BACK
    assert steps.current_target() == "v0.4.0"
