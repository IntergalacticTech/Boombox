# CYD wireless remote — design

Date: 2026-05-12
Status: draft, awaiting review

## Goal

Turn the AITRIP ESP32-2432S028R ("CYD" — Cheap Yellow Display) into a wireless
touchscreen remote for the boombox. The remote pairs to one or more boomboxes,
mirrors the boombox's everyday control surface, and idles into an ambient
now-playing display. Designed to be **awesome offline and awesomer online**:
BLE is the primary always-on connection so the remote works as soon as it has
power and a paired boombox in radio range; WiFi opportunistically enhances the
experience when the boombox is on a known network.

Architected to scale to N boomboxes × M remotes; the existing GPIO control
surface ([../../docs/superpowers/specs/2026-05-12-gpio-buttons-design.md](2026-05-12-gpio-buttons-design.md))
remains the physical control surface and is unchanged by this work.

## Non-goals (this phase)

- Multiroom synchronized playback between boomboxes (architecture leaves hooks).
- Power / shutdown control from the remote — stays physical.
- Replacing or duplicating every GPIO action — the remote is "everyday" surface.
- Battery operation, charging dock, or enclosure design.
- Voice control.
- LED-strip control (separate future work).

## Design posture: BLE-first, WiFi-enhancing

BLE is the primary always-on transport. A paired remote opens a GATT connection
to its active boombox at boot and keeps it alive. State arrives via GATT notify;
commands write to a GATT characteristic. No polling, no WiFi dependency — the
remote works the same on a wilderness camping trip as it does in the living room.

WiFi, when available, replaces BLE as the active transport. The user gets:
- ~10 ms latency instead of ~50–100 ms.
- Full-resolution 240×240 album art instead of BLE's smaller 80×80.
- Lower CYD power draw (BLE radio idles, WiFi MCU handles WS).
- Higher state-update cadence on Mopidy events (push from Mopidy WS).

