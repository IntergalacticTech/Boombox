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
  nginx apache2-utils samba \
  chromium unclutter grim wvkbd \
  libwayland-dev libxkbcommon-dev wayland-protocols pkg-config build-essential \
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

VIDEO_DIR="${BOOMBOX_VIDEO_DIR:-/home/${BOOMBOX_USER}/Videos}"
log "ensuring video dirs exist: $VIDEO_DIR (+ uploads/, .usb/)"
mkdir -p "$VIDEO_DIR" "$VIDEO_DIR/uploads" "$VIDEO_DIR/.usb"

# ---------------------------------------------------------------------------
# 6.5. Jellyfin (video server)
# ---------------------------------------------------------------------------
# Apt repo + install via Jellyfin's official setup script. Idempotent: if
# the package is already there we skip the network round-trip.
if ! dpkg -l jellyfin >/dev/null 2>&1; then
  log "installing Jellyfin from repo.jellyfin.org"
  curl -fsSL https://repo.jellyfin.org/install-debuntu.sh | sudo bash
else
  log "Jellyfin already installed (skipping repo install)"
fi

# Jellyfin runs as the `jellyfin` system user. Add it to the desktop user's
# primary group so it can read the Videos library + symlinked USB drives.
if getent passwd jellyfin >/dev/null; then
  if ! id -nG jellyfin | tr ' ' '\n' | grep -qx "$BOOMBOX_GROUP"; then
    sudo usermod -aG "$BOOMBOX_GROUP" jellyfin
  fi
fi

# Make ~/Videos group-readable + traverseable for jellyfin.
chmod 0755 "$VIDEO_DIR" "$VIDEO_DIR/.usb" "$VIDEO_DIR/uploads"

sudo systemctl enable --now jellyfin 2>/dev/null || warn "jellyfin failed to enable (will retry after reboot)"

# Remote LAN credentials. The kiosk keeps using http://localhost/ with no
# auth, but anything off-device goes through nginx on BOOMBOX_WEB_PORT and
# requires HTTP Basic. Samba uses the same generated password for the music
# share so there is one remote credential to manage.
log "configuring remote web/SMB credentials"
sudo mkdir -p /etc/boombox
WEB_AUTH_ENV=/etc/boombox/web-auth.env
EXISTING_WEB_PORT=""
EXISTING_WEB_USER=""
EXISTING_WEB_PASSWORD=""
if sudo test -f "$WEB_AUTH_ENV"; then
  while IFS='=' read -r key val; do
    case "$key" in
      BOOMBOX_WEB_PORT) EXISTING_WEB_PORT="$val" ;;
      BOOMBOX_WEB_USER) EXISTING_WEB_USER="$val" ;;
      BOOMBOX_WEB_PASSWORD) EXISTING_WEB_PASSWORD="$val" ;;
    esac
  done < <(sudo cat "$WEB_AUTH_ENV")
fi
REMOTE_WEB_PORT="${BOOMBOX_WEB_PORT:-${EXISTING_WEB_PORT:-8090}}"
WEB_AUTH_USER="${BOOMBOX_WEB_USER:-${EXISTING_WEB_USER:-boombox}}"
WEB_AUTH_PASSWORD="${BOOMBOX_WEB_PASSWORD:-${EXISTING_WEB_PASSWORD:-}}"
if [[ -z "$WEB_AUTH_PASSWORD" ]]; then
  WEB_AUTH_PASSWORD="$(python3 -c 'import secrets; print(f"{secrets.randbelow(900000) + 100000:06d}")')"
fi

TMP_AUTH="$(mktemp)"
cat >"$TMP_AUTH" <<EOF
BOOMBOX_WEB_PORT=$REMOTE_WEB_PORT
BOOMBOX_WEB_USER=$WEB_AUTH_USER
BOOMBOX_WEB_PASSWORD=$WEB_AUTH_PASSWORD
BOOMBOX_SMB_USER=$BOOMBOX_USER
EOF
sudo install -m 0640 -o root -g "$BOOMBOX_GROUP" "$TMP_AUTH" "$WEB_AUTH_ENV"
rm -f "$TMP_AUTH"

printf '%s\n' "$WEB_AUTH_PASSWORD" | sudo htpasswd -iB -c /etc/nginx/boombox.htpasswd "$WEB_AUTH_USER" >/dev/null
sudo chown root:www-data /etc/nginx/boombox.htpasswd
sudo chmod 0640 /etc/nginx/boombox.htpasswd

