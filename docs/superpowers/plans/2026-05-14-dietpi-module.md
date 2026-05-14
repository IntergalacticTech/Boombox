# DietPi Install Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DietPi as a second supported install target by extracting the OS-specific graphical-session bootstrap out of `install.sh` into a pluggable `install/session/<os>.sh` component, and writing a new `dietpi.sh` that creates the Wayland session DietPi Lite lacks.

**Architecture:** `install.sh` auto-detects the OS (`detect_os()` in `install/session/detect-os.sh`) and sources `install/session/<os>.sh`, which defines `setup_graphical_session()`. `rpi-os.sh` is a verbatim lift-and-shift of today's behavior (legacy-autostart sweep + `/etc/xdg/labwc/autostart` override). `dietpi.sh` is new: apt-installs `labwc` + Wayland tools, configures tty1 getty autologin, and drops a guarded `labwc` launcher into the boombox user's `~/.bash_profile`. The ~80% OS-agnostic install stays in `install.sh`.

**Tech Stack:** Bash (the installer + the session component); pytest (the `detect_os` unit test, which shells out to bash).

**Spec:** `docs/superpowers/specs/2026-05-14-dietpi-module-design.md`

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `install/session/detect-os.sh` | **New.** Defines `detect_os()` → `dietpi` or `rpi-os`. Sourced by `install.sh` and by the unit test. Pure function, no side effects. |
| `install/session/rpi-os.sh` | **New.** Defines `setup_graphical_session()` for Raspberry Pi OS — the legacy-autostart sweep and the `/etc/xdg/labwc/autostart` override, lifted verbatim out of `install.sh`. |
| `install/session/dietpi.sh` | **New.** Defines `setup_graphical_session()` for DietPi — apt deps, tty1 getty autologin, the guarded `~/.bash_profile` labwc launcher. |
| `services/tests/test_detect_os.py` | **New.** pytest unit test for `detect_os()` — shells out to bash to source `detect-os.sh`. |
| `install/install.sh` | **Modify.** Remove the two inline RPi-OS session blocks; add the `source detect-os.sh` → `detect_os` → `source session/<os>.sh` → `setup_graphical_session` call. |
| `README.md` | **Modify.** Document DietPi as a supported install target and the auto-detect behavior. |

**Task ordering rationale:** Tasks 1–3 each add a *new, not-yet-sourced* file — `install.sh` is untouched and keeps working unchanged through all three. Task 4 is the atomic switch-over: it wires `install.sh` to the new component and removes the now-duplicated inline blocks in the same commit, so the installer is never half-migrated. Task 5 is docs.

---

## Task 1: `detect-os.sh` + unit test

OS detection. A pure bash function with an internal testability seam (`BOOMBOX_DIETPI_MARKER`) so the test can point the dietpi-marker check at a tempdir instead of needing a real `/boot/dietpi`.

**Files:**
- Create: `install/session/detect-os.sh`
- Create: `services/tests/test_detect_os.py`

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_detect_os.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-test/bin/python -m pytest services/tests/test_detect_os.py -v`
Expected: FAIL — all 4 tests error because `install/session/detect-os.sh` does not exist (`bash` exits non-zero on `source` of a missing file, `subprocess.run(check=True)` raises `CalledProcessError`).

- [ ] **Step 3: Create `install/session/detect-os.sh`**

```bash
#!/usr/bin/env bash
# install/session/detect-os.sh — identify the host OS so install.sh can pick
# the right graphical-session bootstrap. SOURCED (not executed) by install.sh
# and by services/tests/test_detect_os.py. Defines one function, detect_os,
# and has no side effects.
#
# detect_os prints one of: dietpi | rpi-os
#   - $BOOMBOX_OS, if set, wins (forces a path — used by tests and for
#     overriding a wrong autodetect).
#   - $BOOMBOX_DIETPI_MARKER (default /boot/dietpi) present → dietpi.
#   - otherwise → rpi-os, the conservative default: an unrecognised Debian
#     gets the established, well-tested path rather than the new one.

