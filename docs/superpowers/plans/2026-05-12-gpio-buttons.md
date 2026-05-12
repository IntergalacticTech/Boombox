# GPIO buttons + rotary encoder — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the minimal `boombox-buttons.py` (5 actions) with a full physical control surface: 17 buttons + 1 rotary encoder with push, fully described by `docs/superpowers/specs/2026-05-12-gpio-buttons-design.md`. Every action independently disable-able; pin map editable from `/etc/boombox/buttons.json` and from a new "Buttons" panel in the touchscreen Settings drawer.

**Architecture:** Single-file Python service (`services/boombox-buttons.py`) following the project's existing pattern — internal organization via sections, not packages. Service hosts an aiohttp server on `:6683` (nginx-fronted at `/api/buttons/*`) for the Learn/Test/Config endpoints. All action routing flows through three already-existing surfaces: Mopidy RPC at `:6680/mopidy/rpc`, the boombox-state aggregator at `:6681/control/*`, `/volume`, `/karaoke/*`, and the kiosk Chromium DevTools endpoint at `:9222`. Pi system changes (disable unused SPI + UART0; remove two legacy `/usr/local/bin/*.py` services) free the GPIO pins this design needs.

**Tech Stack:** Python 3.11 with `gpiod` (libgpiod v2) for GPIO, `aiohttp` for HTTP, `watchdog` for config hot-reload, `pytest` for pure-logic tests. React 19 + TypeScript + Vite on the frontend. Wayland + `wlr-randr` for backlight control. systemd user units. RPi 5 + HiFiBerry DAC+ Pro.

---

## File structure

```
services/
  boombox-buttons.py          # rewrite — full service in one file (~1000 LOC target)
  boombox-state.py            # add /volume/mute endpoint
  tests/                      # new
    __init__.py
    test_buttons_config.py    # JSON schema, defaults merge, hot-reload signal
    test_buttons_press.py     # short/long-press classifier state machine
    test_buttons_encoder.py   # quadrature decode, push detection
    test_buttons_dispatch.py  # action routing, routing-by-source

install/
  config/
    buttons.json              # rewrite — full 17-action schema, all enabled
    usercfg.txt               # add `dtparam=spi=off`, `dtparam=uart0=off`
    nginx-boombox-common.conf # add `/api/buttons/` route
    requirements.txt          # add watchdog, pytest
  systemd/user/
    boombox-buttons.service   # ExecStart unchanged; add Reload signal handling note
  install.sh                  # legacy-handler removal, idempotent
  legacy/
    remove-legacy-buttons.sh  # new helper — disable + delete legacy units/files

ui/src/lib/
  SettingsDrawer.tsx          # add <ButtonsPanel/>
  ButtonsPanel.tsx            # new — config view + learn/test flows
  buttonsApi.ts               # new — typed client for /api/buttons/*

ui/src/overlays/              # new dir
  QrOverlay.tsx               # Web button — QR code + URL + creds
  SleepOsd.tsx                # sleep-timer toast
  RecordIndicator.tsx         # pulsing REC dot
  SourceInstructionOverlay.tsx # AirPlay / Spotify pairing instructions
  OverlayRoot.tsx             # mounts overlays from boombox-state events

docs/
  SERVICES.md                 # update boombox-buttons row, add :6683 + new endpoints
  ARCHITECTURE.md             # update port table
```

---

### Task 1: Pi system cleanup — disable SPI/UART0, remove legacy handlers

**Why first:** The 13 GPIOs free today aren't enough for the 20-pin budget. SPI + UART0 reclaim closes the gap. The legacy `boombox-button-handler` is actively holding 8 of our target GPIOs and will conflict the moment the new service starts.

**Files:**
- Modify: `install/config/usercfg.txt`
- Create: `install/legacy/remove-legacy-buttons.sh`
- Modify: `install/install.sh` (idempotent legacy removal step)

- [ ] **Step 1: Add SPI/UART0 disable lines to usercfg.txt**

Edit `install/config/usercfg.txt` — append at the end:

```
# Reclaim GPIO 7-11 + 14-15 for the boombox-buttons control surface. SPI and
# UART0 are unused by anything in this build (verified 2026-05-12: lsof on
# /dev/spidev*, /dev/serial0, /dev/ttyAMA0 is empty; the running serial-getty
# is on ttyAMA10, the Pi 5 dedicated debug UART, not GPIO 14/15). Re-enable
# either dtparam below if a future feature needs it, but you'll have to
# reassign whichever button pin lands on the conflict.
dtparam=spi=off
dtparam=uart0=off
```

- [ ] **Step 2: Create the legacy removal script**

Create `install/legacy/remove-legacy-buttons.sh`:

```bash
#!/usr/bin/env bash
# Disable and remove the two pre-repo services running on the Pi:
#   boombox-button-handler.service  — older GPIO handler at /usr/local/bin/
#   boombox-mode-manager.service    — older source orchestrator at /usr/local/bin/
# Both are superseded by services/boombox-buttons.py and services/boombox-orchestrator.py.
# Idempotent: safe to re-run.

set -euo pipefail

LEGACY_SERVICES=(
  boombox-button-handler.service
  boombox-mode-manager.service
)
LEGACY_BINARIES=(
  /usr/local/bin/boombox-button-handler.py
  /usr/local/bin/boombox-mode-manager.py
)

for svc in "${LEGACY_SERVICES[@]}"; do
  if systemctl list-unit-files --no-pager 2>/dev/null | grep -q "^${svc}"; then
    echo "[legacy] disabling ${svc}"
    sudo systemctl disable --now "${svc}" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${svc}"
  fi
done

for bin in "${LEGACY_BINARIES[@]}"; do
  if [[ -e "${bin}" ]]; then
    echo "[legacy] removing ${bin}"
    sudo rm -f "${bin}"
  fi
done

sudo systemctl daemon-reload
echo "[legacy] done"
```

Make it executable: `chmod +x install/legacy/remove-legacy-buttons.sh`.

- [ ] **Step 3: Hook the legacy removal into install.sh**

Find the section after group memberships and before the venv creation in `install/install.sh` (around line 80, before "DAC overlay" step). Insert:

```bash
# ---------------------------------------------------------------------------
# 3b. Remove legacy pre-repo services that conflict with this codebase.
# ---------------------------------------------------------------------------
if [[ -x "$SCRIPT_DIR/legacy/remove-legacy-buttons.sh" ]]; then
  log "removing legacy /usr/local/bin/boombox-* services (idempotent)"
  "$SCRIPT_DIR/legacy/remove-legacy-buttons.sh"
fi
```

- [ ] **Step 4: Deploy and run on Pi**

From the Mac:

```bash
./pi deploy install/ /opt/boombox/install/
./pi ssh "/opt/boombox/install/legacy/remove-legacy-buttons.sh"
./pi deploy install/config/usercfg.txt /opt/boombox/install/config/usercfg.txt
./pi ssh "sudo install -m 0644 /opt/boombox/install/config/usercfg.txt /boot/firmware/usercfg.txt"
./pi ssh "sudo reboot"
```

Wait 30 seconds for reboot, then:

```bash
./pi ssh 'pinctrl get 7 8 9 10 11 14 15'
```

Expected: every pin shows `no` (no function) or `ip` (input, unconfigured), not `a0/a3/a4` (alternate functions). Sample expected output:

```
 7: ip    pu | hi // GPIO7 = input
 8: ip    pu | hi // GPIO8 = input
 9: ip    pd | -- // GPIO9 = input
10: ip    pd | -- // GPIO10 = input
11: ip    pd | -- // GPIO11 = input
14: ip    pu | -- // GPIO14 = input
15: ip    pu | -- // GPIO15 = input
```

- [ ] **Step 5: Confirm legacy services gone**

```bash
./pi ssh 'systemctl list-unit-files | grep -E "(button-handler|mode-manager)"; ls /usr/local/bin/boombox-button-handler.py /usr/local/bin/boombox-mode-manager.py 2>&1 | head -5'
```

Expected: no output for the first command, "No such file or directory" for both binaries.

- [ ] **Step 6: Commit**

```bash
git add install/config/usercfg.txt install/legacy/remove-legacy-buttons.sh install/install.sh
git commit -m "buttons(pi): reclaim GPIO 7-11/14-15, remove legacy /usr/local handlers

Disables unused SPI + UART0 in usercfg.txt to free 7 GPIOs for the upcoming
button surface. Adds install/legacy/remove-legacy-buttons.sh to retire the
pre-repo boombox-button-handler and boombox-mode-manager services."
```

---

### Task 2: Bootstrap pytest harness

**Why:** The pure-logic pieces of this service (config parsing, press classification, encoder decode, dispatcher routing) are exactly where unit tests pay off. The codebase has no tests today — bootstrap one minimal harness so future services can use it.

**Files:**
- Modify: `install/config/requirements.txt`
- Create: `services/tests/__init__.py`
- Create: `services/tests/conftest.py`
- Create: `pyproject.toml` (at repo root, minimal pytest config)

- [ ] **Step 1: Add pytest to requirements**

Edit `install/config/requirements.txt` — append:

```
# Dev/test (installed in the venv even on the Pi so /opt/boombox can self-test).
pytest>=8.0
watchdog>=4.0
```

- [ ] **Step 2: Create services/tests/__init__.py**

Empty file:

```python
```

- [ ] **Step 3: Create services/tests/conftest.py**

```python
"""Test fixtures shared across boombox-* service tests."""
from __future__ import annotations

import sys
from pathlib import Path

# The service modules live alongside the tests dir. Add the parent to sys.path
# so `import boombox_buttons` works without packaging.
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))
```

- [ ] **Step 4: Create pyproject.toml at repo root**

```toml
[tool.pytest.ini_options]
testpaths = ["services/tests"]
python_files = ["test_*.py"]
addopts = "-q"
```

- [ ] **Step 5: Verify the harness runs (with zero tests)**

From repo root:

```bash
cd /Users/jwc/code/Boombox
python3 -m venv /tmp/boombox-test-venv
/tmp/boombox-test-venv/bin/pip install pytest aiohttp watchdog gpiod numpy
/tmp/boombox-test-venv/bin/pytest
```

Expected output:

```
no tests ran in 0.01s
```

- [ ] **Step 6: Commit**

```bash
git add install/config/requirements.txt services/tests/__init__.py services/tests/conftest.py pyproject.toml
git commit -m "buttons(test): bootstrap pytest harness for services/

Adds pytest + watchdog to requirements, creates services/tests/ with a
shared conftest that puts services/ on sys.path so `import boombox_buttons`
works without packaging. Pure-logic tests for the new GPIO service will
live here."
```

---

### Task 3: Config schema, parser, and hot-reload

