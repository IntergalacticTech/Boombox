# GPIO buttons + rotary encoder — design

Date: 2026-05-12
Status: approved, ready for implementation planning
Supersedes: the minimal pin map in `services/boombox-buttons.py` (play/pause, prev, next, vol up/down)

## Goal

Add a full retro-style physical control surface to the boombox: 17 buttons + 1 rotary encoder with push, all driven from the Pi 5's 40-pin GPIO header via the existing user-space breakout board. Every action is independently optional — the system runs cleanly with any subset wired. Pin assignments are user-configurable from a JSON config file and from a new "Buttons" panel in the touchscreen Settings drawer.

## Non-goals

- LED output / music-reactive lighting (architecture noted below for a future phase; no code in scope).
- Touchscreen-side UI redesign beyond the new Settings panel and a few overlays (QR, sleep-timer OSD, record indicator).
- A pre-built enclosure or button-cap selection — this spec is firmware/software only.

## Inventory

17 buttons + 1 rotary encoder with push, all individually disable-able.

### Transport (5 buttons + 1 encoder)

| Action | Behavior |
|---|---|
| Play / Pause | Routes to Mopidy if active source is Mopidy or none; otherwise to the active MPRIS player via `/api/control`. |
| Stop | Mopidy `core.playback.stop` (clears position). |
| Previous | Short: prev track. Long-press (held): scrub backward at 5× until released. |
| Next | Short: next track. Long-press: scrub forward at 5× until released. |
| Shuffle | Toggle Mopidy `tracklist.set_random`. |
| Volume knob | Rotary encoder rotate = volume up/down (5% step, clamped to `boombox-state /api/volume`). Push = mute toggle. |

### Sources (6 buttons)

| Action | Behavior |
|---|---|
| Library | Bring kiosk back to main SPA / library view. No-op if already there. |
| AirPlay | Show an instructional overlay ("pick Boombox from your AirPlay menu"). Pi cannot *initiate* AirPlay — this educates the guest. Toast "AirPlay active" if a session is already live. |
| Spotify | Same pattern: overlay with "pick Boombox under Spotify Devices". |
| Bluetooth | Trigger pairing mode by reusing `SourceSwitcher.startBluetoothPairing`. |
| Movies | Pause Mopidy, swap kiosk to Jellyfin. Pressing again while in Jellyfin returns to the SPA. |
| Web | Toggle LAN access on `:8090` and overlay a full-screen QR code with URL + credentials. Press again to dismiss. |

### System (2 buttons)

| Action | Behavior |
|---|---|
| Mic / Karaoke | Toggle mic loopback via the existing `/api/karaoke` endpoint. |
| Power | Short: toggle display backlight (sleep/wake) via `wlr-randr`. Long-press ≥ 2 s with on-screen countdown: graceful shutdown via `systemctl poweroff` after pausing playback and triggering `boombox-resume` snapshot. |

### Extras (3 buttons)

| Action | Behavior |
|---|---|
| Sleep timer | Press cycles 15 → 30 → 60 → off → 15 (within 3 s of last press, otherwise just sets the next value). Long-press cancels. Timer fires → `core.playback.pause` + display sleep + OSD "Slept" toast. |
| Record | Press starts `parec` from PipeWire default-sink monitor → `~/Music/Recordings/YYYY-MM-DD-HHMMSS.flac`. OSD shows pulsing "REC ●". Press again to stop and surface a "Saved → <path>" toast. |
| Skin cycle | Advance to the next skin in the skin registry and reload the kiosk view. |

## Pi system changes

The HiFiBerry DAC+ Pro consumes GPIO 0, 1 (HAT EEPROM, reserved), GPIO 2, 3 (I²C control bus), and GPIO 18-21 (I²S audio). 13 GPIOs are free immediately. SPI (GPIO 7-11) is enabled in `config.txt` but currently has no consumers (`lsof /dev/spidev*` empty). UART0 (GPIO 14, 15) is enabled but only `agetty` on the Pi 5's dedicated debug UART `ttyAMA10` is active — GPIO 14/15 are idle.

Two single-line `/boot/firmware/config.txt` changes free the remaining 7 pins:

```
dtparam=spi=off
dtparam=uart0=off
```

After these changes the available GPIO budget is exactly the 20 pins this spec needs. Both are reversible by toggling back on; neither affects audio, Bluetooth (Pi 5 BT uses its own internal UART), or the existing serial-getty debug console.

