# Boombox wireless remote — firmware

PlatformIO project for the ESP32-based wireless remotes that pair to a
boombox over WiFi. The directory is structured for multi-profile support
(CYD, ELECROW round, headless DIY, etc.); Phase 2 ships one profile.

## Profiles

| `[env]` | Hardware | Status |
|---|---|---|
| `cyd-2432s028r` | AITRIP / generic CYD 2.8″ 240×320 resistive-touch | Phase 2 (this milestone) |
| `crowpanel-rotary-21` | Elecrow CrowPanel 2.1″ 480×480 round ESP32-S3 rotary knob | Volume + transport knob (see below) |
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

## CrowPanel 2.1″ rotary knob (`crowpanel-rotary-21`)

A themed volume/transport knob for the boombox — over USB when it is cabled
to the boombox (its permanent home), over BLE when it isn't. It re-themes
live from the active kiosk skin (`theme` in the state payload).

| Input | Action |
|---|---|
| Turn | Volume (4 % per detent, up to 10 % on a fast spin; arc moves at once, ≤ 8 sends/s, final value always sent, settles to the boombox's value ~1 s after you stop) |
| Click | Play / pause |
| Double click (< 350 ms) | Next track |
| Long press (~600 ms) | Ring menu: Previous, Next, Source, Shuffle, Repeat, Mute. Turn to highlight, click to choose, long press or 5 s idle to go back. Source opens a second ring (current source marked). |
| Tap centre | Play / pause (in the menu: back) |
| Tap a menu chip | Choose it |

The screen follows the boombox (`lib/knob-logic/src/ScreenPolicy.h`): while
it plays the screen stays awake; when it's awake but not playing the screen
dims after 30 s without input and stays dim; while the boombox is asleep
(`"power": "asleep"` in the state) the screen is off. It wakes by itself when
the boombox wakes up or starts playing. Without a live state (link down,
searching, pairing) it dims after 30 s idle and turns off after 2 min. Any
input lights the screen, and the input that wakes it is not acted on;
turning the knob while the boombox is asleep only lights the knob — it does
not wake the boombox. Pairing: the kiosk shows a 6-digit PIN — turn to
set each digit, click for the next, long press to go back. The pairing is
stored in NVS and resumed automatically; "Reconnecting…" shows while the
link is down.

**USB link.** Plugged into the boombox, the knob talks to boombox-remote's
USB bridge (`services/knob_usb.py`) over its USB-Serial/JTAG port, which it
shares with the console and the log. Protocol lines are single-line JSON
starting with `{`; everything else is console (host → knob) or log
(knob → host):

| Direction | Line |
|---|---|
| host → knob | `{"t":"hello"}` — the knob replies `{"t":"hello","profile":"crowpanel-rotary-21","fw":"0.1.0"}` (it also sends that unprompted at boot) |
| host → knob | `{"t":"state","d":{…}}` — the consolidated state, as BLE's `data`, untrimmed (no 512 B cap); on change and every 5 s |
| knob → host | `{"t":"cmd","action":"volume","value":0.42}` — same actions/values as BLE commands |

While a valid state arrived in the last 12 s, USB is the active link: BLE
scanning/connecting stops, an open BLE link is dropped and pairing is
skipped — the cable is the trust boundary, so there is no PIN over USB.
When the host goes quiet (bridge stopped or paused, cable pulled) the knob
falls back to the BLE state machine above, saved pairing and all. Lines over
2 KB are dropped whole. The `usb` console command (and `info`'s `usb=`)
shows the link's state. On the Pi, `/dev/boombox-knob` is its udev name
(`install/udev/99-boombox-knob.rules`).

**Hardware.** ESP32-S3R8 (16 MB flash, 8 MB octal PSRAM), ST7701S RGB
panel, CST8xx touch @0x15, encoder on GPIO 42/4 with its switch, LCD power/
reset and touch reset on a PCF8574 @0x21. Pins and panel timings come from
Elecrow's `RotaryScreen_2_1.ino`; see
`src/devices/crowpanel-rotary-21/board/Board.h`.

**Toolchain.** This env uses the pioarduino platform (Arduino core 3.x),
which Arduino_GFX 1.6.7 requires; the CYD env stays on espressif32 6.x. The
two share PlatformIO package slots, so the first build after switching envs
can fail while packages are swapped — just run it again.

**Build on the Mac, flash from the Pi.** The knob is plugged into MarkII's
USB (native USB-Serial/JTAG → `/dev/ttyACM0`, alias `/dev/boombox-knob`).
Never build on the Pi.

```sh
cd firmware
./pi-flash-knob --all     # first flash: bootloader + partitions + boot_app0 + app
./pi-flash-knob           # later: build + flash the app at 0x10000
./pi-flash-knob --monitor # flash, then 20 s of serial log
```

`pi-flash-knob` waits until `vcgencmd measure_temp` reads below 70 °C
(MarkII has no fan). Elecrow's factory image is backed up (git-ignored) at
`firmware/.factory/crowpanel21-factory.bin`; restore it with esptool
`write-flash 0x0` from the Pi if needed. It pauses the USB bridge for the
flash (see below).

**Seeing and driving it remotely.** The firmware has a serial console;
`tools/knob-snap.py` (run on the Mac) drives it over ssh and turns the
`snap` command's LVGL snapshot into a PNG:

```sh
tools/knob-snap.py -o face.png                    # snapshot
tools/knob-snap.py -c wake -c long -c "enc +3" -o menu.png
tools/knob-snap.py --no-snap -c info --log 3      # commands + log
tools/knob-snap.py --log 20                       # tail the log
```

**Sharing the port with the bridge.** boombox-remote's USB bridge holds the
knob's port. `knob-snap.py` and `pi-flash-knob` create the bridge's pause
file (`/run/user/1000/boombox-knob.pause`; override with `PI_KNOB_PAUSE`)
for the length of their run; the bridge releases the port within half a
second and reconnects when the file goes away (a file older than 5 min is
ignored, so a crashed run can't wedge it). knob-snap waits until nothing
else holds the tty before opening it. A snapshot taken right away still
shows the USB-fed face; if a session runs past 12 s the knob drops to BLE
until the bridge is back. By hand: `touch` the file on the Pi to pause,
`rm` it to resume.

Console commands: `snap`, `enc ±N`, `click`, `dclick`, `long`, `tap X Y`,
`state {json}` (inject a state payload; pauses the BLE and USB links),
`demo face|pair|search`, `ble on|off` (resume/pause the links), `usb`,
`testscreen`, `wake`, `bl N`, `info`, `unpair`, `reboot`, `help`. A snapshot reads LVGL's buffer, so it can't show panel-level faults
(wrong colour order, mirroring, tearing) — check those by eye.

**Host tests.** `pio test -e native` runs the hardware-free logic in
`lib/knob-logic` (CSS colour parser, gesture recogniser, volume coalescer,
text folding for the ASCII-only built-in fonts, the USB link's line
assembler / link window).

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
│           ├── transport/               # WifiManager, HttpClient, WsClient, BleClient
│           ├── state/                   # BoomboxState model + parser
│           ├── storage/                 # NVS wrappers
│           └── action/                  # ActionDispatch
└── src/
    └── devices/
        ├── cyd-2432s028r/
        │   ├── main.cpp                 # entry point
        │   ├── Device.cpp               # IDevice impl (TFT + touch + LDR)
        │   └── ui/                      # LVGL screens
        └── crowpanel-rotary-21/
            ├── main.cpp                 # USB/BLE link state machine + console commands
            ├── UsbHostLink.cpp          # USB host link (JSON lines on the console port)
            ├── KnobApp.cpp              # input routing, menu, theme, power
            ├── DebugConsole.cpp         # serial console + LVGL snapshot
            ├── board/                   # pins, PCF8574, ST7701 RGB, touch, encoder, LVGL port
            ├── conf/lv_conf.h           # profile LVGL config (shadows src/lv_conf.h)
            └── ui/                      # round face (KnobUI) + theme mapping
```

`lib/knob-logic/` holds the knob's pure logic (unit-tested natively) and
`tools/knob-snap.py` the snapshot/console client.
