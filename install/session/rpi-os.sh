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