The legacy `/usr/local/bin/boombox-button-handler.py` (running as root, holding GPIO 4, 17, 22-27) is removed as part of this work — its systemd unit disabled, the file deleted. The repo's `services/boombox-buttons.py` becomes the only button handler.

## Pin assignment

Defaults shipped in `/etc/boombox/buttons.json`. Every value is user-overridable.

| Pin | Action | Pin | Action |
|---|---|---|---|
| GPIO 4 | play_pause | GPIO 16 | airplay |
| GPIO 5 | stop | GPIO 17 | spotify |
| GPIO 6 | previous | GPIO 22 | bluetooth |
| GPIO 12 | next | GPIO 23 | movies |
| GPIO 13 | shuffle | GPIO 24 | web |
| GPIO 7 | repeat | GPIO 25 | mic_karaoke |
| GPIO 8 | sleep_timer | GPIO 26 | record |
| GPIO 9 | skin_cycle | GPIO 27 | power |
| GPIO 10 | library | GPIO 14 | encoder pin_a |
| GPIO 11 | encoder push | GPIO 15 | encoder pin_b |

All buttons short-to-GND via the SoC's internal pull-up; press = falling edge. Encoder phases A/B also pulled up; quadrature decoded in software.

## Dual-purpose semantics

Long-press threshold: **600 ms** for transport buttons. Power uses **2000 ms** with an on-screen countdown so an accidental long-press is visible and cancelable by releasing.

| Button | Short | Long |
|---|---|---|
| Power | Display sleep/wake | Shutdown (2 s hold + visible countdown) |
| Previous | Prev track | Scrub backward at 5× while held, 200 ms tick |
| Next | Next track | Scrub forward at 5× while held, 200 ms tick |
| Sleep timer | Cycle duration | Cancel timer |
| All others | Standard short-press only | — |

### Power button safety