**Files:**
- Create: `services/tests/test_buttons_config.py`
- Modify: `services/boombox-buttons.py` (config section)
- Modify: `install/config/buttons.json` (full schema)

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_buttons_config.py`:

```python
"""Config loading: schema, defaults, validation, disable rules."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

buttons = importlib.import_module("boombox-buttons".replace("-", "_"))
# Service file is `boombox-buttons.py`; importlib can't import hyphenated
# names directly. The service ships a symlink-friendly name via conftest's
# sys.path entry plus a one-line shim. We rely on the renamed import below.


def test_defaults_have_every_action():
    cfg = buttons.default_config()
    assert set(cfg["pins"].keys()) == {
        "play_pause", "stop", "previous", "next", "shuffle", "repeat",
        "sleep_timer", "skin_cycle", "library", "airplay", "spotify",
        "bluetooth", "movies", "web", "mic_karaoke", "record", "power",
    }
    assert "encoder" in cfg
    assert cfg["long_press_ms"] == 600
    assert cfg["power_hold_ms"] == 2000


def test_load_merges_user_overrides(tmp_path: Path):
    user = {"long_press_ms": 800, "pins": {"play_pause": {"pin": 99, "enabled": False}}}
    f = tmp_path / "buttons.json"
    f.write_text(json.dumps(user))
    cfg = buttons.load_config(f)
    assert cfg["long_press_ms"] == 800
    assert cfg["pins"]["play_pause"] == {"pin": 99, "enabled": False}
    # Untouched defaults preserved
    assert cfg["pins"]["stop"]["enabled"] is True


def test_load_missing_file_returns_defaults(tmp_path: Path):
    cfg = buttons.load_config(tmp_path / "does-not-exist.json")
    assert cfg == buttons.default_config()


def test_load_malformed_file_returns_defaults(tmp_path: Path, caplog):
    f = tmp_path / "buttons.json"
    f.write_text("{ not json")
    cfg = buttons.load_config(f)
    assert cfg == buttons.default_config()


def test_enabled_pins_filters_correctly():
    cfg = buttons.default_config()
    cfg["pins"]["stop"]["enabled"] = False
    cfg["pins"]["record"]["pin"] = None
    enabled = buttons.enabled_pins(cfg)
    assert "play_pause" in enabled
    assert "stop" not in enabled       # disabled flag
    assert "record" not in enabled     # null pin
    assert "encoder_a" in enabled      # encoder phases included
    assert "encoder_b" in enabled
    assert "encoder_push" in enabled


def test_pin_conflict_detected():
    cfg = buttons.default_config()
    cfg["pins"]["play_pause"]["pin"] = 99
    cfg["pins"]["stop"]["pin"] = 99
    conflicts = buttons.pin_conflicts(cfg)
    assert ("play_pause", "stop", 99) in conflicts or ("stop", "play_pause", 99) in conflicts
```

- [ ] **Step 2: Add an import-friendly module alias**

Hyphenated module names can't be imported. Add a `services/boombox_buttons.py` (no hyphen) one-liner that re-exports from the real file via `importlib.util.spec_from_file_location`:

```python
"""Underscore-named import shim so tests can `import boombox_buttons`.

The shipped service is `boombox-buttons.py` (hyphenated to match systemd
unit naming). Python imports don't allow hyphens, so this shim loads the
real file by path and re-exports its public names.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_real = Path(__file__).resolve().parent / "boombox-buttons.py"
_spec = importlib.util.spec_from_file_location("boombox_buttons_impl", _real)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["boombox_buttons_impl"] = _mod
_spec.loader.exec_module(_mod)

# Re-export everything the tests touch.
default_config = _mod.default_config
load_config = _mod.load_config
enabled_pins = _mod.enabled_pins
pin_conflicts = _mod.pin_conflicts
```

- [ ] **Step 3: Run the test, watch it fail**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_config.py -v
```

Expected: fails — `default_config`, `load_config`, `enabled_pins`, `pin_conflicts` don't exist in `boombox-buttons.py` yet.

- [ ] **Step 4: Replace boombox-buttons.py with the config layer**

Replace the *top* of `services/boombox-buttons.py` (everything above the existing `# ---------- Mopidy RPC helpers` line) with:

```python
#!/usr/bin/env python3
"""Boombox GPIO button + rotary encoder driver.

Owns the physical control surface described in
docs/superpowers/specs/2026-05-12-gpio-buttons-design.md: 17 buttons + 1
rotary encoder with push. Every action is independently disable-able via
/etc/boombox/buttons.json. Pin assignments are user-editable via that file
or via the Settings drawer's Buttons panel (which writes the file).

Listens on aiohttp 127.0.0.1:6683 for /config, /learn, /test endpoints used
by the Settings panel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Iterable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-buttons")

CONFIG_PATH = Path(os.environ.get("BOOMBOX_BUTTONS_FILE", "/etc/boombox/buttons.json"))


# ---------- Config ---------------------------------------------------------

# Every action ships disabled-by-default? No — the design is "all wired by
# default, user nulls out what they didn't solder." That matches the "more
# the merrier" preference: ship the full inventory, users disable rather
# than enable. Pin assignments come from the spec.
_DEFAULT_PINS = {
    "play_pause":  {"pin": 4,  "enabled": True},
    "stop":        {"pin": 5,  "enabled": True},
    "previous":    {"pin": 6,  "enabled": True},
    "next":        {"pin": 12, "enabled": True},
    "shuffle":     {"pin": 13, "enabled": True},
    "repeat":      {"pin": 7,  "enabled": True},
    "sleep_timer": {"pin": 8,  "enabled": True},
    "skin_cycle":  {"pin": 9,  "enabled": True},
    "library":     {"pin": 10, "enabled": True},
    "airplay":     {"pin": 16, "enabled": True},
    "spotify":     {"pin": 17, "enabled": True},
    "bluetooth":   {"pin": 22, "enabled": True},
    "movies":      {"pin": 23, "enabled": True},
    "web":         {"pin": 24, "enabled": True},
    "mic_karaoke": {"pin": 25, "enabled": True},
    "record":      {"pin": 26, "enabled": True},
    "power":       {"pin": 27, "enabled": True},
}

_DEFAULT_ENCODER = {"pin_a": 14, "pin_b": 15, "pin_push": 11, "enabled": True}


def default_config() -> dict:
    return {
        "long_press_ms": 600,
        "power_hold_ms": 2000,
        "encoder_step": 5,
        "pins": deepcopy(_DEFAULT_PINS),
        "encoder": deepcopy(_DEFAULT_ENCODER),
    }


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        log.info("no %s; using defaults", path)
        return default_config()
    try:
        user = json.loads(path.read_text())
        if not isinstance(user, dict):
            raise ValueError("config root must be an object")
    except Exception as e:
        log.warning("could not read %s: %s — using defaults", path, e)
        return default_config()
    return _merge(default_config(), user)


def enabled_pins(cfg: dict) -> dict[str, int]:
    """Return {action_name: pin} for everything that is wired AND enabled.

    Encoder lines appear as `encoder_a`, `encoder_b`, `encoder_push`.
    """
    out: dict[str, int] = {}
    for name, entry in cfg["pins"].items():
        if entry.get("enabled") and entry.get("pin") is not None:
            out[name] = int(entry["pin"])
    enc = cfg.get("encoder") or {}
    if enc.get("enabled"):
        for k_in, k_out in (("pin_a", "encoder_a"), ("pin_b", "encoder_b"), ("pin_push", "encoder_push")):
            if enc.get(k_in) is not None:
                out[k_out] = int(enc[k_in])
    return out


def pin_conflicts(cfg: dict) -> list[tuple[str, str, int]]:
    """Return a list of (action_a, action_b, pin) triples that collide."""
    by_pin: dict[int, list[str]] = {}
    for name, pin in enabled_pins(cfg).items():
        by_pin.setdefault(pin, []).append(name)
    conflicts: list[tuple[str, str, int]] = []
    for pin, names in by_pin.items():
        if len(names) > 1:
            names.sort()
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    conflicts.append((names[i], names[j], pin))
    return conflicts
```

- [ ] **Step 5: Update install/config/buttons.json to the full schema**

Overwrite `install/config/buttons.json` with the default config:

```json
{
  "_comment": "Override at /etc/boombox/buttons.json. Set pin to null or enabled to false to disable any action. Pin numbers are BCM GPIO. See docs/superpowers/specs/2026-05-12-gpio-buttons-design.md.",
  "long_press_ms": 600,
  "power_hold_ms": 2000,
  "encoder_step": 5,
  "pins": {
    "play_pause":  {"pin": 4,  "enabled": true},
    "stop":        {"pin": 5,  "enabled": true},
    "previous":    {"pin": 6,  "enabled": true},
    "next":        {"pin": 12, "enabled": true},
    "shuffle":     {"pin": 13, "enabled": true},
    "repeat":      {"pin": 7,  "enabled": true},
    "sleep_timer": {"pin": 8,  "enabled": true},
    "skin_cycle":  {"pin": 9,  "enabled": true},
    "library":     {"pin": 10, "enabled": true},
    "airplay":     {"pin": 16, "enabled": true},
    "spotify":     {"pin": 17, "enabled": true},
    "bluetooth":   {"pin": 22, "enabled": true},
    "movies":      {"pin": 23, "enabled": true},
    "web":         {"pin": 24, "enabled": true},
    "mic_karaoke": {"pin": 25, "enabled": true},
    "record":      {"pin": 26, "enabled": true},
    "power":       {"pin": 27, "enabled": true}
  },
  "encoder": {"pin_a": 14, "pin_b": 15, "pin_push": 11, "enabled": true}
}
```

- [ ] **Step 6: Run tests until they pass**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_config.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add services/boombox-buttons.py services/boombox_buttons.py services/tests/test_buttons_config.py install/config/buttons.json
git commit -m "buttons(config): full 17-action schema with defaults, merge, and validation

Adds default_config / load_config / enabled_pins / pin_conflicts to
services/boombox-buttons.py. Ships install/config/buttons.json with all
17 actions enabled at their spec-default pins. Underscore-named shim
services/boombox_buttons.py lets pytest import the hyphenated service file."
```

---

### Task 4: Press classifier — short/long-press state machine

**Files:**
- Create: `services/tests/test_buttons_press.py`
- Modify: `services/boombox-buttons.py` (press classifier section)

- [ ] **Step 1: Write the failing test**

`services/tests/test_buttons_press.py`:

```python
"""Press classifier: timestamps + edges -> short_press / long_press / long_hold events."""
from __future__ import annotations

import boombox_buttons as bb


def test_short_press_emits_short_on_release():
    """Press for 100 ms, release -> single short_press."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    events = list(pc.feed(t_ms=0, edge="down"))
    events += list(pc.feed(t_ms=100, edge="up"))
    assert events == [("short_press",)]


def test_long_press_emits_long_on_threshold():
    """Held past 600 ms -> long_press fires once at threshold."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    events = list(pc.feed(t_ms=0, edge="down"))
    events += list(pc.tick(t_ms=300))   # still under threshold
    assert events == []
    events += list(pc.tick(t_ms=600))   # at threshold
    assert events == [("long_press",)]


