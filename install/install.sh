#!/usr/bin/env bash
# install.sh — first-time + idempotent install of Boombox on Raspberry Pi OS.
#
# Run as the desktop user (the one who will physically use the boombox).
# The script escalates with sudo for apt + system services + /boot.
#
#   /opt/boombox/install/install.sh
#
# Re-running is safe: every step is idempotent.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths and identity
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ "${REPO_DIR}" != "/opt/boombox" ]]; then
  echo "warning: repo is at ${REPO_DIR}, not the expected /opt/boombox." >&2
  echo "         installer paths in systemd units assume /opt/boombox; adjust" >&2
  echo "         install/systemd/user/*.service or relocate the checkout." >&2
fi

# Don't run as root — we need user systemd. install.sh self-escalates with
# sudo where needed.
if [[ "$EUID" -eq 0 ]]; then
  echo "error: run install.sh as your desktop user, not root." >&2
  exit 1
fi

BOOMBOX_USER="$USER"
BOOMBOX_GROUP="$(id -gn)"
BOOMBOX_UID="$(id -u)"
MUSIC_DIR="${BOOMBOX_MUSIC_DIR:-/home/${BOOMBOX_USER}/Music}"

log()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. APT dependencies
# ---------------------------------------------------------------------------
log "installing apt packages"
sudo apt update
sudo apt install -y \
  git rsync curl jq \
  python3 python3-venv python3-pip \
  python3-dbus python3-gi python3-gi-cairo gir1.2-glib-2.0 \
  mopidy mopidy-mpd mopidy-local mpc \
  nginx \
  chromium unclutter grim \
  playerctl \
  pipewire pipewire-pulse wireplumber pulseaudio-utils \
  shairport-sync \
  bluez bluez-tools \
  alsa-utils \
  nodejs npm

# Iris is pip-only; bundle it in a venv we control rather than --break-system-packages.
# Mopidy on Debian Trixie reads its own /usr/lib/python3/dist-packages, so to
# install Iris where Mopidy can see it we *do* need --break-system-packages.
# Trade-off accepted: it's a Pi appliance, not a general workstation.
sudo pip install --break-system-packages Mopidy-Iris

# ---------------------------------------------------------------------------
# 2. Python venv for boombox-* services
# ---------------------------------------------------------------------------
log "creating /opt/boombox/.venv (--system-site-packages for dbus/gi)"
if [[ ! -d "$REPO_DIR/.venv" ]]; then
  python3 -m venv --system-site-packages "$REPO_DIR/.venv"
fi
"$REPO_DIR/.venv/bin/pip" install --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/config/requirements.txt"

# ---------------------------------------------------------------------------
# 3. Group memberships (gpio, audio, render, video, bluetooth, plugdev)
# ---------------------------------------------------------------------------
log "ensuring $BOOMBOX_USER is in required groups"
for grp in gpio audio video render bluetooth plugdev; do
  if getent group "$grp" >/dev/null && ! id -nG "$BOOMBOX_USER" | tr ' ' '\n' | grep -qx "$grp"; then
    sudo usermod -aG "$grp" "$BOOMBOX_USER"
    warn "added $BOOMBOX_USER to $grp — log out / reboot to pick up"
  fi
done

# ---------------------------------------------------------------------------
# 4. DAC overlay (/boot/firmware/usercfg.txt)
# ---------------------------------------------------------------------------
BOOT_FW_DIR=/boot/firmware
if [[ ! -d "$BOOT_FW_DIR" ]]; then
  BOOT_FW_DIR=/boot
fi
log "installing DAC overlay → $BOOT_FW_DIR/usercfg.txt"
sudo install -m 0644 "$SCRIPT_DIR/config/usercfg.txt" "$BOOT_FW_DIR/usercfg.txt"

# Make sure config.txt actually `include`s usercfg.txt under the [all] section.
if [[ -f "$BOOT_FW_DIR/config.txt" ]] && ! sudo grep -qE '^\s*include\s+usercfg\.txt' "$BOOT_FW_DIR/config.txt"; then
  warn "appending 'include usercfg.txt' to $BOOT_FW_DIR/config.txt"
  echo -e "\n[all]\ninclude usercfg.txt" | sudo tee -a "$BOOT_FW_DIR/config.txt" >/dev/null
fi

# ---------------------------------------------------------------------------
# 5. ALSA default device
# ---------------------------------------------------------------------------
log "installing /etc/asound.conf"
sudo install -m 0644 "$SCRIPT_DIR/config/asound.conf" /etc/asound.conf

# ---------------------------------------------------------------------------
# 6. Music dir + Mopidy config
# ---------------------------------------------------------------------------
log "ensuring music dirs exist: $MUSIC_DIR (+ uploads/, .usb/)"
mkdir -p "$MUSIC_DIR" "$MUSIC_DIR/uploads" "$MUSIC_DIR/.usb"

