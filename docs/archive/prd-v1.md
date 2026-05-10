Here’s a clean, structured export of everything we’ve designed together — organized as a **project brief + architecture doc** you could actually use to build this.

---

# 📦 Retro Boombox Build – Full Design Export

## 🎯 Project Goal

Build a **portable, retro-style boombox** with modern capabilities:

* Offline + streaming playback
* Physical controls + touchscreen UI
* Long battery life (~10 hours)
* Expandable features (karaoke, GPS, remote control, server mode)
* Strong “1980s aesthetic” with modern internals

---

# 🧠 Core System Architecture

## 🧩 System Overview

```
                ┌──────────────────────────┐
                │     Raspberry Pi         │
                │  (Volumio OS + Services)│
                └─────────┬────────────────┘
                          │
     ┌────────────────────┼────────────────────┐
     │                    │                    │
Audio System      Control Interfaces     Network + Services
     │                    │                    │
Amp + Speakers    GPIO / Remote / UI     WiFi / Server Mode
```

---

# 🔊 Audio System

## Components

* **Dayton KAB Amplifier Board**

  * Bluetooth built-in
  * Aux input support
  * Battery-compatible
* Speakers:

  * Option A: reuse donor boombox speakers
  * Option B: 4"–5.25" coaxial car speakers (recommended)

## Inputs

* Bluetooth (via amp)
* Aux (external + Pi)
* Raspberry Pi (main source)

## Features

* Stereo output
* Optional tone control / EQ board
* Headphone jack (via amp or separate module)

---

# 🧠 Raspberry Pi (Core Brain)

## OS: Volumio

* Open-source music OS designed for Pi ([Volumio Docs][1])
* Supports:

  * Local playback (offline)
  * Web radio + streaming services
  * Web-based UI (touchscreen + browser)

## Why Volumio Works Here

* Headless web UI = perfect for touchscreen + phone control ([Volumio Docs][1])
* Supports plugins + hardware integration
* Lightweight and stable on Pi ([RaspberryTips][2])

---

# 🎛️ Physical Controls (GPIO)

## Supported via Volumio

* Play / Pause
* Next / Previous
* Volume Up / Down

👉 Enabled via GPIO plugin ([Volumio Community][3])

## Advanced Option

* Use **volumio-buddy**:

  * Rotary encoder (volume knob)
  * Buttons
  * OLED / display feedback
  * LED integration ([PyPI][4])

---

# 📱 Touchscreen Interface

## Features

* Full music browsing UI
* Playback control
* Status display (network, mode, etc.)

## Notes

* Volumio provides browser-based UI accessible locally
* Touchscreen plugin available for embedded UI

---

# 🔋 Power System

## Options Considered

### Option A: 18650 Battery Pack

* Integrated with amp board
* Clean + purpose-built
* Requires charging circuit

### Option B (Preferred): USB-C Power Bank

* Cheap, replaceable
* Safe + widely available
* Can add:

  * USB-C PD trigger (for higher voltage)
  * Bypass for direct power input

---

# 🎤 Karaoke System (Microphone Inputs)

## Requirements

* 1–2 microphone inputs
* Mix mic + music together

## Implementation

* Mic preamp modules
* Analog mixer (op-amp summing circuit)
* Volume knobs per mic

---

# 🌈 Visualizer (Independent System)

## Options

### LED Matrix / Strip (Recommended)

* Arduino or Pi-controlled
* Reactive to music via:

  * Microphone module
  * Or audio signal tap

### Features

* Spectrum display
* Retro animations
* Physical **kill switch**

---

# 📡 GPS Tracking (Add-on)

## Hardware

* USB GPS dongle or NEO-6M module

## Software Flow

```
GPS → gpsd → script → MQTT → OwnTracks / Home Assistant
```

## Behavior

* Reports location when online
* No impact when offline

---

# 🎮 Remote Control

## Options

### RF Remote (433 MHz)

* Simple, reliable
* GPIO-based input

### IR Remote

* Classic stereo feel
* Works with Volumio IR plugin

### Bluetooth Remote (Recommended)

* Native media controls
* More buttons available
* Less wiring complexity

---

# 🌐 Server Mode (File Upload System)

## Goal

Allow users to:

* Connect to boombox WiFi
* Upload/remove music via web UI

---