def test_long_hold_ticks_at_interval():
    """After long_press, every long_hold_tick_ms while still held emits a long_hold tick."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    list(pc.tick(t_ms=600))             # long_press fires
    events = list(pc.tick(t_ms=800))    # 200ms later
    assert events == [("long_hold",)]
    events = list(pc.tick(t_ms=1000))
    assert events == [("long_hold",)]


def test_release_after_long_press_does_not_emit_short():
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    list(pc.tick(t_ms=600))
    events = list(pc.feed(t_ms=900, edge="up"))
    assert events == [("long_release",)]


def test_release_before_threshold_is_short_even_after_multiple_ticks():
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    list(pc.tick(t_ms=300))
    list(pc.tick(t_ms=500))
    events = list(pc.feed(t_ms=599, edge="up"))
    assert events == [("short_press",)]


def test_duplicate_down_edge_does_not_restart():
    """A stray 'down' edge while already pressed is ignored (debounce safety)."""
    pc = bb.PressClassifier(long_press_ms=600, long_hold_tick_ms=200)
    list(pc.feed(t_ms=0, edge="down"))
    events = list(pc.feed(t_ms=50, edge="down"))
    assert events == []
```

- [ ] **Step 2: Run the test, watch it fail**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_press.py -v
```

Expected: `AttributeError: module 'boombox_buttons' has no attribute 'PressClassifier'`.

- [ ] **Step 3: Implement the classifier**

In `services/boombox-buttons.py`, append the following section (after the config section, before the existing Mopidy RPC section):

```python
# ---------- Press classifier ----------------------------------------------

class PressClassifier:
    """State machine: receives (timestamp_ms, edge) events plus periodic ticks,
    emits ("short_press",) / ("long_press",) / ("long_hold",) / ("long_release",).

    No GPIO awareness — pure logic, fully testable. The GPIO loop wires
    falling edges to feed(edge="down") and rising edges to feed(edge="up").
    """

    def __init__(self, long_press_ms: int, long_hold_tick_ms: int = 200):
        self._long_ms = long_press_ms
        self._tick_ms = long_hold_tick_ms
        self._down_at: int | None = None
        self._long_fired: bool = False
        self._last_hold_at: int | None = None

    def feed(self, t_ms: int, edge: str):
        if edge == "down":
            if self._down_at is not None:
                return  # already pressed; ignore duplicates
            self._down_at = t_ms
            self._long_fired = False
            self._last_hold_at = None
            return
        if edge == "up":
            if self._down_at is None:
                return
            held = t_ms - self._down_at
            self._down_at = None
            if self._long_fired:
                self._long_fired = False
                self._last_hold_at = None
                yield ("long_release",)
            else:
                if held < self._long_ms:
                    yield ("short_press",)

    def tick(self, t_ms: int):
        if self._down_at is None:
            return
        held = t_ms - self._down_at
        if not self._long_fired and held >= self._long_ms:
            self._long_fired = True
            self._last_hold_at = t_ms
            yield ("long_press",)
            return
        if self._long_fired:
            if self._last_hold_at is None:
                self._last_hold_at = t_ms
            if t_ms - self._last_hold_at >= self._tick_ms:
                self._last_hold_at = t_ms
                yield ("long_hold",)
```

Re-export from `services/boombox_buttons.py`:

```python
PressClassifier = _mod.PressClassifier
```

- [ ] **Step 4: Run tests until they pass**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_press.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox-buttons.py services/boombox_buttons.py services/tests/test_buttons_press.py
git commit -m "buttons(press): short/long-press state machine with hold ticks

PressClassifier emits short_press on quick release, long_press at the
600ms threshold, long_hold every 200ms while still held, long_release on
final release. Pure logic; no GPIO dependency. Used by prev/next (scrub),
power (shutdown countdown), sleep_timer (cancel)."
```

---

### Task 5: Rotary encoder quadrature decoder

**Files:**
- Create: `services/tests/test_buttons_encoder.py`
- Modify: `services/boombox-buttons.py` (encoder section)

- [ ] **Step 1: Write the failing test**

```python
"""Quadrature decoder for the rotary encoder."""
from __future__ import annotations

import boombox_buttons as bb


def test_cw_rotation_emits_one_step():
    """CW rotation transitions: 11 -> 01 -> 00 -> 10 -> 11 (one detent)."""
    dec = bb.EncoderDecoder()
    out = []
    for ab in [(0, 1), (0, 0), (1, 0), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == [("cw",)]


def test_ccw_rotation_emits_one_step():
    """CCW: 11 -> 10 -> 00 -> 01 -> 11."""
    dec = bb.EncoderDecoder()
    out = []
    for ab in [(1, 0), (0, 0), (0, 1), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == [("ccw",)]


def test_partial_rotation_does_not_emit():
    """Half a detent (11 -> 01 -> 11) emits nothing."""
    dec = bb.EncoderDecoder()
    out = []
    out.extend(dec.feed(a=0, b=1))
    out.extend(dec.feed(a=1, b=1))
    assert out == []


def test_noise_pulses_do_not_emit():
    """Bouncy noise: 11 -> 01 -> 11 -> 01 -> 11 emits nothing."""
    dec = bb.EncoderDecoder()
    out = []
    for ab in [(0, 1), (1, 1), (0, 1), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == []


def test_multiple_consecutive_detents():
    dec = bb.EncoderDecoder()
    out = []
    # Two CW detents back to back.
    for ab in [(0, 1), (0, 0), (1, 0), (1, 1), (0, 1), (0, 0), (1, 0), (1, 1)]:
        out.extend(dec.feed(a=ab[0], b=ab[1]))
    assert out == [("cw",), ("cw",)]
```

- [ ] **Step 2: Run the test, watch it fail**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_encoder.py -v
```

Expected: AttributeError on `EncoderDecoder`.

- [ ] **Step 3: Implement the decoder**

In `services/boombox-buttons.py`, append after the press classifier:

```python
# ---------- Rotary encoder decoder ----------------------------------------

class EncoderDecoder:
    """Decodes a two-phase quadrature encoder. Emits ("cw",) or ("ccw",)
    once per detent (full cycle returning to 11)."""

    # Transition table indexed by ((prev_a, prev_b), (a, b)) -> direction or 0.
    # Built from the canonical 4-state Gray code transitions: a CW detent
    # walks the sequence 11 -> 01 -> 00 -> 10 -> 11 (and CCW reversed).
    _TRANSITION = {
        ((1, 1), (0, 1)): +1, ((0, 1), (0, 0)): +1, ((0, 0), (1, 0)): +1, ((1, 0), (1, 1)): +1,
        ((1, 1), (1, 0)): -1, ((1, 0), (0, 0)): -1, ((0, 0), (0, 1)): -1, ((0, 1), (1, 1)): -1,
    }

    def __init__(self):
        self._state: tuple[int, int] = (1, 1)
        self._accum: int = 0

    def feed(self, a: int, b: int):
        new_state = (a, b)
        if new_state == self._state:
            return
        delta = self._TRANSITION.get((self._state, new_state), 0)
        self._state = new_state
        self._accum += delta
        # A complete detent traverses 4 sub-transitions = ±4 accumulated.
        while self._accum >= 4:
            self._accum -= 4
            yield ("cw",)
        while self._accum <= -4:
            self._accum += 4
            yield ("ccw",)
```

Re-export `EncoderDecoder` from `services/boombox_buttons.py`.

- [ ] **Step 4: Tests pass**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_encoder.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/boombox-buttons.py services/boombox_buttons.py services/tests/test_buttons_encoder.py
git commit -m "buttons(encoder): quadrature decoder with detent debouncing

EncoderDecoder accumulates sub-transitions across the 4-state Gray cycle
and emits one cw/ccw event per detent. Bouncy half-cycles cancel out so
the user has to actually turn the knob to register a step."
```

---

### Task 6: Dispatcher — action routing by source

**Files:**
- Create: `services/tests/test_buttons_dispatch.py`
- Modify: `services/boombox-buttons.py` (dispatcher section)

- [ ] **Step 1: Write the failing test**

```python
"""Action dispatcher: routes transport actions through Mopidy or state-API based on current source."""
from __future__ import annotations

import pytest
import boombox_buttons as bb


class FakeMopidy:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
    async def call(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"result": "playing" if method == "core.playback.get_state" else None}


class FakeStateApi:
    def __init__(self, source="mopidy"):
        self.source = source
        self.calls: list[tuple[str, dict]] = []
    async def current_source(self):
        return self.source
    async def control(self, action):
        self.calls.append(("control", {"action": action}))


@pytest.mark.asyncio
async def test_play_pause_routes_to_mopidy_when_source_is_mopidy():
    m, s = FakeMopidy(), FakeStateApi(source="mopidy")
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None)
    await d.dispatch("play_pause", "short_press")
    assert any(c[0] in ("core.playback.play", "core.playback.pause") for c in m.calls)
    assert s.calls == []


@pytest.mark.asyncio
async def test_play_pause_routes_to_state_api_when_external_source_live():
    m, s = FakeMopidy(), FakeStateApi(source="airplay")
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None)
    await d.dispatch("play_pause", "short_press")
    assert s.calls == [("control", {"action": "play-pause"})]
    assert m.calls == []


@pytest.mark.asyncio
async def test_unknown_action_logs_and_does_nothing():
    m, s = FakeMopidy(), FakeStateApi()
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None)
    await d.dispatch("nonsense_action", "short_press")
    assert m.calls == [] and s.calls == []


@pytest.mark.asyncio
async def test_disabled_button_in_config_does_not_dispatch():
    """Dispatcher receives a 'stop' event but config marks it disabled -> drop."""
    m, s = FakeMopidy(), FakeStateApi()
    d = bb.Dispatcher(mopidy=m, state=s, kiosk=None, recorder=None, display=None, sleep=None,
                     disabled={"stop"})
    await d.dispatch("stop", "short_press")
    assert m.calls == []
```

Top of file, before the test functions:

```python
import asyncio
import pytest_asyncio  # noqa: F401  (optional but documents intent)
```

…actually the tests use `pytest.mark.asyncio`; ensure `pytest-asyncio` is available. Add it to the test-time install.

- [ ] **Step 2: Install pytest-asyncio**

```bash
/tmp/boombox-test-venv/bin/pip install pytest-asyncio
```

Add to `install/config/requirements.txt`:

```
pytest-asyncio>=0.23
```

And add to `pyproject.toml` under the existing pytest section:

```toml
asyncio_mode = "auto"
```

So the final pyproject pytest block is:

```toml
[tool.pytest.ini_options]
testpaths = ["services/tests"]
python_files = ["test_*.py"]
addopts = "-q"
asyncio_mode = "auto"
```

- [ ] **Step 3: Run failing test**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_dispatch.py -v
```

Expected: AttributeError on `Dispatcher`.

- [ ] **Step 4: Implement the dispatcher**

In `services/boombox-buttons.py`, append:

```python
# ---------- Dispatcher ----------------------------------------------------

@dataclass
class Dispatcher:
    """Routes (action, event) pairs to their target. Holds references to
    the four backend clients; each action handler picks the right one.

    `disabled` is a set of action names that should be silently dropped —
    populated from the config's enabled flag at startup and on hot-reload.
    """
    mopidy: object | None
    state:  object | None
    kiosk:  object | None
    recorder: object | None
    display: object | None
    sleep: object | None
    disabled: set[str] | None = None

    async def dispatch(self, action: str, event: str = "short_press") -> None:
        if self.disabled and action in self.disabled:
            return
        handler = _HANDLERS.get((action, event))
        if handler is None:
            log.debug("no handler for (%s, %s)", action, event)
            return
        try:
            await handler(self)
        except Exception as exc:
            log.warning("handler %s/%s raised: %s", action, event, exc)


# Action handlers register themselves below. We separate (short_press) from
# (long_press / long_hold / long_release) so the table is explicit.
_HANDLERS: dict[tuple[str, str], Callable[[Dispatcher], Awaitable[None]]] = {}


def _handler(action: str, event: str = "short_press"):
    def deco(fn):
        _HANDLERS[(action, event)] = fn
        return fn
    return deco


# Transport — short presses
@_handler("play_pause")
async def _h_play_pause(d: Dispatcher):
    source = await d.state.current_source() if d.state else "mopidy"
    if source in (None, "mopidy"):
        if d.mopidy is None:
            return
        state = (await d.mopidy.call("core.playback.get_state")).get("result")
        await d.mopidy.call("core.playback.pause" if state == "playing" else "core.playback.play")
    else:
        await d.state.control("play-pause")


@_handler("stop")
async def _h_stop(d: Dispatcher):
    if d.mopidy:
        await d.mopidy.call("core.playback.stop")


@_handler("previous")
async def _h_previous(d: Dispatcher):
    source = await d.state.current_source() if d.state else "mopidy"
    if source in (None, "mopidy"):
        if d.mopidy:
            await d.mopidy.call("core.playback.previous")
    else:
        await d.state.control("previous")


@_handler("next")
async def _h_next(d: Dispatcher):
    source = await d.state.current_source() if d.state else "mopidy"
    if source in (None, "mopidy"):
        if d.mopidy:
            await d.mopidy.call("core.playback.next")
    else:
        await d.state.control("next")


@_handler("shuffle")
async def _h_shuffle(d: Dispatcher):
    if d.mopidy is None:
        return
    cur = (await d.mopidy.call("core.tracklist.get_random")).get("result")
    await d.mopidy.call("core.tracklist.set_random", {"value": not cur})


@_handler("repeat")
async def _h_repeat(d: Dispatcher):
    if d.mopidy is None:
        return
    repeat = (await d.mopidy.call("core.tracklist.get_repeat")).get("result")
    single = (await d.mopidy.call("core.tracklist.get_single")).get("result")
    # Cycle off -> all -> one -> off
    if not repeat and not single:
        await d.mopidy.call("core.tracklist.set_repeat", {"value": True})
        await d.mopidy.call("core.tracklist.set_single", {"value": False})
    elif repeat and not single:
        await d.mopidy.call("core.tracklist.set_single", {"value": True})
    else:
        await d.mopidy.call("core.tracklist.set_repeat", {"value": False})
        await d.mopidy.call("core.tracklist.set_single", {"value": False})
```

Re-export `Dispatcher` from `services/boombox_buttons.py`. Add an alias so the `play-pause` action name from `boombox-state /control` matches our internal hyphen/underscore convention — the state API accepts both `play-pause` and `play_pause`; tests verify `play-pause`.

- [ ] **Step 5: Tests pass**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/test_buttons_dispatch.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add services/boombox-buttons.py services/boombox_buttons.py services/tests/test_buttons_dispatch.py install/config/requirements.txt pyproject.toml
git commit -m "buttons(dispatch): routing layer + transport handlers

Dispatcher.dispatch(action, event) looks up handlers in a registry and
calls them with backend clients. Transport (play_pause/stop/prev/next)
routes to Mopidy when the active source is Mopidy and to
boombox-state /control otherwise. Shuffle and Repeat toggle directly
on Mopidy. Disabled actions short-circuit silently."
```

---

### Task 7: Backend clients — MopidyRpc, StateApi, KioskClient

**Files:**
- Modify: `services/boombox-buttons.py` (clients section, replacing the old MopidyRpc)

- [ ] **Step 1: Replace the existing MopidyRpc and add StateApi + KioskClient**

Remove the existing `class MopidyRpc:` block in `services/boombox-buttons.py` and replace with the following section (or insert before the dispatcher section):

```python
# ---------- Backend clients -----------------------------------------------

import aiohttp

MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
STATE_BASE = "http://127.0.0.1:6681"
KIOSK_DEBUG = "http://127.0.0.1:9222"


class MopidyRpc:
    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session
        self._id = 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        try:
            async with self._sess.post(MOPIDY_RPC, json=body,
                                       timeout=aiohttp.ClientTimeout(total=2)) as r:
                if r.status != 200:
                    return {}
                return await r.json(content_type=None)
        except Exception as e:
            log.warning("mopidy.%s failed: %s", method, e)
            return {}


class StateApi:
    """Thin client for the boombox-state aggregator at :6681.

    `current_source()` returns the lowercase friendly source name
    ('mopidy', 'airplay', 'spotify', 'bluetooth') or None when nothing is
    playing.
    """

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    async def current_source(self) -> str | None:
        try:
            async with self._sess.get(f"{STATE_BASE}/state",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                if r.status != 200:
                    return None
                body = await r.json()
        except Exception:
            return None
        label = (body.get("label") or "").lower()
        return label or None

    async def control(self, action: str) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/control/{action}",
                                   timeout=aiohttp.ClientTimeout(total=2))
        except Exception as e:
            log.warning("state.control(%s) failed: %s", action, e)

    async def volume_get(self) -> tuple[float, bool] | None:
        try:
            async with self._sess.get(f"{STATE_BASE}/volume",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                body = await r.json()
                if not body.get("ok"):
                    return None
                return float(body["volume"]), bool(body.get("muted"))
        except Exception:
            return None

    async def volume_set(self, volume: float) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/volume", json={"volume": volume},
                                  timeout=aiohttp.ClientTimeout(total=1))
        except Exception as e:
            log.warning("state.volume_set failed: %s", e)

    async def mute_toggle(self) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/volume/mute",
                                  timeout=aiohttp.ClientTimeout(total=1))
        except Exception as e:
            log.warning("state.mute_toggle failed: %s", e)

    async def karaoke_state(self) -> bool:
        try:
            async with self._sess.get(f"{STATE_BASE}/karaoke",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                body = await r.json()
                return bool(body.get("on"))
        except Exception:
            return False

    async def karaoke_toggle(self) -> None:
        on = await self.karaoke_state()
        path = "/karaoke/off" if on else "/karaoke/on"
        try:
            await self._sess.post(f"{STATE_BASE}{path}",
                                  timeout=aiohttp.ClientTimeout(total=2))
        except Exception as e:
            log.warning("state.karaoke_toggle failed: %s", e)

    async def bluetooth_pair(self) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/bluetooth/pair",
                                  timeout=aiohttp.ClientTimeout(total=5))
        except Exception as e:
            log.warning("state.bluetooth_pair failed: %s", e)


class KioskClient:
    """DevTools client for the Chromium kiosk on :9222. Drives navigation
    and runs JS in the kiosk tab. Used for source overlays, swap-to-Jellyfin,
    QR code, sleep OSD, etc."""

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    async def _tab(self) -> dict | None:
        try:
            async with self._sess.get(f"{KIOSK_DEBUG}/json",
                                       timeout=aiohttp.ClientTimeout(total=1)) as r:
                tabs = await r.json()
                for t in tabs:
                    if t.get("type") == "page":
                        return t
        except Exception:
            return None
        return None

    async def navigate(self, url: str) -> None:
        tab = await self._tab()
        if not tab:
            return
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        try:
            import websockets
            async with websockets.connect(ws_url, open_timeout=2, max_size=2**24) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Page.navigate",
                                           "params": {"url": url}}))
        except Exception as e:
            log.warning("kiosk.navigate(%s) failed: %s", url, e)

    async def emit(self, event: str, detail: dict | None = None) -> None:
        """Dispatch a custom DOM event on the kiosk page so the SPA can
        react (overlay mount/unmount). The SPA listens on
        window.addEventListener('boombox:<event>')."""
        tab = await self._tab()
        if not tab:
            return
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        script = (
            f"window.dispatchEvent(new CustomEvent('boombox:{event}', "
            f"{{detail: {json.dumps(detail or {})}}}))"
        )
        try:
            import websockets
            async with websockets.connect(ws_url, open_timeout=2, max_size=2**24) as ws:
                await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                          "params": {"expression": script}}))
        except Exception as e:
            log.warning("kiosk.emit(%s) failed: %s", event, e)
```

- [ ] **Step 2: Manual smoke test on the Pi**

This task has no new tests (clients are integration code best verified on the Pi). After committing, the GPIO-loop task (Task 8) will exercise them end-to-end.

- [ ] **Step 3: Commit**

```bash
git add services/boombox-buttons.py
git commit -m "buttons(clients): MopidyRpc + StateApi + KioskClient

Replaces the inline MopidyRpc with a section that adds:
- StateApi: control, volume get/set, mute_toggle (new endpoint, Task 13),
  karaoke_state/toggle, bluetooth_pair, current_source.
- KioskClient: DevTools-driven navigate() and emit() for SPA custom events.
The three clients give the dispatcher all the surfaces it needs without
the action handlers having to know any HTTP details."
```

---

### Task 8: GPIO event loop

**Files:**
- Modify: `services/boombox-buttons.py` (replace watch_pins / main with a multi-line + encoder + classifier loop)

- [ ] **Step 1: Replace the existing watch_pins and main**

Delete the existing `watch_pins` and `main` functions in `services/boombox-buttons.py`. Append the following at the end:

```python
# ---------- GPIO event loop -----------------------------------------------

import gpiod
from gpiod.line import Direction, Bias, Edge

GPIO_CHIP = "/dev/gpiochip0"
DEBOUNCE_MS = 30
ENCODER_DEBOUNCE_MS = 1
TICK_INTERVAL_S = 0.05  # 20Hz; resolves long-press windows precisely enough


async def gpio_loop(cfg: dict, dispatcher: Dispatcher, stop: asyncio.Event) -> None:
    """Single-pass GPIO loop. Re-call to rebuild after config hot-reload.
    Returns when `stop` is set."""
    pins = enabled_pins(cfg)
    if not pins:
        log.info("no GPIO pins configured; idling")
        await stop.wait()
        return

    long_ms = int(cfg.get("long_press_ms", 600))
    power_hold_ms = int(cfg.get("power_hold_ms", 2000))

    # gpiod line config: encoder phases get fast debounce + both-edge so we
    # see every quadrature transition; buttons get falling-edge only.
    line_config: dict[int, gpiod.LineSettings] = {}
    by_pin: dict[int, str] = {}
    for action, pin in pins.items():
        by_pin[pin] = action
        if action in ("encoder_a", "encoder_b"):
            line_config[pin] = gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,
                debounce_period=ENCODER_DEBOUNCE_MS / 1000,
            )
        else:
            line_config[pin] = gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,  # need both so we can detect release
                debounce_period=DEBOUNCE_MS / 1000,
            )

    log.info("gpio pins: %s", ", ".join(f"{a}=BCM{p}" for a, p in pins.items()))

    # Press classifiers per button action. Power gets the longer threshold.
    classifiers: dict[str, PressClassifier] = {
        action: PressClassifier(
            long_press_ms=power_hold_ms if action == "power" else long_ms,
        )
        for action in pins if action not in ("encoder_a", "encoder_b", "encoder_push")
    }
    encoder = EncoderDecoder()
    enc_a_state = enc_b_state = 1

    with gpiod.request_lines(GPIO_CHIP, consumer="boombox-buttons", config=line_config) as req:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def reader():
            while not stop.is_set():
                if req.wait_edge_events(timeout=0.5):
                    for ev in req.read_edge_events():
                        loop.call_soon_threadsafe(queue.put_nowait, ev)

        loop.run_in_executor(None, reader)

        async def tick():
            while not stop.is_set():
                t_ms = int(loop.time() * 1000)
                for action, pc in classifiers.items():
                    for evt in pc.tick(t_ms):
                        await dispatcher.dispatch(action, evt[0])
                await asyncio.sleep(TICK_INTERVAL_S)

        ticker = asyncio.create_task(tick())

        try:
            while not stop.is_set():
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                t_ms = int(loop.time() * 1000)
                action = by_pin.get(ev.line_offset)
                if not action:
                    continue
                if action == "encoder_a":
                    enc_a_state = 0 if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else 1
                    for evt in encoder.feed(enc_a_state, enc_b_state):
                        await dispatcher.dispatch("encoder", evt[0])
                elif action == "encoder_b":
                    enc_b_state = 0 if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else 1
                    for evt in encoder.feed(enc_a_state, enc_b_state):
                        await dispatcher.dispatch("encoder", evt[0])
                elif action == "encoder_push":
                    if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE:
                        await dispatcher.dispatch("encoder_push", "short_press")
                else:
                    edge = "down" if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else "up"
                    for evt in classifiers[action].feed(t_ms, edge):
                        await dispatcher.dispatch(action, evt[0])
        finally:
            ticker.cancel()


# ---------- Main ----------------------------------------------------------

async def main() -> None:
    cfg = load_config()
    conflicts = pin_conflicts(cfg)
    for a, b, pin in conflicts:
        log.error("pin conflict: %s and %s both on BCM%s — disable one", a, b, pin)

    async with aiohttp.ClientSession() as sess:
        mopidy = MopidyRpc(sess)
        state = StateApi(sess)
        kiosk = KioskClient(sess)
        # Subsystems wired in later tasks:
        recorder = None
        display = None
        sleep_t = None
        disabled = {a for a, e in cfg["pins"].items() if not e.get("enabled")}
        dispatcher = Dispatcher(mopidy=mopidy, state=state, kiosk=kiosk,
                                recorder=recorder, display=display, sleep=sleep_t,
                                disabled=disabled)

        # Encoder rotation handlers — these always go through volume.
        async def _enc_cw(d: Dispatcher):
            cur = await d.state.volume_get()
            if cur is None:
                return
            step = (cfg.get("encoder_step", 5)) / 100.0
            await d.state.volume_set(min(1.0, cur[0] + step))
        async def _enc_ccw(d: Dispatcher):
            cur = await d.state.volume_get()
            if cur is None:
                return
            step = (cfg.get("encoder_step", 5)) / 100.0
            await d.state.volume_set(max(0.0, cur[0] - step))
        async def _enc_push(d: Dispatcher):
            await d.state.mute_toggle()
        _HANDLERS[("encoder", "cw")] = _enc_cw
        _HANDLERS[("encoder", "ccw")] = _enc_ccw
        _HANDLERS[("encoder_push", "short_press")] = _enc_push

        stop = asyncio.Event()
        await gpio_loop(cfg, dispatcher, stop)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify the file still passes existing tests**

```bash
/tmp/boombox-test-venv/bin/pytest services/tests/ -v
```

Expected: 21 passed (config 6, press 6, encoder 5, dispatch 4).

- [ ] **Step 3: Deploy and smoke-test on Pi**

```bash
./pi deploy services/ /opt/boombox/services/
./pi deploy install/config/buttons.json /opt/boombox/install/config/buttons.json
./pi ssh "sudo install -m 0644 /opt/boombox/install/config/buttons.json /etc/boombox/buttons.json"
./pi ssh "systemctl --user restart boombox-buttons"
./pi ssh "journalctl --user-unit boombox-buttons -n 50 --no-pager"
```

Expected journal output: `gpio pins: play_pause=BCM4, stop=BCM5, ...` listing all 17 buttons + 3 encoder lines. No conflicts.

Physically press any wired button and confirm a journal line like `handler play_pause/short_press`. (If no buttons are wired yet, this is logically validated by the fact that the service started without crashing.)

- [ ] **Step 4: Commit**

```bash
git add services/boombox-buttons.py
git commit -m "buttons(gpio): multi-line event loop with classifier + encoder

Replaces the 5-action watch_pins with a single loop that:
- requests every enabled GPIO line in one gpiod call,
- routes button edges through per-action PressClassifier instances,
- decodes encoder phases through EncoderDecoder,
- handles encoder push as a plain short_press,
- runs a 20Hz tick to resolve long-press windows.
Encoder rotation drives volume via /volume; push drives /volume/mute."
```

---

### Task 9: Power button safety — display backlight + shutdown handoff

**Files:**
- Modify: `services/boombox-buttons.py` (Display + Shutdown sections, power handlers)

- [ ] **Step 1: Add Display + Shutdown helpers**

Append to `services/boombox-buttons.py` before the `# ---------- Main` section:

```python
# ---------- Display backlight ---------------------------------------------

class Display:
    """Wayland backlight control via wlr-randr. Async subprocess calls.

    On the kiosk, `wlr-randr` returns the active output's name on its first
    line. We cache it after the first call."""

    def __init__(self):
        self._output: str | None = None
        self._on: bool = True

    async def _detect_output(self) -> str | None:
        if self._output:
            return self._output
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        for line in out.decode().splitlines():
            if line and not line.startswith(" "):
                self._output = line.split()[0]
                return self._output
        return None

    async def toggle(self) -> None:
        out = await self._detect_output()
        if not out:
            return
        new = "off" if self._on else "on"
        await asyncio.create_subprocess_exec(
            "wlr-randr", "--output", out, "--" + new,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        self._on = not self._on

    async def wake(self) -> None:
        if self._on:
            return
        out = await self._detect_output()
        if not out:
            return
        await asyncio.create_subprocess_exec(
            "wlr-randr", "--output", out, "--on",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        self._on = True


# ---------- Shutdown sequence ---------------------------------------------

async def shutdown_sequence(mopidy: MopidyRpc, state: StateApi, kiosk: KioskClient,
                            display: Display) -> None:
    """Pause everything, trigger resume snapshot, then poweroff."""
    log.info("shutdown: pausing playback")
    try:
        await mopidy.call("core.playback.pause")
        await state.control("pause")
    except Exception:
        pass
    log.info("shutdown: nudging boombox-resume to snapshot")
    try:
        async with aiohttp.ClientSession() as s:
            await s.post("http://127.0.0.1:6681/mopidy/restart",
                         timeout=aiohttp.ClientTimeout(total=1))
    except Exception:
        pass  # snapshot is best-effort; the resume service auto-runs on shutdown anyway
    log.info("shutdown: systemctl poweroff")
    await asyncio.create_subprocess_exec("systemctl", "poweroff")
```

- [ ] **Step 2: Wire the Display into main() and add power handlers**

In `services/boombox-buttons.py`, inside `main()` after the line `display = None`, replace with:

```python
        display = Display()
```

Add the power handlers near the other transport handlers (anywhere in the dispatcher handlers section is fine; put them just after `_h_repeat`):

```python
@_handler("power", "short_press")
async def _h_power_short(d: Dispatcher):
    if d.display:
        await d.display.toggle()


@_handler("power", "long_press")
async def _h_power_long(d: Dispatcher):
    """Triggered at the 2-second threshold. Show a kiosk overlay with a
    short countdown so the user can release to abort. The actual shutdown
    fires on long_release if the press is still held when the countdown
    ends; we just emit the overlay event here."""
    if d.display:
        await d.display.wake()
    if d.kiosk:
        await d.kiosk.emit("shutdown-countdown", {"seconds": 2})


@_handler("power", "long_release")
async def _h_power_release(d: Dispatcher):
    """If the kiosk's countdown completed and the user is still holding,
    long_release fires after the full hold duration. The kiosk overlay
    polls release timing itself; here we treat any long_release as confirm."""
    if d.kiosk:
        await d.kiosk.emit("shutdown-confirm", {})
    await shutdown_sequence(d.mopidy, d.state, d.kiosk, d.display)
```

Note: with `power_hold_ms=2000`, `long_press` fires *at* 2s, then `long_release` fires whenever the user releases after that. If they release before 2s, only `short_press` fires (toggle display). The on-screen overlay listening for `boombox:shutdown-countdown` mounts the visible countdown and is also responsible for showing "shutting down…" on `boombox:shutdown-confirm`.

- [ ] **Step 3: Manual smoke test on the Pi**

```bash
./pi deploy services/ /opt/boombox/services/
./pi ssh "systemctl --user restart boombox-buttons"
```

If a power button is wired, short-press → display sleeps (it's safe; the kiosk will be hidden until press again). Long-press 2s → overlay event fires (you can confirm with `./pi ssh 'journalctl --user-unit boombox-buttons -n 20'` showing `handler power/long_press`).

If no button is wired, smoke-test the shutdown sequence directly:

```bash
./pi ssh '/opt/boombox/.venv/bin/python -c "import asyncio, aiohttp; import sys; sys.path.insert(0, \"/opt/boombox/services\"); from boombox_buttons import Display; asyncio.run(Display().toggle())"'
```

Expected: the screen toggles off then on again on a second invocation.

- [ ] **Step 4: Commit**

```bash
git add services/boombox-buttons.py
git commit -m "buttons(power): backlight toggle + shutdown handoff

Display wraps wlr-randr for Wayland backlight control with output
detection cached after first call. shutdown_sequence pauses Mopidy, nudges
the resume snapshot, then systemctl poweroff. Power-short toggles the
display; power-long emits a kiosk countdown overlay; power long-release
fires the shutdown after the on-screen countdown."
```

---

### Task 10: Sleep timer

**Files:**
- Modify: `services/boombox-buttons.py` (SleepTimer section + handler)

- [ ] **Step 1: Add SleepTimer and handlers**

Append to `services/boombox-buttons.py` before the `# ---------- Main` section:

```python
# ---------- Sleep timer ---------------------------------------------------

class SleepTimer:
    """Cycles 15 -> 30 -> 60 -> off -> 15 (subsequent presses within 3s
    cycle the duration; otherwise the first press sets the next value).
    Long-press cancels.

    Fires by calling on_expire() (set externally). The dispatcher hooks
    in pause + display sleep + kiosk OSD events at startup."""

    _CYCLE = [15, 30, 60, None]

    def __init__(self, on_expire: Callable[[], Awaitable[None]]):
        self._on_expire = on_expire
        self._idx: int = -1            # -1 = inactive
        self._task: asyncio.Task | None = None
        self._last_press_ms: int | None = None

    @property
    def active_minutes(self) -> int | None:
        if self._idx < 0:
            return None
        return self._CYCLE[self._idx]

    async def press(self, t_ms: int) -> int | None:
        """Returns the new value in minutes, or None when cycled to off."""
        if self._last_press_ms is not None and (t_ms - self._last_press_ms) <= 3000:
            self._idx = (self._idx + 1) % len(self._CYCLE)
        else:
            self._idx = 0
        self._last_press_ms = t_ms
        await self._reschedule()
        return self.active_minutes

    async def cancel(self) -> None:
        self._idx = -1
        await self._reschedule()

    async def _reschedule(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        mins = self.active_minutes
        if mins is None:
            return
        async def _runner():
            try:
                await asyncio.sleep(mins * 60)
                await self._on_expire()
            except asyncio.CancelledError:
                return
        self._task = asyncio.create_task(_runner())
```

In `main()`, replace `sleep_t = None` with:

```python
        async def _on_sleep_expire():
            try:
                await mopidy.call("core.playback.pause")
                await state.control("pause")
                if display:
                    await display.toggle() if True else None  # ensure off
                if kiosk:
                    await kiosk.emit("sleep-expired", {})
            except Exception as e:
                log.warning("sleep expire failed: %s", e)
        sleep_t = SleepTimer(on_expire=_on_sleep_expire)
```

Add handlers (near other handlers in the dispatcher section):

```python
@_handler("sleep_timer", "short_press")
async def _h_sleep(d: Dispatcher):
    if d.sleep is None:
        return
    t_ms = int(asyncio.get_running_loop().time() * 1000)
    new_mins = await d.sleep.press(t_ms)
    if d.kiosk:
        await d.kiosk.emit("sleep-timer", {"minutes": new_mins})


@_handler("sleep_timer", "long_press")
async def _h_sleep_cancel(d: Dispatcher):
    if d.sleep is None:
        return
    await d.sleep.cancel()
    if d.kiosk:
        await d.kiosk.emit("sleep-timer", {"minutes": None})
```

- [ ] **Step 2: Commit**

```bash
git add services/boombox-buttons.py
git commit -m "buttons(sleep): cyclable sleep timer with kiosk OSD events

SleepTimer.press() cycles 15/30/60/off if within 3s of the last press,
otherwise sets 15. Long-press cancels. Expiry pauses playback, sleeps
the display, and emits boombox:sleep-expired for the SPA toast."
```

---

### Task 11: Recorder

**Files:**
- Modify: `services/boombox-buttons.py` (Recorder section + handler)

- [ ] **Step 1: Add Recorder + handler**

Append before `# ---------- Main`:

```python
# ---------- Recorder ------------------------------------------------------

class Recorder:
    """Captures the current default PipeWire sink's monitor to FLAC.
    Start = spawn `parec | flac -`. Stop = SIGTERM the pipeline.

    Output: ~/Music/Recordings/YYYY-MM-DD-HHMMSS.flac
    """

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._flac: asyncio.subprocess.Process | None = None
        self._path: str | None = None

    @property
    def recording(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> str | None:
        if self.recording:
            return self._path
        from datetime import datetime
        rec_dir = Path.home() / "Music" / "Recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = rec_dir / f"{ts}.flac"
        self._path = str(out)
        # parec reads the default-sink monitor; flac encodes to FLAC stdout->file.
        self._proc = await asyncio.create_subprocess_exec(
            "parec", "--monitor-stream=@DEFAULT_AUDIO_SINK@",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        self._flac = await asyncio.create_subprocess_exec(
            "flac", "--silent", "-", "-o", str(out),
            stdin=self._proc.stdout, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return self._path

    async def stop(self) -> str | None:
        path = self._path
        for p in (self._proc, self._flac):
            if p is not None and p.returncode is None:
                p.terminate()
                try:
                    await asyncio.wait_for(p.wait(), timeout=3)
                except asyncio.TimeoutError:
                    p.kill()
        self._proc = None
        self._flac = None
        self._path = None
        return path
```

Update `main()` — replace `recorder = None` with `recorder = Recorder()`.

Add handler:

```python
@_handler("record", "short_press")
async def _h_record(d: Dispatcher):
    if d.recorder is None:
        return
    if d.recorder.recording:
        path = await d.recorder.stop()
        if d.kiosk:
            await d.kiosk.emit("record", {"on": False, "path": path})
    else:
        path = await d.recorder.start()
        if d.kiosk:
            await d.kiosk.emit("record", {"on": True, "path": path})
```

- [ ] **Step 2: Verify flac is installed on the Pi**

```bash
./pi ssh "which flac parec || sudo apt install -y flac"
```

Add `flac` to the apt list in `install/install.sh` — find the `sudo apt install -y \` block and add `flac \` on a new line near `alsa-utils`:

```bash
  alsa-utils \
  flac \
  nodejs npm
```

- [ ] **Step 3: Commit**

```bash
git add services/boombox-buttons.py install/install.sh
git commit -m "buttons(record): parec -> flac pipeline with toggle handler

Recorder.start/stop manages a parec --monitor-stream | flac pipeline,
writing ~/Music/Recordings/YYYY-MM-DD-HHMMSS.flac. The record button
toggles; SPA gets boombox:record events with on/off + path."
```

---

### Task 12: Source + kiosk action handlers

**Files:**
- Modify: `services/boombox-buttons.py` (source handlers section)

- [ ] **Step 1: Add the source handlers**

Append to the dispatcher handlers in `services/boombox-buttons.py`:

```python
# Source switch handlers
@_handler("library", "short_press")
async def _h_library(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.navigate("http://localhost/")


@_handler("airplay", "short_press")
async def _h_airplay(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.emit("source-overlay", {"source": "airplay"})


@_handler("spotify", "short_press")
async def _h_spotify(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.emit("source-overlay", {"source": "spotify"})


@_handler("bluetooth", "short_press")
async def _h_bluetooth(d: Dispatcher):
    if d.state:
        await d.state.bluetooth_pair()
    if d.kiosk:
        await d.kiosk.emit("source-overlay", {"source": "bluetooth"})


@_handler("movies", "short_press")
async def _h_movies(d: Dispatcher):
    """Toggle between SPA and Jellyfin. The kiosk-guard service is already
    aware of Jellyfin via the SourceSwitcher SPA logic; we just navigate."""
    if d.mopidy:
        await d.mopidy.call("core.playback.pause")
    if d.kiosk:
        await d.kiosk.navigate("http://localhost:8096/web/index.html#/home")


@_handler("web", "short_press")
async def _h_web(d: Dispatcher):
    """Toggle the LAN web access state + show a QR overlay. The SPA owns
    the toggle bookkeeping; we just emit and let it call /upload/enable
    or /upload/disable."""
    if d.kiosk:
        await d.kiosk.emit("web-qr", {})


@_handler("skin_cycle", "short_press")
async def _h_skin(d: Dispatcher):
    if d.kiosk:
        await d.kiosk.emit("skin-cycle", {})


# Microphone / karaoke
@_handler("mic_karaoke", "short_press")
async def _h_mic(d: Dispatcher):
    if d.state:
        await d.state.karaoke_toggle()


# Previous/Next long-press scrub. While held, each long_hold tick seeks 5s.
async def _scrub(d: Dispatcher, delta_ms: int) -> None:
    if d.mopidy is None:
        return
    res = await d.mopidy.call("core.playback.get_time_position")
    cur = (res or {}).get("result") or 0
    await d.mopidy.call("core.playback.seek", {"time_position": max(0, cur + delta_ms)})


_HANDLERS[("previous", "long_press")] = lambda d: _scrub(d, -5000)
_HANDLERS[("previous", "long_hold")]  = lambda d: _scrub(d, -5000)
_HANDLERS[("next",     "long_press")] = lambda d: _scrub(d, +5000)
_HANDLERS[("next",     "long_hold")]  = lambda d: _scrub(d, +5000)
```

- [ ] **Step 2: Deploy + verify service starts**

```bash
./pi deploy services/ /opt/boombox/services/
./pi ssh "systemctl --user restart boombox-buttons && journalctl --user-unit boombox-buttons -n 30 --no-pager"
```

Expected: clean startup, "gpio pins: ..." line listing all enabled actions.

- [ ] **Step 3: Commit**

```bash
git add services/boombox-buttons.py
git commit -m "buttons(sources): library/airplay/spotify/bluetooth/movies/web/skin handlers

Adds all source-side handlers plus mic_karaoke and prev/next long-press
scrub. Library and Movies use kiosk.navigate; AirPlay/Spotify/Bluetooth/
Web/Skin use kiosk.emit so the SPA owns the overlay UI. Bluetooth also
calls state.bluetooth_pair to actually kick off pairing."
```

---

### Task 13: Add /volume/mute endpoint to boombox-state

**Files:**
- Modify: `services/boombox-state.py`

- [ ] **Step 1: Add the mute toggle handler**

Find the `volume_set` function in `services/boombox-state.py` (around line 230). Right after it, insert:

```python
async def volume_mute_toggle(_request: web.Request) -> web.Response:
    """POST /volume/mute toggles the default sink's mute state."""
    rc, out = await run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
    if rc != 0:
        return web.json_response({"ok": False, "error": out}, status=502)
    # Re-read to surface the resulting state.
    rc, out = await run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    muted = "MUTED" in out if rc == 0 else None
    return web.json_response({"ok": True, "muted": muted})
