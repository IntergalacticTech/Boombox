#!/usr/bin/env bash
# apply-release.sh — install a specific git ref into /opt/boombox/releases/<ref>,
# swap the `current` symlink, restart services. Designed to be safe to call
# from boombox-updater (window-driven) or from `boombox-update` (CLI fallback).
#
# Usage:
#   apply-release.sh fetch    <ref>
#   apply-release.sh build    <ref>
#   apply-release.sh preflight <ref>
#   apply-release.sh swap     <ref>
#   apply-release.sh restart
#   apply-release.sh verify
#   apply-release.sh revert
#   apply-release.sh cleanup  <ref>
#
# Each subcommand maps 1:1 to a Steps method on the Python side. Keeping
# them separate means the state machine can run them, log between them,
# and short-circuit cleanly on failure.
#
# Exit codes: 0 = ok, non-zero = step failed (the Python side translates
# this into StepResult.FAIL).

set -euo pipefail

ROOT="${BOOMBOX_ROOT:-/opt/boombox}"
RELEASES="$ROOT/releases"
CURRENT="$ROOT/current"
PREVIOUS="$ROOT/previous"
VENV="$ROOT/.venv"
REPO_URL="${BOOMBOX_REPO_URL:-https://github.com/IntergalacticTech/Boombox.git}"

log()  { printf '\033[1;36m[apply]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[apply]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,/^$/p' "$0" >&2
  exit 64
}

cmd="${1:-}"
[[ -n "$cmd" ]] || usage
shift || true

