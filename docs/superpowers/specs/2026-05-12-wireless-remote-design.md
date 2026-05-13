# Wireless remote — design

Date: 2026-05-12
Status: draft, awaiting review
Working title: "boombox-remote"

## Goal

A wireless remote-control surface for the boombox that supports multiple
hardware variants — touchscreen displays of different sizes and shapes, plus
DIY headless button-only remotes — all running one shared core firmware with
per-device shells. Remotes pair to one or more boomboxes, mirror the
boombox's everyday control surface where they have a screen, and idle into
an ambient now-playing display where they can.

The boombox itself is the firmware installer: plug an ESP32-class board
into the Pi's USB and the kiosk surfaces an install/update flow. No dev
machine, no CH340 driver hunting, no `esptool` incantations for the user.

Designed to be **awesome offline and awesomer online**. BLE is the primary
always-on connection so a paired remote works as soon as it has power and
its boombox is in radio range. WiFi opportunistically enhances the
experience (faster, full-res art, push WS) when a known network is
reachable.

Architected to scale to N boomboxes × M remotes × P device profiles. The
existing GPIO control surface ([2026-05-12-gpio-buttons-design.md](2026-05-12-gpio-buttons-design.md))
remains the physical control surface on the boombox itself and is
unchanged by this work — but the same action dispatcher gets extracted so
GPIO buttons and wireless remotes can't drift.

## Non-goals (this phase)

- Multiroom synchronized playback between boomboxes (architecture leaves hooks).
- Power / shutdown control from a remote — stays on the boombox's physical surface.
- Duplicating every GPIO action in the wireless surface — the remote is "everyday."
- Battery / charging / enclosure design.
- Voice control.
- LED-strip control.
- OTA firmware update over WiFi/BLE — USB-plug-in update is the only path for now.
- Building firmware *on* the Pi at install time — binaries are pre-built artifacts.

## Design posture

Three principles guide the design:

1. **BLE-first, WiFi-enhancing.** A paired remote opens a GATT connection at
   boot and keeps it alive. State arrives via GATT notify; commands write
   to a GATT characteristic. WiFi, when reachable, swaps in as the active
   transport for lower latency and higher-res art. The BLE link stays warm
   throughout as instant fallback.

2. **Profile-first firmware.** All hardware-specific code lives behind a
   small device interface (display, input, sensors). The transport, state,
   pairing, and storage logic are device-agnostic. Adding a new device is
   "write a new shell + register a profile," not a fork.

3. **The boombox is the installer.** Hardware-supplier knowledge — which
   chip, which display, which pin map — is the boombox's responsibility,
   not the user's. The Pi runs the USB-detect, the kiosk runs the UX, and
   the Pi flashes the device. Updates use the same flow.

## Device profiles

A **profile** describes one supported ESP32-class hardware variant. The
firmware build matrix iterates over profiles and produces one binary each.

### Profile registry shape

`firmware/profiles.json`:

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "cyd-2432s028r",
      "name": "CYD 2.8\" Display",
      "vendor": "AITRIP / generic",
      "chip": "esp32",
      "flash_size_mb": 4,
      "usb_hints": [{"vid": "1A86", "pid": "7523"}],
      "display": {"driver": "ILI9341", "w": 240, "h": 320, "shape": "rect"},
      "touch":   {"driver": "XPT2046", "type": "resistive"},
      "extras":  {"ldr": true, "rgb_led": true, "sd_card": true},
      "ui_class": "rect-240x320",
      "firmware_bin": "build/cyd-2432s028r.bin"
    },
    {
      "id": "elecrow-round-128",
      "name": "ELECROW Round 1.28\"",
      "vendor": "ELECROW",
      "chip": "esp32",
      "flash_size_mb": 4,
      "usb_hints": [{"vid": "1A86", "pid": "7523"}],
      "display": {"driver": "GC9A01", "w": 240, "h": 240, "shape": "round"},
      "touch":   {"driver": "CST816S", "type": "capacitive"},
      "extras":  {},
      "ui_class": "round-240",
      "firmware_bin": "build/elecrow-round-128.bin"
    },
    {
      "id": "headless-gpio",
      "name": "Headless DIY",
      "vendor": "DIY",
      "chip": "esp32",
      "flash_size_mb": 4,
      "usb_hints": [{"vid": "1A86", "pid": "7523"},
                    {"vid": "10C4", "pid": "EA60"},
                    {"vid": "303A", "pid": "1001"}],
      "display": null,
      "touch":   null,
      "inputs": {
        "buttons_max": 16,
        "encoder_supported": true,
        "config_source": "boombox-kiosk-while-usb"
      },
      "ui_class": "none",
      "firmware_bin": "build/headless-gpio.bin"
    }
  ]
}
```

### MVP scope

Three profiles ship together:

| Profile | What it is | UI |
|---|---|---|
| `cyd-2432s028r` | The user's existing CYDs. ESP32 + 2.8″ rect resistive touch. | Full NowPlaying with art, transport, scrub, volume; Sources / More / Switcher / Ambient. |
| `elecrow-round-128` | The ELECROW 1.28″ round capacitive board. Same ESP32, smaller round display. | Radial NowPlaying optimized for round canvas. Fewer info-dense views. |
| `headless-gpio` | DIY enclosure with physical buttons and optional encoder; **no display**. | None — GPIO-event → action. Configured from the boombox kiosk while USB-connected. |

The CYD profile is fully designed in this doc. The ELECROW profile's UI is
sketched at the level needed for scope/risk; full design comes when the
user actually has one (or when a contributor wants to). The headless
profile is fully described — its complexity is in the config flow, not the
UI.

### Profile extensibility — first-class

The profile system is designed so that **new profiles can be added
without modifying the boombox core repo or releasing a new boombox
version**. This is a hard requirement: the boombox ships with three
profiles for MVP and then keeps absorbing more (M5StickC, ESP32-S3 +
e-paper, Waveshare round, custom PCB, community variants, the user's own
one-off DIY board) on its own schedule, not the boombox's.

#### Three integration tiers

| Tier | Where it lives | When to use |
|---|---|---|
| **Built-in** | `firmware/` in this repo, listed in `profiles.json`. | Profiles the maintainers commit to supporting. The MVP three live here. |
| **External pack** | A directory dropped into `/etc/boombox/firmware-profiles/<profile-id>/` on the Pi. Contains `profile.json`, `firmware.bin`, `firmware.bin.sha256`, optional `thumb.png` + `README.md`. | Community-contributed profiles, third-party hardware vendors, a user's own builds. No boombox release needed. |
| **Sideload** | A user-uploaded `.zip` via a future kiosk "Install profile from file" flow (post-MVP — manifest below already supports it). | One-off testing, prerelease drops. |

On startup the boombox-remote service unions the built-in profiles with
every valid external pack into a single in-memory registry. The USB
installer's profile picker shows the union — built-ins, externals, and
sideloaded profiles all appear with no UI difference except optional
"community" / "experimental" / "beta" badges.

#### External pack layout

```
/etc/boombox/firmware-profiles/
└── waveshare-round-147/
    ├── profile.json         # the manifest (schema below)
    ├── firmware.bin         # pre-built binary for this profile
    ├── firmware.bin.sha256  # hex hash, matched against profile.json
    ├── thumb.png            # 128x128 icon shown in the kiosk picker
    └── README.md            # optional — surfaced via "Details" button
