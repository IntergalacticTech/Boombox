# Home screen + standby ("off") — design

**Date:** 2026-09-18
**Status:** approved in conversation; implementation follows this spec.

## Goal

Give the boombox an appliance-style on/off cycle and a Home screen:

- **Cold boot** lands on **Home**, not Now Playing.
- **Off** (physical power button short-press, or the digital Off button)
  stops audio, sleeps the screen, and after a grace period powers the Pi
  down.
- **Touch or any button while asleep** wakes the unit to **Home**.
- **Home** is where the user picks an input: onboard music, video
  (Jellyfin), Bluetooth, AirPlay, Spotify, AUX. It replaces the Source
  drawer. Every skin's chrome gets a Home button; every drawer gets a Home
  link.

Out of scope (deliberately): auto-return-to-Home after inactivity, waking on
an incoming AirPlay/Bluetooth stream, per-skin Home layouts, changing the
long-press-to-poweroff behaviour.

## Current state (what this changes)

- `ui/src/App.tsx` mounts one always-on Now Playing surface plus five modal
  drawers; there is no view state, no routing, no persisted view.
- "Off" today = `Display.toggle()` (backlight via `wlr-randr`) from the
  `power` GPIO short-press; audio keeps playing. Long press = pause +
  `systemctl poweroff`.
- `boombox-resume` restores the last playlist (paused) at boot; that stays.
- Wake from a halted Pi 5 is only possible from the onboard/J2 power-button
  header, so the enclosure button will be wired to J2 in parallel with
  GPIO 27 (hardware task, tracked outside this spec).

## Part 1 — Power state (server)

### Module: `services/power.py` (new, pure asyncio, unit-tested)

```python
class PowerManager:
    state: "awake" | "asleep"
    since: float
    poweroff_at: float | None

    async def sleep() -> dict   # idempotent
    async def wake()  -> dict   # idempotent
    async def toggle() -> dict
    async def off()   -> dict   # sleep + immediate poweroff
    def snapshot() -> dict      # {"state", "since", "poweroff_at"}
```

Constructor takes injectable callbacks so the module is testable without
hardware: `stop_audio`, `display_off`, `display_on`, `kiosk_home`,
`poweroff`, and `grace_s` (`float`; `0` disables auto-poweroff). All
callbacks are best-effort — a failing one is logged and the sequence
continues, because a dark screen with a stuck timer is worse than a
missed `wlr-randr`.

`sleep()` sequence: `state=asleep` first (so the UI reacts immediately),
then `stop_audio` → `kiosk_home` → `display_off` → arm timer. `wake()`:
cancel timer → `display_on` → `state=awake`. `wake()` never resumes
playback.

Persistence: the snapshot is written to
`$XDG_STATE_HOME/boombox/power.json` on every transition. On startup the
manager always initialises **awake** and, if the file says `asleep`,
forces `display_on` — a crash mid-sleep must not leave the panel dark.

### Wiring in `services/boombox-state.py`

- Instantiate `PowerManager` in `main()` with:
  - `stop_audio` = Mopidy `core.playback.stop` via its HTTP RPC on
    `127.0.0.1:6680` + `playerctl -a pause` (external sources).
  - `display_off/on` = `clients.Display` (`wlr-randr`; needs
    `WAYLAND_DISPLAY`, which the user session already exports — the
    buttons service uses the same class from the same unit type).
  - `kiosk_home` = `clients.KioskClient.navigate("http://localhost/")`.
  - `poweroff` = `sudo -n systemctl poweroff` (already in
    `install/sudoers/boombox`).
  - `grace_s` = `BOOMBOX_SLEEP_POWEROFF_S` from the environment, default
    `180`.
- `GET /state` payload gains `"power": manager.snapshot()`.
- New routes: `POST /power/sleep`, `POST /power/wake`, `POST /power/toggle`,
  `POST /power/off`, `GET /power`. All return the snapshot. nginx already
  proxies `/api/` → boombox-state, so the UI paths are
  `/api/power/...`.

`clients.Display` gains an explicit `off()` (today only `toggle()` and
`wake()` exist).

### Buttons (`services/actions.py`)

- `power short_press` → `state.power_toggle()` (new `StateApi` method
  posting `/power/toggle`).
- `Dispatcher.dispatch()` gains a prelude: if the last-known power state is
  `asleep` and the action is not `power`, POST `/power/wake` and **drop**
  the press. The buttons service learns the power state from the
  `StateApi` (`/power`, cached for 1 s) so a first press wakes rather than
  acts. Long-press poweroff unchanged.

