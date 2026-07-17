#!/usr/bin/env bash
# install/session/dietpi.sh — graphical-session bootstrap for DietPi.
# DietPi Lite boots to a bare console with no compositor, so this *creates*
# the Wayland session the boombox kiosk needs:
#   0. enables the KMS display stack in config.txt — DietPi ships with
#      vc4-kms-v3d commented out and no display_auto_detect, so without
#      this there is no DRM device at all: the DSI touchscreen stays dark
#      and labwc has nothing to render to. RPi OS ships all of it enabled.
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
  # 0. KMS display stack. Uncomment DietPi's stock '#dtoverlay=vc4-kms-v3d,
  #    noaudio' line (dropping ,noaudio — HDMI audio cards are harmless and
  #    this matches the RPi OS default; the DAC stays the ALSA default via
  #    /etc/asound.conf) and add the display keys RPi OS ships out of the
  #    box. display_auto_detect makes the firmware probe the DSI ports and
  #    load the right panel overlay (e.g. the official 7" touchscreen);
  #    i2c_arm is needed for panel/touch detection and DAC probing.
  local cfg="${BOOT_FW_DIR:-/boot/firmware}/config.txt"
  [[ -f "$cfg" ]] || cfg=/boot/config.txt
  if [[ -f "$cfg" ]]; then
    log "enabling KMS display stack in $cfg"
    sudo sed -i 's|^#dtoverlay=vc4-kms-v3d.*|dtoverlay=vc4-kms-v3d|' "$cfg"
    sudo grep -q '^dtoverlay=vc4-kms-v3d' "$cfg" \
      || echo 'dtoverlay=vc4-kms-v3d' | sudo tee -a "$cfg" >/dev/null
    local kv
    for kv in display_auto_detect=1 max_framebuffers=2 \
              disable_fw_kms_setup=1 dtparam=i2c_arm=on; do
      # compare on everything up to the *value* so dtparam keys match as
      # 'dtparam=i2c_arm', not just 'dtparam'
      sudo grep -q "^${kv%=*}=" "$cfg" \
        || echo "$kv" | sudo tee -a "$cfg" >/dev/null
    done
  else
    warn "no config.txt found — skipping KMS display enablement"
  fi

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
