"""Install state machine.

State transitions are pure logic; the actual filesystem / subprocess work
lives behind the Steps protocol (see services/boombox-updater.py for the
real implementation that calls install/apply-release.sh).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

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
        on_step: Optional[Callable[[InstallStep], None]] = None,
    ) -> None:
        self._steps = steps
        self._current = current_ref
        self._previous = previous_ref
        self._on_step = on_step

    def _emit(self, step: InstallStep) -> None:
        if self._on_step is not None:
            self._on_step(step)

    def install(self, ref: str) -> InstallOutcome:
        # 1. Fetch
        self._emit(InstallStep.FETCHING)
        if self._steps.do_fetch(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.FETCH_FAILED, "git clone failed")

        # 2. Build
        self._emit(InstallStep.BUILDING)
        if self._steps.do_build(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.BUILD_FAILED, "build failed")

        # 3. Preflight (still safe to abort — no symlinks moved yet).
        self._emit(InstallStep.PREFLIGHT)
        if self._steps.do_preflight(ref) != StepResult.OK:
            self._steps.do_cleanup_failed_release(ref)
            return InstallOutcome(AttemptResult.BUILD_FAILED, "preflight failed")

        # 4. Swap. After this, `current` points at the new release.
        self._emit(InstallStep.SWAPPING)
        if self._steps.do_swap(ref) != StepResult.OK:
            return self._attempt_revert("swap failed")

        # 5. Restart services.
        self._emit(InstallStep.RESTARTING)
        if self._steps.do_restart() != StepResult.OK:
            return self._attempt_revert("restart failed")

        # 6. Verify the new install is alive.
        self._emit(InstallStep.VERIFYING)
        if self._steps.do_verify() != StepResult.OK:
            return self._attempt_revert("smoke test failed")

        return InstallOutcome(AttemptResult.OK)

    def _attempt_revert(self, why: str) -> InstallOutcome:
        self._emit(InstallStep.REVERTING)
        if self._previous is None:
            return InstallOutcome(AttemptResult.SMOKE_FAILED, why)
        if self._steps.do_revert() != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert failed")
        if self._steps.do_revert_verify() != StepResult.OK:
            return InstallOutcome(AttemptResult.BROKEN, f"{why}; revert verify failed")
        return InstallOutcome(AttemptResult.ROLLED_BACK, why)
