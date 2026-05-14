# DietPi install module

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-05-14
**Owner:** jwc

## Goal

Today `install.sh` only works on Raspberry Pi OS. It doesn't *create* a
graphical session — it assumes RPi OS already boots into the `rpd-labwc`
desktop session and merely tweaks that session's autostart. We want a second
supported install target: **DietPi**, a bare-bones Debian for the Pi. DietPi
gives us a kernel, Debian, and a console — but no desktop session — so the
module's real job is creating the Wayland session the kiosk needs, while
reusing the ~80% of `install.sh` that is already OS-agnostic Debian.

## Scope

**In scope:** an install-time module. You flash stock DietPi yourself, run
the Boombox `install.sh`, and it sets up the Wayland session plus everything
else — same one-command install as on RPi OS.

**Out of scope:**
- A flashable pre-baked DietPi+Boombox image (a separate, later build-pipeline
  project).
- Replacing or re-doing DietPi's own base config (swap, journald,
  `dietpi-services`, etc.). The module owns the *graphical session
  bootstrap*, nothing else about the OS.
- Fixing the existing `graphical-session.target` retry-loop hack (see
  "Non-goals" below).

## Decisions (from brainstorming)

| Topic | Decision |
|-------|----------|
| Deliverable | Install-time module only. |
| Boot-to-session | `getty` autologin on tty1 → `labwc` exec'd from the boombox user's shell profile. No DietPi-specific tooling, no dedicated session service. |
| Factoring | `install.sh` auto-detects the OS and sources a pluggable `install/session/<os>.sh`. Both OSes get a file (`rpi-os.sh`, `dietpi.sh`); the ~80% OS-agnostic install stays in `install.sh`. |
| OS detection | `[[ -d /boot/dietpi ]]` → `dietpi`, else `rpi-os` (conservative default). `BOOMBOX_OS` env override accepted for testing. |
| Compositor | `labwc` — same as RPi OS. The boombox's existing `~/.config/labwc/{rc.xml,autostart}` kiosk config is reused unchanged. |
| `rpi-os.sh` | Pure lift-and-shift of the current behavior. Byte-identical, just relocated — zero behavior change to the working RPi-OS path. |
| Shell profile | `~/.bash_profile` (agetty gives a bash login shell; correct for an appliance). |

## Non-goals

- **`graphical-session.target` wiring.** RPi OS today doesn't properly order
  the kiosk against the compositor — `boombox-kiosk.service` is
  `WantedBy=default.target` with `Restart=on-failure` and just retry-loops
  every 3s until labwc's Wayland socket appears. The DietPi path deliberately
  matches this (the shell-profile launch, not a dedicated `boombox-session`
  service with proper target wiring). Doing it "properly" for *both* OSes is
  a separate cleanup, not part of this module.
- **`seatd`.** Not needed. `getty` autologin gives the boombox user a real
  logind session on tty1, so `labwc` gets seat access through logind.

## Architecture: the session-bootstrap seam

`install.sh` carries one new sourced helper and one new call site.

### `detect_os()`

Lives in its own sourceable file, `install/session/detect-os.sh`, so it can
be unit-tested without sourcing `install.sh` (which has side effects):

```bash
# install/session/detect-os.sh — sourced by install.sh and by the test.
detect_os() {
  if [[ -n "${BOOMBOX_OS:-}" ]]; then echo "$BOOMBOX_OS"; return; fi
  [[ -d /boot/dietpi ]] && echo dietpi || echo rpi-os
}
```

`rpi-os` is the default — an unknown Debian falls through to the established,
well-tested path. `install.sh` logs the detected OS prominently.

### The pluggable component

```
install/session/
├── detect-os.sh — detect_os(): sourced by install.sh and the test
├── rpi-os.sh    — setup_graphical_session() for Raspberry Pi OS
└── dietpi.sh    — setup_graphical_session() for DietPi
```