## Part 2 — Kiosk UI

### View model (`ui/src/App.tsx`)

```
view: "home" | "player"          // React state, initial "home"
asleep: boolean                  // derived from /api/state power.state
```

- `asleep` renders `<SleepScreen/>` above everything: a fixed black layer
  that captures any pointer/touch/key event and POSTs `/api/power/wake`.
  While asleep nothing else is interactive.
- On the transition `asleep → awake`, `view` is set to `"home"` and all
  drawers close.
- `view === "home"` renders `<HomeScreen/>` inside `ScaleToFit`; the skin's
  `Audio` component is **not** mounted (so skins don't animate under Home).
- `view === "player"` is today's behaviour.
- `useActiveSource` (already polling `/api/state`) exposes `power` so no
  new polling loop is added.

### `HomeScreen` (`ui/src/lib/HomeScreen.tsx`, shared, themed)

Takes the active `SkinTheme` (bg/panel/ink/accent/font) and renders a tile
grid in the 1280×800 design space:

| Tile | Action |
|---|---|
| Music | `view = "player"`, open LibraryDrawer if the queue is empty, else just Now Playing |
| Video | pause Mopidy, `window.location.href = <jellyfin base>` (the kiosk extension's return pill brings the user back to `/`, i.e. Home) |
| Bluetooth | `POST /api/bluetooth/pair`, `view = "player"` with the existing source overlay |
| AirPlay / Spotify | `view = "player"` + source overlay (same event the GPIO buttons emit) |
| AUX | informational tile (as today's card) |
| Settings | open SettingsDrawer |
| Off | `POST /api/power/sleep` |

Tile metadata (name, tag, blurb, accent, glyph) moves out of
`SourceSwitcher.tsx` into `ui/src/lib/sources.ts` so Home and the
"live source" badge share one list. `SourceDrawer` is deleted.

A small "now playing" strip appears at the bottom of Home when something is
paused/playing, tapping it goes to `player` — this is the existing
`NowPlayingBar`, reused.

### Chrome (`ui/src/lib/ChromeButtons.tsx`, `skinRegistry.tsx`)

- `ChromeApi.onOpenSource` is renamed `onGoHome`; `ChromeSourceBtn` becomes
  `ChromeHomeBtn` (same slot, glyph ⌂ + the live-source label/dot it shows
  today, so skins keep their "AIRPLAY ●" indicator). All six skins are
  updated mechanically.
- `QueueDrawer`, `LibraryDrawer`, `SettingsDrawer`, `SkinPickerDrawer` get
  an `onHome` prop rendered as a Home link in their header; it closes the
  drawer and sets `view = "home"`.
- Settings › System gains an **Off** row (`POST /api/power/sleep`) beside
  "Restart Mopidy".

### Boot

Nothing to persist: the app's initial `view` is `"home"`. The kiosk still
opens `http://localhost/`.

## Error handling

- Any `/api/power/*` failure in the UI is silent (button re-enables); the
  polled state is the truth.
- If `boombox-state` is down the UI never sees `asleep` and behaves as
  today. The buttons service now routes power through boombox-state, so
  if that POST fails the handler falls back to `Display.toggle()` — the
  panel can always be blanked/unblanked from the physical button.
- Poweroff timer fires only from `asleep`; `wake()` cancels it. A
  `sleep()` while already asleep does not re-arm it.

## Testing

- `services/tests/test_power.py`: state transitions, idempotency, timer
  arm/cancel with a fake clock (`grace_s=0.01`), callback failure
  tolerance, persistence file, startup-forces-display-on.
- `services/tests/test_actions.py`: power short-press → toggle; a
  non-power press while asleep → wake + dropped; fallback to
  `Display.toggle()` when the state API errors.
- `ui/src/lib/__tests__/HomeScreen.test.tsx`: tiles render from
  `sources.ts`; Off tile posts to `/api/power/sleep`; Music tile switches
  view.
- `ui/src/lib/__tests__/SleepScreen.test.tsx`: a pointer event posts wake.
- Manual on MarkII: short-press → audio stops, panel dark; touch → Home;
  wait grace → poweroff; boot → Home; drawers show Home link on all skins.

## Config & docs

- `/etc/boombox/boombox.env`: `BOOMBOX_SLEEP_POWEROFF_S=180` documented in
  `docs/SERVICES.md`; `docs/BUTTONS.md` row 17 updated (short press =
  sleep/wake).
- `hardware/`: note that the power button must also be wired to the Pi 5
  J2 PWR_BTN header for wake-from-halt.
