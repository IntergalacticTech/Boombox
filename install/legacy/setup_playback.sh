#!/bin/bash
set -e

echo "🎶 Setting up auto-resume playback for Raspberry Pi Boombox"

# Ensure Mopidy is installed
if ! command -v mopidy >/dev/null; then
  echo "Installing Mopidy..."
  sudo apt update
  sudo apt install -y mopidy mopidy-mpd mopidy-local
fi

# Install persistence + autoplay extensions
echo "Installing Mopidy persistence plugins..."
sudo pip install --break-system-packages Mopidy-Local-SaveState Mopidy-Autoplay

# Enable Mopidy service at boot
sudo systemctl enable mopidy

# Update Mopidy config with software mixer and persistence
sudo tee /etc/mopidy/mopidy.conf >/dev/null <<'EOF'
[core]
cache_dir = /var/cache/mopidy
data_dir = /var/lib/mopidy

[audio]
output = alsasink
mixer = software

[local]
media_dir = /home/jwc/Music
scan_timeout = 1000

[iris]
enabled = true
country = US

[savestate]
enabled = true

[autoplay]
enabled = true
EOF

# Restart Mopidy
sudo systemctl restart mopidy

# Add crontab entry to resume playback on reboot (optional)
if ! crontab -l 2>/dev/null | grep -q "mpc play"; then
  (crontab -l 2>/dev/null; echo "@reboot sleep 10 && mpc play") | crontab -
fi

echo "✅ Setup complete!"
echo "→ Mopidy will resume the last played track automatically after boot."
echo "→ Chromium kiosk will open Iris interface at http://localhost:6680/iris."
echo "→ If Iris shows a 'Welcome' screen, tap Submit once and it will remember."