log "installing /etc/mopidy/mopidy.conf"
sudo mkdir -p /etc/mopidy
sudo install -m 0644 "$SCRIPT_DIR/config/mopidy.conf" /etc/mopidy/mopidy.conf
sudo sed -i "s|__MUSIC_DIR__|$MUSIC_DIR|g" /etc/mopidy/mopidy.conf

# Apply the Trixie scan.py compatibility patch (idempotent).
SCAN_PY=/usr/lib/python3/dist-packages/mopidy/audio/scan.py
if [[ -f "$SCAN_PY" ]] && sudo grep -q 'msg.get_structure().get_value("caps").get_name()' "$SCAN_PY"; then
  log "patching mopidy scan.py (Trixie python3-gi compatibility)"
  ( cd / && sudo patch -p0 < "$REPO_DIR/services/scan-py-fix.diff" ) || warn "scan.py patch failed (already applied?)"
fi

# ---------------------------------------------------------------------------
# 7. Build UI → /var/www/boombox
# ---------------------------------------------------------------------------
log "building UI"
(
  cd "$REPO_DIR/ui"
  npm install --no-audit --no-fund
  npm run build
)
sudo mkdir -p /var/www/boombox
sudo rsync -a --delete "$REPO_DIR/ui/dist/" /var/www/boombox/
sudo chown -R www-data:www-data /var/www/boombox

# ---------------------------------------------------------------------------
# 8. nginx site
# ---------------------------------------------------------------------------
log "installing nginx site"
sudo install -m 0644 "$SCRIPT_DIR/config/nginx.conf" /etc/nginx/sites-available/boombox
sudo ln -sf /etc/nginx/sites-available/boombox /etc/nginx/sites-enabled/boombox
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# ---------------------------------------------------------------------------
# 9. systemd units
# ---------------------------------------------------------------------------
log "installing user systemd units"
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 "$SCRIPT_DIR/systemd/user/"*.service "$HOME/.config/systemd/user/"

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

systemctl --user daemon-reload

USER_UNITS=(
  boombox-state
  boombox-audio
  boombox-orchestrator
  boombox-buttons
  boombox-resume
  boombox-bt-volume
  boombox-kiosk
  boombox-kiosk-guard
)
for u in "${USER_UNITS[@]}"; do
  systemctl --user enable "$u.service"
done

# boombox-uploader is intentionally NOT enabled — it's toggled by the
# touchscreen Settings drawer.

# System-side template + udev rule for USB auto-mount.
log "installing USB auto-mount (system unit + udev rule)"
sudo install -m 0644 "$SCRIPT_DIR/systemd/system/boombox-usb-mount@.service" \
  /etc/systemd/system/boombox-usb-mount@.service
sudo install -m 0644 "$SCRIPT_DIR/udev/99-boombox-usb.rules" \
  /etc/udev/rules.d/99-boombox-usb.rules
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=block --action=change || true

# usb-mount needs to know which user owns the music directory.
sudo mkdir -p /etc/boombox
echo "$BOOMBOX_USER" | sudo tee /etc/boombox/desktop-user >/dev/null
sudo chmod 0644 /etc/boombox/desktop-user

# Sudoers fragment for library-scan / mopidy-restart from the touch UI.
log "installing sudoers fragment for boombox"
TMP_SUDOERS="$(mktemp)"
sed "s/%BOOMBOX_USER%/$BOOMBOX_USER/g" "$SCRIPT_DIR/sudoers/boombox" > "$TMP_SUDOERS"
sudo install -m 0440 -o root -g root "$TMP_SUDOERS" /etc/sudoers.d/boombox
sudo visudo -cf /etc/sudoers.d/boombox
rm -f "$TMP_SUDOERS"

# Lingering so user services come up on boot before the user logs in.
sudo loginctl enable-linger "$BOOMBOX_USER"

log "enabling system services"
sudo systemctl enable mopidy
sudo systemctl restart mopidy
sudo systemctl enable nginx

# ---------------------------------------------------------------------------
# 10. /etc/boombox config dir
# ---------------------------------------------------------------------------
sudo mkdir -p /etc/boombox
if [[ ! -f /etc/boombox/buttons.json ]]; then
  sudo install -m 0644 "$SCRIPT_DIR/config/buttons.json" /etc/boombox/buttons.json
fi

# ---------------------------------------------------------------------------
# 11. boombox-update on PATH
# ---------------------------------------------------------------------------
sudo install -m 0755 "$REPO_DIR/bin/boombox-update" /usr/local/bin/boombox-update

# ---------------------------------------------------------------------------
# 12. Try to start what we can right now (the rest comes up after reboot)
# ---------------------------------------------------------------------------
log "starting boombox services (where possible without a reboot)"
for u in boombox-state boombox-resume; do
  systemctl --user restart "$u.service" || warn "$u failed to start now — it will retry after reboot"
done

cat <<EOF

✅ Install complete.

Next:
  1. sudo reboot
  2. Chromium kiosk should come up on the touchscreen with the boombox UI.
  3. Drop music in $MUSIC_DIR and run:  sudo mopidyctl local scan

Status from your laptop (via ./pi):
  ./pi status
  ./pi logs mopidy
EOF