```

The Pi validates each pack at service start:
1. `profile.json` parses and matches the manifest schema (version, required fields).
2. SHA-256 of `firmware.bin` matches the manifest's claimed hash.
3. The declared `min_boombox_version` is ≤ the current boombox version.
4. The declared chip family is one the installer knows how to flash.

Failures are logged with a clear error path; the pack is skipped, not
fatal. Kiosk surfaces a "1 profile pack failed to load — see logs"
notice so the user knows.

#### Manifest schema (`profile.json`)

```json
{
  "schema_version": 1,
  "id": "waveshare-round-147",
  "name": "Waveshare Round 1.47\"",
  "vendor": "Waveshare",
  "maintainer": {"name": "...", "homepage": "..."},
  "description": "Round IPS with rotary encoder, no touch.",
  "experimental": false,
  "min_boombox_version": "0.4.0",
  "chip": "esp32-s3",
  "flash_size_mb": 8,
  "usb_hints": [{"vid": "303A", "pid": "1001"}],
  "display": {"driver": "ST77916", "w": 412, "h": 412, "shape": "round"},
  "touch":   null,
  "inputs":  {"encoder_supported": true, "buttons_max": 0},
  "ui_class": "round-412",
  "extras":   {},
  "firmware_bin": "firmware.bin",
  "firmware_sha256": "abc123…",
  "thumb": "thumb.png",
  "docs_url": "https://...",
  "license": "MIT"
}
```

`schema_version` lets the manifest format evolve without breaking older
packs — the Pi rejects schema versions it doesn't understand and logs
the version mismatch.

`experimental: true` causes the kiosk to render a yellow "Beta" tag in
the install picker and adds a "this profile may not work" confirmation
step.

#### Stable contract: `IDevice` + `IUI`

The shared core library exposes a versioned C++ interface that profile
shells implement. As long as a profile builds against
`boombox-remote-core@^N`, it works on any boombox running a forward-
compatible core. Bumping the core's major version is the boombox team's
signal "you need to rebuild your shell."

This is the same contract model as PlatformIO libraries everywhere —
nothing exotic. External profiles consume the core like any library:

```ini
; external profile's own platformio.ini
[env:waveshare-round-147]
platform = espressif32
framework = arduino
board = esp32-s3-devkitc-1
lib_deps =
    https://github.com/<boombox-repo>/boombox-remote-core.git#v1
build_flags =
    -D PROFILE_ID=\"waveshare-round-147\"
    -D HAS_DISPLAY=1