```

Then find the `def setup_routes(app)` or `app.router.add_*` block near line 956 and add:

```python
    app.router.add_post("/volume/mute", volume_mute_toggle)
```

- [ ] **Step 2: Deploy + verify**

```bash
./pi deploy services/ /opt/boombox/services/
./pi ssh "systemctl --user restart boombox-state"
./pi ssh "curl -s -X POST http://127.0.0.1:6681/volume/mute"
./pi ssh "curl -s http://127.0.0.1:6681/volume"
./pi ssh "curl -s -X POST http://127.0.0.1:6681/volume/mute"
```

Expected: first POST returns `{"ok": true, "muted": true}` (or false depending on starting state); GET shows `muted: true`; second POST flips back.

- [ ] **Step 3: Commit**

```bash
git add services/boombox-state.py
git commit -m "state(volume): POST /volume/mute toggles default-sink mute

Wraps `wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle` and surfaces the
resulting muted state. Called by the rotary encoder push handler in
boombox-buttons."
```

---

### Task 14: Buttons HTTP API server on :6683

**Files:**
- Modify: `services/boombox-buttons.py` (HTTP API section)
- Modify: `install/config/nginx-boombox-common.conf` (add /api/buttons/ route)

- [ ] **Step 1: Add the aiohttp server in boombox-buttons.py**

Insert at the bottom of `services/boombox-buttons.py`, just before `if __name__ == "__main__":`:

```python
# ---------- Settings HTTP API ---------------------------------------------