Each file defines exactly one function, `setup_graphical_session()`, and
nothing else (no top-level side effects — it's `source`d, then called).
`install.sh` does, at the point where the session bootstrap currently lives
(after the systemd-unit install, ~section 9):

```bash
source "$ACTIVE_SCRIPT_DIR/session/detect-os.sh"
BOOMBOX_DETECTED_OS="$(detect_os)"
log "graphical session: $BOOMBOX_DETECTED_OS"
source "$ACTIVE_SCRIPT_DIR/session/$BOOMBOX_DETECTED_OS.sh"
setup_graphical_session
```

`$ACTIVE_SCRIPT_DIR` is `install.sh`'s post-migration install dir (set by the
release-pointer refactor already on `main`). If `detect_os` returns a value
with no matching `session/<os>.sh`, `install.sh` fails loudly before
`source`.

### What stays shared vs. what moves

**Stays in `install.sh` (both OSes, identical):**
- DAC overlay → `/boot/firmware/usercfg.txt` + the `config.txt` include
  (Pi *hardware* config, not OS-session).
- Chromium managed policy → `/etc/chromium/policies/managed/boombox.json`.
- The boombox labwc kiosk config → `~/.config/labwc/rc.xml` and
  `~/.config/labwc/autostart` (both OSes run the *same* boombox labwc
  config).
- `loginctl enable-linger`.
- All `boombox-*` user systemd units.

**Moves to `install/session/rpi-os.sh`:**
- The `/etc/xdg/labwc/autostart` system-wide override, including the
  `/etc/xdg/labwc/autostart.pi-os.orig` backup-if-absent.
- The legacy `~/.config/autostart/{chromium-kiosk.desktop,*.bak,unclutter.desktop}`
  sweep.

**New in `install/session/dietpi.sh`:** see next section.

## `install/session/dietpi.sh`

`setup_graphical_session()` for DietPi creates the session RPi OS provides
for free. Four steps, all idempotent (re-running `install.sh` is safe).

### 1. Compositor + Wayland deps via apt

RPi OS ships these with its desktop; DietPi Lite does not. Install:
- `labwc` — the Wayland compositor.
- `wlrctl` — the boombox `labwc-autostart` calls it to park the cursor
  off-screen.
- `kanshi` — the boombox `labwc-autostart` calls it for output config.

`chromium`, `wvkbd`, `grim`, `unclutter` are already in `install.sh`'s shared
apt line and are not repeated here.