The shutdown path:
1. Long-press detected (≥ 2 s).
2. If display is asleep, wake it first so the countdown overlay is visible.
3. Overlay shows a 2-second countdown; release cancels.
4. On confirm: pause the active player (Mopidy or external MPRIS), trigger `boombox-resume` snapshot explicitly (don't rely on shutdown ordering), then `systemctl poweroff`.

Display backlight is controlled via `wlr-randr --output <name> --off/--on` — the same Wayland output the kiosk runs on.

## Action dispatch architecture

| Target | Transport | Actions |
|---|---|---|
| Mopidy (`:6680/mopidy/rpc`) | HTTP JSON-RPC, existing `MopidyRpc` helper | Play/Pause (Mopidy source), Stop, Prev, Next, Shuffle, Repeat, scrub |
| `boombox-state` (`:6681/api/control`) | New `POST {action}` endpoint that proxies to the active MPRIS player | Play/Pause/Prev/Next when external source is live |
| `boombox-state` other endpoints | Existing `/api/volume`, `/api/karaoke`, `/api/state` | Encoder volume, Mic toggle, source detection |
| Kiosk (Chromium DevTools `:9222`) | Reuse the `./pi goto`-style WebSocket path | Source overlays, Movies, Web/QR overlay, Skin cycle, Library view, sleep/record OSDs |
| systemd | `subprocess.run(["systemctl", "poweroff"])` | Power long-press |
| Display | `wlr-randr` subprocess | Power short-press, sleep-timer expiry |
| Recorder | `parec` → encoder subprocess | Record start/stop |
| Internal | asyncio task | Sleep timer countdown |

**Routing for play/pause/prev/next:** the button service subscribes to `boombox-state /api/state` (or polls every 500 ms). When `source` is `null` or `mopidy`, it takes the direct Mopidy RPC path; otherwise it posts to `/api/control` which fans out to the active MPRIS player. Mopidy gets the fast path because (a) it's already the privileged source in this codebase and (b) keeping its existing direct-RPC dispatch unchanged minimizes regression risk.

## Config schema

`/etc/boombox/buttons.json`:

```json
{
  "long_press_ms": 600,
  "power_hold_ms": 2000,
  "encoder_step": 5,
  "pins": {
    "play_pause":   {"pin": 4,  "enabled": true},
    "stop":         {"pin": 5,  "enabled": true},
    "previous":     {"pin": 6,  "enabled": true},
    "next":         {"pin": 12, "enabled": true},
    "shuffle":      {"pin": 13, "enabled": true},
    "repeat":       {"pin": 7,  "enabled": true},
    "sleep_timer":  {"pin": 8,  "enabled": true},
    "skin_cycle":   {"pin": 9,  "enabled": true},
    "library":      {"pin": 10, "enabled": true},
    "airplay":      {"pin": 16, "enabled": true},
    "spotify":      {"pin": 17, "enabled": true},
    "bluetooth":    {"pin": 22, "enabled": true},
    "movies":       {"pin": 23, "enabled": true},
    "web":          {"pin": 24, "enabled": true},
    "mic_karaoke":  {"pin": 25, "enabled": true},
    "record":       {"pin": 26, "enabled": true},
    "power":        {"pin": 27, "enabled": true}
  },
  "encoder": {
    "pin_a":    14,
    "pin_b":    15,
    "pin_push": 11,
    "enabled":  true
  }
}
```

Rules:
- Any action with `enabled: false` or `pin: null` is skipped at startup; the service runs cleanly with any subset.
- File is watched via `watchdog`; edits hot-reload without `systemctl restart`.
- Future actions add keys without breaking existing installs (forward-compatible).

## Settings UI

New "Buttons" panel in the existing `SettingsDrawer`. Per row:

- Action name, current pin, enabled toggle.
- **Test** button — fires the action so you can confirm wiring without standing across the room.
- **Learn** button — puts the service in capture mode for 5 seconds; the next falling edge is bound to that action, JSON is rewritten, hot-reload picks it up. Surfaces "captured GPIO N" toast.

A separate "System" row at the top lets you reset the entire JSON to defaults.

Required new endpoint on `boombox-state` (or directly on the button service if simpler): `POST /api/buttons/learn {action}` → captures next press → returns `{pin, action}`. `POST /api/buttons/test {action}` → fires the action without GPIO. `GET /api/buttons/config` → returns the JSON.

## Future extension: LED strips

Out of scope for this work, but the architecture supports it without redesign.

Direct Pi-driven WS2812B / APA102 strips conflict with this build:
- WS2812B canonical PWM driver wants GPIO 18 (held by I²S DAC).
- WS2812B SPI driver wants GPIO 10 (will be allocated to a button under this spec, and we disable SPI anyway).
- APA102 / DotStar needs SPI (disabled).

Recommended path: a dedicated USB-serial micro-controller (Raspberry Pi Pico, ~$4) plugged into the Pi over USB-CDC. The existing `boombox-audio` service does FFT on the PipeWire monitor and exposes spectrum data at `ws://localhost/audio/ws`. A new helper streams spectrum frames to the Pico over USB-serial; the Pico runs the LED animation locally with no kernel jitter and no GPIO impact on the Pi. The strip needs its own 5V PSU; do not draw from the Pi's 5V rail.

Alternative: networked WLED on an ESP32, fed via UDP from `boombox-audio`. More decoupled (LEDs can be physically separated from the boombox), great existing ecosystem.

## Out of scope

- LED strip implementation (architecture noted; no code).
- An LED status indicator per button (would be a v2 enhancement).
- Enclosure / cap design.
- Replacing the kiosk's existing on-screen controls — the SPA's transport bar stays as-is.

## Risks and gotchas

1. **`dtparam=spi=off` / `dtparam=uart0=off`** — verified idle today but a future feature may re-enable them. Document in `docs/SERVICES.md` so a future maintainer doesn't enable a peripheral without first reclaiming pins from this spec.
2. **Legacy `/usr/local/bin/boombox-button-handler.py`** — its systemd unit must be located and disabled before removal. Likely under `/etc/systemd/system/` or a user unit; the installer needs to track this.
3. **Long-press timing** — 600 ms is a guess from common practice. If it feels too long or too short during integration testing, the value is in the JSON and trivial to retune.
4. **Encoder debouncing** — quadrature decode in software needs care on the Pi 5's faster GPIO; we'll start with `gpiod` hardware debounce at 1 ms (vs 30 ms for buttons) and tune up if we see missed pulses.
5. **`/api/control` is a new state-API endpoint** — needs MPRIS DBus dispatch to whichever player is currently primary. Some MPRIS implementations (notably older AirPlay/shairport-sync builds) ignore `Next`/`Previous` — that's a per-source limitation we surface but don't try to work around.
6. **Hot-reload on config edits** — needs to drop and re-request the gpiod line set cleanly; a stale lease will block the next reload. Implementation must explicitly release lines before re-requesting.
