"""Boot-ordering sanity for the user units in install/systemd/user/.

A unit WantedBy=default.target is implicitly ordered *before*
default.target, unless it says After=default.target itself. If such a
unit is After= a unit that IS After=default.target, systemd finds an
ordering cycle at boot and silently drops one job (it dropped
boombox-resume on MarkII, 2026-09-29) — manual restarts never show it.
"""
from __future__ import annotations

import configparser
from pathlib import Path

UNIT_DIR = Path(__file__).resolve().parents[2] / "install" / "systemd" / "user"


def _load(path: Path) -> dict[str, set[str]]:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # type: ignore[assignment,method-assign]
    cp.read(path)
    def words(section: str, key: str) -> set[str]:
        return set(cp.get(section, key, fallback="").split())
    return {"after": words("Unit", "After"), "wanted_by": words("Install", "WantedBy")}


def test_no_default_target_ordering_cycles():
    units = {p.name: _load(p) for p in UNIT_DIR.glob("*.service")}
    after_default = {n for n, u in units.items() if "default.target" in u["after"]}
    offenders = []
    for name, u in units.items():
        if "default.target" not in u["wanted_by"] or name in after_default:
            continue  # not ordered before default.target
        for dep in u["after"] & after_default:
            offenders.append(f"{name} After={dep}")
    assert not offenders, "ordering cycles via default.target: " + ", ".join(offenders)
