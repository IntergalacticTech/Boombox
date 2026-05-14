#!/usr/bin/env bash
# update.sh — back-compat shim. The real updater lives in the boombox-updater
# service + install/apply-release.sh; this is here so anything still calling
# `update.sh` keeps working.
set -euo pipefail
exec /usr/local/bin/boombox-update "$@"
