# Hardware notes

## Power button — wire to GPIO 27 **and** the Pi 5 J2 header

The front-panel power button does two jobs:

- **While running:** short press = sleep / wake, hold ≥ 2 s = shutdown.
  This is read by `boombox-buttons` on **BCM GPIO 27** (see `docs/BUTTONS.md`).
- **After the unit has powered itself down** (standby → auto-poweroff, see
  `docs/superpowers/specs/2026-09-18-home-screen-and-standby-design.md`):
  a halted Pi 5 ignores GPIO 27 entirely. The only thing that wakes it is
  the onboard power button or the 2-pin **J2 "PWR_BTN"** header next to it.

So wire the button's contacts to **both** in parallel: one leg to GPIO 27 +
GND as today, and the same momentary contact across the two J2 pins. J2 is
just a dry contact to ground; no resistor needed. A press while halted boots
the Pi (which lands on the Home screen).

**Caveat:** while the Pi is running, a J2 press is reported by the PMIC as a
power key, and `systemd-logind` powers the system off on that key by
default. The installer therefore ships a drop-in
(`/etc/systemd/logind.conf.d/boombox.conf` with `HandlePowerKey=ignore`) so
the running-state behaviour stays with `boombox-buttons` on GPIO 27. Keep
the EEPROM at `POWER_OFF_ON_HALT=0` (MarkII's current setting): halt then
stays in the low-power state that J2 can wake from.

If the enclosure only reaches GPIO 27, set `BOOMBOX_SLEEP_POWEROFF_S=0` in
`/etc/boombox/boombox.env` so standby never powers the Pi down.