# ---------------------------------------------------------------------------
# 6.6. wvkbd ≥ 0.17 from source (Trixie ships 0.15, no --layer flag)
# ---------------------------------------------------------------------------
# Trixie's wvkbd 0.15 renders on the layer-shell `top` layer, which sits
# below Chromium's --kiosk surface, so the keyboard is invisible. The
# `--layer overlay` flag landed in upstream after 0.15 — build a fresh
# binary so the OSK actually appears over the kiosk.
WVKBD_REPO=https://github.com/jjsullivan5196/wvkbd.git
WVKBD_REF="${BOOMBOX_WVKBD_REF:-master}"
WVKBD_BIN=/usr/local/bin/wvkbd-mobintl
if [[ -x "$WVKBD_BIN" ]] && "$WVKBD_BIN" --help 2>&1 | grep -q -- '--layer'; then
  log "wvkbd at $WVKBD_BIN already supports --layer (skipping rebuild)"
else
  log "building wvkbd from source (Trixie's 0.15 lacks --layer)"
  WVKBD_BUILD="$(mktemp -d)"
  git clone --depth 1 --branch "$WVKBD_REF" "$WVKBD_REPO" "$WVKBD_BUILD"
  make -C "$WVKBD_BUILD" -j"$(nproc)"
  sudo make -C "$WVKBD_BUILD" PREFIX=/usr/local install
  rm -rf "$WVKBD_BUILD"
fi

# ---------------------------------------------------------------------------
# 6.7. Jellyfin auto-setup (run the wizard via the Startup API)
# ---------------------------------------------------------------------------
# If Jellyfin was manually set up before we took over (no boombox-managed
# state file present), wipe its DB and the StartupWizardCompleted flag so
# our automation can take ownership of admin credentials + library config.
JELLYFIN_ENV=/etc/boombox/jellyfin.env
if dpkg -l jellyfin >/dev/null 2>&1 && ! sudo test -f "$JELLYFIN_ENV"; then
  if sudo grep -q 'IsStartupWizardCompleted>true' /etc/jellyfin/system.xml 2>/dev/null; then
    log "Jellyfin is configured but not by us — wiping for fresh setup"
    sudo systemctl stop jellyfin
    sudo rm -f /var/lib/jellyfin/data/jellyfin.db \
               /var/lib/jellyfin/data/jellyfin.db-shm \
               /var/lib/jellyfin/data/jellyfin.db-wal \
               /etc/jellyfin/system.xml
    sudo systemctl start jellyfin
  fi
fi

log "running Jellyfin first-run automation"
sudo BOOMBOX_VIDEO_DIR="$VIDEO_DIR" python3 \
  "$REPO_DIR/services/boombox-jellyfin-setup.py" \
  || warn "Jellyfin auto-setup didn't finish cleanly (check /etc/boombox/jellyfin.env)"

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
sudo mkdir -p /etc/nginx/snippets
sudo install -m 0644 "$SCRIPT_DIR/config/nginx-boombox-common.conf" /etc/nginx/snippets/boombox-common.conf
TMP_NGINX="$(mktemp)"
sed "s|__REMOTE_WEB_PORT__|$REMOTE_WEB_PORT|g" "$SCRIPT_DIR/config/nginx.conf" > "$TMP_NGINX"
sudo install -m 0644 "$TMP_NGINX" /etc/nginx/sites-available/boombox
rm -f "$TMP_NGINX"
sudo ln -sf /etc/nginx/sites-available/boombox /etc/nginx/sites-enabled/boombox
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

log "installing Samba music share"
TMP_SMB="$(mktemp)"
sed \
  -e "s|__MUSIC_DIR__|$MUSIC_DIR|g" \
  -e "s|__BOOMBOX_USER__|$BOOMBOX_USER|g" \
  "$SCRIPT_DIR/config/smb.conf" > "$TMP_SMB"
sudo install -m 0644 "$TMP_SMB" /etc/samba/smb.conf
rm -f "$TMP_SMB"
if sudo pdbedit -L -u "$BOOMBOX_USER" >/dev/null 2>&1; then
  printf '%s\n%s\n' "$WEB_AUTH_PASSWORD" "$WEB_AUTH_PASSWORD" | sudo smbpasswd -s "$BOOMBOX_USER" >/dev/null
else
  printf '%s\n%s\n' "$WEB_AUTH_PASSWORD" "$WEB_AUTH_PASSWORD" | sudo smbpasswd -s -a "$BOOMBOX_USER" >/dev/null
fi
sudo smbpasswd -e "$BOOMBOX_USER" >/dev/null
sudo testparm -s >/dev/null
sudo systemctl enable --now smbd

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
  boombox-osk
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
sudo systemctl enable smbd

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

Remote access:
  Web UI: http://<pi-ip>:$REMOTE_WEB_PORT/  user: $WEB_AUTH_USER
  SMB:    smb://<pi-ip>/boombox-music     user: $BOOMBOX_USER
  Password/PIN is stored on the Pi at: $WEB_AUTH_ENV

Video (Jellyfin):
  http://<pi-ip>:8096/        first-run wizard sets admin user + library
  On first visit, point Jellyfin at:  $VIDEO_DIR
  Native apps: install Jellyfin from your app store, point at <pi-ip>:8096
EOF