from aiohttp import web

BUTTONS_API_PORT = 6683


async def _http_api(cfg_ref: list, dispatcher_ref: list, learn_state: dict) -> web.AppRunner:
    """cfg_ref and dispatcher_ref are single-element lists so the handlers
    can mutate them when the config hot-reloads.

    learn_state is a dict shared with the GPIO loop; when in learn mode it
    is {"action": "<name>", "until": <t_ms>, "result": None|<pin>}.
    """
    async def get_config(_req):
        return web.json_response(cfg_ref[0])

    async def post_config(req):
        body = await req.json()
        CONFIG_PATH.write_text(json.dumps(body, indent=2))
        return web.json_response({"ok": True})

    async def post_learn(req):
        body = await req.json()
        action = body.get("action")
        if not action:
            return web.json_response({"ok": False, "error": "action required"}, status=400)
        loop = asyncio.get_running_loop()
        learn_state["action"] = action
        learn_state["until"] = int(loop.time() * 1000) + 5000
        learn_state["result"] = None
        # Poll for up to 5s for a captured pin.
        for _ in range(50):
            await asyncio.sleep(0.1)
            if learn_state.get("result") is not None:
                pin = learn_state["result"]
                learn_state["action"] = None
                return web.json_response({"ok": True, "action": action, "pin": pin})
        learn_state["action"] = None
        return web.json_response({"ok": False, "error": "no press detected"}, status=408)

    async def post_test(req):
        body = await req.json()
        action = body.get("action")
        event = body.get("event", "short_press")
        if not action or dispatcher_ref[0] is None:
            return web.json_response({"ok": False, "error": "action required"}, status=400)
        await dispatcher_ref[0].dispatch(action, event)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/config", get_config)
    app.router.add_post("/config", post_config)
    app.router.add_post("/learn", post_learn)
    app.router.add_post("/test", post_test)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", BUTTONS_API_PORT)
    await site.start()
    log.info("buttons HTTP API listening on 127.0.0.1:%d", BUTTONS_API_PORT)
    return runner
