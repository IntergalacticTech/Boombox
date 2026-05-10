# 🎶 Raspberry Pi Boombox Project – Conversation Export & Summary

## 📌 Project Goal
Build a **portable Raspberry Pi-based boombox** with:
- Touchscreen UI
- High-quality DAC audio output
- Local music playback
- Optional streaming (Spotify, AirPlay, etc.)
- Future extensibility (GPS, hotspot upload mode, GPIO controls)

---

## 🧠 Key Decisions & Learnings

### 1. Abandoning Volumio
- Initial attempt used **Volumio**
- Issue: touchscreen not working
- Decision: move to **Raspberry Pi OS + custom stack**
- Benefit:
  - Full control over UI, drivers, and services
  - Easier debugging and extensibility

---

### 2. Choosing Software Stack
Evaluated:
- MoOde → good but less customizable
- piCorePlayer → too minimal
- Custom Raspbian → chosen

Final stack:
- **OS:** Raspberry Pi OS (Debian Trixie)
- **UI:** Chromium (kiosk mode)
- **Backend:** Mopidy
- **Frontend:** Iris (web UI)

---

### 3. Chromium Kiosk Setup
Problem:
- `chromium-browser` package not available

Solution:
- Use `chromium` package
- Configure autostart via:
  ~/.config/autostart/chromium-kiosk.desktop

---

### 4. DAC Setup (Critical Breakthrough)

Hardware:
- 52Pi EP-0218 DAC (PCM5102A / PCM5122)

Initial issue:
- No sound despite device appearing in `aplay -l`

Root cause:
- **Device Tree overlays not loading**

Fix:
- Use `/boot/firmware/usercfg.txt`
- Add:
  dtparam=i2s=on  
  dtparam=audio=off  
  dtoverlay=hifiberry-dacplus  

Result:
- DAC properly initialized
- Audio output working

---

### 5. ALSA Configuration

`/etc/asound.conf`
pcm.!default { type plug slave.pcm "hw:sndrpihifiberry" }  
ctl.!default { type hw card sndrpihifiberry }

---

### 6. Mopidy + Iris Setup
- Installed Mopidy + Iris
- Configured local music + software mixer

Result:
- Working touchscreen player UI

---

### 7. Auto-Resume Playback
- Implemented via custom scripts + systemd
- Saves queue + position
- Restores on boot

Result:
- Appliance-like behavior

---

## 🚀 Current Status
- DAC working  
- UI working  
- Playback working  
- Auto-resume working  

---

## 🔜 Next Steps
- GPIO controls  
- Upload mode (WiFi hotspot)  
- UI improvements  
- System image packaging  

---

🎵 This system is now a solid foundation for a polished boombox build.