The remote keeps the BLE connection open even while WiFi is active so that a
dropped WiFi connection (router reboot, hopping rooms) is instant fallback,
not a reconnect dance.

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │              Pi (boombox)            │
                  │                                      │
                  │  Mopidy ──┐                          │
                  │           ├── boombox-state ─────┐   │
                  │  MPRIS  ──┘   (existing)         │   │
                  │                                  │   │
                  │  ┌────────────────────────────┐  │   │
                  │  │  boombox-remote (NEW)      │◄─┘   │
                  │  │  • aiohttp /api/remote/*   │      │
                  │  │  • aiohttp /api/remote/ws  │      │
                  │  │  • BlueZ GATT peripheral   │      │
                  │  │  • mDNS _boombox._tcp      │      │
                  │  │  • pair-confirm overlay    │      │
                  │  │    posts to kiosk          │      │
                  │  └────────────────────────────┘      │
                  │              ▲                       │
                  │              │ same dispatcher as    │
                  │              │ boombox-buttons.py    │
                  └──────────────┼───────────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │ WiFi (LAN, opt)│                │ BLE (always)
                ▼                                 ▼
            ┌──────────────────────────────────────────┐
            │                CYD remote                 │
            │  ┌────────────────────────────────────┐  │
            │  │  Transport manager                 │  │
            │  │  • NimBLE central (persistent)     │  │
            │  │  • WiFi/WS client (opportunistic)  │  │
            │  │  • prefers WiFi when up            │  │
            │  └────────────────┬───────────────────┘  │
            │                   │                      │
            │  ┌────────────────▼───────────────────┐  │
            │  │  Observable state model            │  │
            │  └────────────────┬───────────────────┘  │
            │                   │                      │
            │  ┌────────────────▼───────────────────┐  │
            │  │  LVGL UI                           │  │
            │  │  NowPlaying / Sources / More /     │  │
            │  │  Ambient / Pair / BoomboxSwitcher  │  │
            │  └────────────────────────────────────┘  │
            └──────────────────────────────────────────┘
```

Three new things on the Pi:
1. `services/boombox-remote.py` — aiohttp + BlueZ GATT service.
2. Consolidated state endpoint and WebSocket aimed at the remote.
3. mDNS advertisement.

On the CYD: one PlatformIO firmware image (Arduino-ESP32 + LVGL +
NimBLE-Arduino), same binary on every remote.

## Pi-side: `services/boombox-remote.py`

A new aiohttp service running alongside `boombox-state`. Runs as a systemd
unit. Three concerns:

### 1. REST + WebSocket (WiFi transport)

`GET /api/remote/state` — single consolidated JSON. Replaces the SPA's
multi-endpoint stitching with one payload sized for the remote:

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

`POST /api/remote/command` — fires any everyday action. Body:
`{"action": "play_pause"}` or `{"action": "source", "value": "spotify"}` or
`{"action": "volume", "value": 70}`. Internally dispatches to the **same
handler** the GPIO buttons use — one code path, two control surfaces.
Auth via `Authorization: Bearer <token>` where `<token>` is issued at pairing
time (see Pairing flow).

`GET /api/remote/art/{hash}.jpg` — current art resized to 240×240, cached
on disk by hash. ETags + `If-None-Match` for skipping refetches. The
`art_url` field in `/api/remote/state` is path-relative; the remote prefixes
its WiFi base URL.

`GET /api/remote/ws` — WebSocket. Server pushes state on change (transitions,
track changes, volume) at most every 100 ms. JSON wire format identical to
`/state`.

### 2. BLE GATT peripheral (BLE transport)

Implementation: a Python BLE-peripheral library that speaks BlueZ over D-Bus.
Candidates (decide during phase-0 spike): `bluez_peripheral`, `bless`, or raw
D-Bus via `dbus-next`. Likely requires `bluetoothd --experimental` on Pi OS
Bookworm.

**Service UUID**: `0000bbbb-0000-1000-8000-00805f9b34fb` (custom 16-bit-prefixed).

| Characteristic | Properties | Payload |
|---|---|---|
| `device_info` | read | `{id, name, version, hostname, mdns_name, current_ssid}` |
| `state` | read, notify | CBOR-encoded subset of the REST state, trimmed to fit MTU (target 244 B). Long fields (titles) truncated to 96 chars with `…` suffix. |
| `command` | write, write-no-response | CBOR `{action, value?}`, same shape as REST command body. |
| `art_meta` | read | `{hash, size_bytes, width, height}` for current art (80×80 BLE variant). |
| `art_chunk` | read with offset | JPG bytes at offset. Client reads in MTU-sized chunks until `size_bytes` reached. |
| `pair_request` | write | Client writes a 16-byte token + ASCII device label (e.g. `CYD-1A2B`). Boombox shows kiosk overlay; on user confirm, populates `pair_response`. |
| `pair_response` | read, notify | After kiosk confirm: `{accepted: true, auth_token, wifi: {ssid, psk}?}`. Notify fires once per `pair_request`. |

The Pi service maintains one BLE connection per paired remote (target 4
concurrent for MVP — to be load-tested before declaring done). Each
connection has its own subscriber list; the service fans out state
notifications.

### 3. mDNS advertisement

Uses `python-zeroconf` to advertise `_boombox._tcp.local` on the
`/api/remote` port. TXT records: `name`, `id`, `version`. Remotes scanning
on WiFi resolve their paired boombox by `id`.

### 4. Pairing-confirm kiosk overlay

When a remote writes to `pair_request`, the service POSTs an overlay to the
kiosk (reusing the existing kiosk overlay mechanism from the GPIO spec): a
full-screen card with:

```
Remote 'CYD-1A2B' wants to pair.
Share WiFi "HomeNet" with this remote?
   [ ] Share WiFi credentials
   [ Confirm ]  [ Reject ]
```

The share-WiFi checkbox is **on by default** (a remote without WiFi creds is
significantly degraded for the first-day experience). The user can untick it
for guests or for a security-sensitive remote.

The Pi reads its own WiFi PSK via
`nmcli -s -g 802-11-wireless-security.psk connection show <active-ssid>`,
which requires permission to read connection secrets. Install step: either
ship a polkit rules file granting NetworkManager-secret read access to the
`boombox-remote` service user, or run the service as root — pragmatic for a
single-tenant appliance. (Exact polkit action name to confirm during install
scripting — recent NetworkManager versions use the secret-agent flow rather
than a plain action grant.)

If the boombox has no active WiFi connection (Ethernet-only setup), the
WiFi-share checkbox is hidden and only BLE pairing happens.

### Same-dispatcher requirement

The GPIO button service (`services/boombox-buttons.py`) and the remote
service must dispatch through a shared action layer. Refactor target:
extract an `actions.py` module exposing
`async def fire(action: str, value: Any = None) -> None` that both services
import. The existing per-action logic (Mopidy RPC, MPRIS, kiosk overlays,
wlr-randr, etc.) moves there.

## Remote-side: firmware

PlatformIO project at `firmware/boombox-remote/`. Toolchain:
Arduino-ESP32 framework, LVGL for UI, NimBLE-Arduino for BLE, TFT_eSPI for
display driver, ArduinoWebsockets for WS, ArduinoJson for command encoding,
`CBORcpp` (or equivalent) for BLE state decoding.

```
firmware/boombox-remote/
├── platformio.ini                # ESP32 board, partition, build flags
├── src/
│   ├── main.cpp                  # entry, setup, loop
│   ├── config.h                  # CYD pin map (display, touch, LDR, RGB LED)
│   ├── transport/
│   │   ├── ITransport.h          # iface: connect, sendCommand, onState
│   │   ├── BLETransport.cpp      # NimBLE central, persistent
│   │   ├── WiFiTransport.cpp     # REST + WS, opportunistic
│   │   └── TransportManager.cpp  # picks active; manages WiFi retry schedule
│   ├── state/
│   │   ├── BoomboxState.h        # observable model, LVGL bindings
│   │   └── ArtCache.cpp          # SPIFFS, keyed by art_hash
│   ├── storage/
│   │   ├── PairedBoomboxes.cpp   # NVS list (up to 16)
│   │   └── WiFiCreds.cpp         # NVS, keyed by SSID
│   ├── ui/
│   │   ├── App.cpp               # LVGL screen manager, ambient timer
│   │   ├── NowPlaying.cpp
│   │   ├── Sources.cpp
│   │   ├── More.cpp              # sleep timer, mic, record, skin, retry-wifi
│   │   ├── Ambient.cpp
│   │   ├── Pair.cpp              # BLE scan + tap list
│   │   └── BoomboxSwitcher.cpp   # multi-pair switcher
│   └── platform/
│       ├── Backlight.cpp         # PWM brightness + LDR curve
│       └── Touch.cpp             # XPT2046 + calibration screen
```

## UI: views

### NowPlaying (default active view)

240×320 portrait. All touch targets ≥48 px on a side (resistive touch is
sloppy; oversize matters).

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

- Status bar: tap boombox name → BoomboxSwitcher. Transport badge changes
  color: green = WiFi, blue = BLE, grey = offline.
- Scrub bar updates from position_s notifications. Tap-to-seek; no drag
  scrub (avoids latency-driven jumpiness).
- "🅼" badge = current source icon; tap opens Sources view. (Mopidy / 
  AirPlay / Spotify / BT / Movies — each has its own glyph.)
- Volume slider: tap-anywhere-to-set; drag also supported. Updates locally
  immediately for snappiness; reconciles on next state push.

### Sources

Full-screen 2×3 icon grid of available sources. Each tile shows source name +
status icon (active / standby). Tap → fires `source` command. Auto-returns
to NowPlaying on success or after 3 s.

### More

Full-screen list. Rows:
- **Sleep timer**: tap cycles 15 → 30 → 60 → off (matches GPIO spec).
- **Mic / karaoke**: toggle.
- **Record**: toggle. Pulsing red dot when recording.
- **Cycle skin**: advances the boombox's kiosk skin.
- **Retry WiFi now**: forces a WiFi retry outside the schedule. Greyed out
  when WiFi is already active.

### Ambient

After 30 s of no touch:

```
┌────────────────────────────────┐
│                                │
│       ┌──────────────┐         │
│       │              │         │
│       │ full art     │         │  240×240, centered, padded
│       │              │         │
│       └──────────────┘         │
│                                │
│  Bohemian Rhapsody             │  fades in for 5s on track change
└────────────────────────────────┘
```

- LDR-driven backlight curve: ~10 % at black-dark, ~100 % in daylight.
- Touch anywhere → wake to NowPlaying for 30 s.
- When paused: art stays; track text persists faintly.
- When no playback: rotates a slideshow of recent track arts every 60 s
  (great as a passive shelf display).

### Pair

Animated radar UI while NimBLE central scans. Discovered boomboxes listed
with name, id-tail, RSSI bars. Tap a row to attempt pairing.

```
┌────────────────────────────────┐
│ ← Pair new boombox             │
├────────────────────────────────┤
│                                │
│    🔍 Looking for boomboxes…   │
│                                │
│  ●●●●○  Living Room            │
│  ●●●○○  Bedroom                │
│  ●●○○○  Kitchen (unpaired)     │
│                                │
└────────────────────────────────┘
```

### BoomboxSwitcher

```
┌────────────────────────────────┐
│ ← Switch boombox               │
├────────────────────────────────┤
│  ●  Living Room ⏵ Bohemian…    │  ← currently active
│  ○  Bedroom    ⏸ —              │
│  ○  Kitchen    ⏵ Sade — Smooth │
│                                │
│  + Pair new boombox            │
└────────────────────────────────┘
```

## Pairing flow

```
   CYD                                Boombox
    │                                    │
    │  (in Pair view, scanning)          │
    │ ─── BLE scan ──────────────►       │
    │ ◄── advertise: BoomboxRemoteSvc ───│
    │                                    │
    │  user taps row                     │
    │ ─── BLE connect ──────────────►    │
    │ ─── read device_info ──────────►   │
    │ ◄── {name, id, ssid, …} ───────────│
    │                                    │
    │  user taps Confirm on CYD          │
    │ ─── write pair_request ────────►   │
    │     {token, label:"CYD-1A2B"}      │
    │                                    │
    │                                    │ ─── POST kiosk overlay ───►  kiosk
    │                                    │                              shows
    │                                    │                              dialog
    │                                    │ ◄── user taps Confirm ───────┘
    │                                    │
    │ ◄── notify pair_response ──────────│
    │     {accepted:true, auth_token,    │
    │      wifi:{ssid,psk}}              │
    │                                    │
    │  NVS: save paired boombox          │
    │  NVS: save WiFi creds (if shared)  │
    │  Switch to NowPlaying              │
```

If the user rejects on the kiosk, `pair_response` carries
`{accepted: false, reason: "rejected"}`. The CYD disconnects, returns to
Pair view with a "Pairing rejected" toast, and the radar resumes scanning.

Token security: `auth_token` is a 32-byte random secret generated per pairing,
stored on the Pi in `~/.config/boombox-remote/peers.json`. The remote includes
it in every REST and BLE command. A `POST /api/remote/unpair` endpoint on the
boombox lets the user revoke a remote (later UI work — for MVP the file can
be edited by hand).

## Transport behavior

### At boot

1. Power on → load paired-boomboxes list from NVS.
2. If list is empty → enter Pair view.
3. If list has entries → load `active_boombox` (defaults to most-recently-used).
4. Try BLE connect to `active_boombox.ble_mac` (with 10 s timeout).
   - Success → subscribe to `state` notify, fetch initial state, draw
     NowPlaying. **BLE is the active transport.**
   - Failure → keep retrying every 5 s in the background; meanwhile, draw
     NowPlaying with last-cached state and an offline badge.
5. In parallel: try WiFi.
   - If `WiFiCreds` has an SSID visible in the current scan → associate.
   - On association: mDNS-resolve `active_boombox.id`. On resolve, GET
     `/api/remote/state` with the stored `auth_token`.
   - On success: open WS to `/api/remote/ws`. **WiFi promotes to active
     transport.** BLE connection stays open as hot standby; state from BLE
     notify is ignored while WiFi WS is healthy.
   - On any failure (no SSID match, no mDNS, no WS, auth fail): enter
     WiFi-retry schedule (below).

### WiFi retry schedule (the key power-budget change)

When WiFi is **not the active transport**, the retry cadence is bounded:

- **Phase 1 (first 5 minutes)**: retry every 30 s.
- **Phase 2 (after 5 minutes)**: retry once per hour.
- **Manual retry**: the More view has a "Retry WiFi now" row; tapping it
  fires an immediate retry and resets to Phase 1.
- **Transport restart**: any pairing change, boombox switch, or reboot
  resets to Phase 1.

A "retry" is a full check: scan for known SSIDs, associate if present,
mDNS-resolve the active boombox, attempt a `GET /api/remote/state`. The
WiFi radio is powered down between retries (`WiFi.mode(WIFI_OFF)`),
keeping the BLE-only steady state at ~30 mA on the CYD instead of ~80 mA.

### When WiFi drops

If the active transport is WiFi and the WS or `/state` times out:
1. Mark WiFi unhealthy. Immediately swap to BLE notify as active.
2. Try 3 quick reconnects (5 s apart). If any succeed, swap back.
3. Otherwise, enter Phase 1 retry. (User just moved through a dead-zone.)

The BLE connection is kept warm throughout, so swaps are instant.

### Commands

Commands always route through the active transport. They are not duplicated
across both — toggle actions (play/pause, mute) would double-fire.

If a command write fails (WiFi POST returns non-2xx or WS write errors), the
remote immediately retries on BLE before surfacing an error to the user. Most
commands are idempotent (`source`, `volume`) so a retry is safe; for toggles
the remote also sends the command with a 16-bit `nonce` field so the Pi
dedupes within a 2 s window.

## Album art

| Transport | Resolution | Source | Notes |
|---|---|---|---|
| WiFi | 240×240 JPG | `GET /api/remote/art/{hash}.jpg` | Cached on Pi side; ETags. |
| BLE | 80×80 JPG | `art_meta` + chunked `art_chunk` reads | ~3–5 KB at q=70 |

Remote caches the active resolution's bytes in SPIFFS keyed by
`art_hash + transport_tag`. On hash change, refetch. On transport swap
(WiFi → BLE or BLE → WiFi), refetch the art at the new resolution.

## NVS layout (CYD storage)

Namespace: `boombox`.

| Key | Type | Purpose |
|---|---|---|
| `paired[i]` | blob (PairedBoombox struct) | Up to 16 paired boomboxes |
| `paired_count` | u8 | Length of `paired[]` |
| `active_boombox` | str (id) | Currently controlled boombox |
| `wifi[ssid]` | blob `{psk}` | WiFi credentials per SSID |
| `wifi_known` | str (comma list) | SSID list for fast iteration |
| `touch_cal` | blob `{x_min, x_max, y_min, y_max}` | Resistive touch calibration |
| `brightness_curve` | u8[2] | LDR range mapping endpoints |

```c
struct PairedBoombox {
  char id[40];           // mDNS-safe id, e.g. "boombox-living-room"
  char name[24];         // display name, e.g. "Living Room"
  uint8_t ble_mac[6];    // peer MAC for BLE reconnect
  char service_uuid[37]; // GATT service UUID (string form)
  char auth_token[65];   // hex-encoded 32-byte secret + null terminator
  char mdns_name[40];    // service name on mDNS, used for WiFi resolve
  uint32_t paired_at;    // epoch
  uint32_t last_seen;    // epoch, updated by transport on any success
};
```

## Multiroom hooks (architecture only, no code)

Three places the multiroom future plugs in cleanly:

1. The `boombox.id` field already exists in state. A future group is just a
   virtual id like `group-kitchen-livingroom`. Same payload shape.
2. mDNS gains an extra TXT record `group_members=<csv-of-boombox-ids>` for
   the group's virtual service. Remotes can show groups in the switcher.
3. The command dispatcher already centralizes routing; later it can fan
   commands out to all group members for synchronized play.

When multiroom ships, no CYD firmware change is required for basic group
control — only a UI affordance (group glyph in the switcher) and a
group-management view that we can ship later.

## Failure modes and resilience

| Failure | Behavior |
|---|---|
| BLE connect fails at boot | Retry every 5 s. UI shows last-cached state, offline badge. |
| WiFi never reachable | Phase 1→2 retry schedule, BLE remains active. |
| Boombox crashes | Both BLE and WS drop. Remote shows offline badge after 5 s. |
| Boombox swaps active player (Mopidy → AirPlay) | Push arrives, UI updates without flicker (LVGL animation). |
| Multiple remotes simultaneous volume change | Last-write-wins. Remote receives a state push within 100 ms of any change and snaps the slider to the new value. |
| Pair attempt while paired remote count = max (per boombox) | Boombox kiosk overlay shows "remote slot full, unpair one first". `pair_response` carries `{accepted:false, reason:"full"}`. |
| User unpairs from boombox | Next CYD command fails with 401. Remote drops back to Pair view with a "no longer paired" toast. |

## Risks and unknowns

1. **BLE peripheral + A2DP coexistence on Pi 5.** Modern BlueZ supports both
   stacks concurrently, but the user's specific Bookworm + bluez version
   needs verification before this work commits. **Mitigation**: phase-0 spike
   — write a 50-line `bluez_peripheral` test program, advertise, connect from
   a phone while a phone is also feeding A2DP. If it fights, the MVP becomes
   WiFi-only and BLE is rescheduled.

2. **BlueZ GATT-server experimental flag.** Likely required. **Mitigation**:
   document the `bluetoothd --experimental` flag in the install step.

3. **`bluez_peripheral` library maturity.** Active but small-community.
   **Mitigation**: prototype-first; fallback options are `bless` or raw
   D-Bus over `dbus-next`.

4. **Polkit / WiFi creds read.** Service needs permission to read the
   active connection's PSK. **Mitigation**: ship a polkit rules file with
   the install step that grants the boombox-remote service user the right
   permission. Document it in `docs/SERVICES.md`.

5. **CH340 driver to flash the CYD from macOS.** **Mitigation**: documented
   one-time install in the firmware README.

6. **Resistive touch calibration drift.** **Mitigation**: 3-point calibration
   screen on first boot; recalibrate command in More menu.

7. **Two remotes hitting volume slider simultaneously.** Last-write-wins is
   acceptable; the >100 ms state push reconciles. Stress-test with both CYDs
   before declaring done.

8. **CYD's RGB LED is wired weirdly (active-low, shared SPI pins on some
   batches).** **Mitigation**: don't depend on it for UX. Use it only for a
   pairing-blink and offline indicator.

9. **SPIFFS size on the CYD.** Default partition layout gives ~1.5 MB SPIFFS.
   Each cached art is ~10 KB (WiFi) or ~3 KB (BLE). With 16 paired boomboxes
   and one art each, well within budget. **Mitigation**: LRU evict on cache full.

10. **WiFi-creds share UX security boundary.** A pairing remote receives a
    plaintext PSK over BLE. **Mitigation**: kiosk dialog makes it explicit;
    user can untick the share box. The PSK never leaves NVS on the remote
    (no transmission off the device). Document this trade-off in
    `docs/SERVICES.md` so future maintainers understand the threat model.

11. **N concurrent BLE connections to one Pi.** Targeting 4 for MVP. BlueZ
    per-connection memory and the radio's link capacity are both bounded;
    actual limit depends on Pi model and BlueZ version. **Mitigation**:
    stress-test with 4 simulated centrals before declaring done; document
    the verified cap. If the cap is below 4, the boombox refuses additional
    `pair_request` writes with `{accepted:false, reason:"full"}`.

## Out of scope (explicit)

- Multiroom synchronized playback.
- Battery; charging dock; enclosure.
- LED-strip control.
- Voice control.
- Remote-unpair UI (one-time hand-edit of `peers.json` is acceptable for MVP).
- An on-CYD WiFi-network picker — only the SSID the boombox shares is
  remembered. (Adding manual SSID entry is a follow-up.)
- Continuous-touch volume scrub gesture (tap-to-set + drag-then-release only).
- Lock screen / parental controls.
- OTA firmware updates for the CYD (ship-and-flash for MVP; OTA later).

## Open questions for review

- Token security: 32-byte random per pairing is enough; do we want token
  rotation on a schedule? **Default**: no rotation — pairing-token-leak risk
  is local-network only, and re-pair is the manual remediation.
- WiFi-share opt-out: should it default off for "guest mode" pairings? **Default**:
  on; user can untick.
- Ambient slideshow when no playback: pull arts from recent-tracks history?
  Or skip entirely (black screen)? **Default**: slideshow from recent tracks.