```

The core library is published from this repo on each release tagged
`core-v<major>.<minor>.<patch>`.

#### Developer workflow for adding a profile

For a maintainer of this repo:

1. Add an entry to `firmware/profiles.json`.
2. Add a `[env:<profile-id>]` to `firmware/platformio.ini`.
3. Add `firmware/src/devices/<profile-id>/{main.cpp, Device.cpp, ui/}`.
4. If the screen shape/size is novel, write a new UI class in
   `firmware/src/ui/<ui-class>/`. Otherwise reuse an existing one — a
   variant 240×320 board can share `rect-240x320` with no UI code.
5. `firmware/build-all.sh` produces `dist/<profile-id>.bin`.
6. Release tags ship the binary alongside the boombox-remote-core
   library.

For an external contributor:

1. Pin `boombox-remote-core` in their own PlatformIO project's
   `lib_deps`.
2. Build their own profile shell in their own repo.
3. Produce `firmware.bin` + `profile.json` + `firmware.bin.sha256`.
4. Distribute as a tarball / git repo / GitHub release. End-user
   install:
   ```sh
   sudo mkdir -p /etc/boombox/firmware-profiles/<profile-id>
   sudo tar -xf <profile-id>.tar.gz -C /etc/boombox/firmware-profiles/
   sudo systemctl restart boombox-remote
   ```
   The new profile shows up in the kiosk installer immediately — no
   boombox release, no source edits.

For a user with a custom one-off device:

1. Use the **headless profile** as the starting point — it's the
   simplest shell and demonstrates the IDevice contract end-to-end.
2. Fork the shell, swap in their pin map / display driver, re-build.
3. Drop into `/etc/boombox/firmware-profiles/` as above.

#### CLI for development iteration

`bin/boombox-firmware` (Pi-side helper) provides:

```sh
boombox-firmware list                    # show registered profiles
boombox-firmware validate <pack-dir>     # check manifest + hash
boombox-firmware install <pack-dir>      # copy to /etc/boombox/firmware-profiles/
boombox-firmware remove <profile-id>     # uninstall an external pack
boombox-firmware flash <profile-id>      # flash the connected USB device manually
```

This is the developer's iteration loop: build local → `validate` →
`install` → plug device → kiosk picker shows the new profile.

#### What `boombox-remote-core` guarantees

Profile authors can rely on the core providing:
- BLE peripheral discovery + connection state machine.
- WiFi association, mDNS resolve, REST client, WS client.
- Pairing protocol (USB fast-path, BLE scan-and-tap).
- NVS storage of paired boomboxes + WiFi creds + device-specific keys.
- Action dispatch (any action the boombox knows, fired from any input).
- Schema migrations on firmware update.
- `boombox-info` partition write at first boot.

Profile authors are responsible for:
- Display init + redraw (`IUI::renderFrame`, `IUI::onStateUpdate`).
- Touch / button / encoder input → calling `ActionDispatch::fire`.
- Brightness control if applicable.
- Profile-specific NVS keys (e.g. `pin_map` for headless variants).

#### Profile-removal flow

External packs are removed by deleting the directory and restarting the
service. Pairings to remotes built from removed profiles continue to
work (the remote firmware lives on the device, not on the Pi), but the
kiosk installer no longer offers that profile for future installs. When
an already-paired remote of a removed profile checks in, the
BoomboxSwitcher's remote list shows it as "Unknown profile (last seen:
`<id>`)" so the user understands why the profile picker doesn't list it.

#### Versioning across profiles

Each profile maintains its own `fw_version` independent of every other
profile and independent of the boombox version. Update prompts on plug-in
compare per-profile. A CYD running v0.5.1 and an ELECROW running v0.7.0
peacefully coexist; nothing in the pairing protocol or state shape
depends on profile version alignment.

Nothing else changes — transport, pairing, storage, state are all
profile-agnostic.

## Architecture

```
                  ┌─────────────────────────────────────────┐
                  │              Pi (boombox)               │
                  │                                         │
                  │  Mopidy ──┐                             │
                  │           ├── boombox-state ────┐       │
                  │  MPRIS  ──┘                     │       │
                  │           ┌─────────────────────┴─────┐ │
                  │           │  actions.py (NEW shared)  │ │
                  │           │  one dispatcher for all   │ │
                  │           │  control surfaces         │ │
                  │           └─────┬──────────┬──────────┘ │
                  │                 │          │            │
                  │       ┌─────────▼──┐ ┌─────▼─────────┐  │
                  │       │ boombox-   │ │ boombox-      │  │
                  │       │ buttons.py │ │ remote.py     │  │
                  │       │ (existing  │ │ (NEW)         │  │
                  │       │  GPIO)     │ │ • HTTP+WS     │  │
                  │       └────────────┘ │ • BLE GATT    │  │
                  │                      │ • mDNS        │  │
                  │                      │ • USB flasher │  │
                  │                      └──┬─────────┬──┘  │
                  └─────────────────────────┼─────────┼─────┘
                                            │         │
                              ┌─────────────┘         └───────┐
                              │ WiFi (LAN, opt)               │ BLE
                              │                               │ (always)
                              ▼                               ▼
                        ┌────────────────────────────────────────────┐
                        │           ESP32 remote (any profile)        │
                        │  ┌──────────────────────────────────────┐  │
                        │  │       Shared core library            │  │
                        │  │  • Transport (BLE + WiFi)            │  │
                        │  │  • State model                       │  │
                        │  │  • Pairing                           │  │
                        │  │  • NVS storage                       │  │
                        │  │  • Action dispatcher                 │  │
                        │  └──────────────────┬───────────────────┘  │
                        │                     │ IDevice + IUI        │
                        │  ┌──────────────────▼───────────────────┐  │
                        │  │  Per-profile shell                   │  │
                        │  │  (display, touch, inputs, UI views)  │  │
                        │  └──────────────────────────────────────┘  │
                        └────────────────────────────────────────────┘