detect_os() {
  if [[ -n "${BOOMBOX_OS:-}" ]]; then
    echo "$BOOMBOX_OS"
    return
  fi
  local dietpi_marker="${BOOMBOX_DIETPI_MARKER:-/boot/dietpi}"
  if [[ -d "$dietpi_marker" ]]; then
    echo dietpi
  else
    echo rpi-os
  fi
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv-test/bin/python -m pytest services/tests/test_detect_os.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint the new shell file**

Run: `bash -n install/session/detect-os.sh`
Expected: no output (clean parse).

- [ ] **Step 6: Commit**

```bash
git add install/session/detect-os.sh services/tests/test_detect_os.py
git commit -m "dietpi: detect_os() — OS detection for session-bootstrap dispatch"
```

---

## Task 2: `rpi-os.sh` — extract the RPi-OS session bootstrap

A **verbatim lift-and-shift**. `setup_graphical_session()` contains the two RPi-OS-specific blocks that currently live inline in `install.sh`: the legacy-autostart sweep and the `/etc/xdg/labwc/autostart` override. The commands are copied byte-for-byte (only re-indented two spaces into the function body); `install.sh` is **not** touched in this task — it still has its own inline copies, so the installer keeps working unchanged. The two copies are deduplicated in Task 4.

**Files:**
- Create: `install/session/rpi-os.sh`

- [ ] **Step 1: Create `install/session/rpi-os.sh`**

The body of `setup_graphical_session()` below is lifted verbatim from `install/install.sh` — the `for f in ... chromium-kiosk.desktop ...` sweep, and the `/etc/xdg/labwc/autostart` override `if`-block + `sudo install`. Do not reword the inline comments; they are part of the verbatim lift.

```bash
#!/usr/bin/env bash
# install/session/rpi-os.sh — graphical-session bootstrap for Raspberry Pi
# OS. RPi OS already boots into the rpd-labwc desktop session, so this only
# *tweaks* that existing session to behave as a kiosk.
#
# SOURCED by install.sh, which calls setup_graphical_session right after it
# has installed the shared labwc kiosk config (~/.config/labwc/*). Runs in
# install.sh's environment — relies on $HOME, $ACTIVE_SCRIPT_DIR, and the
# log() helper being defined there.

setup_graphical_session() {
  # Sweep any legacy chromium-kiosk autostart entries — they predate the
  # boombox-kiosk.service and otherwise launch a second, unmanaged kiosk
  # Chromium at session start, fighting with our systemd-managed one.
  for f in "$HOME/.config/autostart/chromium-kiosk.desktop" \
           "$HOME/.config/autostart/chromium-kiosk.desktop.bak" \
           "$HOME/.config/autostart/unclutter.desktop"; do
    if [[ -e "$f" ]]; then
      log "removing legacy autostart: $f"
      rm -f "$f"
    fi
  done

  # Pi OS's rpd-labwc session sources /etc/xdg/labwc/autostart explicitly
  # (not the labwc lookup path), so the user override above isn't enough
  # to keep wf-panel-pi / pcmanfm-pi off the screen. Replace it system-
  # wide. We keep a .pi-os.orig copy in case anyone needs the desktop
  # session back.
  if [[ -f /etc/xdg/labwc/autostart && ! -f /etc/xdg/labwc/autostart.pi-os.orig ]]; then
    sudo cp /etc/xdg/labwc/autostart /etc/xdg/labwc/autostart.pi-os.orig
  fi
  sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/labwc-autostart" /etc/xdg/labwc/autostart
}
```

- [ ] **Step 2: Lint the new shell file**

Run: `bash -n install/session/rpi-os.sh`
Expected: no output (clean parse).

- [ ] **Step 3: Verify the lift is faithful**

Run:
```bash
grep -n 'chromium-kiosk.desktop\|/etc/xdg/labwc/autostart\|labwc-autostart' install/install.sh
```
Expected: `install.sh` still shows its inline copies (lines ~371–373 sweep, ~457–460 override). Confirm the command lines in `rpi-os.sh`'s `setup_graphical_session()` match `install.sh`'s inline versions character-for-character apart from the two-space function indentation — read both and compare. (Task 4 removes the `install.sh` copies; this step proves `rpi-os.sh` is a faithful copy *before* that removal.)

- [ ] **Step 4: Commit**

```bash
git add install/session/rpi-os.sh
git commit -m "dietpi: rpi-os.sh — RPi-OS session bootstrap (verbatim lift)"
```

---

## Task 3: `dietpi.sh` — the new DietPi session bootstrap

The new work. `setup_graphical_session()` for DietPi creates the Wayland session DietPi Lite lacks: it apt-installs the compositor + tools, autologins the boombox user on tty1, and execs `labwc` from that login's shell profile.

**`wlrctl` availability note:** `labwc` and `kanshi` are in Debian's repos (Bookworm and later), so they are installed as hard requirements. `wlrctl` is less common and may not be packaged for the target Debian release — it is therefore installed best-effort with a `warn` on failure. This is safe: the shared `config/labwc-autostart` runs `wlrctl` in a backgrounded subshell (`( sleep 2; wlrctl ... ) &`), so a missing `wlrctl` degrades gracefully (the cursor simply isn't parked off-screen) — consistent with the project's "every feature independently optional" principle.

