"""boombox-usb-mount.sh runs as root but touches paths under the boombox
user's home. Guard against regressions that let root follow a user-planted
symlink (e.g. ~/Music/.usb -> /etc/systemd/system)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "boombox-usb-mount.sh"
USER_PATHS = ("$USB_LINKS_DIR", "$VIDEO_USB_LINKS_DIR", "$LINK", "$VIDEO_LINK")


def _code_lines() -> list[str]:
    return [ln.strip() for ln in SCRIPT.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_user_home_paths_only_touched_as_user() -> None:
    for ln in _code_lines():
        if not re.match(r"(mkdir|chown|ln|rm)\b", ln):
            continue
        # A bare root mkdir/chown/ln/rm is fine only on root-owned paths.
        assert not any(p in ln for p in USER_PATHS), (
            f"root touches a user-controlled path: {ln!r}")


def test_user_steps_go_through_as_user() -> None:
    lines = _code_lines()
    assert any(ln.startswith("as_user mkdir -p \"$USB_LINKS_DIR\"") for ln in lines)
    assert any(ln.startswith("as_user ln -snf") and "$LINK" in ln for ln in lines)
    assert any(ln.startswith("as_user rm -f") for ln in lines)
    assert "runuser -u \"$BBX_USER\" --" in SCRIPT.read_text()
