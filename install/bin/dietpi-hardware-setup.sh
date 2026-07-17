#!/usr/bin/env bash
# install/bin/dietpi-hardware-setup.sh — bring up the boombox hardware on a
# fresh DietPi image *before* (or without) the full Boombox install.
#
# DietPi Lite ships with the whole display stack disabled: vc4-kms-v3d is
# commented out in config.txt and there is no display_auto_detect, so a DSI
# touchscreen (e.g. the official Raspberry Pi 7" panel) stays completely
# dark — not even a boot console. The I²S DAC overlay is likewise absent.
# This script enables both. install.sh's DietPi session bootstrap
# (install/session/dietpi.sh) applies the same display settings, so running
# this first is safe and the full install remains idempotent on top of it.
#
# What it does (all idempotent):
#   1. config.txt: enable dtoverlay=vc4-kms-v3d, display_auto_detect=1,
#      max_framebuffers=2, disable_fw_kms_setup=1, dtparam=i2c_arm=on
#   2. usercfg.txt: install the repo's DAC overlay file (hifiberry-dacplus,
#      i2s on, onboard audio off) and ensure config.txt includes it
#   3. /etc/asound.conf: pin the ALSA default to the HiFiBerry by name
#   4. apt-install alsa-utils + i2c-tools for verification
#
# Usage (as root on the Pi, repo checked out anywhere):
#   install/bin/dietpi-hardware-setup.sh
#   reboot   # overlays only bind at boot
#
# Verify after reboot:
#   cat /sys/class/drm/card*-DSI-1/status   # → connected
#   aplay -l                                # → card 'sndrpihifiberry'
#   speaker-test -D default -c 2 -t wav -l 1

set -euo pipefail

log()  { echo "→ $*"; }
fail() { echo "✗ $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "run as root (fresh DietPi: ssh root@<pi>)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/../config"
[[ -f "$CONFIG_DIR/usercfg.txt" ]] || fail "can't find install/config/usercfg.txt next to this script"

# Newer DietPi (v10+, Trixie) mounts the boot partition at /boot/firmware
# like Raspberry Pi OS Bookworm; older images used /boot.
BOOT_FW_DIR=/boot/firmware
[[ -d $BOOT_FW_DIR ]] || BOOT_FW_DIR=/boot
CFG="$BOOT_FW_DIR/config.txt"
[[ -f $CFG ]] || fail "no config.txt at $CFG"

log "backing up $CFG"
cp -n "$CFG" "$CFG.bak-hardware-setup" || true

# --- 1. KMS display stack ---------------------------------------------------
log "enabling KMS display stack in $CFG"
# DietPi's stock line is '#dtoverlay=vc4-kms-v3d,noaudio' — uncomment it,
# dropping ',noaudio' to match the known-good RPi OS boombox (the extra HDMI
# ALSA cards are harmless; /etc/asound.conf pins the default to the DAC).
sed -i 's|^#dtoverlay=vc4-kms-v3d.*|dtoverlay=vc4-kms-v3d|' "$CFG"
grep -q '^dtoverlay=vc4-kms-v3d' "$CFG" || echo 'dtoverlay=vc4-kms-v3d' >> "$CFG"
for kv in display_auto_detect=1 max_framebuffers=2 disable_fw_kms_setup=1 dtparam=i2c_arm=on; do
  # compare on everything up to the value so dtparam keys match as
  # 'dtparam=i2c_arm', not just 'dtparam'
  grep -q "^${kv%=*}=" "$CFG" || echo "$kv" >> "$CFG"
done

# --- 2. DAC overlay ----------------------------------------------------------
log "installing DAC overlay → $BOOT_FW_DIR/usercfg.txt"
install -m 0644 "$CONFIG_DIR/usercfg.txt" "$BOOT_FW_DIR/usercfg.txt"
if ! grep -qE '^\s*include\s+usercfg\.txt' "$CFG"; then
  log "appending 'include usercfg.txt' to $CFG"
  printf '\n[all]\ninclude usercfg.txt\n' >> "$CFG"
fi

# --- 3. ALSA default ---------------------------------------------------------
log "installing /etc/asound.conf (default → hw:sndrpihifiberry)"
install -m 0644 "$CONFIG_DIR/asound.conf" /etc/asound.conf

# --- 4. Verification tools ---------------------------------------------------
log "installing alsa-utils + i2c-tools"
apt-get install -y -qq alsa-utils i2c-tools >/dev/null

log "done — reboot to bind the overlays, then verify:"
echo "    cat /sys/class/drm/card*-DSI-1/status   # → connected"
echo "    aplay -l                                # → card 'sndrpihifiberry'"
echo "    speaker-test -D default -c 2 -t wav -l 1"
