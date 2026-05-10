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
  sudo install -m 0644 "$SCRIPT_DIR/config/asound.conf" /etc/asound.conf || true
  sudo install -m 0644 "$SCRIPT_DIR/config/mopidy.conf" /etc/mopidy/mopidy.conf
  sudo sed -i "s|__MUSIC_DIR__|${BOOMBOX_MUSIC_DIR:-/home/$USER/Music}|g" /etc/mopidy/mopidy.conf
  sudo install -m 0644 "$SCRIPT_DIR/config/nginx.conf" /etc/nginx/sites-available/boombox
  sudo nginx -t && sudo systemctl reload nginx
  sudo systemctl restart mopidy
fi

if systemd_changed; then
  log "systemd units changed — reinstalling"
  install -m 0644 "$SCRIPT_DIR/systemd/user/"*.service "$HOME/.config/systemd/user/"
  systemctl --user daemon-reload
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
