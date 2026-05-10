#!/usr/bin/env bash
set -euo pipefail

echo "🎶 Setting up auto-resume playback WITHOUT third-party plugins"

# Ensure prerequisites
if ! command -v mpc >/dev/null 2>&1; then
  echo "Installing Mopidy + MPD client (mpc)..."
  sudo apt update
  sudo apt install -y mopidy mopidy-mpd mopidy-local mpc
fi

STATE_DIR="/var/lib/mopidy-autoresume"
sudo mkdir -p "$STATE_DIR"
sudo chown -R $USER:$USER "$STATE_DIR"

# Create saver script
sudo tee /usr/local/bin/mopidy-save-state.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="/var/lib/mopidy-autoresume"
QUEUE_FILE="$STATE_DIR/queue.lst"
META_FILE="$STATE_DIR/meta.env"

# If Mopidy (MPD) isn't reachable, exit quietly
if ! mpc status >/dev/null 2>&1; then
  exit 0
fi

# Save full queue (as file URIs or local paths)
mpc -f "%file%" playlist > "$QUEUE_FILE" || true

# Get current status info
STATUS="$(mpc status || true)"
# Extract playing/paused, current file, elapsed time, and position index
STATE="stopped"
echo "$STATUS" | grep -q "playing" && STATE="playing"
echo "$STATUS" | grep -q "paused" && STATE="paused"

CURRENT_FILE="$(mpc -f "%file%" current || true)"
# Position looks like: "#5/20  1:23/3:45"
POS_LINE="$(echo "$STATUS" | sed -n '2p' || true)"
# Get current index number between '#' and '/'
CUR_INDEX="$(echo "$POS_LINE" | sed -n 's/.*#\([0-9]\+\)\/.*/\1/p')"
# Get elapsed mm:ss left side of " / "
ELAPSED="$(echo "$POS_LINE" | sed -n 's/.* \([0-9]\+:[0-9]\+\)\/.*/\1/p')"

# Defaults if parsing failed
CUR_INDEX="${CUR_INDEX:-1}"
ELAPSED="${ELAPSED:-0:00}"

cat > "$META_FILE" <<META
STATE="$STATE"
CURRENT_FILE="$CURRENT_FILE"
CUR_INDEX="$CUR_INDEX"
ELAPSED="$ELAPSED"
META
EOF

sudo chmod +x /usr/local/bin/mopidy-save-state.sh

# Create restore script
sudo tee /usr/local/bin/mopidy-restore-state.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="/var/lib/mopidy-autoresume"
QUEUE_FILE="$STATE_DIR/queue.lst"
META_FILE="$STATE_DIR/meta.env"

# Wait briefly for Mopidy to accept MPD connections
for i in {1..20}; do
  if mpc status >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! mpc status >/dev/null 2>&1; then
  exit 0
fi

# If no saved state, exit
[ -f "$QUEUE_FILE" ] || exit 0
[ -f "$META_FILE" ] || exit 0

# shellcheck source=/dev/null
. "$META_FILE"

# Rebuild queue
mpc clear
while IFS= read -r track; do
  # Skip empty lines
  [ -n "$track" ] && mpc add "$track" || true
done < "$QUEUE_FILE"

# If there is no queue, bail
COUNT="$(mpc playlist | wc -l)"
if [ "${COUNT}" -eq 0 ]; then
  exit 0
fi

# Jump to the previous track index if possible
mpc play "${CUR_INDEX:-1}"

# Seek to previous elapsed time (mm:ss), ignore errors if format differs
if [ -n "${ELAPSED:-}" ]; then
  mpc seek "$ELAPSED" || true
fi

# Resume only if previously playing; if paused, leave paused
if [ "${STATE:-stopped}" = "playing" ]; then
  mpc play
elif [ "${STATE:-stopped}" = "paused" ]; then
  mpc pause
fi
EOF

sudo chmod +x /usr/local/bin/mopidy-restore-state.sh

# systemd unit to SAVE on shutdown / service stop
sudo tee /etc/systemd/system/mopidy-save-state.service >/dev/null <<'EOF'
[Unit]
Description=Save Mopidy queue and playback state
DefaultDependencies=no
Before=shutdown.target
After=mopidy.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/mopidy-save-state.sh
TimeoutSec=10

[Install]
WantedBy=shutdown.target
EOF

# systemd unit to RESTORE after Mopidy is running
sudo tee /etc/systemd/system/mopidy-restore-state.service >/dev/null <<'EOF'
[Unit]
Description=Restore Mopidy queue and resume playback
After=network-online.target mopidy.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/mopidy-restore-state.sh

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mopidy-restore-state.service
sudo systemctl enable mopidy-save-state.service

# Ensure Mopidy starts at boot
sudo systemctl enable mopidy

echo "✅ Auto-resume is set up."
echo "• State is saved at shutdown and restored after boot."
echo "• No third-party Mopidy plugins required."
echo "Tip: play something now, then 'sudo reboot' to test restore."