**Files:**
- Create: `install/session/dietpi.sh`

- [ ] **Step 1: Create `install/session/dietpi.sh`**

```bash
#!/usr/bin/env bash
# install/session/dietpi.sh — graphical-session bootstrap for DietPi.
# DietPi Lite boots to a bare console with no compositor, so this *creates*
# the Wayland session the boombox kiosk needs:
#   1. apt-installs labwc + the Wayland tools the shared labwc-autostart
#      calls (chromium / wvkbd / grim / unclutter are already in
#      install.sh's shared apt line and are not repeated here).
#   2. autologins the boombox user on tty1 via a getty drop-in.
#   3. execs labwc from that login's ~/.bash_profile — guarded so SSH
#      logins and other ttys never spawn a compositor.
#
# SOURCED by install.sh; runs in its environment — relies on $HOME,
# $BOOMBOX_USER, and the log()/warn() helpers being defined there.

setup_graphical_session() {
  # 1. Compositor + Wayland tools. labwc and kanshi are in Debian's repos;
  #    wlrctl may not be packaged for every Debian release, so it is
  #    best-effort — config/labwc-autostart calls it in a backgrounded
  #    subshell, so its absence only means the cursor isn't parked.
  log "installing Wayland session packages (labwc, kanshi)"
  sudo apt install -y labwc kanshi
  if ! sudo apt install -y wlrctl; then
    warn "wlrctl not available in apt — cursor will not be parked off-screen"
  fi

  # 2. Autologin the boombox user on tty1 via a getty drop-in. The empty
  #    ExecStart= line clears the unit's default before the override.
  log "configuring tty1 autologin for $BOOMBOX_USER"
  sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
  sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $BOOMBOX_USER --noclear %I \$TERM
EOF
  sudo systemctl daemon-reload

  # 3. Exec labwc from the boombox user's bash login profile, but ONLY on
  #    the tty1 console login — never over SSH or on another tty. The block
  #    is bounded by markers so re-running install.sh replaces it rather
  #    than appending a duplicate.
  log "installing labwc launcher in ~/.bash_profile"
  local profile="$HOME/.bash_profile"
  touch "$profile"
  local tmp
  tmp="$(mktemp)"
  # Strip any prior boombox block, then append a fresh one.
  sed '/^# >>> boombox session >>>$/,/^# <<< boombox session <<<$/d' \
    "$profile" >"$tmp"
  cat >>"$tmp" <<'EOF'
# >>> boombox session >>>
# Start the Wayland compositor on the tty1 console login. Guarded so SSH
# logins and other ttys never spawn a compositor.
if [ "$(tty)" = "/dev/tty1" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  exec labwc
fi
# <<< boombox session <<<
EOF
  install -m 0644 "$tmp" "$profile"
  rm -f "$tmp"
}
```

- [ ] **Step 2: Lint the new shell file**

Run: `bash -n install/session/dietpi.sh`
Expected: no output (clean parse). This confirms the nested heredocs (`<<EOF` for the getty drop-in, `<<'EOF'` for the profile block) and the function body parse correctly.

The `~/.bash_profile` block uses the standard marker-bounded strip-then-append idiom (`sed '/^marker-start$/,/^marker-end$/d'` then `cat >>`), which is idempotent by construction — re-running it replaces the prior block rather than appending a duplicate. Its real-hardware idempotency is confirmed by the "re-run `install.sh`" step in Manual Verification.

- [ ] **Step 3: Commit**

```bash
git add install/session/dietpi.sh
git commit -m "dietpi: dietpi.sh — create the Wayland session DietPi Lite lacks"
```

---

## Task 4: Wire `install.sh` to the pluggable session component

The atomic switch-over. Remove the two inline RPi-OS session blocks from `install.sh` and replace them with a single `source` + `setup_graphical_session` call. After this commit, `install.sh` no longer carries OS-specific session logic — `detect_os` picks `rpi-os.sh` or `dietpi.sh`.

**Files:**
- Modify: `install/install.sh`

- [ ] **Step 1: Remove the legacy-autostart sweep block**

In `install/install.sh`, find this block (it sits just after the `install -m 0644 "$ACTIVE_SCRIPT_DIR/systemd/user/"*.service ...` line in section 9, before `systemctl --user daemon-reload`) and **delete it entirely**:

