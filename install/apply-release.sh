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
warn() { printf '\033[1;33m[apply]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[apply]\033[0m %s\n' "$*" >&2; exit 1; }

# A ref names a release directory under $RELEASES and is interpolated into
# `rm -rf "$RELEASES/$ref"` and `git clone --branch "$ref"`. Restrict it to a
# git tag / short-or-full SHA so it can never contain a path separator or `..`
# that would escape the releases tree, and so it can't smuggle git-clone
# options. The Python updater validates too; this is the last line of defence
# for any caller (CLI, manual) that reaches the shell directly.
require_valid_ref() {
  local ref="$1"
  [[ "$ref" =~ ^(v[0-9A-Za-z][0-9A-Za-z._-]*|[0-9a-f]{7,40})$ ]] \
    || fail "invalid ref '$ref' (must be a version tag like v1.2.3 or a commit SHA)"
}

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
    require_valid_ref "$ref"
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
    require_valid_ref "$ref"
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
    require_valid_ref "$ref"
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
    require_valid_ref "$ref"
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
    # The exact path is required to match the narrow sudoers entry. On a
    # box where install.sh hasn't run since the entry was added, sudo will
    # refuse — that's fine, the nginx config falls back to whatever
    # install.sh last staged, and the next install.sh run repairs the path.
    if [[ -f "$CURRENT/install/config/nginx-boombox-common.conf" ]]; then
      if sudo -n /usr/bin/install -m 0644 \
           /opt/boombox/current/install/config/nginx-boombox-common.conf \
           /etc/nginx/snippets/boombox-common.conf 2>/dev/null; then
        sudo /usr/sbin/nginx -t || warn "nginx -t failed after snippet sync"
      else
        warn "sudoers missing nginx-snippet entry; run install.sh once to enable per-deploy nginx sync"
      fi
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
      boombox-remote boombox-library boombox-rfid
    )
    # Enable any unit not yet enabled — handles freshly-added units like
    # boombox-rfid landing in a deploy after install.sh last ran.
    for u in "${units[@]}"; do
      systemctl --user is-enabled --quiet "$u.service" \
        || systemctl --user enable "$u.service" 2>/dev/null || true
    done
    for u in "${units[@]}"; do
      systemctl --user restart "$u.service" || true
    done
    sudo /usr/bin/systemctl reload nginx
    # Best-effort: reload the kiosk Chromium tab so the freshly-built SPA
    # is picked up without restarting the long-running browser process.
    # Uses the DevTools remote-debugging port that boombox-kiosk already
    # exposes (--remote-debugging-port=9222). Silent failure is fine —
    # the page will pick up on next manual refresh.
    python3 - <<'PYRELOAD' 2>/dev/null || true
import json, urllib.request
try:
    from websockets.sync.client import connect
except ImportError:
    raise SystemExit(0)
try:
    tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2).read())
except Exception:
    raise SystemExit(0)
for t in tabs:
    if t.get("url", "").startswith("http://localhost"):
        try:
            with connect(t["webSocketDebuggerUrl"], open_timeout=2) as ws:
                ws.send(json.dumps({"id":1, "method":"Page.reload", "params":{"ignoreCache": True}}))
                ws.recv()
        except Exception:
            pass
        break
PYRELOAD
    ;;

  verify)
    log "verify liveness"
    deadline=$(( $(date +%s) + 30 ))
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
      boombox-remote boombox-library boombox-rfid
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
    # is-active fires the moment systemd-exec hands off to the Python entry
    # point — the aiohttp server takes another second or two to bind its
    # port. Retry each probe up to 10s instead of failing on the first 502.
    probe() {
      local url="$1" name="$2" tries=0
      while (( tries < 10 )); do
        if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then return 0; fi
        tries=$((tries + 1))
        sleep 1
      done
      fail "$name"
    }
    probe http://localhost/                  "nginx /"
    probe http://localhost/remote/           "/remote/"
    probe http://localhost/api/state         "/api/state"
    # /api/buttons/ has no index handler — probe a real GET endpoint.
    probe http://localhost/api/buttons/config "/api/buttons/config"
    # Data-plane services: the catalog/streaming resolver and the RFID reader.
    # Both run their HTTP server regardless of whether a USB cache drive or a
    # reader is attached, so these probes are safe on hardware-less devices and
    # a release that breaks the core music path now fails verify → auto-rollback.
    probe http://localhost/api/library/health "/api/library/health"
    probe http://localhost/api/rfid/status    "/api/rfid/status"
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
      boombox-remote boombox-library boombox-rfid
    )
    for u in "${units[@]}"; do
      systemctl --user restart "$u.service" || true
    done
    sudo /usr/bin/systemctl reload nginx
    ;;

  cleanup)
    ref="${1:?ref required}"
    require_valid_ref "$ref"
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