case "$cmd" in
  fetch)
    ref="${1:?ref required}"
    log "fetch $ref → $RELEASES/$ref"
    mkdir -p "$RELEASES"
    rm -rf "$RELEASES/$ref"
    git clone --depth=1 --branch "$ref" "$REPO_URL" "$RELEASES/$ref"
    # Persist the resolved version for later runs to compare against.
    if [[ "$ref" == v* ]]; then
      printf '%s\n' "$ref" >"$RELEASES/$ref/VERSION"
    else
      ( cd "$RELEASES/$ref" && git rev-parse --short HEAD ) >"$RELEASES/$ref/VERSION"
    fi
    ;;

  build)
    ref="${1:?ref required}"
    log "build $ref"
    [[ -d "$RELEASES/$ref" ]] || fail "$RELEASES/$ref missing — run fetch first"
    "$VENV/bin/pip" install -r "$RELEASES/$ref/install/config/requirements.txt"
    (
      cd "$RELEASES/$ref/ui"
      npm install --no-audit --no-fund
      npm run build
    )
    # nginx (www-data) will serve the SPA straight from this release tree
    # once `swap` points `current` here — make the bundle world-readable and
    # the release dir + ui/ world-traversable.
    chmod -R a+rX "$RELEASES/$ref/ui/dist"
    chmod o+x "$ROOT" "$RELEASES" "$RELEASES/$ref" "$RELEASES/$ref/ui"
    (
      cd "$RELEASES/$ref/remote-ui"
      npm install --no-audit --no-fund
      npm run build
    )
    chmod -R a+rX "$RELEASES/$ref/remote-ui/dist"
    chmod o+x "$RELEASES/$ref/remote-ui"
    ;;

  preflight)
    ref="${1:?ref required}"
    log "preflight $ref"
    [[ -f "$RELEASES/$ref/ui/dist/index.html" ]] || fail "ui/dist/index.html missing"
    [[ -f "$RELEASES/$ref/remote-ui/dist/index.html" ]] || fail "remote-ui/dist/index.html missing"
    for unit in "$RELEASES/$ref"/install/systemd/user/*.service; do
      systemd-analyze --user verify "$unit" || fail "systemd-analyze rejected $unit"
    done
    sudo /usr/sbin/nginx -t
    "$VENV/bin/python" -c "
import importlib.util, sys
for mod in ('boombox_updater', 'boombox_buttons'):
    spec = importlib.util.spec_from_file_location(
        mod, '$RELEASES/$ref/services/' + mod.replace('_', '-') + '.py')
" 2>/dev/null || true   # smoke; full import test runs in verify step
    ;;

  swap)
    ref="${1:?ref required}"
    log "swap → $ref"
    [[ -d "$RELEASES/$ref" ]] || fail "$RELEASES/$ref missing"
    # Capture current target as the new previous, atomically.
    if [[ -L "$CURRENT" ]]; then
      old_target="$(readlink "$CURRENT")"
      ln -sfn "$old_target" "$PREVIOUS.new"
      mv -Tf "$PREVIOUS.new" "$PREVIOUS"
    fi
    ln -sfn "releases/$ref" "$CURRENT.new"
    mv -Tf "$CURRENT.new" "$CURRENT"
    # Sync any new systemd unit files into ~/.config/systemd/user/.
    install -m 0644 "$CURRENT/install/systemd/user/"*.service \
      "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    # Sync the nginx snippet so source-controlled location blocks (e.g. the
    # /remote/ PWA mount, /api/remote/) land without re-running install.sh.
    # The reload happens in the `restart` step; this just stages the file.
    # The exact path is required to match the narrow sudoers entry.
    if [[ -f "$CURRENT/install/config/nginx-boombox-common.conf" ]]; then
      sudo /usr/bin/install -m 0644 \
        /opt/boombox/current/install/config/nginx-boombox-common.conf \
        /etc/nginx/snippets/boombox-common.conf
      sudo /usr/sbin/nginx -t
    fi
    ;;

  restart)
    log "restart user services (excluding updater)"
    # boombox-kiosk (Chromium itself) is intentionally NOT restarted — killing
    # the kiosk browser mid-update is disruptive; restarting boombox-kiosk-guard
    # (which IS in the list) re-pins/reloads the page so the new SPA loads.
    # boombox-updater self-restarts last (Python side, after verify).
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
      boombox-remote
    )
    for u in "${units[@]}"; do
      systemctl --user restart "$u.service" || true
    done
    sudo /usr/bin/systemctl reload nginx
    ;;

  verify)
    log "verify liveness"
    deadline=$(( $(date +%s) + 30 ))
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
      boombox-remote
    )
    while (( $(date +%s) < deadline )); do
      ok=1
      for u in "${units[@]}"; do
        systemctl --user is-active --quiet "$u.service" || { ok=0; break; }
      done
      (( ok == 1 )) && break
      sleep 1
    done
    (( ok == 1 )) || fail "user services did not all become active"
    curl -fsS --max-time 5 http://localhost/            >/dev/null || fail "nginx /"
    curl -fsS --max-time 5 http://localhost/remote/     >/dev/null || fail "/remote/"
    curl -fsS --max-time 5 http://localhost/api/state   >/dev/null || fail "/api/state"
    curl -fsS --max-time 5 http://localhost/api/buttons/ >/dev/null || fail "/api/buttons/"
    ;;

  revert)
    log "revert: current ↔ previous"
    [[ -L "$PREVIOUS" ]] || fail "no previous symlink to revert to"
    prev_target="$(readlink "$PREVIOUS")"
    cur_target="$(readlink "$CURRENT")"
    ln -sfn "$prev_target" "$CURRENT.new"
    mv -Tf "$CURRENT.new" "$CURRENT"
    ln -sfn "$cur_target" "$PREVIOUS.new"
    mv -Tf "$PREVIOUS.new" "$PREVIOUS"
    install -m 0644 "$CURRENT/install/systemd/user/"*.service \
      "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    # (see restart case for why these units — and why others — are omitted)
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
      boombox-remote
    )
    for u in "${units[@]}"; do
      systemctl --user restart "$u.service" || true
    done
    sudo /usr/bin/systemctl reload nginx
    ;;

  cleanup)
    ref="${1:?ref required}"
    log "cleanup $RELEASES/$ref"
    rm -rf "$RELEASES/$ref"
    ;;

  prune)
    log "prune releases (keep current, previous, +1 most recent)"
    keep_set=()
    [[ -L "$CURRENT" ]]  && keep_set+=("$(readlink "$CURRENT")")
    [[ -L "$PREVIOUS" ]] && keep_set+=("$(readlink "$PREVIOUS")")
    in_keep() { local needle="$1"; for k in "${keep_set[@]}"; do [[ "$k" == "$needle" ]] && return 0; done; return 1; }
    mapfile -t all < <(ls -1t "$RELEASES" 2>/dev/null || true)
    extra_kept=0
    for entry in "${all[@]}"; do
      target="releases/$entry"
      if in_keep "$target"; then continue; fi
      if (( extra_kept < 1 )); then extra_kept=$((extra_kept+1)); continue; fi
      log "  pruning $RELEASES/$entry"
      rm -rf "${RELEASES:?}/$entry"
    done
    ;;

  *)
    usage
    ;;
esac
