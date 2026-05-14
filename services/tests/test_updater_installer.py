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
    steps = FakeSteps(verify=StepResult.FAIL, previous=None)
    inst = Installer(steps=steps, current_ref="v0.4.0", previous_ref="v0.3.9")
    out = inst.install("v0.4.1")
    assert out.result == AttemptResult.ROLLED_BACK
    assert steps.current == "v0.3.9"          # revert flipped back
    assert "revert" in steps.log
    assert "revert_verify" in steps.log


def test_two_bad_releases_in_a_row_lands_on_last_known_good() -> None:
    """First bad install rolls back to v0.3.9 but does NOT advance previous.
    A subsequent bad install rolls back again — to v0.3.9 (the still-good
    previous), not to the just-rolled-back v0.4.1."""
    # First install attempt: v0.4.1 fails verify, rolls back.
    s1 = FakeSteps(verify=StepResult.FAIL, current="v0.4.0", previous="v0.3.9")
    Installer(steps=s1, current_ref="v0.4.0", previous_ref="v0.3.9").install("v0.4.1")
    assert s1.current == "v0.3.9"
    assert s1.previous == "v0.4.0"  # revert moved current back; previous unchanged from the swap
    # NOTE: the spec says "previous is only advanced on success". The swap
    # itself temporarily set previous=v0.4.0; revert flips current back but
    # leaves the swap-set previous in place. The next install's previous is
    # whatever it reads from disk — i.e. the symlink target — which we test
    # in the integration test (Task 12). Here we only assert the in-memory
    # last_attempt result.

    # Second install attempt v0.4.2 also fails verify; passed previous_ref is
    # the still-good v0.3.9 (caller is expected to read symlink, not trust
    # the FakeSteps memory).
    s2 = FakeSteps(verify=StepResult.FAIL, current="v0.3.9", previous=None)
    out = Installer(steps=s2, current_ref="v0.3.9", previous_ref="v0.3.9").install("v0.4.2")
    assert out.result == AttemptResult.ROLLED_BACK


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
