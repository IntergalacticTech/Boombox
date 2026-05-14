# Boombox wireless remote — firmware

PlatformIO project for the ESP32-based wireless remotes that pair to a
boombox over WiFi. The directory is structured for multi-profile support
(CYD, ELECROW round, headless DIY, etc.); Phase 2 ships one profile.

## Profiles

| `[env]` | Hardware | Status |
|---|---|---|
| `cyd-2432s028r` | AITRIP / generic CYD 2.8″ 240×320 resistive-touch | Phase 2 (this milestone) |
| `elecrow-round-128` | ELECROW 1.28″ 240×240 capacitive | Phase 7 (deferred) |
| `headless-gpio` | DIY button panel, no display | Phase 5 |

Each profile is a separate PlatformIO environment in `platformio.ini` that
reuses the shared library at `lib/boombox-remote-core/`.

## One-time setup (macOS)

1. **PlatformIO Core:**
   ```sh
   brew install platformio
   ```
2. **CH340 USB-serial driver** (the CYD uses a CH340 chip; macOS doesn't
   ship the driver):
   ```sh
   brew install --cask wch-ch34x-usb-serial-driver
   ```
   - The cask requires `sudo` and a system extension approval. After
     install, reboot and approve the WCH extension in System Settings →
     Privacy & Security.
   - It's an Intel-built driver, so macOS will also prompt to install
     Rosetta 2. Accept.
   - Verify after reboot:
     ```sh
     ls /dev/cu.wchusbserial*
     ```

## Build

```sh
cd firmware
pio run -e cyd-2432s028r
```

The first build downloads the ESP32 platform toolchain (~300 MB) and the
project's library deps (LVGL, TFT_eSPI, ArduinoJson, ArduinoWebsockets,
XPT2046_Touchscreen, TJpg_Decoder). Subsequent builds are seconds.

## Flash

Plug the CYD in via USB-data cable. Verify `/dev/cu.wchusbserial*` exists.

```sh
pio run -e cyd-2432s028r -t upload
```

## Monitor serial output

```sh
pio device monitor -e cyd-2432s028r -b 115200
```

Ctrl-A K (then `y`) exits the monitor.

## Layout

```
firmware/
├── platformio.ini                       # build matrix + per-env pins
├── README.md                            # this file
├── lib/
│   └── boombox-remote-core/             # shared C++ library
│       ├── library.json
│       └── src/
│           ├── device/                  # IDevice + IUI interfaces
│           ├── transport/               # WifiManager, HttpClient, WsClient
│           ├── state/                   # BoomboxState model + parser
│           ├── storage/                 # NVS wrappers
│           └── action/                  # ActionDispatch
└── src/
    └── devices/
        └── cyd-2432s028r/
            ├── main.cpp                 # entry point
            ├── Device.cpp               # IDevice impl (TFT + touch + LDR)
            └── ui/                      # LVGL screens
```