## Option A (Simple + Recommended)

### Volumio Hotspot Mode

* Pi creates WiFi when not connected
* SSID: “Volumio” (default) ([Pi My Life Up][5])

### Add File Manager

* Use **File Browser**
* Upload files directly to music folder

---

## Option B (Advanced – Captive Portal)

### Stack

* RaspAP + NoDogSplash

### Behavior

* Connect to WiFi → auto-redirect to UI
* Like hotel WiFi experience

### How it works

* Captive portal intercepts traffic and redirects users ([RaspAP][6])

---

# 📶 Dual WiFi System (Advanced Feature)

## Architecture

| Interface   | Role                |
| ----------- | ------------------- |
| wlan0       | Connect to internet |
| wlan1 (USB) | Always-on hotspot   |

## Benefits

* Always accessible locally
* Internet + local control simultaneously
* Enables “server mode” anytime

---

## Toggle via GPIO

### Button Behavior

* Toggle “Server Mode” ON/OFF

### Implementation

* Start/stop:

  * hostapd (WiFi AP)
  * DHCP server
  * captive portal

---

## Captive Portal System

### Tool: NoDogSplash

* Redirects users to splash page ([Nodogsplash][7])
* Customizable UI page

---

## Screen Integration

Display:

* SSID
* IP address
* Internet status
* Mode (Server ON/OFF)

---

# 🔧 Integration Strategy

## Build Layers

### Layer 1 – Core Audio

* Amp + speakers + power

### Layer 2 – Pi + Playback

* Volumio + touchscreen

### Layer 3 – Controls

* Buttons + knobs + remote

### Layer 4 – Network Features

* Server mode
* Captive portal
* Dual WiFi

### Layer 5 – Extras

* GPS
* Visualizer
* Karaoke

---

# 💡 Key Design Decisions (Why They Matter)

| Decision        | Benefit                        |
| --------------- | ------------------------------ |
| Volumio         | Fast setup, great UI, flexible |
| USB power bank  | Easy battery management        |
| Dual WiFi       | Always-accessible device       |
| GPIO controls   | Authentic physical feel        |
| LED visualizer  | Strong retro aesthetic         |
| Modular add-ons | Can phase build complexity     |

---

# 🚀 Suggested Build Order

1. **Core audio + amp + speakers**
2. **Raspberry Pi + Volumio**
3. **Touchscreen UI**
4. **Battery system**
5. **Physical controls (GPIO)**
6. **Visualizer**
7. **Server mode (File Browser)**
8. **Dual WiFi + captive portal**
9. **GPS + extras**

---

# 🧠 Final Thoughts

This project evolved into something much bigger than a boombox — it’s essentially:

👉 A **portable, self-contained media server + speaker system**
👉 With **offline capability + network services + hardware controls**
👉 Wrapped in a **retro 1980s aesthetic**

The architecture we landed on is:

* **Modular**
* **Expandable**
* **Realistic within budget**
* And honestly… very cool

---

If you want next steps, I’d recommend:
👉 I can turn this into a **shopping list + wiring diagram + enclosure layout** so you can actually start building.

[1]: https://docs.volumio.org/?utm_source=chatgpt.com "Welcome to Volumio Developers Docs | Volumio Developers Documentation"
[2]: https://raspberrytips.com/install-volumio-on-raspberry-pi/?utm_source=chatgpt.com "Getting Started With Volumio on Raspberry Pi (Media Player)"
[3]: https://community.volumio.com/t/plugin-gpio-buttons-control-volumio-2-volumio-3-with-buttons/4076?utm_source=chatgpt.com "[Plugin] GPIO Buttons: Control Volumio 2/ Volumio 3 with buttons"
[4]: https://pypi.org/project/volumio-buddy/?utm_source=chatgpt.com "volumio-buddy · PyPI"
[5]: https://pimylifeup.com/raspberry-pi-volumio/?utm_source=chatgpt.com "How to install Volumio on the Raspberry Pi - Pi My Life Up"
[6]: https://docs.raspap.com/features-insiders/captive/?utm_source=chatgpt.com "Captive portal - RaspAP Documentation"
[7]: https://nodogsplash.readthedocs.io/en/latest/install.html?utm_source=chatgpt.com "Installing Nodogsplash — NoDogSplash v3.3.3-beta"