```

Modify `main()`: just before `await gpio_loop(...)`, add:

```python
        cfg_ref = [cfg]
        dispatcher_ref = [dispatcher]
        learn_state: dict = {"action": None, "until": 0, "result": None}
        api_runner = await _http_api(cfg_ref, dispatcher_ref, learn_state)
```

And inside the `gpio_loop` function, every place that dispatches a button press, also check learn mode. Specifically modify the section in `gpio_loop` that handles button edges. Replace:

```python
                else:
                    edge = "down" if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else "up"
                    for evt in classifiers[action].feed(t_ms, edge):
                        await dispatcher.dispatch(action, evt[0])
```

with:

```python
                else:
                    edge = "down" if ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE else "up"
                    if edge == "down" and learn_state.get("action") and t_ms < learn_state.get("until", 0):
                        learn_state["result"] = ev.line_offset
                        continue   # don't dispatch, just capture
                    for evt in classifiers[action].feed(t_ms, edge):
                        await dispatcher.dispatch(action, evt[0])
```

Note: `learn_state` is captured from the enclosing scope of `main()`. To make that work, `gpio_loop` needs `learn_state` passed in. Change the signature:

```python
async def gpio_loop(cfg: dict, dispatcher: Dispatcher, stop: asyncio.Event,
                   learn_state: dict | None = None) -> None:
```

And in `main()`:

```python
        await gpio_loop(cfg, dispatcher, stop, learn_state=learn_state)
```

If `learn_state is None`, default to `{"action": None, "until": 0, "result": None}` at the top of `gpio_loop`.

- [ ] **Step 2: Add nginx route**

Edit `install/config/nginx-boombox-common.conf`. Find the existing `location /api/` block and add a sibling block immediately after:

```nginx
# boombox-buttons settings API (config, learn, test).
location /api/buttons/ {
    proxy_pass http://127.0.0.1:6683/;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_read_timeout 30s;
}
```

- [ ] **Step 3: Deploy + verify**

```bash
./pi deploy services/ /opt/boombox/services/
./pi deploy install/config/nginx-boombox-common.conf /opt/boombox/install/config/nginx-boombox-common.conf
./pi ssh "sudo install -m 0644 /opt/boombox/install/config/nginx-boombox-common.conf /etc/nginx/snippets/boombox-common.conf && sudo nginx -t && sudo systemctl reload nginx"
./pi ssh "systemctl --user restart boombox-buttons"
./pi ssh "curl -s http://127.0.0.1/api/buttons/config | jq .long_press_ms"
```

Expected: `600`.

```bash
./pi ssh "curl -s -X POST http://127.0.0.1/api/buttons/test -H 'Content-Type: application/json' -d '{\"action\":\"play_pause\"}'"
```

Expected: `{"ok":true}` and a journal line showing the dispatch fired.

- [ ] **Step 4: Commit**

```bash
git add services/boombox-buttons.py install/config/nginx-boombox-common.conf
git commit -m "buttons(api): :6683 HTTP server for config/learn/test + nginx route

Exposes GET/POST /config, POST /learn (waits up to 5s for a falling edge
and returns the captured BCM pin), POST /test (dispatches an action
without GPIO). nginx fronts at /api/buttons/. Used by the Settings
drawer panel."
```

---

### Task 15: ButtonsPanel in Settings drawer

**Files:**
- Create: `ui/src/lib/buttonsApi.ts`
- Create: `ui/src/lib/ButtonsPanel.tsx`
- Modify: `ui/src/lib/SettingsDrawer.tsx` (mount the new panel)

- [ ] **Step 1: Create the typed API client**

`ui/src/lib/buttonsApi.ts`:

```typescript
export type ButtonsConfig = {
  long_press_ms: number;
  power_hold_ms: number;
  encoder_step: number;
  pins: Record<string, { pin: number | null; enabled: boolean }>;
  encoder: { pin_a: number | null; pin_b: number | null; pin_push: number | null; enabled: boolean };
};

export async function getConfig(): Promise<ButtonsConfig> {
  const r = await fetch("/api/buttons/config");
  if (!r.ok) throw new Error(`config GET failed: ${r.status}`);
  return r.json();
}