```bash
# Sweep any legacy chromium-kiosk autostart entries — they predate the
# boombox-kiosk.service and otherwise launch a second, unmanaged kiosk
# Chromium at session start, fighting with our systemd-managed one.
for f in "$HOME/.config/autostart/chromium-kiosk.desktop" \
         "$HOME/.config/autostart/chromium-kiosk.desktop.bak" \
         "$HOME/.config/autostart/unclutter.desktop"; do
  if [[ -e "$f" ]]; then
    log "removing legacy autostart: $f"
    rm -f "$f"
  fi
done

```
Delete the whole block above **including the blank line after `done`**. The
result: the `install -m 0644 ... *.service ...` line, the blank line that was
already before this block, then `systemctl --user daemon-reload` — one blank
line of separation, no stray double blank. This logic now lives in
`rpi-os.sh`'s `setup_graphical_session()` (Task 2).

- [ ] **Step 2: Replace the `/etc/xdg/labwc/autostart` override with the session-component call**

In `install/install.sh`, find this block (it sits right after the `install -m 0644 "$ACTIVE_SCRIPT_DIR/config/labwc-autostart" "$HOME/.config/labwc/autostart"` line):

```bash

# Pi OS's rpd-labwc session sources /etc/xdg/labwc/autostart explicitly
# (not the labwc lookup path), so the user override above isn't enough
# to keep wf-panel-pi / pcmanfm-pi off the screen. Replace it system-
# wide. We keep a .pi-os.orig copy in case anyone needs the desktop
# session back.
if [[ -f /etc/xdg/labwc/autostart && ! -f /etc/xdg/labwc/autostart.pi-os.orig ]]; then
  sudo cp /etc/xdg/labwc/autostart /etc/xdg/labwc/autostart.pi-os.orig
fi
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/labwc-autostart" /etc/xdg/labwc/autostart
```

Replace that entire block with:

```bash

# Graphical-session bootstrap is OS-specific: RPi OS already has a desktop
# session to tweak; DietPi has none and needs one created from scratch.
# detect_os picks the right install/session/<os>.sh, each of which defines
# setup_graphical_session().
source "$ACTIVE_SCRIPT_DIR/session/detect-os.sh"
BOOMBOX_DETECTED_OS="$(detect_os)"
log "graphical session bootstrap: $BOOMBOX_DETECTED_OS"
SESSION_SCRIPT="$ACTIVE_SCRIPT_DIR/session/$BOOMBOX_DETECTED_OS.sh"
[[ -f "$SESSION_SCRIPT" ]] || fail "no session bootstrap for OS '$BOOMBOX_DETECTED_OS' ($SESSION_SCRIPT)"
source "$SESSION_SCRIPT"
setup_graphical_session
```

The shared lines just above (the `log "installing labwc kiosk config"`, the `mkdir -p "$HOME/.config/labwc"`, and the two `install -m 0644 ... ~/.config/labwc/...` lines) stay exactly as they are — both OSes use the same boombox labwc kiosk config.

- [ ] **Step 3: Lint the modified installer**

Run: `bash -n install/install.sh`
Expected: no output (clean parse).

- [ ] **Step 4: Verify no RPi-OS session logic remains inline**

Run:
```bash
grep -n 'chromium-kiosk.desktop\|/etc/xdg/labwc/autostart\|setup_graphical_session\|detect_os' install/install.sh
```
Expected: the only matches are the new `source`/`detect_os`/`setup_graphical_session` lines from Step 2. No `chromium-kiosk.desktop` and no `/etc/xdg/labwc/autostart` references remain — that logic is now exclusively in `rpi-os.sh`.

- [ ] **Step 5: Regression guard — confirm the move was behaviour-preserving**

Run: `git show HEAD:install/install.sh | grep -n 'chromium-kiosk\|xdg/labwc'`
Expected: the pre-modification `install.sh` (HEAD, before this commit) shows the inline copies. Compare them against `install/session/rpi-os.sh`'s `setup_graphical_session()` body — every command must match (modulo the two-space function indentation). This proves the RPi-OS install path is behaviour-identical, just relocated. The full proof is the on-Pi no-regression test in the Manual Verification section.

- [ ] **Step 6: Run the full test suite**

Run: `.venv-test/bin/python -m pytest services/tests/ -q`
Expected: 125 passed (121 baseline + 4 from `test_detect_os.py`). Nothing else changed, so nothing else should move.

- [ ] **Step 7: Commit**

```bash
git add install/install.sh
git commit -m "dietpi: install.sh sources pluggable session/<os>.sh component"
```

---

## Task 5: Document DietPi as a supported install target

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the README's install section**

