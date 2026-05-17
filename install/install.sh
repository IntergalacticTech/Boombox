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

# BOOMBOX_ROOT is the physical /opt/boombox dir — the parent of releases/,
# the shared venv, state/, and the `current` symlink. install.sh may run
# from a flat checkout (first install) OR from inside the migrated layout
# (releases/<ref>/install/, reached via the `current` symlink). Resolve the
# real install dir through any symlink, then strip the known layout suffix
# so BOOMBOX_ROOT is correct no matter how we were invoked.
REAL_SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd -P)"
case "$REAL_SCRIPT_DIR" in
  */releases/*/install) BOOMBOX_ROOT="${REAL_SCRIPT_DIR%/releases/*/install}" ;;
  */install)            BOOMBOX_ROOT="${REAL_SCRIPT_DIR%/install}" ;;
  *)                    BOOMBOX_ROOT="$REPO_DIR" ;;
esac

if [[ "${BOOMBOX_ROOT}" != "/opt/boombox" ]]; then
  echo "warning: boombox root is at ${BOOMBOX_ROOT}, not the expected /opt/boombox." >&2
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

# ---------------------------------------------------------------------------
# Layout helpers — releases/<ref>/, current symlink
# ---------------------------------------------------------------------------
RELEASES_DIR="$BOOMBOX_ROOT/releases"
CURRENT_LINK="$BOOMBOX_ROOT/current"
PREVIOUS_LINK="$BOOMBOX_ROOT/previous"
SHARED_VENV="$BOOMBOX_ROOT/.venv"
STATE_DIR="$BOOMBOX_ROOT/state"

# True when BOOMBOX_ROOT is still a flat git checkout (pre-migration layout).
# After migration the .git dir lives under releases/<ref>/, so BOOMBOX_ROOT/.git
# no longer exists and this correctly returns false — no recursive migration.
is_legacy_layout() {
  [[ -d "$BOOMBOX_ROOT/.git" ]] && [[ ! -L "$CURRENT_LINK" ]]
}