export async function saveConfig(cfg: ButtonsConfig): Promise<void> {
  const r = await fetch("/api/buttons/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error(`config POST failed: ${r.status}`);
}

export async function learn(action: string): Promise<{ ok: boolean; pin?: number; error?: string }> {
  const r = await fetch("/api/buttons/learn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return r.json();
}

export async function test(action: string): Promise<void> {
  await fetch("/api/buttons/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}

export const ACTION_LABELS: Record<string, string> = {
  play_pause: "Play / Pause",
  stop: "Stop",
  previous: "Previous",
  next: "Next",
  shuffle: "Shuffle",
  repeat: "Repeat",
  sleep_timer: "Sleep timer",
  skin_cycle: "Skin cycle",
  library: "Library",
  airplay: "AirPlay",
  spotify: "Spotify",
  bluetooth: "Bluetooth",
  movies: "Movies",
  web: "Web",
  mic_karaoke: "Mic / Karaoke",
  record: "Record",
  power: "Power",
};
```

- [ ] **Step 2: Create the ButtonsPanel component**

`ui/src/lib/ButtonsPanel.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { ACTION_LABELS, ButtonsConfig, getConfig, learn, saveConfig, test } from "./buttonsApi";

export function ButtonsPanel() {
  const [cfg, setCfg] = useState<ButtonsConfig | null>(null);
  const [learning, setLearning] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  useEffect(() => { getConfig().then(setCfg).catch(e => setStatus(`load failed: ${e.message}`)); }, []);

  const updateRow = useCallback((action: string, patch: Partial<ButtonsConfig["pins"][string]>) => {
    if (!cfg) return;
    const next = { ...cfg, pins: { ...cfg.pins, [action]: { ...cfg.pins[action], ...patch } } };
    setCfg(next);
    saveConfig(next).catch(e => setStatus(`save failed: ${e.message}`));
  }, [cfg]);

  const onLearn = useCallback(async (action: string) => {
    setLearning(action);
    setStatus(`press a button to bind to ${ACTION_LABELS[action] ?? action}…`);
    try {
      const r = await learn(action);
      if (r.ok && r.pin != null) {
        updateRow(action, { pin: r.pin });
        setStatus(`captured BCM${r.pin}`);
      } else {
        setStatus(r.error ?? "no press detected");
      }
    } finally {
      setLearning(null);
    }
  }, [updateRow]);

  const onTest = useCallback((action: string) => {
    test(action).catch(() => {});
    setStatus(`fired ${ACTION_LABELS[action] ?? action}`);
  }, []);

  if (!cfg) return <div style={{ padding: 16 }}>loading buttons…</div>;

  return (
    <div style={{ padding: 16, display: "grid", gap: 8 }}>
      <div style={{ fontWeight: 700, fontSize: 14 }}>Physical buttons</div>
      {status && <div style={{ fontSize: 12, opacity: 0.7 }}>{status}</div>}
      <table style={{ width: "100%", fontSize: 13 }}>
        <thead>
          <tr><th align="left">Action</th><th>Pin</th><th>Enabled</th><th></th><th></th></tr>
        </thead>
        <tbody>
          {Object.entries(ACTION_LABELS).map(([action, label]) => {
            const row = cfg.pins[action];
            if (!row) return null;
            return (
              <tr key={action} style={{ background: learning === action ? "rgba(255,200,0,0.15)" : "transparent" }}>
                <td>{label}</td>
                <td align="center">{row.pin ?? "—"}</td>
                <td align="center">
                  <input type="checkbox" checked={row.enabled} onChange={e => updateRow(action, { enabled: e.target.checked })} />
                </td>
                <td><button onClick={() => onTest(action)}>Test</button></td>
                <td><button onClick={() => onLearn(action)} disabled={learning != null}>Learn</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Mount in SettingsDrawer**

Read `ui/src/lib/SettingsDrawer.tsx` and identify its existing panel structure (look for tab names / collapsible sections). Add a new section that imports and renders `<ButtonsPanel/>`. The exact structure depends on the existing component; the change will look like:

```tsx
import { ButtonsPanel } from "./ButtonsPanel";

// inside the drawer's content:
<section>
  <h3>Buttons</h3>
  <ButtonsPanel />
</section>
```

If `SettingsDrawer.tsx` uses tabs, add a `"buttons"` tab entry following the same pattern as existing tabs.

- [ ] **Step 4: Build the UI and deploy**

```bash
cd ui && npm run build && cd ..
./pi deploy ui/dist/ /var/www/boombox/
./pi reload
```

Open the kiosk, open the Settings drawer, navigate to Buttons. Confirm: 17 rows render, each shows its pin, the Enabled toggle persists across reloads, Test fires the action (visible in `journalctl --user-unit boombox-buttons -f`), Learn prompts and captures the next press.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/buttonsApi.ts ui/src/lib/ButtonsPanel.tsx ui/src/lib/SettingsDrawer.tsx
git commit -m "ui(buttons): Settings drawer panel for pin/enable/learn/test

ButtonsPanel renders all 17 actions with: current pin, enabled toggle,
Test button (dispatches without GPIO), Learn button (5s capture window
that writes the next falling-edge pin into buttons.json). Live-saved
via POST /api/buttons/config; hot-reload picks it up automatically."
```

---

### Task 16: Kiosk overlays — QR, Sleep OSD, Record indicator, Source instructions

**Files:**
- Create: `ui/src/overlays/QrOverlay.tsx`
- Create: `ui/src/overlays/SleepOsd.tsx`
- Create: `ui/src/overlays/RecordIndicator.tsx`
- Create: `ui/src/overlays/SourceInstructionOverlay.tsx`
- Create: `ui/src/overlays/ShutdownOverlay.tsx`
- Create: `ui/src/overlays/OverlayRoot.tsx`
- Modify: `ui/src/App.tsx` (mount OverlayRoot)
- Modify: `ui/package.json` (qrcode lib)

- [ ] **Step 1: Install QR code library**

```bash
cd ui && npm install qrcode.react@^4 && cd ..
```

- [ ] **Step 2: Create the overlay components**

`ui/src/overlays/QrOverlay.tsx`:

```tsx
import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

export function QrOverlay() {
  const [visible, setVisible] = useState(false);
  const [info, setInfo] = useState<{ url: string; user: string; pin: string } | null>(null);

  useEffect(() => {
    const onShow = async () => {
      try {
        const r = await fetch("/api/upload/enable", { method: "POST" });
        const body = await r.json();
        setInfo({
          url: body.url ?? `http://${location.hostname}:8090/`,
          user: body.user ?? "boombox",
          pin: body.pin ?? "—",
        });
      } catch {
        setInfo({ url: `http://${location.hostname}:8090/`, user: "boombox", pin: "—" });
      }
      setVisible(v => !v);
    };
    window.addEventListener("boombox:web-qr", onShow as EventListener);
    return () => window.removeEventListener("boombox:web-qr", onShow as EventListener);
  }, []);

  if (!visible || !info) return null;
  const value = `${info.url}#user=${info.user}&pin=${info.pin}`;
  return (
    <div onClick={() => setVisible(false)} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9999,
    }}>
      <div style={{ display: "grid", gap: 12, placeItems: "center" }}>
        <div style={{ background: "white", padding: 16 }}>
          <QRCodeSVG value={value} size={320} />
        </div>
        <div style={{ fontSize: 18 }}>{info.url}</div>
        <div style={{ fontSize: 14, opacity: 0.7 }}>user: {info.user}  pin: {info.pin}</div>
        <div style={{ fontSize: 12, opacity: 0.5 }}>tap to dismiss</div>
      </div>
    </div>
  );
}
```

`ui/src/overlays/SleepOsd.tsx`:

```tsx
import { useEffect, useState } from "react";

export function SleepOsd() {
  const [mins, setMins] = useState<number | null>(null);
  useEffect(() => {
    let timer: number | undefined;
    const onTimer = (e: Event) => {
      const detail = (e as CustomEvent).detail as { minutes: number | null };
      setMins(detail.minutes);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setMins(prev => prev), 2000); // OSD stays visible
    };
    const onExpired = () => setMins(null);
    window.addEventListener("boombox:sleep-timer", onTimer as EventListener);
    window.addEventListener("boombox:sleep-expired", onExpired);
    return () => {
      window.removeEventListener("boombox:sleep-timer", onTimer as EventListener);
      window.removeEventListener("boombox:sleep-expired", onExpired);
    };
  }, []);
  if (mins == null) return null;
  return (
    <div style={{
      position: "fixed", top: 24, left: "50%", transform: "translateX(-50%)",
      background: "rgba(0,0,0,0.8)", color: "white", padding: "8px 16px",
      borderRadius: 12, fontSize: 16, zIndex: 9998,
    }}>
      Sleep: {mins} min
    </div>
  );
}
```

`ui/src/overlays/RecordIndicator.tsx`:

```tsx
import { useEffect, useState } from "react";

export function RecordIndicator() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { on: boolean };
      setOn(detail.on);
    };
    window.addEventListener("boombox:record", handler as EventListener);
    return () => window.removeEventListener("boombox:record", handler as EventListener);
  }, []);
  if (!on) return null;
  return (
    <div style={{
      position: "fixed", top: 12, right: 12, zIndex: 9997,
      display: "flex", alignItems: "center", gap: 6,
      background: "rgba(0,0,0,0.6)", padding: "4px 10px", borderRadius: 12,
      color: "white", fontSize: 14, fontWeight: 600,
    }}>
      <span style={{
        width: 10, height: 10, background: "red", borderRadius: "50%",
        animation: "rec-pulse 1.2s infinite",
      }} />
      REC
      <style>{`@keyframes rec-pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.3 } }`}</style>
    </div>
  );
}
```

`ui/src/overlays/SourceInstructionOverlay.tsx`:

```tsx
import { useEffect, useState } from "react";

const COPY: Record<string, { title: string; body: string }> = {
  airplay:  { title: "AirPlay", body: "Tap the AirPlay icon on your iPhone, iPad, or Mac and pick \"Boombox\"." },
  spotify:  { title: "Spotify", body: "Open Spotify on any device, tap Devices, and pick \"Boombox\"." },
  bluetooth:{ title: "Bluetooth", body: "Pairing is open for 60 seconds. Pair your phone to \"Boombox\"." },
};

export function SourceInstructionOverlay() {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { source: string };
      setSource(detail.source);
      setTimeout(() => setSource(null), 5000);
    };
    window.addEventListener("boombox:source-overlay", handler as EventListener);
    return () => window.removeEventListener("boombox:source-overlay", handler as EventListener);
  }, []);
  if (!source || !COPY[source]) return null;
  const { title, body } = COPY[source];
  return (
    <div onClick={() => setSource(null)} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", color: "white",
      display: "grid", placeItems: "center", zIndex: 9998, padding: 32,
    }}>
      <div style={{ textAlign: "center", maxWidth: 640 }}>
        <div style={{ fontSize: 36, fontWeight: 700, marginBottom: 16 }}>{title}</div>
        <div style={{ fontSize: 20, lineHeight: 1.4 }}>{body}</div>
      </div>
    </div>
  );
}
```

`ui/src/overlays/ShutdownOverlay.tsx`:

```tsx
import { useEffect, useState } from "react";

export function ShutdownOverlay() {
  const [seconds, setSeconds] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    let timer: number | undefined;
    const onCountdown = (e: Event) => {
      const detail = (e as CustomEvent).detail as { seconds: number };
      setSeconds(detail.seconds);
      let s = detail.seconds;
      timer = window.setInterval(() => {
        s -= 1;
        if (s <= 0) { window.clearInterval(timer); setSeconds(0); }
        else setSeconds(s);
      }, 1000);
    };
    const onConfirm = () => { setConfirmed(true); window.clearInterval(timer); };
    window.addEventListener("boombox:shutdown-countdown", onCountdown as EventListener);
    window.addEventListener("boombox:shutdown-confirm", onConfirm);
    return () => {
      window.removeEventListener("boombox:shutdown-countdown", onCountdown as EventListener);
      window.removeEventListener("boombox:shutdown-confirm", onConfirm);
      window.clearInterval(timer);
    };
  }, []);
  if (seconds == null) return null;
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.9)", color: "white",
      display: "grid", placeItems: "center", zIndex: 10000, fontSize: 48, fontWeight: 700,
    }}>
      {confirmed ? "Shutting down…" : `Power off in ${seconds}s — release to cancel`}
    </div>
  );
}
```

`ui/src/overlays/OverlayRoot.tsx`:

```tsx
import { QrOverlay } from "./QrOverlay";
import { SleepOsd } from "./SleepOsd";
import { RecordIndicator } from "./RecordIndicator";
import { SourceInstructionOverlay } from "./SourceInstructionOverlay";
import { ShutdownOverlay } from "./ShutdownOverlay";

