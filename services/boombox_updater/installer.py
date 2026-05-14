"""Install state machine.

State transitions are pure logic; the actual filesystem / subprocess work
lives behind the Steps protocol (see services/boombox-updater.py for the
real implementation that calls install/apply-release.sh).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, Protocol

from .state import AttemptResult


class StepResult(str, enum.Enum):
    OK = "ok"
    FAIL = "fail"


class InstallStep(str, enum.Enum):
    FETCHING = "fetching"
    BUILDING = "building"
    PREFLIGHT = "preflight"
    SWAPPING = "swapping"
    RESTARTING = "restarting"
    VERIFYING = "verifying"
    REVERTING = "reverting"
    IDLE = "idle"


class Steps(Protocol):
    def do_fetch(self, ref: str) -> StepResult: ...
    def do_build(self, ref: str) -> StepResult: ...
    def do_preflight(self, ref: str) -> StepResult: ...
    def do_swap(self, ref: str) -> StepResult: ...
    def do_restart(self) -> StepResult: ...
    def do_verify(self) -> StepResult: ...
    def do_revert(self) -> StepResult: ...
    def do_revert_verify(self) -> StepResult: ...
    def do_cleanup_failed_release(self, ref: str) -> None: ...


@dataclass(frozen=True)
class InstallOutcome:
    result: AttemptResult
    error: Optional[str] = None


class Installer:
    def __init__(
        self,
        *,
        steps: Steps,
        current_ref: str,
        previous_ref: Optional[str],
    ) -> None:
        self._steps = steps
        self._current = current_ref
        self._previous = previous_ref

    def install(self, ref: str) -> InstallOutcome:
        # 1. Fetch
        if self._steps.do_fetch(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.FETCH_FAILED, "git clone failed")

        # 2. Build
        if self._steps.do_build(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.BUILD_FAILED, "build failed")

        # 3. Preflight (still safe to abort — no symlinks moved yet).
        if self._steps.do_preflight(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.BUILD_FAILED, "preflight failed")

        # 4. Swap. After this, `current` points at the new release.
        if self._steps.do_swap(ref) != StepResult.OK:
            return self._attempt_revert("swap failed")

        # 5. Restart services.
        if self._steps.do_restart() != StepResult.OK:
            return self._attempt_revert("restart failed")

        # 6. Verify the new install is alive.
        if self._steps.do_verify() != StepResult.OK:
            return self._attempt_revert("smoke test failed")

        return InstallOutcome(AttemptResult.OK)

    def _attempt_revert(self, why: str) -> InstallOutcome:
        # Nothing to fall back to — leave the (broken) install in place and
        # report the smoke failure rather than a rollback.
        if self._previous is None:
            return InstallOutcome(AttemptResult.SMOKE_FAILED, why)

        # Roll the release symlink back. do_revert() unwinds the just-applied
        # swap; do_swap() then re-points current at the last known-good
        # release so we land on `previous`, not on the failed swap target.
        if self._steps.do_revert() != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert failed")
        if self._steps.do_swap(self._previous) != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert failed")

        # Confirm the rolled-back release actually comes up healthy.
        if self._steps.do_revert_verify() != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert verify failed")
        return InstallOutcome(AttemptResult.ROLLED_BACK, why)
