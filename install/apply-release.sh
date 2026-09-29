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

# Re-sync the nginx site file + shared snippet from $CURRENT through the root
# helper: it renders the LAN port from the root-owned web-auth.env, installs
# both files together, runs `nginx -t` and restores the previous pair if that
# fails. Never install the snippet alone — the kiosk's `location /` lives in
# the site file.
#
# `nginx_sync strict` (swap) FAILS when the helper is too old to know the
# action, so a device whose root helper was never refreshed stops before
# restart/verify instead of restarting everything and failing the LAN-app
# probe. `revert` calls it non-strict: putting the old release back must
# never be blocked by the helper.
HELPER_TOO_OLD="the root helper /usr/local/sbin/boombox-setup-apply predates nginx-sync — reinstall the root helper — re-run install.sh on this device, then retry the update"
SETUP_APPLY_BIN="${BOOMBOX_SETUP_APPLY_BIN:-/usr/local/sbin/boombox-setup-apply}"
nginx_sync() {
  local strict="${1:-}" out
  out="$(printf '{"action":"nginx-sync"}' | sudo -n /usr/local/sbin/boombox-setup-apply 2>&1)" || true
  if [[ "$out" == *'"ok": true'* ]]; then
    log "nginx site + snippet in sync with $(readlink "$CURRENT")"
  elif [[ "$strict" == strict && "$out" == *'unknown action: nginx-sync'* ]]; then
    fail "nginx config not synced: $HELPER_TOO_OLD"
  else
    warn "nginx config not synced: ${out:-no output} — reinstall /usr/local/sbin/boombox-setup-apply (install.sh) to enable per-deploy nginx sync"
  fi
}