export function OverlayRoot() {
  return (
    <>
      <QrOverlay />
      <SleepOsd />
      <RecordIndicator />
      <SourceInstructionOverlay />
      <ShutdownOverlay />
    </>
  );
}
```

- [ ] **Step 3: Mount in App.tsx**

Add the import and render alongside the main app content:

```tsx
import { OverlayRoot } from "./overlays/OverlayRoot";

// inside the main App component's returned JSX, at the top of the root:
<>
  <OverlayRoot />
  {/* existing app content */}
</>
```

- [ ] **Step 4: Build and deploy**

```bash
cd ui && npm run build && cd ..
./pi deploy ui/dist/ /var/www/boombox/
./pi reload
```

Manual smoke test, from the Mac:

```bash
# Trigger each overlay via the test endpoint.
./pi ssh "curl -s -X POST http://127.0.0.1/api/buttons/test -H 'Content-Type: application/json' -d '{\"action\":\"web\"}'"
./pi shot
# Inspect ./screenshots/shot-*.png — should show the QR overlay.

./pi ssh "curl -s -X POST http://127.0.0.1/api/buttons/test -H 'Content-Type: application/json' -d '{\"action\":\"sleep_timer\"}'"
./pi shot
# Should show "Sleep: 15 min" toast top-center.

./pi ssh "curl -s -X POST http://127.0.0.1/api/buttons/test -H 'Content-Type: application/json' -d '{\"action\":\"airplay\"}'"
./pi shot
# Should show the AirPlay instruction overlay.
```

- [ ] **Step 5: Commit**

```bash
git add ui/src/overlays/ ui/src/App.tsx ui/package.json ui/package-lock.json
git commit -m "ui(overlays): QR, sleep OSD, record indicator, source/shutdown overlays

Five overlay components mounted via OverlayRoot, each listening on a
boombox:<event> custom event from the buttons service's KioskClient:
- QrOverlay (web button): full-screen QR + URL + creds
- SleepOsd (sleep timer): top-center toast with current duration
- RecordIndicator: pulsing REC dot top-right while recording
- SourceInstructionOverlay (AirPlay/Spotify/Bluetooth)
- ShutdownOverlay: 2-second countdown for the power long-press"
```

---

### Task 17: Config hot-reload (watchdog)

**Files:**
- Modify: `services/boombox-buttons.py` (hot-reload section)

- [ ] **Step 1: Add the file watcher in main()**

In `services/boombox-buttons.py`, modify `main()` to spin up a watcher that re-loads the config and restarts `gpio_loop` cleanly:

Replace the `main()` body's `await gpio_loop(cfg, dispatcher, stop, learn_state=learn_state)` line with:

```python
        # Wrap the loop so we can rebuild it on config change.
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        reload_event = asyncio.Event()
        loop_ref = asyncio.get_running_loop()

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if Path(event.src_path) == CONFIG_PATH:
                    loop_ref.call_soon_threadsafe(reload_event.set)

        observer = Observer()
        observer.schedule(_Handler(), str(CONFIG_PATH.parent), recursive=False)
        observer.start()

        try:
            while True:
                stop = asyncio.Event()
                loop_task = asyncio.create_task(
                    gpio_loop(cfg, dispatcher, stop, learn_state=learn_state)
                )
                wait_reload = asyncio.create_task(reload_event.wait())
                done, _ = await asyncio.wait(
                    {loop_task, wait_reload}, return_when=asyncio.FIRST_COMPLETED
                )
                if wait_reload in done:
                    log.info("config changed; rebuilding gpio loop")
                    reload_event.clear()
                    stop.set()
                    await loop_task
                    cfg = load_config()
                    cfg_ref[0] = cfg
                    dispatcher.disabled = {a for a, e in cfg["pins"].items() if not e.get("enabled")}
                    continue
                break
        finally:
            observer.stop()
            observer.join()
            await api_runner.cleanup()
```

- [ ] **Step 2: Deploy and verify**

```bash
./pi deploy services/ /opt/boombox/services/
./pi ssh "systemctl --user restart boombox-buttons"
# Edit the config remotely and watch for the reload log line.
./pi ssh 'sudo jq ".pins.stop.enabled = false" /etc/boombox/buttons.json | sudo tee /etc/boombox/buttons.json.tmp >/dev/null && sudo mv /etc/boombox/buttons.json.tmp /etc/boombox/buttons.json'
./pi ssh "journalctl --user-unit boombox-buttons -n 10 --no-pager | grep -i reload"
```

Expected: a log line `config changed; rebuilding gpio loop`.

Restore the config:

```bash
./pi ssh 'sudo jq ".pins.stop.enabled = true" /etc/boombox/buttons.json | sudo tee /etc/boombox/buttons.json.tmp >/dev/null && sudo mv /etc/boombox/buttons.json.tmp /etc/boombox/buttons.json'
```

- [ ] **Step 3: Commit**

```bash
git add services/boombox-buttons.py
git commit -m "buttons(reload): watchdog-driven hot-reload of buttons.json

A FileSystemEventHandler watches /etc/boombox/buttons.json. On modify
events, the running gpio_loop is signalled to stop, the config is
re-read, and the loop restarts with the new pin set. The settings panel
saves through the same path so edits in the UI take effect within ~1s
with no systemctl restart."
```

---

### Task 18: Installer + docs

**Files:**
- Modify: `install/install.sh` (atomic-overwrite of buttons.json on schema bump)
- Modify: `docs/SERVICES.md`
- Modify: `docs/ARCHITECTURE.md` (port table)
- Modify: `README.md` (if the services table mentions buttons)

- [ ] **Step 1: Update install.sh to handle schema bump**

The existing install.sh installs `buttons.json` only if `/etc/boombox/buttons.json` doesn't exist (line 363-364). For users upgrading from the old 5-action schema, force-overwrite if the file lacks the new keys. Replace the block:

```bash
sudo mkdir -p /etc/boombox
if [[ ! -f /etc/boombox/buttons.json ]]; then
  sudo install -m 0644 "$SCRIPT_DIR/config/buttons.json" /etc/boombox/buttons.json
fi
```

with:

```bash
sudo mkdir -p /etc/boombox
if [[ ! -f /etc/boombox/buttons.json ]]; then
  sudo install -m 0644 "$SCRIPT_DIR/config/buttons.json" /etc/boombox/buttons.json
elif ! sudo grep -q '"power"' /etc/boombox/buttons.json; then
  # Old 5-action schema detected; back up and replace with the full one.
  log "upgrading buttons.json schema (backup at /etc/boombox/buttons.json.pre-fullbuttons)"
  sudo cp /etc/boombox/buttons.json /etc/boombox/buttons.json.pre-fullbuttons
  sudo install -m 0644 "$SCRIPT_DIR/config/buttons.json" /etc/boombox/buttons.json
fi
```

- [ ] **Step 2: Update docs/SERVICES.md**

Find the `boombox-buttons` row and replace with:

```markdown
### `boombox-buttons` — GPIO control surface

User unit. Drives 17 buttons + 1 rotary encoder over `/dev/gpiochip0`. Pin
map at `/etc/boombox/buttons.json`; hot-reloaded on save. Exposes
`/api/buttons/{config,learn,test}` (port 6683, nginx-fronted) for the
Settings drawer's Buttons panel.

Routing:
- Mopidy is the active source -> Mopidy RPC at `:6680/mopidy/rpc`.
- Anything else live -> `boombox-state /control/<action>`.
- Encoder rotate -> `/volume`; push -> `/volume/mute`.
- Source overlays, swap-to-Jellyfin, QR, sleep OSD, record indicator,
  shutdown countdown -> Chromium DevTools (`:9222`) custom events:
  `boombox:web-qr`, `boombox:sleep-timer`, `boombox:sleep-expired`,
  `boombox:record`, `boombox:source-overlay`,
  `boombox:shutdown-countdown`, `boombox:shutdown-confirm`,
  `boombox:skin-cycle`.

GPIO budget on a Pi 5 + HiFiBerry DAC+ Pro is 20 pins after disabling SPI
and UART0 (see `install/config/usercfg.txt`). Free pins: 4-13, 16-17,
22-27. Reserved by DAC: 0-3, 18-21.

Debug:
- `journalctl --user-unit boombox-buttons -f`
- `curl http://127.0.0.1/api/buttons/config | jq`
- `pinctrl get` on the Pi to see line states.
```

- [ ] **Step 3: Update docs/ARCHITECTURE.md port table**

Add a row to the port table:

```markdown
| `boombox-buttons` HTTP API | 6683 | localhost only; nginx-fronted at `/api/buttons/` |
```

- [ ] **Step 4: Smoke-test full installer on Pi**

```bash
./pi deploy install/ /opt/boombox/install/
./pi ssh "/opt/boombox/install/install.sh"
./pi ssh "systemctl --user status boombox-buttons | head -10"
```

Expected: active (running), no errors.

- [ ] **Step 5: Commit**

```bash
git add install/install.sh docs/SERVICES.md docs/ARCHITECTURE.md
git commit -m "buttons(install): schema-bump migration + docs update

install.sh detects the old 5-action buttons.json and backs it up before
replacing with the full schema. SERVICES.md and ARCHITECTURE.md updated
to reflect the new :6683 HTTP API, the full action inventory, and the
SPI/UART0 GPIO-budget tradeoff."
```

---

## Self-review

**Spec coverage:**
- 17 buttons + encoder (spec §Inventory) → Tasks 4-12 cover all handlers; pin map in Task 3.
- Pi system changes (spec §Pi system changes) → Task 1.
- Dual-purpose semantics (spec §Dual-purpose semantics) → Press classifier in Task 4; prev/next scrub + power short/long in Tasks 9 + 12.
- Power button safety (spec §Power button safety) → Task 9 + ShutdownOverlay in Task 16.
- Action dispatch architecture (spec §Action dispatch) → Tasks 6 (router), 7 (clients), 13 (mute endpoint).
- Config schema (spec §Config schema) → Task 3.
- Settings UI (spec §Settings UI) → Task 15 + supporting API in Task 14.
- LED extension is noted as future-only; no task — consistent with spec §Future extension.
- Risks (spec §Risks): legacy handler removal in Task 1; SPI/UART note in install docs in Task 18; long-press tuning is the JSON value in Task 3; encoder debouncing at 1ms in Task 8; `/control` already exists (verified); hot-reload line lease handled by Task 17's stop+await pattern.

**Placeholder scan:** No "TBD" / "TODO" / "implement later". Every step has executable content. The SettingsDrawer integration in Task 15 step 3 says "the exact structure depends on the existing component" but provides the JSX shape and explicit guidance — the engineer reads the file first per the instruction; this is concrete, not a placeholder.

**Type consistency:** `default_config`, `load_config`, `enabled_pins`, `pin_conflicts` defined in Task 3 and used by tests; `PressClassifier` API consistent across Tasks 4/8; `EncoderDecoder` same; `Dispatcher` fields match between Tasks 6, 7, 9-12; `Display`, `Recorder`, `SleepTimer`, `StateApi`, `KioskClient`, `MopidyRpc` all keep stable signatures. Action name strings match the JSON config keys throughout.

---

## Execution choice

Plan complete and saved to `docs/superpowers/plans/2026-05-12-gpio-buttons.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration. Best fit here because the plan has 18 tasks spanning Python, TypeScript, system config, and installer — each subagent gets a clean context window for its slice.

2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
