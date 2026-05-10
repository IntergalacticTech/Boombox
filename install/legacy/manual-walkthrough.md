# 🎶 Raspberry Pi Boombox  
**A self-contained touchscreen music player built on Raspberry Pi 5 + 52Pi EP-0218 DAC**

This guide walks through setting up a full-featured, kiosk-style music player using Raspberry Pi OS 64-bit (Debian 13 “trixie”), Chromium, Mopidy + Iris, and the 52Pi EP-0218 PCM5122 DAC.  
The result: a standalone boombox that boots directly into a touchscreen interface and plays through high-quality analog audio.

---

## 🧰 Hardware
- Raspberry Pi 5 (or Pi 4)
- 52Pi EP-0218 DAC (PCM5102A / PCM5122 I²S)
- 5″ HDMI + USB touchscreen
- Powered speakers or amplifier
- microSD card (16 GB+)
- Optional: Wi-Fi dongle for hotspot mode, GPIO buttons

---

## ⚙️ 1. Install the Base OS
1. Flash **Raspberry Pi OS 64-bit** with Raspberry Pi Imager.  
2. Boot and run:
   ```bash
   sudo raspi-config
   ```
   Enable:
   - SSH  
   - I²S interface  
   - Disable onboard audio (`dtparam=audio=off`)  
   - Set locale/timezone/Wi-Fi  

3. Update:
   ```bash
   sudo apt update && sudo apt full-upgrade -y && sudo reboot
   ```

---

## 🖥️ 2. Touchscreen + Kiosk Mode
Install Chromium and autostart it full-screen:

```bash
sudo apt install -y chromium unclutter
mkdir -p ~/.config/autostart
tee ~/.config/autostart/chromium-kiosk.desktop >/dev/null <<'EOF'
[Desktop Entry]
Type=Application
Name=Chromium Kiosk
Exec=chromium --kiosk http://localhost:6680/iris --incognito   --noerrdialogs --disable-session-crashed-bubble   --overscroll-history-navigation=0
X-GNOME-Autostart-enabled=true
EOF
```

Disable screen blanking:
```bash
sudo raspi-config  # Display → Screen Blanking → Disable
```

---

## 🔊 3. Enable the 52Pi EP-0218 DAC
Create `/boot/firmware/usercfg.txt`:

```bash
sudo tee /boot/firmware/usercfg.txt >/dev/null <<'EOF'
dtparam=i2s=on
dtparam=audio=off
dtoverlay=hifiberry-dacplus
EOF
```

Reboot and verify:
```bash
aplay -l
```
Expected line:
```
card 2: sndrpihifiberry [HifiBerry DAC HiFi pcm5102a/5122-hifi-0]
```

---

## 🎚️ 4. Set the DAC as the Default ALSA Device
Create `/etc/asound.conf`:
```bash
sudo tee /etc/asound.conf >/dev/null <<'EOF'
pcm.!default {
    type plug
    slave.pcm "hw:sndrpihifiberry"
}
ctl.!default {
    type hw
    card sndrpihifiberry
}
EOF
```

Reboot or restart sound:
```bash
sudo systemctl restart sound.target
```

### Test Audio
```bash
speaker-test -D plughw:2,0 -c 2 -t sine
```
You should hear alternating tones on the DAC’s RCA or 3.5 mm output.  
Use **powered speakers or an amplifier**.

---

## 🎵 5. Install Mopidy + Iris Web UI
```bash
sudo apt install -y mopidy mopidy-mpd mopidy-local
sudo pip install Mopidy-Iris --break-system-packages
```

Create `/etc/mopidy/mopidy.conf`:
```ini
[core]
cache_dir = /var/cache/mopidy
data_dir  = /var/lib/mopidy

[audio]
output = alsasink
mixer  = software

[local]
media_dir = /home/jwc/Music
scan_timeout = 1000

[iris]
enabled = true
country = US
```

Start and enable Mopidy:
```bash
sudo systemctl enable mopidy
sudo systemctl start mopidy
```

Open **http://localhost:6680/iris** on the Pi’s touchscreen — you’ll see the Iris interface.

---

## 📁 6. Add Music
Copy files to:
```
/home/jwc/Music
```
Scan your library:
```bash
sudo mopidyctl local scan
```

---

## 🌐 7. Optional Add-Ons

| Feature | Command | Notes |
|----------|----------|-------|
| **Spotify** | `sudo apt install -y mopidy-spotify` | Add `[spotify]` section in `mopidy.conf` with credentials |
| **AirPlay Receiver** | `sudo apt install -y shairport-sync` | Appears as “Boombox” on AirPlay devices |
| **Bluetooth Input** | `sudo apt install -y pulseaudio-module-bluetooth bluez-tools` | Pair via `bluetoothctl` |
| **Server Mode (Hotspot + Uploader)** | `sudo apt install -y hostapd dnsmasq python3-flask` | Host Wi-Fi AP + simple Flask upload page |

---

## 🔁 8. Reliability + Polish
- Enable auto-start:
  ```bash
  sudo systemctl enable mopidy
  ```
- Auto-mount USB/NAS drives to `/home/jwc/Music`.
- Mopidy’s **software mixer** handles volume safely.
- The kiosk autostarts Chromium → Iris → plays through DAC.

---

## ✅ Result
After boot:

1. Desktop loads.  
2. Chromium opens full-screen to **Iris**.  
3. Mopidy provides local / Spotify / AirPlay / Bluetooth playback.  
4. Audio outputs through the 52Pi EP-0218 DAC.  
5. System recovers cleanly after power loss.

---

## 🧩 Troubleshooting Appendix

| Symptom | Check |
|----------|-------|
| `dtoverlay -l` shows “No overlays loaded” | Create `/boot/firmware/usercfg.txt` (don’t edit `config.txt` directly) |
| Still no overlay | If using Pi 5, check `/boot/firmware/extlinux/extlinux.conf` for `fdtoverlays /overlays/hifiberry-dacplus.dtbo` |
| No sound | Try one of these overlays:<br>`dtoverlay=hifiberry-dacplus`<br>`dtoverlay=hifiberry-dac`<br>`dtoverlay=rpi-dac`<br>`dtoverlay=iqaudio-dac` |
| “Invalid argument” from `speaker-test` | Make sure `/etc/asound.conf` uses `type plug` not `type hw` |
| Volume control missing | Use Mopidy’s `mixer = software` |
| No `/boot/firmware` directory | Mount boot partition or ensure firmware installed (`sudo apt install -y raspi-firmware`) |

---

## 📦 Directory Snapshot
```
/boot/firmware/usercfg.txt     → enables DAC overlay
/etc/asound.conf               → defaults audio to DAC
/etc/mopidy/mopidy.conf        → Mopidy + Iris config
~/.config/autostart/…          → kiosk Chromium launcher
/home/jwc/Music/               → local music library
```

---

Enjoy your new **Raspberry Pi Boombox** — boot, touch, and play 🎵
