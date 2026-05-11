#!/usr/bin/env bash
# update.sh — pull latest, reinstall what drifted, restart services.
#
# Designed to be safe to run any time. Refuses to update if the working tree
# has local changes (override with --force) to avoid clobbering edits made
# on the Pi directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { printf '\033[1;36m[update]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[update]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[update]\033[0m %s\n' "$*" >&2; exit 1; }

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) fail "unknown arg: $arg" ;;
  esac
done

cd "$REPO_DIR"

if [[ -n "$(git status --porcelain)" ]] && [[ "$FORCE" -eq 0 ]]; then
  fail "local changes present in $REPO_DIR. Commit/stash them or rerun with --force."
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
log "fetching origin"
git fetch --prune origin

OLD_HEAD="$(git rev-parse HEAD)"
log "fast-forwarding $CURRENT_BRANCH"
if [[ "$FORCE" -eq 1 ]]; then
  git reset --hard "origin/$CURRENT_BRANCH"
else
  git merge --ff-only "origin/$CURRENT_BRANCH"
fi
NEW_HEAD="$(git rev-parse HEAD)"

if [[ "$OLD_HEAD" == "$NEW_HEAD" ]]; then
  log "already up to date ($NEW_HEAD)"
  exit 0
fi

CHANGED="$(git diff --name-only "$OLD_HEAD" "$NEW_HEAD")"
log "$(echo "$CHANGED" | wc -l | tr -d ' ') files changed"

ui_changed()       { echo "$CHANGED" | grep -qE '^ui/'; }
systemd_changed()  { echo "$CHANGED" | grep -qE '^install/systemd/'; }
config_changed()   { echo "$CHANGED" | grep -qE '^install/config/'; }
services_changed() { echo "$CHANGED" | grep -qE '^services/'; }
reqs_changed()     { echo "$CHANGED" | grep -qE '^install/config/requirements\.txt$'; }
install_changed()  { echo "$CHANGED" | grep -qE '^install/install\.sh$'; }

# Big changes → just rerun install.sh, which is idempotent.
if install_changed; then
  log "install.sh changed — rerunning the full installer"
  exec "$SCRIPT_DIR/install.sh"
fi

if reqs_changed; then
  log "Python deps changed — refreshing venv"
  "$REPO_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/config/requirements.txt"
fi

if ui_changed; then
  log "UI changed — rebuilding"
  (
    cd "$REPO_DIR/ui"
    npm install --no-audit --no-fund
    npm run build
  )
  sudo rsync -a --delete "$REPO_DIR/ui/dist/" /var/www/boombox/
  sudo chown -R www-data:www-data /var/www/boombox
fi

if config_changed; then
  log "configs changed — reinstalling"
  REMOTE_WEB_PORT="${BOOMBOX_WEB_PORT:-8090}"
  if sudo test -f /etc/boombox/web-auth.env; then
    while IFS='=' read -r key val; do
      case "$key" in
        BOOMBOX_WEB_PORT) REMOTE_WEB_PORT="${BOOMBOX_WEB_PORT:-$val}" ;;
      esac
    done < <(sudo cat /etc/boombox/web-auth.env)
  fi
  sudo install -m 0644 "$SCRIPT_DIR/config/asound.conf" /etc/asound.conf || true
  sudo install -m 0644 "$SCRIPT_DIR/config/mopidy.conf" /etc/mopidy/mopidy.conf
  sudo sed -i "s|__MUSIC_DIR__|${BOOMBOX_MUSIC_DIR:-/home/$USER/Music}|g" /etc/mopidy/mopidy.conf
  sudo mkdir -p /etc/nginx/snippets
  sudo install -m 0644 "$SCRIPT_DIR/config/nginx-boombox-common.conf" /etc/nginx/snippets/boombox-common.conf
  TMP_NGINX="$(mktemp)"
  sed "s|__REMOTE_WEB_PORT__|$REMOTE_WEB_PORT|g" "$SCRIPT_DIR/config/nginx.conf" > "$TMP_NGINX"
  sudo install -m 0644 "$TMP_NGINX" /etc/nginx/sites-available/boombox
  rm -f "$TMP_NGINX"
  sudo nginx -t && sudo systemctl reload nginx
  if [[ -f "$SCRIPT_DIR/config/smb.conf" ]]; then
    TMP_SMB="$(mktemp)"
    sed \
      -e "s|__MUSIC_DIR__|${BOOMBOX_MUSIC_DIR:-/home/$USER/Music}|g" \
      -e "s|__BOOMBOX_USER__|$USER|g" \
      "$SCRIPT_DIR/config/smb.conf" > "$TMP_SMB"
    sudo install -m 0644 "$TMP_SMB" /etc/samba/smb.conf
    rm -f "$TMP_SMB"
    sudo testparm -s >/dev/null && sudo systemctl reload-or-restart smbd 2>/dev/null || true
  fi
  sudo systemctl restart mopidy
fi

if systemd_changed; then
  log "systemd units changed — reinstalling"
  install -m 0644 "$SCRIPT_DIR/systemd/user/"*.service "$HOME/.config/systemd/user/"
  if [[ -f "$SCRIPT_DIR/systemd/system/boombox-usb-mount@.service" ]]; then
    sudo install -m 0644 "$SCRIPT_DIR/systemd/system/boombox-usb-mount@.service" \
      /etc/systemd/system/boombox-usb-mount@.service
    sudo systemctl daemon-reload
  fi
  systemctl --user daemon-reload
fi

# udev rules drift their own way.
if echo "$CHANGED" | grep -qE '^install/udev/'; then
  log "udev rules changed — reinstalling + reloading"
  sudo install -m 0644 "$SCRIPT_DIR/udev/99-boombox-usb.rules" \
    /etc/udev/rules.d/99-boombox-usb.rules
  sudo udevadm control --reload-rules
fi

# Sudoers fragment.
if echo "$CHANGED" | grep -qE '^install/sudoers/boombox$'; then
  log "sudoers fragment changed — reinstalling"
  TMP_SUDOERS="$(mktemp)"
  sed "s/%BOOMBOX_USER%/$USER/g" "$SCRIPT_DIR/sudoers/boombox" > "$TMP_SUDOERS"
  sudo install -m 0440 -o root -g root "$TMP_SUDOERS" /etc/sudoers.d/boombox
  sudo visudo -cf /etc/sudoers.d/boombox
  rm -f "$TMP_SUDOERS"
fi

if services_changed || systemd_changed || reqs_changed; then
  log "restarting user services"
  systemctl --user restart \
    boombox-state.service \
    boombox-audio.service \
    boombox-orchestrator.service \
    boombox-buttons.service \
    boombox-resume.service \
    boombox-bt-volume.service \
    boombox-kiosk-guard.service \
    2>/dev/null || true
fi

if ui_changed; then
  log "asking kiosk to reload the page"
  curl -s "http://localhost:9222/json" >/dev/null 2>&1 && \
    systemctl --user reload boombox-kiosk-guard.service 2>/dev/null || true
fi

log "update complete: $OLD_HEAD → $NEW_HEAD"