```

Three new things on the Pi:

1. **`services/boombox-remote.py`** — aiohttp + BlueZ peripheral + mDNS +
   **USB firmware installer**. Listens to udev for ESP32 devices appearing.
2. **`services/actions.py`** — extracted from `boombox-buttons.py`. Both
   GPIO and remote command paths import it. Ensures GPIO and remote can
   never drift.
3. **mDNS advertisement** of `_boombox._tcp.local`.

On any remote device: one shared firmware library + one per-profile shell.
The build matrix produces one `.bin` per profile, pre-built and stored in
`/usr/local/share/boombox/firmware/`.

## Pi-side: `services/boombox-remote.py`

Five responsibilities:

### 1. REST + WebSocket (WiFi transport)

`GET /api/remote/state` — single consolidated JSON payload:

```json
{
  "boombox": {"id": "boombox-living-room", "name": "Living Room", "version": 1},
  "source": "mopidy",
  "playing": true,
  "track": {
    "title": "Bohemian Rhapsody",
    "artist": "Queen",
    "album": "A Night at the Opera",
    "duration_s": 354,
    "position_s": 87
  },
  "art_hash": "sha1:7fa3...",
  "art_url": "/api/remote/art/7fa3.jpg",
  "volume": 65,
  "muted": false,
  "sources_available": ["mopidy", "airplay", "spotify", "bluetooth", "movies"],
  "sleep_timer_s": null,
  "recording": false,
  "mic_on": false,
  "skin": "retro-blue"
}
```

`POST /api/remote/command` — `{"action": "play_pause"}` etc. Auth via
`Authorization: Bearer <token>`. Dispatches through `actions.py`.

`GET /api/remote/art/{hash}.jpg` — art at the resolution the requesting
remote can use. Profile-aware: a query param `?for=cyd-2432s028r` returns
240×240, `?for=elecrow-round-128` returns 240×240 (round-masked), and
headless never asks. ETags + `If-None-Match`. `art_url` field in
`/api/remote/state` is path-relative; the remote prefixes its WiFi base URL
and appends its profile.

`GET /api/remote/ws` — WebSocket. Server pushes state on change at most
every 100 ms.

### 2. BLE GATT peripheral (BLE transport)

Implementation: a Python BLE-peripheral library that speaks BlueZ over
D-Bus. Candidates (decide during phase-0 spike): `bluez_peripheral`,
`bless`, or raw D-Bus via `dbus-next`. Likely requires `bluetoothd
--experimental` on Pi OS Bookworm.

**Service UUID**: `0000bbbb-0000-1000-8000-00805f9b34fb`.

| Characteristic | Properties | Payload |
|---|---|---|
| `device_info` | read | `{id, name, version, hostname, mdns_name, current_ssid}` |
| `state` | read, notify | CBOR subset, trimmed to MTU 244 B. Titles ellipsized to 96 chars. |
| `command` | write, write-no-response | CBOR `{action, value?, nonce}`. |
| `art_meta` | read | `{hash, size_bytes, width, height}` for the 80×80 BLE variant. |
| `art_chunk` | read with offset | JPG bytes; client reads MTU-sized chunks until size_bytes reached. |
| `pair_request` | write | `{token, label, profile_id}`. Kiosk overlay fires. |
| `pair_response` | read, notify | After confirm: `{accepted, auth_token, wifi:{ssid,psk}?}` or `{accepted:false, reason}`. |

The Pi maintains one BLE connection per paired remote (target 4
concurrent for MVP — load-tested before declaring done). Each connection
has its own subscriber list; the service fans out state notifications.

### 3. mDNS advertisement

`python-zeroconf` advertises `_boombox._tcp.local` on the `/api/remote`
port. TXT records: `name`, `id`, `version`. Remotes resolve their active
boombox by `id`.

### 4. Pairing-confirm kiosk overlay

When a remote writes to `pair_request`, the service POSTs an overlay to
the kiosk:

```
Remote 'CYD-1A2B' (CYD 2.8") wants to pair.
[x] Share WiFi "HomeNet" with this remote
[ Confirm ]  [ Reject ]
```

The share-WiFi checkbox defaults on. WiFi PSK retrieval:
`nmcli -s -g 802-11-wireless-security.psk connection show <active-ssid>`,
which requires permission to read connection secrets. Install step:
either ship a polkit rules file granting NetworkManager-secret read access
to the `boombox-remote` service user, or run the service as root —
pragmatic for a single-tenant appliance.

If the boombox is on Ethernet (no active WiFi), the share-WiFi checkbox is
hidden.

### 5. USB firmware installer

See "USB firmware installer" section below.

### Shared action dispatcher

`services/actions.py` exposes:

```python
async def fire(action: str, value: Any = None, *, source: str) -> dict:
    """Run an action. Returns {ok, error?}. `source` is for telemetry/logging."""
```

Both `boombox-buttons.py` and `boombox-remote.py` import this module. The
existing per-action logic in `boombox-buttons.py` moves here as part of
this work. The GPIO button service becomes a thin event→`fire` adapter.

## USB firmware installer

The killer feature: plug an ESP32 board into the boombox's USB port and
the kiosk walks the user through install or update.

### Detection (udev → service)

A udev rule matches the common ESP32 USB-serial chip VID/PIDs:

```
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", TAG+="systemd", ENV{SYSTEMD_WANTS}="boombox-remote-usbnotify@%k.service"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", TAG+="systemd", ENV{SYSTEMD_WANTS}="boombox-remote-usbnotify@%k.service"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", TAG+="systemd", ENV{SYSTEMD_WANTS}="boombox-remote-usbnotify@%k.service"
```

(CH340, CP210x, ESP32 native USB CDC respectively.)

A small notifier unit pokes the `boombox-remote` service's
`/internal/usb-event` endpoint with the tty path. The service handles the
rest.

### Identification flow

```
1. tty appears (e.g. /dev/ttyUSB0)
2. esptool.py --port /dev/ttyUSB0 chip_id
       → chip family: ESP32 / ESP32-S2 / ESP32-S3 / ESP32-C3 / ESP32-C6
3. esptool.py --port /dev/ttyUSB0 read_flash 0x3F0000 0x1000 /tmp/info
       → read boombox-info partition (last 4KB):
          {magic: "BBR1", profile_id, fw_version, paired_count, device_label}
       → if magic doesn't match: blank or non-boombox firmware
4a. If valid boombox firmware:
       compare fw_version vs latest_version_for_profile
       same  → kiosk: "Remote 'CYD-1A2B' connected. Reconfigure / Re-pair / Cancel?"
       older → kiosk: "Update 'CYD-1A2B' from v0.3 to v0.5? [Update][Cancel]"
4b. If blank / unknown firmware:
       chip family narrows possibilities; kiosk shows a list of compatible
       profiles with thumbnails:
       "Install boombox-remote on this device?
          ○ CYD 2.8" Display
          ○ ELECROW Round 1.28"
          ○ Headless DIY (custom button panel)
          [Install]  [Cancel]"
       user picks one → flash that profile's binary
```

### Flashing

```
esptool.py --port <tty> --baud 921600 write_flash \
    --flash_size detect \
    0x0 bootloader.bin \
    0x8000 partition-table.bin \
    0x10000 firmware-<profile>.bin
```

For updates, the NVS partition is **explicitly preserved** so paired
boomboxes and WiFi creds survive:

```
esptool.py write_flash --erase-all \
    0x10000 firmware-<profile>.bin
# NVS partition at 0x9000 is NOT touched; --erase-all is per-region in
# our partition layout (NVS lives in its own segment we skip)
```

Kiosk shows a progress bar driven by `esptool`'s stdout (`Writing at 0x...
(XX %)`). Flash takes ~30 s. On success, the kiosk transitions to either
the pair-confirm overlay (if the firmware is fresh) or a "Updated to v0.5"
toast (if it was an update on an already-paired remote).

### USB fast-path pairing

When a freshly flashed remote reboots while still plugged in, the
boombox-remote service offers a **USB-channel pairing** as the very first
step — no BLE scan needed. The remote opens its USB-CDC serial channel
and listens for a pairing token. The boombox writes `{boombox_id, name,
auth_token, wifi: {ssid, psk}}` over serial. The remote saves it to NVS
and is paired before BLE is even attempted. After the remote is
unplugged, BLE picks up where USB left off.

This skips the BLE pairing dance entirely for the common case of "the
user is at the boombox plugging in a fresh remote." Manual BLE pairing
(for a remote that already has firmware and is across the room) remains
available.

### Headless-profile configuration

The headless profile has no display, so the user can't see UI to
configure pin maps. The boombox kiosk takes over while the headless
device is USB-connected:

```
Configure headless remote 'HL-7C2E':
   Pin 4 = [ play_pause ▾ ]    enabled [x]
   Pin 5 = [ next       ▾ ]    enabled [x]
   Pin 6 = [ previous   ▾ ]    enabled [x]
   …
   Encoder pin_a = [ 14 ▾ ]    enabled [x]
   Encoder pin_b = [ 15 ▾ ]
   Encoder push  = [ 11 ▾ ]
   [ Save and Pair ]
```

This UI mirrors the GPIO `buttons.json` schema. The saved config is
written to NVS on the device over serial during the install flow. Later
edits happen the same way: plug it back in, edit, save. A pin-map
config UI can also live in the boombox's Settings drawer for over-BLE
edits, but USB-while-plugged is the canonical path.

### Update policy

Updates are **always opt-in** via the kiosk overlay. The boombox
never silently flashes a connected remote — flashing interrupts the
remote's operation and a user mid-flash with no warning would be
surprising. The kiosk overlay defaults focus to "Cancel" for the same
reason.

A "Skip until next version" option remembers the answered version per
remote `device_label` and won't re-prompt until the latest version
advances.

## Remote-side: firmware

PlatformIO project at `firmware/`. Multi-environment build with shared
core library and per-profile shells.

### Layout

```
firmware/
├── platformio.ini              # one [env] per profile
├── VERSION                     # bumped per release; embedded into each .bin
├── profiles.json               # the device registry (shared with Pi)
├── build-all.sh                # iterates envs, copies .bin to dist/
├── dist/                       # pre-built binaries (gitignored or release artifact)
│
├── lib/
│   └── boombox-remote-core/    # shared library used by every profile
│       ├── library.json
│       ├── src/
│       │   ├── core/
│       │   │   ├── App.cpp                # lifecycle, profile bootstrap
│       │   │   ├── BoombInfoPartition.cpp # writes magic+version+profile
│       │   │   └── UsbProvisioning.cpp    # USB-CDC fast-path pairing
│       │   ├── transport/
│       │   │   ├── ITransport.h
│       │   │   ├── BLETransport.cpp       # NimBLE central, persistent
│       │   │   ├── WiFiTransport.cpp      # REST + WS, opportunistic
│       │   │   └── TransportManager.cpp   # retry schedule + swap logic
│       │   ├── state/
│       │   │   ├── BoomboxState.h         # observable model
│       │   │   └── ArtCache.cpp           # SPIFFS by art_hash
│       │   ├── storage/
│       │   │   ├── PairedBoomboxes.cpp    # NVS list (up to 16)
│       │   │   └── WiFiCreds.cpp          # NVS by SSID
│       │   ├── action/
│       │   │   └── ActionDispatch.cpp     # local fire→transport
│       │   └── device/
│       │       ├── IDevice.h              # display, touch, brightness, inputs
│       │       └── IUI.h                  # screen manager interface
│
└── src/
    └── devices/
        ├── cyd-2432s028r/
        │   ├── main.cpp                   # registers profile, boots core
        │   ├── Device.cpp                 # implements IDevice
        │   └── ui/                        # CYD-specific LVGL screens
        │       ├── NowPlaying.cpp
        │       ├── Sources.cpp
        │       ├── More.cpp
        │       ├── Ambient.cpp
        │       ├── Pair.cpp
        │       └── BoomboxSwitcher.cpp
        ├── elecrow-round-128/
        │   ├── main.cpp
        │   ├── Device.cpp                 # GC9A01 + CST816S
        │   └── ui/                        # round-canvas LVGL
        │       └── …
        └── headless-gpio/
            ├── main.cpp
            ├── Device.cpp                 # button/encoder polling
            └── PinMap.cpp                 # loads NVS pin config
```

### `IDevice` interface

```cpp
class IDevice {
public:
    virtual void initDisplay() = 0;       // no-op for headless
    virtual void initInputs() = 0;
    virtual void pollInputs() = 0;        // pushes events to ActionDispatch
    virtual void setBrightness(uint8_t pct) = 0;  // 0 for headless
    virtual bool hasDisplay() const = 0;
    virtual DeviceCapabilities caps() const = 0;
};
```

`DeviceCapabilities` declares what the device can do — drives feature flags
(e.g. ambient mode is skipped for headless; volume gesture is touch-only).

### Build matrix (`platformio.ini`)

```ini
[platformio]
default_envs = cyd-2432s028r

[env]
platform = espressif32
framework = arduino
lib_deps =
    lvgl/lvgl@^9
    h2zero/NimBLE-Arduino@^2
    bblanchon/ArduinoJson@^7
    gilmaimon/ArduinoWebsockets@^0.5
build_flags =
    -D BOOMBOX_FW_VERSION=\"$BOOMBOX_VERSION\"

[env:cyd-2432s028r]
board = esp32dev
build_src_filter = +<devices/cyd-2432s028r/> +<../lib/boombox-remote-core/>
build_flags = ${env.build_flags} -D PROFILE_ID=\"cyd-2432s028r\" -D HAS_DISPLAY=1

[env:elecrow-round-128]
board = esp32dev
build_src_filter = +<devices/elecrow-round-128/> +<../lib/boombox-remote-core/>
build_flags = ${env.build_flags} -D PROFILE_ID=\"elecrow-round-128\" -D HAS_DISPLAY=1

[env:headless-gpio]
board = esp32dev
build_src_filter = +<devices/headless-gpio/> +<../lib/boombox-remote-core/>
build_flags = ${env.build_flags} -D PROFILE_ID=\"headless-gpio\" -D HAS_DISPLAY=0
lib_ignore = lvgl
```

The headless build drops LVGL entirely — saves ~150 KB and a bunch of
RAM, keeping headroom for more action types or future features.

## Per-profile UI

### Profile: `cyd-2432s028r` (CYD 2.8″)

240×320 portrait, resistive touch. All touch targets ≥48 px.

**NowPlaying (default active view):**

```
┌────────────────────────────────┐
│ Living Room ▾  📶 WiFi         │  16px status bar
├────────────────────────────────┤
│        ┌──────────────┐        │
│        │              │        │
│        │  album art   │        │  160×160 centered
│        │              │        │
│        └──────────────┘        │
│                                │
│  Bohemian Rhapsody             │  24px, 2-line wrap
│  Queen — A Night at the Opera  │  16px, single line, ellipsized
│                                │
│  ▶━━━━━━━━━━━━━━━━━━○━━━━━     │  scrub bar
│                                │
│   ⏮      ⏯       ⏭   🅼  ⋯     │  56px tap, transport row
│                       │   └── More menu
│                       └── tap = Sources view
├────────────────────────────────┤
│         🔊 ━━━━━━━━━━━━○━━     │  volume drag-or-tap-to-set
└────────────────────────────────┘
```

- Status bar: tap boombox name → BoomboxSwitcher. Transport badge:
  green=WiFi, blue=BLE, grey=offline.
- Tap-to-seek on scrub; no drag scrub.
- Volume: tap or drag.

**Sources** — full-screen 2×3 icon grid (Mopidy / AirPlay / Spotify /
BT / Movies / +1 slot). Tap fires `source` command. Auto-returns after 3 s.

**More** — list rows: Sleep timer (15/30/60/off), Mic, Record, Cycle
skin, Retry WiFi now (greyed when WiFi already active).

**Ambient** (after 30 s no touch):

```
┌────────────────────────────────┐
│                                │
│       ┌──────────────┐         │
│       │              │         │
│       │ full art     │         │  240×240, centered
│       │              │         │
│       └──────────────┘         │
│                                │
│  Bohemian Rhapsody             │  fades in for 5s on track change
└────────────────────────────────┘
```

LDR-driven backlight curve: ~10 % black-dark, ~100 % daylight. Touch
anywhere → wake.

**Pair / BoomboxSwitcher** — list views, both detailed in the
boombox-shared UI guide.

### Profile: `elecrow-round-128` (1.28″ round, capacitive)

240×240, circular display, capacitive touch. UI compromise: less info, but
crisper interactions. Sketch only — full design defers until physical
testing.

**NowPlaying (radial):**

```
        ┌──────────────────────┐
        │   ▢▢▢ Living Room ▢▢▢ │  top arc: boombox name +
        │ ┌──────────────────┐ │   tiny transport badge
        │ │                  │ │
        │ │   album art      │ │  140×140 in the round center
        │ │   (rounded)      │ │
        │ │                  │ │
        │ └──────────────────┘ │
        │                       │
        │ Bohemian Rhapsody     │  bottom arc: title (1 line, scrolls)
        │ Queen                 │  artist (1 line, scrolls)
        └───────────────────────┘
```

- **No persistent transport buttons.** Single tap on art = play/pause.
  Swipe left = next, swipe right = previous. Two-finger tap = sources.
- **Volume**: clockwise/counterclockwise drag around the bezel
  (radial scrub).
- **Switcher**: long-press the top arc → boombox list.

Caveats: round-display UX patterns are weaker than rectangular. The user
should hold off building enclosures around this until they've used the
firmware for a week.

### Profile: `headless-gpio` (DIY, no display)

No screen. The remote is a battery + ESP32 + custom button matrix in a
3D-printed enclosure. It does one thing: GPIO event → BLE/WiFi command.

**Behavior:**

- At boot: load pin map from NVS. If unconfigured, idle (RGB LED, if any,
  blinks the "needs config" pattern); plug into a boombox to configure.
- Each press → fires the mapped action via ActionDispatch → BLE/WiFi.
- Long-press supported for actions that have a long-press variant (e.g.
  `previous` long-press = scrub backward).
- Encoder, if configured: clockwise → `volume +N`, counterclockwise →
  `volume -N`, push → `mute_toggle`.
- No ambient mode. No display logic. LVGL not linked.

**Config flow** (already described above under USB-firmware-installer →
Headless-profile configuration). Stored in NVS in the same shape as the
boombox's `buttons.json`. Reconfigurable by re-plugging into any boombox.

**Indicator (if RGB LED present on the user's board):**

| State | LED |
|---|---|
| Unconfigured | slow yellow blink |
| Paired, BLE connected | solid faint green |
| Paired, WiFi active | solid faint blue |
| Offline | slow red blink |
| Action fired | brief white flash |

## Pairing flow

Three paths into a paired state:

### Path A: USB fast-path (during install)

```
   Remote (USB)                       Pi (boombox)
       │                                   │
       │  freshly flashed, boots up        │
       │  USB-CDC line raises DTR          │
       │ ◄── kiosk asks "Pair to this?" ──│
       │     (overlay on kiosk; user OKs)  │
       │                                   │
       │ ◄── serial write ─────────────────│
       │     {boombox_id, name,            │
       │      auth_token,                  │
       │      wifi:{ssid,psk}?}            │
       │                                   │
       │  NVS: save paired boombox         │
       │  NVS: save WiFi creds (if shared) │
       │  Confirm back over serial         │
       │ ─── serial write ─────────────────►
       │     {ok:true, paired:1}           │
       │                                   │
       │  Kiosk: "Pairing complete"        │
```

After unplug, the remote initializes BLE and connects to the paired
boombox.

### Path B: BLE scan + tap (across the room)

```
   Remote                              Pi (boombox)
     │                                    │
     │  (in Pair view, scanning)          │
     │ ─── BLE scan ──────────────►       │
     │ ◄── advertise: BoomboxSvc ─────────│
     │                                    │
     │  user taps row                     │
     │ ─── connect, read device_info ─►   │
     │                                    │
     │ ─── write pair_request ────────►   │
     │     {token, label, profile_id}     │
     │                                    │
     │                                    │ ─── kiosk overlay ──►  user
     │                                    │                        confirms
     │                                    │ ◄── confirm ─────────────┘
     │                                    │
     │ ◄── notify pair_response ──────────│
     │     {accepted:true, auth_token,    │
     │      wifi:{ssid,psk}?}             │
     │                                    │
     │  NVS save; switch to NowPlaying    │
```

### Path C: re-pair (already paired, switch boomboxes)

Identical to Path B but initiated from the BoomboxSwitcher's "Pair new" entry.

## Transport behavior

### At boot

1. Load paired-boomboxes list from NVS. If empty → enter Pair view (Path B).
2. Load `active_boombox`; try BLE connect (10 s timeout, retry every 5 s
   in background on failure).
3. In parallel: try WiFi from stored creds; on success, mDNS-resolve the
   active boombox, GET `/api/remote/state`, open `/api/remote/ws`. WiFi
   promotes to active transport.
4. BLE stays warm even while WiFi is active.

### WiFi retry schedule (the power-budget constraint)

When WiFi is **not the active transport** (BLE-only mode):

- **Phase 1 (first 5 minutes)**: retry every 30 s.
- **Phase 2 (after 5 minutes)**: retry once per hour.
- **Manual retry**: "Retry WiFi now" in More menu (for touch profiles); a
  long-press of a dedicated button (for headless profiles, configurable).
- **Reset to Phase 1**: any pairing change, boombox switch, reboot, or
  manual retry.

A retry is: scan for known SSIDs, associate if present, mDNS-resolve
active boombox, attempt `GET /state`. Radio is `WiFi.mode(WIFI_OFF)`
between retries. BLE-only steady state targets ~30 mA on a CYD; with WiFi
polling every 30 s it'd be ~80 mA average.

### When WiFi drops

If WiFi is active and WS/`/state` times out:
1. Mark unhealthy; immediately swap to BLE notify.
2. Try 3 quick reconnects (5 s apart). If any succeeds, swap back.
3. Else enter Phase 1.

### Commands

Always route through the active transport. Not duplicated.

If a write fails (WiFi POST non-2xx or WS error), the remote retries on
BLE before surfacing an error. Commands carry a `nonce` so the Pi can
deduplicate within a 2 s window.

## Album art

| Transport | Resolution | Source |
|---|---|---|
| WiFi | 240×240 JPG (rect) or 240×240 round-masked | `GET /api/remote/art/{hash}.jpg?for=<profile>` |
| BLE | 80×80 JPG | `art_meta` + chunked `art_chunk` reads |

Cached in SPIFFS by `art_hash + transport_tag`. Refetched on hash change
or transport swap.

## NVS layout (any remote)

Namespace: `boombox`.

| Key | Type | Purpose |
|---|---|---|
| `schema_version` | u8 | NVS layout version, drives migration on update |
| `profile_id` | str | Profile this firmware was built for (sanity check vs flash) |
| `paired[i]` | blob (PairedBoombox struct) | Up to 16 paired boomboxes |
| `paired_count` | u8 | Length of `paired[]` |
| `active_boombox` | str (id) | Currently controlled boombox |
| `wifi[ssid]` | blob `{psk}` | WiFi credentials per SSID |
| `wifi_known` | str (csv) | SSID list for fast iteration |
| `touch_cal` | blob | Resistive touch cal (touch profiles only) |
| `brightness_curve` | u8[2] | LDR mapping endpoints (display profiles only) |
| `pin_map` | blob | Headless profile only: GPIO → action map |
| `device_label` | str | "CYD-1A2B", "HL-7C2E", etc. — set by Pi at pair time |

```c
struct PairedBoombox {
  char id[40];
  char name[24];
  uint8_t ble_mac[6];
  char service_uuid[37];
  char auth_token[65];   // hex-encoded 32-byte secret + null
  char mdns_name[40];
  uint32_t paired_at;
  uint32_t last_seen;
};
```

**Migration**: when firmware boots and finds `schema_version <
CURRENT_SCHEMA`, run a one-time migration function. The
`UsbFirmwareInstaller` preserves the NVS partition during update, so
migration must always succeed forward. Schema bumps that aren't
trivially backward-compatible require a `mark_for_factory_reset` flag
the user is prompted to confirm — losing pairings is acceptable, losing
them silently is not.

## Boombox-info partition

A 4 KB partition at the very end of flash (last sector) stores:

```c
struct BoombInfo {
  char magic[4];          // "BBR1"
  char profile_id[40];
  char fw_version[16];    // e.g. "0.5.1"
  uint32_t built_at;      // epoch
  uint32_t paired_count;  // mirrors NVS for quick read without parsing
  char device_label[16];
  uint8_t reserved[64];
  uint32_t checksum;
};
```

The Pi reads this partition during USB identification without touching
NVS. It's the source of truth for "what version is this remote running"
and "what profile was this built for."

## Multiroom hooks (architecture only, no code)

1. The `boombox.id` field is already a generic id; a future group is
   `group-kitchen-livingroom` with the same payload shape.
2. mDNS gains an extra TXT `group_members=<csv>` for virtual group
   services. Remotes show them in the switcher with a group glyph.
3. The action dispatcher centralizes command routing; later it can fan
   out to all group members.

When multiroom ships, no remote firmware change is required for basic
group control — only kiosk UI work on the boombox(es) and a small
"group glyph" in the switcher (which is a UI tweak, not a refactor).

## Failure modes and resilience

| Failure | Behavior |
|---|---|
| BLE connect fails at boot | Retry every 5 s. Last-cached state, offline badge. |
| WiFi never reachable | Phase 1→2 retry schedule. BLE remains active. |
| Boombox crashes | Both BLE and WS drop. Offline badge after 5 s. |
| Source swap on the boombox | Push arrives; UI updates without flicker. |
| Two remotes concurrent volume change | Last-write-wins; ≤100 ms reconciliation push. |
| Pair attempt while slot full | Kiosk overlay "remote slot full, unpair one first"; `pair_response: {accepted:false, reason:"full"}`. |
| User unpairs from boombox | Next CYD command fails with 401; remote drops to Pair view with toast. |
| USB device unplugged mid-flash | Kiosk shows "flash interrupted — re-plug device"; remote is in indeterminate state but esptool can recover (it always re-flashes bootloader). |
| esptool unable to read chip_id (bad cable / power-only) | Kiosk: "Detected USB device but can't communicate. Try a data cable." |
| NVS migration fails | Boot into "factory reset required" screen with a single button; user confirms; NVS wiped; back to Pair view. |
| Headless device with no buttons configured | RGB LED slow yellow blink forever; replug to configure. |
| Profile mismatch on update (e.g. user picked wrong profile during install) | Firmware boots, detects display/touch driver returns no response, falls back to "wrong profile?" indicator (LED pattern or display test pattern). User replugs; kiosk offers re-flash. |

## Risks and unknowns

1. **BLE peripheral + A2DP coexistence on Pi 5.** **Mitigation**: phase-0
   spike — write a 50-line BLE-peripheral test, advertise, connect from a
   phone while another phone feeds A2DP. If it fights, MVP becomes
   WiFi-only and BLE is rescheduled.

2. **BlueZ GATT-server experimental flag.** Likely required. **Mitigation**:
   document `bluetoothd --experimental` in install.

3. **Python BLE-peripheral library maturity.** **Mitigation**:
   prototype-first; fallbacks `bless` or raw D-Bus.

4. **Polkit / WiFi creds read.** **Mitigation**: ship a polkit rules file
   or run service as root.

5. **Multi-profile build matrix maintenance cost.** Three profiles at
   launch; each adds test surface, doc burden, driver code. **Mitigation**:
   the shared core library is large; each profile's shell is ~300–500 lines.
   The headless profile is the cheapest to maintain (no UI). The CYD
   profile is the canonical one — if a refactor breaks it first, it's
   fixed first; ELECROW and headless are lower-frequency check.

6. **NVS schema migration across firmware versions.** **Mitigation**:
   `schema_version` field + explicit migration functions; factory-reset
   fallback prompt rather than silent data loss.

7. **udev-driven service hot-plug timing.** udev fires before the tty
   `/dev/ttyUSB0` is fully ready; esptool can fail with "port not open."
   **Mitigation**: the notifier service retries `chip_id` for up to 3 s
   with 200 ms backoff before declaring "no response."

8. **esptool on a USB hub or with marginal cabling.** Frequent in real
   life. **Mitigation**: surface clear "try a different cable" message
   when retries exhaust.

9. **Profile detection ambiguity on blank firmware.** A blank CYD and a
   blank ELECROW round look identical over USB (same CH340 chip, same
   ESP32 family). **Mitigation**: the kiosk shows a picker with
   thumbnails. The user knows what they plugged in.

10. **Round-display UX is weaker than rectangular.** Specifically for
    ELECROW. **Mitigation**: ship the profile with the sketch in this
    doc, let the user use it for a week, iterate on actual ergonomics.

11. **CH340 driver still needed on the user's Mac for development.**
    USB firmware install via the boombox removes the user-flow need, but
    contributors who want to flash from a laptop still need the driver.
    **Mitigation**: documented in `docs/REMOTE.md`.

12. **N concurrent BLE connections to one Pi.** Target 4 for MVP.
    Actual limit depends on BlueZ + radio. **Mitigation**: stress test;
    document cap; refuse `pair_request` past cap with `accepted:false`.

13. **WiFi-creds-over-BLE security boundary.** Plaintext PSK transmitted
    over BLE during pairing. **Mitigation**: kiosk dialog makes this
    explicit; user can untick; threat model documented in
    `docs/SERVICES.md`.

14. **Pre-built firmware binaries vs supply-chain trust.** Binaries
    shipped to the Pi need provenance. **Mitigation**: ship `.bin` +
    `.bin.sha256` from a build CI; the Pi verifies hash before flashing.
    Reject hash mismatch with a kiosk error.

15. **Headless profile + power.** A wireless button panel needs a
    battery; a battery needs charging; this is real hardware design. The
    firmware works on USB power for development, but a finished headless
    remote is a hardware project the user must complete separately.

## Out of scope (explicit)

- Multiroom synchronized playback.
- Battery; charging; enclosure design for any profile.
- LED-strip control.
- Voice control.
- OTA firmware updates over WiFi/BLE — USB plug-in is the only update path.
- Building firmware on the Pi at install time (binaries are pre-built and shipped).
- A remote-unpair UI (one-time hand-edit of `peers.json` for MVP).
- A custom hardware reference design (PCB / schematic) for the headless variant.
- ELECROW round full UI design (sketch-only until the user has one).
- Lock screen / parental controls.
- A profile picker browser-UI on the boombox web port (kiosk is sufficient).

## Open questions for review

- **WiFi-share default**: on for first pairing; off for re-pairings?
  **Default**: on for every pairing; user can untick. The "guest mode"
  case is rare enough that the friction tax isn't worth it.
- **Auto-update on plug-in vs always opt-in**: spec defaults to opt-in
  with a "skip until next version" memory per device. Confirm.
- **Token rotation**: no scheduled rotation; re-pair is the manual
  remediation if a token is compromised. Confirm.
- **Ambient slideshow when paused**: rotate through recent track arts
  every 60 s. Confirm.
- **Profile choice on blank flash**: kiosk lists all profiles compatible
  with the detected chip; user picks. No auto-detect by inspecting
  display response (would require flashing diagnostic firmware first —
  too clever).
- **Headless config drift**: if a user edits `boombox-state` GPIO action
  names later, do they have to re-plug every headless remote to
  reconfigure? **Default**: yes for MVP, BLE-channel re-config in
  follow-up.
