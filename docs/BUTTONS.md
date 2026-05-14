# Physical buttons

Everything you need to wire 17 panel buttons and one rotary encoder into
the Pi's 40-pin header, configure them from the touchscreen, and debug
when something doesn't fire.

For the service internals see
[SERVICES.md → boombox-buttons](./SERVICES.md#boombox-buttons--full-gpio-control-surface).

---

## What you get

| # | Action            | Press     | Long-press (≥ 600 ms)    |
|---|-------------------|-----------|--------------------------|
| 1 | play_pause        | toggle    | —                        |
| 2 | stop              | stop      | —                        |
| 3 | previous          | prev track| **scrub −5 s/tick**      |
| 4 | next              | next track| **scrub +5 s/tick**      |
| 5 | shuffle           | toggle Mopidy random | —             |
| 6 | repeat            | cycle off → all → one | —            |
| 7 | sleep_timer       | cycle 15/30/60/off (within 3 s) | cancel timer |
| 8 | skin_cycle        | next skin | —                        |
| 9 | library           | navigate to Now-Playing | —          |
|10 | airplay           | show AirPlay instructions overlay | —|
|11 | spotify           | show Spotify instructions overlay | —|
|12 | bluetooth         | open 60-s pairing window + overlay | —|
|13 | movies            | pause Mopidy, jump to Jellyfin | —    |
|14 | web               | toggle LAN QR overlay (URL + PIN) | —|
|15 | mic_karaoke       | toggle mic loopback | —              |
|16 | record            | start / stop FLAC capture of current sink | —|
|17 | power             | toggle backlight (display sleep) | **≥ 2 s** → shutdown countdown |
| ⊙ | encoder rotate    | ±5 % volume per detent | —          |
| ⊙ | encoder push      | mute toggle | —                       |

Long-press threshold is **600 ms** by default; the power button uses its
own **2 s** threshold so an accidental brush can't shut you off. Both
values live in `/etc/boombox/buttons.json` (`long_press_ms`,
`power_hold_ms`) and hot-reload on save.

---

## GPIO budget

A Pi 5 + HiFiBerry DAC+ Pro reserves 8 GPIOs out of 28. The full button
surface needs 20. The installer (`install.sh` step 4 + `usercfg.txt`)
reclaims 7 more by disabling SPI and UART0, which the boombox doesn't
use:

| GPIO | Reserved for | Notes |
|------|--------------|-------|
| 0, 1 | HAT EEPROM | untouchable |
| 2, 3 | I²C-1 (DAC config) | untouchable |
| 18–21 | I²S (DAC audio) | untouchable |
| **4–17, 22–27** | **available** | 20 lines free after SPI/UART0 off |

If you fork the project and need SPI or UART0 back (e.g. you wire in an
LCD or a temperature sensor on SPI), re-enable them in
`/boot/firmware/usercfg.txt` and remap or disable the actions on those
pins via `/etc/boombox/buttons.json`.

### Default pin map

| Action       | BCM pin | Action      | BCM pin |
|--------------|---------|-------------|---------|
| play_pause   | 4       | airplay     | 16      |
| stop         | 5       | spotify     | 17      |
| previous     | 6       | bluetooth   | 22      |
| repeat       | 7       | movies      | 23      |
| sleep_timer  | 8       | web         | 24      |
| skin_cycle   | 9       | mic_karaoke | 25      |
| library      | 10      | record      | 26      |
| encoder_push | 11      | power       | 27      |
| next         | 12      | encoder_a   | 14      |
| shuffle      | 13      | encoder_b   | 15      |

This is just the default — every pin is editable in the Settings panel
("Learn" mode walks you through assigning a press to an action) or by
hand in `/etc/boombox/buttons.json`.

---

## Wiring

Each button is a normally-open momentary switch between its BCM pin and
**any ground pin**. The SoC's internal pull-up holds the line high; a
press shorts it to ground and the driver sees a falling edge.

```
   3.3 V ────────────────────────  (don't connect to buttons)
                              │
                              ▼  internal pull-up enabled in software
                ┌─────────────────────┐
                │  BCM pin (e.g. 4)   │ ──── button ──── GND
                └─────────────────────┘
                              ▲
                              │
                          press = LOW
```

Use **GND pin 6, 9, 14, 20, 25, 30, 34, or 39** on the 40-pin header
(they're all the same rail). Any of them is fine; pick whichever is
geographically convenient.

### Rotary encoder

A standard 2-phase encoder with built-in push switch (e.g. KY-040) needs
three GPIOs:

```
                     ┌──────────┐
       BCM 14 (A) ───┤ A      C ├─── GND
                     │          │
       BCM 15 (B) ───┤ B      D ├─── GND   (push switch ground)
                     │          │
       BCM 11 (SW) ──┤ SW       │
                     └──────────┘
```

Most KY-040 boards already include the pull-up resistors and a small
debounce cap; the firmware also debounces in software so noisy contacts
are tolerable.

### Optional: 0.1 µF debounce cap

If your switches are particularly bouncy (cheap tactile buttons can ring
for a few ms), drop a 0.1 µF ceramic capacitor between each GPIO and
GND right at the switch. The software debounce window is 30 ms for
buttons / 1 ms for encoder phases, which already handles most
contacts — the cap just gives the kernel less work to do.

---

## Setup

### From the touchscreen (recommended)

1. Swipe in the Settings drawer (gear icon, top-right) and scroll to the
   **Buttons** section.
2. Each row shows: **action name · current BCM pin · enabled toggle ·
   Test · Learn**.
3. To bind a pin: tap **Learn**, then press the physical button within
   5 s. The captured pin is written to `/etc/boombox/buttons.json` and
   reloads instantly.
4. To verify a wired button without leaving the screen: tap **Test**.
   The action fires as though the button had been pressed.
5. To disable an action (e.g. you didn't wire a Record button): tap the
   **Enabled** toggle off. The action stops dispatching live without a
   restart.

### From a shell

```bash
sudo $EDITOR /etc/boombox/buttons.json   # hot-reloaded on save
./pi ssh "curl -s http://127.0.0.1/api/buttons/config | jq"  # see current state
./pi ssh "curl -s -X POST http://127.0.0.1/api/buttons/test \
    -H 'Content-Type: application/json' -d '{\"action\":\"play_pause\"}'"
```

The config schema:

```json
{
  "long_press_ms": 600,
  "power_hold_ms": 2000,
  "encoder_step": 5,
  "pins": {
    "play_pause":  {"pin": 4,  "enabled": true},
    "stop":        {"pin": 5,  "enabled": true},
    "...":         "..."
  },
  "encoder": {"pin_a": 14, "pin_b": 15, "pin_push": 11, "enabled": true}
}
```

Set any `pin` to `null` or `enabled` to `false` to disable that action —
the service starts cleanly with any subset wired.

---

## On-screen feedback

Several actions trigger overlay components that mount above the active
skin (so they look the same regardless of which skin you're running):

| Trigger                  | Overlay                                          |
|--------------------------|--------------------------------------------------|
| sleep_timer press        | Pill top-center: `Sleep: 30 min` (auto-hides 2 s after last update) |
| sleep_timer expires      | Toast: `Slept`; display dims                     |
| record press (start)     | Red pulsing `REC ●` indicator top-right         |
| record press (stop)      | Indicator clears                                 |
| airplay / spotify / bluetooth | Full-screen instruction card (5 s, tap to dismiss) |
| web                      | Full-screen QR with LAN URL + PIN                |
| power long-press         | Countdown: `Power off in Ns — release to cancel` |

These are wired in `ui/src/overlays/OverlayRoot.tsx`; each listens on a
`boombox:<event>` DOM event the button service dispatches via DevTools.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Service won't start; journal shows `gpiod` errors | Another process holds the pins | `sudo lsof /dev/gpiochip0`; on a fresh upgrade re-run `install/legacy/remove-legacy-buttons.sh` |
| `gpio pins: ...` listing in journal is shorter than expected | One or more pins disabled in `buttons.json` | Open the Settings drawer; flip the **Enabled** toggle back on |
| Test from Settings fires the journal entry but the wired button doesn't | Bad solder or wrong pin | Use **Learn** to confirm which BCM pin the press actually lands on |
| Encoder reports backwards (left rotation increases volume) | A/B phases swapped | Swap encoder_a and encoder_b in `/etc/boombox/buttons.json` |
| Encoder skips detents or jitters | Bouncy contacts | Add a 0.1 µF cap each on A and B to GND; or bump `encoder_step` down to 2 so each detent costs less |
| Power long-press does nothing | Missing sudoers grant for `systemctl poweroff` | `./pi ssh "sudo -n -l \| grep poweroff"` — should list `NOPASSWD: /usr/bin/systemctl poweroff`. If not, reinstall: `/opt/boombox/install/install.sh` |
| Record button starts a job but the FLAC file stays 0 bytes | `parec` couldn't open the default sink monitor | `./pi ssh "wpctl status \| head -30"` — check that a real sink is `*` (default). If a Bluetooth sink dropped, default may have orphaned |
| `pinctrl get` shows `a0`/`a3`/`a4` on a pin you want for a button | A device tree overlay claimed it | Edit `/boot/firmware/usercfg.txt` and reboot |
| SPI or UART0 needed for a different feature | They're disabled by default | Re-enable in `usercfg.txt`; remap any conflicting button pins in `buttons.json` |

### Verifying the current pin state

```bash
./pi ssh "pinctrl get 4,5,6,7,8,9,10,11,12,13,14,15,16,17,22,23,24,25,26,27"
```

You should see `ip pu | hi` (input, pull-up, high) on every line when
nothing is pressed. Press a wired button and the corresponding line
flicks to `lo` during the press.

### Watching presses live

```bash
./pi ssh "journalctl --user -u boombox-buttons -f"
```

Each dispatched action logs a line. Useful for confirming end-to-end
wiring without watching the screen.

### Reverting to a known-good config

The installer keeps the previous schema at
`/etc/boombox/buttons.json.pre-fullbuttons` whenever it migrates an old
5-action file. You can also reset to defaults:

```bash
./pi ssh "sudo install -m 0644 /opt/boombox/install/config/buttons.json /etc/boombox/buttons.json"
```

The watchdog observer picks up the change within ~1 s; no restart
needed.

---

## Extending

Adding an 18th action means:

1. Append a row to `_DEFAULT_PINS` in `services/boombox-buttons.py`
   (config layer).
2. Decorate a handler with `@_handler("my_action")` in the dispatcher
   section.
3. Add the matching key to `install/config/buttons.json`.
4. Add a friendly label to `ACTION_LABELS` in
   `ui/src/lib/buttonsApi.ts` so the Settings panel renders a row.
5. (Optional) emit a `boombox:<event>` for a new overlay; add a listener
   in `ui/src/overlays/`.

Hot-reload covers points 1–4 automatically once the service restarts;
point 5 needs a UI rebuild.

---

## Future ideas (not implemented)

- **LED strip output** — drive a WS2812 strip off a dedicated MCU (a $4
  Pico over USB) fed by the existing `boombox-audio` spectrum WebSocket.
  Pi-direct WS2812 conflicts with the I²S DAC's GPIO 18, so an external
  controller is the right answer. Out of scope for the current ship.
- **Per-button LEDs** — backlit panel buttons with status indication
  (e.g. red while recording). Easiest via a port expander like MCP23017
  on the existing I²C bus.
- **IR remote bridge** — feed an IR receiver into a dedicated GPIO and
  translate decoded codes into the same dispatcher action names. The
  whole dispatcher is action-name-keyed, so an IR daemon could just call
  `POST /api/buttons/test {"action": ...}`.
