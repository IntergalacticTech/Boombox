"""install/udev/99-boombox-knob.rules + its install.sh step: the knob gets a
stable /dev/boombox-knob that the boombox user can open without a re-login,
and the CYD's CH340 ports are left alone."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULE = REPO / "install" / "udev" / "99-boombox-knob.rules"
INSTALL = REPO / "install" / "install.sh"


def _rule_lines() -> list[str]:
    return [ln for ln in RULE.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def test_rule_matches_the_knob_and_names_it():
    (line,) = _rule_lines()
    assert 'SUBSYSTEM=="tty"' in line
    assert 'ATTRS{idVendor}=="303a"' in line
    assert 'ATTRS{idProduct}=="1001"' in line
    assert 'SYMLINK+="boombox-knob"' in line
    assert 'MODE="0660"' in line and 'GROUP="dialout"' in line
    assert 'OWNER="%BOOMBOX_USER%"' in line
    # Not add-only: a `udevadm trigger --action=change` must re-apply it.
    assert "ACTION" not in line
    assert "1a86" not in line            # never the CYD's CH340


def test_install_sh_substitutes_the_user_and_installs_the_rule():
    text = INSTALL.read_text()
    assert re.search(r'sed "s/%BOOMBOX_USER%/\$BOOMBOX_USER/g" '
                     r'"\$ACTIVE_SCRIPT_DIR/udev/99-boombox-knob.rules"', text)
    assert "/etc/udev/rules.d/99-boombox-knob.rules" in text
    assert "--subsystem-match=tty --action=change" in text
    assert re.search(r"for grp in [^;]*\bdialout\b", text)


def test_substituted_rule_has_no_placeholder_left():
    out = subprocess.run(["sed", "s/%BOOMBOX_USER%/dietpi/g", str(RULE)],
                         capture_output=True, text=True, check=True).stdout
    assert "%BOOMBOX_USER%" not in out
    assert 'OWNER="dietpi"' in out