# Read-only capability probe for preflight: does the installed root helper
# know the nginx-sync action at all? (0755 root-owned, so readable.) Lets an
# un-prepped device abort cleanly — no symlink moved, nothing restarted.
require_helper_nginx_sync() {
  grep -qF '"nginx-sync"' "$SETUP_APPLY_BIN" 2>/dev/null || fail "$HELPER_TOO_OLD"
}

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
    rm -rf "${RELEASES:?}/$ref"
    if [[ "$ref" == v* ]]; then
      git clone --depth=1 --branch "$ref" "$REPO_URL" "$RELEASES/$ref"
    else
      # `clone --branch` only takes branch/tag names, never a commit SHA.
      # Clone without checkout (blobless, so only the target commit's files
      # are downloaded), then check the SHA out detached. A commit that is
      # not reachable from any branch/tag (e.g. a PR head) isn't in the
      # clone — fetch it by id; servers only honour want-by-id for a FULL
      # 40-char SHA, so a short one must be reachable from a branch/tag.
      git clone --no-checkout --filter=blob:none "$REPO_URL" "$RELEASES/$ref"
      if ! git -C "$RELEASES/$ref" cat-file -e "$ref^{commit}" 2>/dev/null; then
        git -C "$RELEASES/$ref" fetch origin "$ref" \
          || fail "commit $ref not found upstream (short SHAs must be on a branch or tag)"
      fi
      git -C "$RELEASES/$ref" switch --detach "$ref^{commit}"
    fi
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
    # nginx (www-data) will serve each SPA straight from this release tree
    # once `swap` points `current` here — make the bundle world-readable and
    # the release dir + package dir world-traversable. `npm ci` installs
    # exactly what the committed lockfile pins (and fails loudly if it's out
    # of sync) instead of re-resolving ranges on the device.
    build_spa() {
      local dir="$1"
      (
        cd "$dir"
        if [[ -f package-lock.json ]]; then
          npm ci --no-audit --no-fund
        else
          npm install --no-audit --no-fund
        fi
        npm run build
      )
      chmod -R a+rX "$dir/dist"
      chmod o+x "$dir"
    }
    chmod o+x "$ROOT" "$RELEASES" "$RELEASES/$ref"
    build_spa "$RELEASES/$ref/ui"
    build_spa "$RELEASES/$ref/remote-ui"
    # The first-run wizard (/setup/, also Settings → "Run setup again").
    # install.sh builds it; without this an OTA update left /setup/ 404ing.
    # Guarded so an older release that predates setup-ui still builds.
    if [[ -f "$RELEASES/$ref/setup-ui/package.json" ]]; then
      build_spa "$RELEASES/$ref/setup-ui"
    fi
    ;;

  preflight)
    ref="${1:?ref required}"
    require_valid_ref "$ref"
    log "preflight $ref"
    require_helper_nginx_sync
    [[ -f "$RELEASES/$ref/ui/dist/index.html" ]] || fail "ui/dist/index.html missing"
    [[ -f "$RELEASES/$ref/remote-ui/dist/index.html" ]] || fail "remote-ui/dist/index.html missing"
    if [[ -f "$RELEASES/$ref/setup-ui/package.json" ]]; then
      [[ -f "$RELEASES/$ref/setup-ui/dist/index.html" ]] || fail "setup-ui/dist/index.html missing"
    fi
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
    # Site file + snippet move together (see nginx_sync). The reload happens
    # in the `restart` step; this only stages the files. Strict: an old
    # helper fails the swap here, before restart/verify.
    nginx_sync strict
    # Root-executed helpers live as root-owned copies outside the release
    # tree precisely so this (unprivileged) deploy can NOT rewrite them —
    # granting sudo to copy them from here would reopen that hole. So they
    # only refresh when install.sh runs; just flag drift for the operator.
    for pair in \
      "services/boombox-usb-mount.sh:/usr/local/sbin/boombox-usb-mount" \
      "install/bin/boombox-setup-apply:/usr/local/sbin/boombox-setup-apply"; do
      src="$CURRENT/${pair%%:*}"; dst="${pair#*:}"
      if [[ -f "$src" ]] && ! cmp -s "$src" "$dst"; then
        warn "$dst differs from this release's ${pair%%:*} — re-run install.sh to refresh the root-owned copy"
      fi
    done
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
      boombox-remote boombox-library boombox-rfid boombox-setup
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
    # Self-heal a release that ships setup-ui but whose build step predates
    # building it (the build ran from the OLD release's script, which didn't
    # know about setup-ui) — otherwise /setup/ 404s until the next update.
    # Best-effort: a failed build is caught by verify's /setup/ probe.
    if [[ -f "$CURRENT/setup-ui/package.json" && ! -f "$CURRENT/setup-ui/dist/index.html" ]]; then
      log "setup-ui/dist missing — building it"
      # Chained with && — errexit is suspended inside an `if` condition,
      # so a failed `npm ci` would otherwise fall through to the build.
      if (
        cd "$CURRENT/setup-ui" && {
          if [[ -f package-lock.json ]]; then
            npm ci --no-audit --no-fund
          else
            npm install --no-audit --no-fund
          fi
        } && npm run build
      ); then
        chmod -R a+rX "$CURRENT/setup-ui/dist"
        chmod o+x "$CURRENT/setup-ui"
      else
        warn "setup-ui build failed; verify will fail the /setup/ probe"
      fi
    fi
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
      boombox-remote boombox-library boombox-rfid boombox-setup
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
    probe http://localhost/                  "nginx / (kiosk UI)"
    # The LAN app at / on the LAN port, without Basic auth. A 401 here means
    # the nginx pair wasn't synced (old boombox-setup-apply) — fail so the
    # release rolls back instead of leaving the LAN on the old config.
    lan_port="$(sed -n 's/^BOOMBOX_WEB_PORT=//p' /etc/boombox/web-auth.env 2>/dev/null | head -n1)" || true
    lan_port="${lan_port:-8090}"
    probe "http://127.0.0.1:$lan_port/"      "LAN app / (nginx site not synced? reinstall boombox-setup-apply)"
    probe http://localhost/api/state         "/api/state"
    # /api/buttons/ has no index handler — probe a real GET endpoint.
    probe http://localhost/api/buttons/config "/api/buttons/config"
    # Data-plane services: the catalog/streaming resolver and the RFID reader.
    # Both run their HTTP server regardless of whether a USB cache drive or a
    # reader is attached, so these probes are safe on hardware-less devices and
    # a release that breaks the core music path now fails verify → auto-rollback.
    probe http://localhost/api/library/health "/api/library/health"
    probe http://localhost/api/rfid/status    "/api/rfid/status"
    # The first-run wizard SPA — only for releases that ship it. A release
    # missing setup-ui/dist makes nginx's try_files fallback loop (500), so
    # the probe fails and the updater rolls back instead of leaving /setup/
    # broken.
    if [[ -f "$CURRENT/setup-ui/package.json" ]]; then
      probe http://localhost/setup/           "/setup/"
    fi
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
    # Put the reverted release's nginx pair back before the reload below.
    nginx_sync
    # (see restart case for why these units — and why others — are omitted)
    units=(
      boombox-state boombox-audio boombox-orchestrator boombox-buttons
      boombox-resume boombox-bt-volume boombox-kiosk-guard boombox-osk
      boombox-remote boombox-library boombox-rfid boombox-setup
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
    rm -rf "${RELEASES:?}/$ref"
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