Run: `grep -n 'Raspberry Pi OS\|Quick start\|install.sh\|Flash' README.md`
Expected: locate the "Quick start — install on a fresh Pi" section (it currently opens by telling the user to flash Raspberry Pi OS 64-bit).

- [ ] **Step 2: Add a DietPi note to the install section**

In `README.md`, immediately after the numbered "Quick start" steps (after the line describing what happens post-reboot — "Chromium launches in kiosk mode..."), add this paragraph:

```markdown
### Installing on DietPi

The installer also supports [DietPi](https://dietpi.com/) as a leaner base
than Raspberry Pi OS. Flash DietPi Lite, complete its first-boot, then run
`install/install.sh` the same way — it auto-detects the OS (`detect_os` in
`install/session/detect-os.sh`) and, on DietPi, additionally installs the
Wayland compositor, configures tty1 autologin, and sets up the kiosk
session that Raspberry Pi OS provides out of the box. Override the
autodetect with `BOOMBOX_OS=dietpi` or `BOOMBOX_OS=rpi-os` if needed.
```

- [ ] **Step 3: Update the repo-layout table**

In `README.md`, find the "Repo layout" table row for `install/` and update its description to mention the session component. The row currently reads roughly:

```markdown
| `install/` | First-time installer, systemd units, config templates, self-update script |
```

Change it to:

```markdown
| `install/` | First-time installer, per-OS session bootstrap (`install/session/`), systemd units, config templates |
```

(If the exact wording of that row differs, preserve its existing content and just add the `per-OS session bootstrap (install/session/)` clause.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document DietPi as a supported install target"
```

---

## Manual Verification (on the spare Pi — not automated)

The automated tests cover `detect_os` and the lint/syntax of the shell files. Everything OS-coupled — apt installs, getty autologin, the compositor actually starting — can only be verified on hardware. Run this checklist on the spare Pi once the tasks are done:

1. Flash stock **DietPi Lite** to the spare Pi; complete DietPi's first-boot.
2. Clone Boombox, run `install/install.sh`. Confirm it logs
   `graphical session bootstrap: dietpi` and completes without error.
3. Reboot. Confirm the Pi boots **straight into the Chromium kiosk** showing
   the boombox UI — no console prompt, no manual login.
4. SSH into the Pi. Confirm the SSH session lands at a normal shell prompt
   and does **not** spawn a compositor (proves the `~/.bash_profile` tty1
   guard works).
5. Confirm audio, the touchscreen, and the `boombox-*` services behave the
   same as on a Raspberry Pi OS install.
6. **RPi-OS no-regression:** re-run `install/install.sh` on the actual
   Raspberry Pi OS Boombox. Confirm it logs
   `graphical session bootstrap: rpi-os` and that nothing about the running
   system changes (the kiosk stays up, no services bounce unexpectedly).

---

## Self-Review

**Spec coverage:** Every spec section maps to a task —
`detect-os.sh` + `detect_os()` (Task 1), `rpi-os.sh` verbatim lift (Task 2),
`dietpi.sh` apt deps / getty autologin / `~/.bash_profile` launcher (Task 3),
`install.sh` seam — `detect_os` + `source session/<os>.sh` +
`setup_graphical_session` (Task 4), README docs (Task 5), the
`detect_os` unit test (Task 1), `bash -n` linting (Tasks 1–4), the RPi-OS
regression guard (Task 4 Step 5 + Manual Verification step 6), the on-DietPi
manual checklist (Manual Verification). The `wlrctl`/`kanshi` apt-availability
unknown the spec deferred "to the plan" is resolved in Task 3's header note
and Step 1 (`labwc`/`kanshi` required, `wlrctl` best-effort with graceful
degradation).

**Placeholder scan:** No TBDs, no "implement later", no "similar to Task N",
no naked commits. Every shell file and the test file are shown in full; the
`install.sh` edits show the exact blocks to remove and the exact block to
add.

**Type/interface consistency:** The interface is two bash functions —
`detect_os` (defined in `detect-os.sh` Task 1, called in `install.sh` Task 4)
and `setup_graphical_session` (defined in `rpi-os.sh` Task 2 and `dietpi.sh`
Task 3, called in `install.sh` Task 4). Names, and the
"sourced, runs in install.sh's environment" contract, are consistent across
all four files. `BOOMBOX_DIETPI_MARKER` and `BOOMBOX_OS` are used identically
in `detect-os.sh` and `test_detect_os.py`.

**Out-of-scope confirmed absent:** no flashable-image pipeline, no
`graphical-session.target` rewrite, no changes to DietPi's own base config —
all correctly excluded per the spec's Non-goals.
