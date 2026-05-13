#!/usr/bin/env bash
# Disable and remove the two pre-repo services running on the Pi:
#   boombox-button-handler.service  — older GPIO handler at /usr/local/bin/
#   boombox-mode-manager.service    — older source orchestrator at /usr/local/bin/
# Both are superseded by services/boombox-buttons.py and services/boombox-orchestrator.py.
# Idempotent: safe to re-run.

set -euo pipefail

LEGACY_SERVICES=(
  boombox-button-handler.service
  boombox-mode-manager.service
)
LEGACY_BINARIES=(
  /usr/local/bin/boombox-button-handler.py
  /usr/local/bin/boombox-mode-manager.py
)

# Snapshot unit-file list once. Avoids `set -o pipefail` + SIGPIPE killing
# the pipeline when `grep -q` exits early on a match.
UNIT_FILES="$(systemctl list-unit-files --no-pager 2>/dev/null || true)"

for svc in "${LEGACY_SERVICES[@]}"; do
  if grep -q "^${svc}" <<<"$UNIT_FILES"; then
    echo "[legacy] disabling ${svc}"
    sudo systemctl disable --now "${svc}" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${svc}"
  fi
done

for bin in "${LEGACY_BINARIES[@]}"; do
  if [[ -e "${bin}" ]]; then
    echo "[legacy] removing ${bin}"
    sudo rm -f "${bin}"
  fi
done

sudo systemctl daemon-reload
echo "[legacy] done"