migrate_legacy_layout() {
  log "migrating legacy /opt/boombox layout → releases/<sha>/ + current symlink"
  local sha base
  sha="$(git -C "$BOOMBOX_ROOT" rev-parse --short HEAD)"
  local target="$RELEASES_DIR/legacy-$sha"
  mkdir -p "$RELEASES_DIR" "$STATE_DIR"
  if [[ ! -d "$target" ]]; then
    # Move the entire checkout (including .git) into releases/legacy-<sha>/.
    # Skip the venv: it's about to live one level up.
    mkdir "$target"
    shopt -s dotglob nullglob
    for entry in "$BOOMBOX_ROOT"/*; do
      base="$(basename "$entry")"
      case "$base" in
        .venv|releases|current|previous|state) continue ;;
      esac
      mv "$entry" "$target/"
    done
    shopt -u dotglob nullglob
    printf 'legacy\n' >"$target/VERSION"
  fi
  ln -sfn "releases/legacy-$sha" "$CURRENT_LINK"
  # No previous yet — first auto-update will populate it.
}

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
  playerctl \
  pipewire pipewire-pulse wireplumber pulseaudio-utils \
  shairport-sync \
  bluez bluez-tools \
  alsa-utils \
  flac \
  nodejs npm

# Iris is pip-only; bundle it in a venv we control rather than --break-system-packages.
# Mopidy on Debian Trixie reads its own /usr/lib/python3/dist-packages, so to
# install Iris where Mopidy can see it we *do* need --break-system-packages.
# Trade-off accepted: it's a Pi appliance, not a general workstation.
# Mopidy-Iris stays. Mopidy-Subsonic is intentionally NOT installed —
# the plugin is Python-2 bit-rotten (NameError: 'unicode' is not defined
# on Py3.13). Streaming works via direct /rest/stream.view URLs that
# boombox-library's resolver constructs, played by Mopidy's built-in
# stream backend.
sudo pip install --break-system-packages Mopidy-Iris

# Patch Mopidy 3.4.2's audio/scan.py for compatibility with Debian Trixie's
# python3-gi (which returns StructureWrapper from Gst.Structure.get_value
# instead of a Caps with get_name()). Without this, every http:// stream
# fails at scan time with AttributeError. The original line tries
# get_name() on the wrapped caps; the patch falls through to get_structure
# + to_string + None.
_scan_py=/usr/lib/python3/dist-packages/mopidy/audio/scan.py
if [[ -f "$_scan_py" ]] && ! grep -q "_mime_caps" "$_scan_py"; then
  sudo python3 - <<'PYPATCH'
path = "/usr/lib/python3/dist-packages/mopidy/audio/scan.py"
with open(path) as f: src = f.read()
src = src.replace(
    "mime = msg.get_structure().get_value(\"caps\").get_name()",
    "_mime_caps = msg.get_structure().get_value(\"caps\")\n                try:\n                    mime = _mime_caps.get_name()\n                except AttributeError:\n                    try:\n                        mime = _mime_caps.get_structure(0).get_name()\n                    except AttributeError:\n                        try:\n                            mime = _mime_caps.to_string().split(\",\", 1)[0].split(\";\", 1)[0].strip()\n                        except AttributeError:\n                            mime = None",
)
src = src.replace(
    "mime = caps.get_structure(0).get_name()",
    "try:\n                    mime = caps.get_structure(0).get_name()\n                except AttributeError:\n                    mime = None",
)
with open(path, "w") as f: f.write(src)
PYPATCH
  echo "[install] patched mopidy/audio/scan.py for StructureWrapper compat"
fi

# Place default boombox-library config if absent (atomic, idempotent).
if [ ! -f /etc/boombox/library.yml ]; then
    sudo mkdir -p /etc/boombox
    sudo cp "$(dirname "$0")/config/library.yml.template" /etc/boombox/library.yml
    sudo chown "$BOOMBOX_USER:$BOOMBOX_USER" /etc/boombox/library.yml
    sudo chmod 600 /etc/boombox/library.yml
fi

# Place default boombox-rfid config if absent (atomic, idempotent).
if [ ! -f /etc/boombox/rfid.yml ]; then
    sudo mkdir -p /etc/boombox
    sudo cp "$(dirname "$0")/config/rfid.yml.template" /etc/boombox/rfid.yml
    sudo chown "$BOOMBOX_USER:$BOOMBOX_USER" /etc/boombox/rfid.yml
    sudo chmod 644 /etc/boombox/rfid.yml
fi

# boombox-rfid reads /dev/input/by-id/<reader>-event-kbd; add the
# kiosk user to the 'input' group so the reader is openable without root.
if ! id -nG "$BOOMBOX_USER" | tr ' ' '\n' | grep -qx input; then
    sudo usermod -aG input "$BOOMBOX_USER"
    echo "[install] added $BOOMBOX_USER to 'input' group (reboot or re-login to take effect)"
fi

# State dir for SQLite catalog
sudo mkdir -p /opt/boombox/state
sudo chown "$BOOMBOX_USER:$BOOMBOX_USER" /opt/boombox/state

# ---------------------------------------------------------------------------
# 1.5. Layout migration (must run before anything else touches REPO_DIR)
# ---------------------------------------------------------------------------
if is_legacy_layout; then
  migrate_legacy_layout
fi

# Re-anchor SCRIPT_DIR / REPO_DIR to the migrated layout. SCRIPT_DIR no longer
# refers to the actual checkout — install.sh was launched from inside the
# legacy tree, but now lives at $CURRENT_LINK/install/install.sh after the
# move. Re-exec ourselves from the new location once.
ACTIVE_INSTALL="$CURRENT_LINK/install/install.sh"
# $SCRIPT_DIR was resolved to an absolute path at the top of this file,
# before migration moved anything — so this comparison is reliable
# regardless of how install.sh was invoked (absolute or relative path).
THIS_INSTALL="$SCRIPT_DIR/install.sh"
if [[ "$THIS_INSTALL" != "$ACTIVE_INSTALL" ]]; then
  [[ -x "$ACTIVE_INSTALL" ]] || fail "post-migration installer missing at $ACTIVE_INSTALL"
  exec "$ACTIVE_INSTALL" "$@"
fi

ACTIVE_REPO="$CURRENT_LINK"
ACTIVE_SCRIPT_DIR="$CURRENT_LINK/install"

# ---------------------------------------------------------------------------
# 2. Python venv for boombox-* services (shared across releases)
# ---------------------------------------------------------------------------
log "creating $SHARED_VENV (--system-site-packages for dbus/gi)"
if [[ ! -d "$SHARED_VENV" ]]; then
  python3 -m venv --system-site-packages "$SHARED_VENV"
fi
"$SHARED_VENV/bin/pip" install --upgrade pip
"$SHARED_VENV/bin/pip" install -r "$ACTIVE_SCRIPT_DIR/config/requirements.txt"

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
# 3b. Remove legacy pre-repo services that conflict with this codebase.
# ---------------------------------------------------------------------------
if [[ -x "$ACTIVE_SCRIPT_DIR/legacy/remove-legacy-buttons.sh" ]]; then
  log "removing legacy /usr/local/bin/boombox-* services (idempotent)"
  "$ACTIVE_SCRIPT_DIR/legacy/remove-legacy-buttons.sh"
fi

# ---------------------------------------------------------------------------
# 4. DAC overlay (/boot/firmware/usercfg.txt)
# ---------------------------------------------------------------------------
BOOT_FW_DIR=/boot/firmware
if [[ ! -d "$BOOT_FW_DIR" ]]; then
  BOOT_FW_DIR=/boot
fi
log "installing DAC overlay → $BOOT_FW_DIR/usercfg.txt"
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/usercfg.txt" "$BOOT_FW_DIR/usercfg.txt"

# Make sure config.txt actually `include`s usercfg.txt under the [all] section.
if [[ -f "$BOOT_FW_DIR/config.txt" ]] && ! sudo grep -qE '^\s*include\s+usercfg\.txt' "$BOOT_FW_DIR/config.txt"; then
  warn "appending 'include usercfg.txt' to $BOOT_FW_DIR/config.txt"
  echo -e "\n[all]\ninclude usercfg.txt" | sudo tee -a "$BOOT_FW_DIR/config.txt" >/dev/null
fi

# ---------------------------------------------------------------------------
# 5. ALSA default device
# ---------------------------------------------------------------------------
log "installing /etc/asound.conf"
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/asound.conf" /etc/asound.conf

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
# 6.7. Jellyfin auto-setup (run the wizard via the Startup API)
# ---------------------------------------------------------------------------
# If Jellyfin was manually set up before we took over (no boombox-managed
# state file present), wipe its DB and the StartupWizardCompleted flag so
# our automation can take ownership of admin credentials + library config.
JELLYFIN_ENV=/etc/boombox/jellyfin.env
# Take ownership if Jellyfin isn't boombox-managed yet. Triggers in two
# cases: a hand-completed wizard (IsStartupWizardCompleted=true) OR a
# half-wiped state where the DB exists but seeding never finished.
if dpkg -l jellyfin >/dev/null 2>&1 && ! sudo test -f "$JELLYFIN_ENV"; then
  log "Jellyfin not boombox-managed yet — full reset for clean wizard"
  sudo systemctl stop jellyfin
  # Whole data dir, not just jellyfin.db, so EF migrations seed users.
  sudo rm -rf /var/lib/jellyfin/data /var/lib/jellyfin/metadata \
              /var/lib/jellyfin/transcodes
  sudo find /etc/jellyfin -maxdepth 1 -name '*.xml' -delete
  sudo systemctl start jellyfin
fi

log "running Jellyfin first-run automation"
sudo BOOMBOX_VIDEO_DIR="$VIDEO_DIR" python3 \
  "$ACTIVE_REPO/services/boombox-jellyfin-setup.py" \
  || warn "Jellyfin auto-setup didn't finish cleanly (check /etc/boombox/jellyfin.env)"

log "installing /etc/mopidy/mopidy.conf"
sudo mkdir -p /etc/mopidy
# Install with 0600 + boombox-user ownership so boombox-library can
# rewrite the [subsonic] block at runtime when the user saves Settings.
# Mopidy reads the file before dropping privileges so user ownership is fine.
sudo install -m 0600 -o "$BOOMBOX_USER" -g "$BOOMBOX_USER" \
    "$ACTIVE_SCRIPT_DIR/config/mopidy.conf" /etc/mopidy/mopidy.conf
sudo sed -i "s|__MUSIC_DIR__|$MUSIC_DIR|g" /etc/mopidy/mopidy.conf

# Apply the Trixie scan.py compatibility patch (idempotent).
SCAN_PY=/usr/lib/python3/dist-packages/mopidy/audio/scan.py
if [[ -f "$SCAN_PY" ]] && sudo grep -q 'msg.get_structure().get_value("caps").get_name()' "$SCAN_PY"; then
  log "patching mopidy scan.py (Trixie python3-gi compatibility)"
  ( cd / && sudo patch -p0 < "$ACTIVE_REPO/services/scan-py-fix.diff" ) || warn "scan.py patch failed (already applied?)"
fi

# ---------------------------------------------------------------------------
# 7. Build UI in place — nginx serves directly out of current/ui/dist/
# ---------------------------------------------------------------------------
log "building UI in $ACTIVE_REPO/ui"
(
  cd "$ACTIVE_REPO/ui"
  npm install --no-audit --no-fund
  npm run build
)
# nginx (www-data) serves the SPA straight from the release tree. The bundle
# is non-sensitive (it ships to browsers anyway), so make it world-readable
# and ensure every parent dir up to it is world-traversable. No chgrp/sudo
# needed — the install user owns /opt/boombox.
chmod -R a+rX "$ACTIVE_REPO/ui/dist"
chmod o+x "$BOOMBOX_ROOT" "$RELEASES_DIR" "$ACTIVE_REPO" "$ACTIVE_REPO/ui"

log "building remote-ui (PWA) in $ACTIVE_REPO/remote-ui"
(
  cd "$ACTIVE_REPO/remote-ui"
  npm install --no-audit --no-fund
  npm run build
)
chmod -R a+rX "$ACTIVE_REPO/remote-ui/dist"
chmod o+x "$ACTIVE_REPO/remote-ui"
# Tear down the legacy doc root if it's still around.
if [[ -d /var/www/boombox && ! -L /var/www/boombox ]]; then
  log "removing legacy /var/www/boombox (nginx now serves from current/ui/dist)"
  sudo rm -rf /var/www/boombox
fi

# ---------------------------------------------------------------------------
# 8. nginx site
# ---------------------------------------------------------------------------
log "installing nginx site"
sudo mkdir -p /etc/nginx/snippets
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/nginx-boombox-common.conf" /etc/nginx/snippets/boombox-common.conf
TMP_NGINX="$(mktemp)"
sed "s|__REMOTE_WEB_PORT__|$REMOTE_WEB_PORT|g" "$ACTIVE_SCRIPT_DIR/config/nginx.conf" > "$TMP_NGINX"
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
  "$ACTIVE_SCRIPT_DIR/config/smb.conf" > "$TMP_SMB"
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
install -m 0644 "$ACTIVE_SCRIPT_DIR/systemd/user/"*.service "$HOME/.config/systemd/user/"

systemctl --user daemon-reload

USER_UNITS=(
  boombox-state
  boombox-audio
  boombox-orchestrator
  boombox-buttons
  boombox-remote
  boombox-resume
  boombox-bt-volume
  boombox-kiosk
  boombox-kiosk-guard
  boombox-osk
  boombox-updater
  boombox-library
  boombox-rfid
)
for u in "${USER_UNITS[@]}"; do
  systemctl --user enable "$u.service"
done

# System-side template + udev rule for USB auto-mount.
log "installing USB auto-mount (system unit + udev rule)"
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/systemd/system/boombox-usb-mount@.service" \
  /etc/systemd/system/boombox-usb-mount@.service
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/udev/99-boombox-usb.rules" \
  /etc/udev/rules.d/99-boombox-usb.rules

# System-side auto-flash for CYD wireless remotes: any CH340 USB-to-serial
# plugged in is checked against /opt/boombox/firmware/cyd/firmware.bin and
# re-flashed if it differs. The staged binary is populated by `pi-flash`.
log "installing CYD auto-flash (script + system unit + udev rule)"
sudo install -m 0755 "$ACTIVE_SCRIPT_DIR/bin/cyd-autoflash" /usr/local/bin/cyd-autoflash
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/systemd/system/cyd-autoflash@.service" \
  /etc/systemd/system/cyd-autoflash@.service
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/udev/99-cyd-autoflash.rules" \
  /etc/udev/rules.d/99-cyd-autoflash.rules
sudo install -d -o root -g root -m 755 /opt/boombox/firmware/cyd

sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=block --action=change || true

# usb-mount needs to know which user owns the music directory.
echo "$BOOMBOX_USER" | sudo tee /etc/boombox/desktop-user >/dev/null
sudo chmod 0644 /etc/boombox/desktop-user

# Sudoers fragment for library-scan / mopidy-restart from the touch UI.
log "installing sudoers fragment for boombox"
TMP_SUDOERS="$(mktemp)"
sed "s/%BOOMBOX_USER%/$BOOMBOX_USER/g" "$ACTIVE_SCRIPT_DIR/sudoers/boombox" > "$TMP_SUDOERS"
sudo install -m 0440 -o root -g root "$TMP_SUDOERS" /etc/sudoers.d/boombox
sudo visudo -cf /etc/sudoers.d/boombox
rm -f "$TMP_SUDOERS"

# Lingering so user services come up on boot before the user logs in.
sudo loginctl enable-linger "$BOOMBOX_USER"

# Labwc kiosk config: hide window title bars + don't autostart the
# desktop panel / file-manager-as-desktop. These run as the user, not
# system-wide, so install lands them in ~/.config/labwc/.
log "installing Chromium managed policy (suppresses save-password, autofill, etc.)"
sudo mkdir -p /etc/chromium/policies/managed
sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/chromium-policy.json" \
  /etc/chromium/policies/managed/boombox.json

log "installing labwc kiosk config"
mkdir -p "$HOME/.config/labwc"
install -m 0644 "$ACTIVE_SCRIPT_DIR/config/labwc-rc.xml" "$HOME/.config/labwc/rc.xml"
install -m 0644 "$ACTIVE_SCRIPT_DIR/config/labwc-autostart" "$HOME/.config/labwc/autostart"

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
  sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/buttons.json" /etc/boombox/buttons.json
elif ! sudo grep -q '"power"' /etc/boombox/buttons.json; then
  # Old 5-action schema detected; back up and replace with the full one.
  log "upgrading buttons.json schema (backup at /etc/boombox/buttons.json.pre-fullbuttons)"
  sudo cp /etc/boombox/buttons.json /etc/boombox/buttons.json.pre-fullbuttons
  sudo install -m 0644 "$ACTIVE_SCRIPT_DIR/config/buttons.json" /etc/boombox/buttons.json
fi

# ---------------------------------------------------------------------------
# 11. boombox-update on PATH
# ---------------------------------------------------------------------------
sudo install -m 0755 "$ACTIVE_REPO/bin/boombox-update" /usr/local/bin/boombox-update

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
