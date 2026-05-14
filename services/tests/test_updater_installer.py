"""Tests for boombox_updater.installer — the install state machine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from boombox_updater.installer import (
    InstallOutcome,
    InstallStep,
    Installer,
    StepResult,
)
from boombox_updater.state import AttemptResult


@dataclass
class FakeSteps:
    """Programmable Steps implementation. Each step returns the next entry
    from its list (default OK). Supports per-step overrides."""
    log: List[str] = field(default_factory=list)
    fetch: StepResult = StepResult.OK
    build: StepResult = StepResult.OK
    preflight: StepResult = StepResult.OK
    swap: StepResult = StepResult.OK
    restart: StepResult = StepResult.OK
    verify: StepResult = StepResult.OK
    revert: StepResult = StepResult.OK
    revert_verify: StepResult = StepResult.OK

    # Symlink "filesystem" — a dict updated by swap/revert so tests can assert.
    current: str = "v0.4.0"
    previous: Optional[str] = None

    def do_fetch(self, ref: str) -> StepResult:
        self.log.append(f"fetch {ref}")
        return self.fetch

    def do_build(self, ref: str) -> StepResult:
        self.log.append(f"build {ref}")
        return self.build

    def do_preflight(self, ref: str) -> StepResult:
        self.log.append(f"preflight {ref}")
        return self.preflight

    def do_swap(self, ref: str) -> StepResult:
        self.log.append(f"swap {ref}")
        if self.swap == StepResult.OK:
            self.previous = self.current
            self.current = ref
        return self.swap

    def do_restart(self) -> StepResult:
        self.log.append("restart")
        return self.restart

    def do_verify(self) -> StepResult:
        self.log.append("verify")
        return self.verify

    def do_revert(self) -> StepResult:
        self.log.append("revert")
        if self.revert == StepResult.OK and self.previous is not None:
            self.current = self.previous
        return self.revert

    def do_revert_verify(self) -> StepResult:
        self.log.append("revert_verify")
        return self.revert_verify

    def do_cleanup_failed_release(self, ref: str) -> None:
        self.log.append(f"cleanup {ref}")


def test_happy_path_advances_previous_and_returns_ok() -> None:
    steps = FakeSteps()
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.OK
    assert steps.current == "v0.4.1"
    assert steps.previous == "v0.4.0"
    assert steps.log == [
        "fetch v0.4.1", "build v0.4.1", "preflight v0.4.1",
        "swap v0.4.1", "restart", "verify",
    ]


def test_fetch_failure_does_not_swap() -> None:
    steps = FakeSteps(fetch=StepResult.FAIL)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.FETCH_FAILED
    assert steps.current == "v0.4.0"
    assert steps.previous is None
    assert "swap v0.4.1" not in steps.log
    assert "cleanup v0.4.1" in steps.log


def test_build_failure_cleans_up_release_dir() -> None:
    steps = FakeSteps(build=StepResult.FAIL)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.BUILD_FAILED
    assert steps.current == "v0.4.0"
    assert "cleanup v0.4.1" in steps.log


def test_smoke_failure_reverts() -> None:
    # Machine + Installer start consistent: current=v0.4.0, previous=v0.3.9.
    steps = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous="v0.3.9")
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref="v0.3.9")
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.ROLLED_BACK
    # do_swap set previous=v0.4.0, current=v0.4.1; do_revert flips current
    # back to the release that was running before this install (v0.4.0).
    assert steps.current == "v0.4.0"
    assert "revert" in steps.log
    assert "revert_verify" in steps.log


def test_two_bad_releases_in_a_row_lands_on_last_known_good() -> None:
    """Because do_swap always re-captures the current (good) release into
    `previous` before pointing `current` at the new release, a do_revert
    after a bad swap always lands back on the release that was running
    before this install. Two bad installs in a row therefore both land on
    the good release — even though after the first rollback `previous`
    points at the bad v0.4.1."""
    # First bad install: current=v0.4.0 (good), previous=v0.3.9.
    s1 = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous="v0.3.9")
    out1 = Installer(steps=s1, current_ref="v0.4.0",
                     previous_ref="v0.3.9").install("v0.4.1")
    assert out1.result == AttemptResult.ROLLED_BACK
    assert s1.current == "v0.4.0"   # back on the good release

    # Second bad install. On real disk, `previous` now points at the bad
    # v0.4.1 — but do_swap re-captures the good v0.4.0 before the revert,
    # so the second rollback still lands on v0.4.0.
    s2 = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous="v0.4.1")
    out2 = Installer(steps=s2, current_ref="v0.4.0",
                     previous_ref="v0.4.1").install("v0.4.2")
    assert out2.result == AttemptResult.ROLLED_BACK
    assert s2.current == "v0.4.0"   # STILL on the good release


def test_revert_failure_marks_broken() -> None:
    steps = FakeSteps(verify=StepResult.FAIL, revert_verify=StepResult.FAIL,
                     current="v0.4.0", previous="v0.3.9")
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref="v0.3.9")
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.BROKEN


def test_no_previous_means_no_revert_attempt() -> None:
    """If there's nothing to revert to, a verify failure stays as-is and
    is reported as smoke_failed (not rolled_back)."""
    steps = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous=None)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None)
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.SMOKE_FAILED
    assert "revert" not in steps.log


def test_install_step_enum_in_order() -> None:
    """Catches accidental reordering of the state machine."""
    assert list(InstallStep) == [
        InstallStep.FETCHING, InstallStep.BUILDING, InstallStep.PREFLIGHT,
        InstallStep.SWAPPING, InstallStep.RESTARTING, InstallStep.VERIFYING,
        InstallStep.REVERTING, InstallStep.IDLE,
    ]


def test_on_step_callback_receives_progress_sequence() -> None:
    seen: list[InstallStep] = []
    steps = FakeSteps()
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref=None,
                     on_step=seen.append)
    inst.install("v0.4.1")
    assert seen == [
        InstallStep.FETCHING, InstallStep.BUILDING, InstallStep.PREFLIGHT,
        InstallStep.SWAPPING, InstallStep.RESTARTING, InstallStep.VERIFYING,
    ]


def test_on_step_emits_reverting_on_smoke_failure() -> None:
    seen: list[InstallStep] = []
    steps = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous="v0.3.9")
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref="v0.3.9",
                     on_step=seen.append)
    inst.install("v0.4.1")
    assert InstallStep.REVERTING in seen
    assert seen.index(InstallStep.REVERTING) > seen.index(InstallStep.VERIFYING)