> If `wlrctl` or `kanshi` is not available in DietPi's apt repos for the
> target Debian release, the implementation plan must resolve this (build
> from source, or make `labwc-autostart`'s use of them tolerant of their
> absence — consistent with the project's "every feature independently
> optional" principle). Flagged for the plan; not pre-decided here.

### 2. Autologin on tty1

A getty drop-in at `/etc/systemd/system/getty@tty1.service.d/autologin.conf`:

```ini
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin BOOMBOX_USER --noclear %I $TERM
```

`BOOMBOX_USER` is substituted with the actual boombox user. The empty
`ExecStart=` first line is required to clear the unit's default before
overriding. Installed with `sudo`, followed by `sudo systemctl daemon-reload`.

### 3. Shell-profile labwc launcher

A snippet appended to the boombox user's `~/.bash_profile`, bounded by marker
comments so re-running `install.sh` *replaces* it rather than appending a
duplicate:

```bash
# >>> boombox session >>>
# Start the Wayland compositor on the console login. Guarded so SSH logins
# and other ttys never spawn a compositor.
if [ "$(tty)" = "/dev/tty1" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  exec labwc
fi
# <<< boombox session <<<
```

The marker-bounded block is removed-and-reinserted on each install run
(idempotent). If `~/.bash_profile` does not exist it is created.

The guard is **load-bearing**: without the `tty1` + `WAYLAND_DISPLAY` checks,
every SSH login would spawn a compositor, and a stray check error would mean
the kiosk never starts. The plan must include explicit test steps for it.

### 4. Hand-off

Once `labwc` is running it reads the shared `~/.config/labwc/autostart`
(installed by `install.sh`), which parks the cursor and starts `kanshi`. The
existing `boombox-kiosk.service` attaches via its `Restart=on-failure`
retry-loop — exactly as on RPi OS today.

## `install/session/rpi-os.sh`

A pure lift-and-shift. `setup_graphical_session()` contains the existing
RPi-OS session bits, moved verbatim out of `install.sh`:

- Install `/etc/xdg/labwc/autostart` from `config/labwc-autostart`, backing up
  the Pi-OS original to `/etc/xdg/labwc/autostart.pi-os.orig` if that backup
  doesn't exist yet.
- Sweep the legacy `~/.config/autostart/chromium-kiosk.desktop` (+ `.bak`)
  and `~/.config/autostart/unclutter.desktop`.

No behavior change. Verification is a `git diff` confirming the moved lines
are byte-identical to what `install.sh` did before, plus a re-run of
`install.sh` on a real RPi-OS Boombox being a behavioral no-op.

## Testing

### Automated

- **`detect_os()` unit test** — `services/tests/test_detect_os.py`, a pytest
  that sources `install/session/detect-os.sh` via a subprocess and asserts:
  `/boot/dietpi` present → `dietpi`; absent → `rpi-os`; `BOOMBOX_OS` set →
  overrides both. Uses `services/tests/` because that is the repo's only
  established test convention; `detect-os.sh` being its own sourceable file
  is what makes this testable without running `install.sh`.
- **`bash -n`** on `install/session/detect-os.sh`,
  `install/session/rpi-os.sh`, `install/session/dietpi.sh`, and the modified
  `install/install.sh`.
- **RPi-OS regression guard** — `git diff` showing the `rpi-os.sh` content is
  byte-identical to the lines removed from `install.sh`.

### Manual (on the spare Pi — checklist in the plan)

1. Flash stock DietPi Lite to the spare Pi, complete DietPi's first-boot.
2. Clone Boombox, run `install/install.sh`. Confirm it logs
   `graphical session: dietpi` and completes.
3. Reboot. Confirm the Pi boots straight into the Chromium kiosk showing the
   boombox UI — no console, no manual login.
4. SSH in. Confirm the SSH session does **not** spawn a compositor (the
   `~/.bash_profile` guard works).
5. Confirm audio, the touchscreen, and the `boombox-*` services all behave
   the same as on an RPi-OS install.
6. **RPi-OS no-regression:** re-run `install/install.sh` on the actual
   RPi-OS Boombox; confirm it logs `graphical session: rpi-os` and nothing
   about the running system changes.

## Risks

- **The `~/.bash_profile` guard** (`dietpi.sh` step 3) is the highest-risk
  line. Wrong → SSH logins spawn compositors, or the kiosk never starts.
  Explicit manual test steps 3 and 4 above target it.
- **`wlrctl` / `kanshi` availability** in DietPi's apt repos — see the
  call-out in `dietpi.sh` step 1. Resolved in the plan.
- **DietPi version drift.** Targets current DietPi (Debian Bookworm/Trixie
  base) — the same Debian support matrix as the RPi-OS path. The OS axis
  (RPi OS vs DietPi) is orthogonal to the Debian-version axis;
  `install.sh`'s existing Trixie-specific handling (the mopidy `scan.py`
  patch) already covers the latter.
- **DietPi's own service management** (`dietpi-services`) and base-config
  choices are out of scope; if a future DietPi default conflicts with a
  boombox service, that's a separate issue, not this module's responsibility.

## Files

| Path | Change |
|------|--------|
| `install/session/detect-os.sh` | **New** — `detect_os()`, sourced by `install.sh` and the test. |
| `install/session/rpi-os.sh` | **New** — `setup_graphical_session()`, lifted verbatim from `install.sh`. |
| `install/session/dietpi.sh` | **New** — `setup_graphical_session()` for DietPi (apt deps, autologin, shell-profile launcher). |
| `install/install.sh` | Remove the inline RPi-OS session bootstrap; add the `source session/detect-os.sh` + `source session/<os>.sh` + `setup_graphical_session` call. |
| `services/tests/test_detect_os.py` | **New** — `detect_os()` unit test. |
| `README.md` / `docs/` | Document DietPi as a supported install target and the auto-detect behavior. |
