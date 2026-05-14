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
