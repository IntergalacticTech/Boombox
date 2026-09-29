"""Tests for which apply-release.sh each updater step runs.

build/preflight/swap must run the fetched TARGET release's script (so a
release's fixes to those steps apply on the update that ships them);
fetch/restart/verify/revert/cleanup run current's. The target script is
only trusted when it's an executable regular file inside releases/<ref>.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from boombox_updater.installer import StepResult
from boombox_updater.scripts import target_apply_script

_SCRIPT = Path(__file__).resolve().parent.parent / "boombox-updater.py"


def _load_updater():
    spec = importlib.util.spec_from_file_location("boombox_updater_service", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


upd = _load_updater()

REF = "v1.2.3"


def _script(path: Path, name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "RAN {name} $*"\n')
    path.chmod(0o755)
    return path


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "boombox"
    cur_rel = root / "releases" / "v1.0.0"
    _script(cur_rel / "install" / "apply-release.sh", "current")
    (root / "current").symlink_to("releases/v1.0.0")
    monkeypatch.setattr(upd, "REPO_ROOT", root)
    monkeypatch.setattr(upd, "APPLY", root / "current" / "install" / "apply-release.sh")
    return root


def _ran(log: Path) -> list[str]:
    return [ln for ln in log.read_text().splitlines() if ln.startswith("RAN ")]


def test_build_preflight_swap_use_target_script(root: Path, tmp_path: Path):
    _script(root / "releases" / REF / "install" / "apply-release.sh", "target")
    log = tmp_path / "log.txt"
    steps = upd.ShellSteps(log_path=log)
    assert steps.do_fetch(REF) == StepResult.OK
    assert steps.do_build(REF) == StepResult.OK
    assert steps.do_preflight(REF) == StepResult.OK
    assert steps.do_swap(REF) == StepResult.OK
    assert steps.do_restart() == StepResult.OK
    assert steps.do_verify() == StepResult.OK
    assert steps.do_revert() == StepResult.OK
    steps.do_cleanup_failed_release(REF)
    assert _ran(log) == [
        f"RAN current fetch {REF}",
        f"RAN target build {REF}",
        f"RAN target preflight {REF}",
        f"RAN target swap {REF}",
        "RAN current restart",
        "RAN current verify",
        "RAN current revert",
        f"RAN current cleanup {REF}",
    ]


def test_falls_back_to_current_when_target_lacks_script(root: Path, tmp_path: Path):
    (root / "releases" / REF).mkdir(parents=True)  # older release layout
    log = tmp_path / "log.txt"
    steps = upd.ShellSteps(log_path=log)
    assert steps.do_build(REF) == StepResult.OK
    assert _ran(log) == [f"RAN current build {REF}"]


def test_target_script_failure_is_step_failure(root: Path, tmp_path: Path):
    s = root / "releases" / REF / "install" / "apply-release.sh"
    s.parent.mkdir(parents=True)
    s.write_text("#!/bin/sh\nexit 3\n")
    s.chmod(0o755)
    steps = upd.ShellSteps(log_path=tmp_path / "log.txt")
    assert steps.do_preflight(REF) == StepResult.FAIL


# ---- target_apply_script validation ----

def test_target_apply_script_returns_resolved_script(root: Path):
    s = _script(root / "releases" / REF / "install" / "apply-release.sh", "t")
    assert target_apply_script(root, REF) == s.resolve()


@pytest.mark.parametrize("ref", ["../v1.0.0", "-rf", "", "main", "v1/../x", "a" * 6])
def test_target_apply_script_rejects_invalid_ref(root: Path, ref: str):
    assert target_apply_script(root, ref) is None


def test_target_apply_script_rejects_symlinked_script_escape(root: Path, tmp_path: Path):
    outside = _script(tmp_path / "evil" / "apply-release.sh", "evil")
    inst = root / "releases" / REF / "install"
    inst.mkdir(parents=True)
    (inst / "apply-release.sh").symlink_to(outside)
    assert target_apply_script(root, REF) is None


def test_target_apply_script_rejects_symlinked_release_dir(root: Path, tmp_path: Path):
    _script(tmp_path / "elsewhere" / "install" / "apply-release.sh", "evil")
    (root / "releases" / REF).symlink_to(tmp_path / "elsewhere")
    assert target_apply_script(root, REF) is None


def test_target_apply_script_rejects_release_dir_aliasing_another(root: Path):
    # releases/<ref> -> releases/v1.0.0 stays inside the tree but isn't <ref>
    (root / "releases" / REF).symlink_to(root / "releases" / "v1.0.0")
    assert target_apply_script(root, REF) is None


def test_target_apply_script_rejects_directory_and_non_executable(root: Path):
    inst = root / "releases" / REF / "install"
    (inst / "apply-release.sh").mkdir(parents=True)
    assert target_apply_script(root, REF) is None
    os.rmdir(inst / "apply-release.sh")
    (inst / "apply-release.sh").write_text("#!/bin/sh\n")
    (inst / "apply-release.sh").chmod(0o644)
    assert target_apply_script(root, REF) is None


def test_target_apply_script_missing_release(root: Path):
    assert target_apply_script(root, REF) is None
    assert target_apply_script(root / "nope", REF) is None
