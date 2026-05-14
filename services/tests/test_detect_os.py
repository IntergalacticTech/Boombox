# services/tests/test_detect_os.py
"""Tests for install/session/detect-os.sh — OS detection for the
session-bootstrap dispatch. The function is bash; the test sources it in a
clean bash subprocess and asserts what detect_os prints."""
from __future__ import annotations

import subprocess
from pathlib import Path

DETECT_OS = (
    Path(__file__).resolve().parents[2] / "install" / "session" / "detect-os.sh"
)


def _detect(env_extra: dict[str, str]) -> str:
    """Source detect-os.sh in a clean-env bash subprocess, run detect_os,
    return its stdout. A clean env keeps a stray BOOMBOX_OS in the
    developer's shell from leaking into the test."""
    result = subprocess.run(
        ["bash", "-c", f'source "{DETECT_OS}"; detect_os'],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **env_extra},
        check=True,
    )
    return result.stdout.strip()


def test_dietpi_marker_present_returns_dietpi(tmp_path) -> None:
    marker = tmp_path / "dietpi"
    marker.mkdir()
    assert _detect({"BOOMBOX_DIETPI_MARKER": str(marker)}) == "dietpi"


def test_dietpi_marker_absent_returns_rpi_os(tmp_path) -> None:
    missing = tmp_path / "nope"  # never created
    assert _detect({"BOOMBOX_DIETPI_MARKER": str(missing)}) == "rpi-os"


def test_boombox_os_override_wins_over_marker(tmp_path) -> None:
    # Even with the dietpi marker present, an explicit BOOMBOX_OS wins.
    marker = tmp_path / "dietpi"
    marker.mkdir()
    assert _detect(
        {"BOOMBOX_DIETPI_MARKER": str(marker), "BOOMBOX_OS": "rpi-os"}
    ) == "rpi-os"


def test_boombox_os_override_can_force_dietpi(tmp_path) -> None:
    missing = tmp_path / "nope"
    assert _detect(
        {"BOOMBOX_DIETPI_MARKER": str(missing), "BOOMBOX_OS": "dietpi"}
    ) == "dietpi"
