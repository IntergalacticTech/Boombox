# Architecture

How the boombox is wired up, end-to-end. Read this once and the rest of the
repo organises itself in your head.

---

## One-screen summary

```
                      ┌──────────────────────────────┐
                      │   Raspberry Pi 5 + HiFiBerry  │
                      └──────────────┬───────────────┘
                                     │
   ┌─────────────┐     ┌──────────────┴────────────┐     ┌────────────────────┐
   │   Touch UI  │◀────│  nginx localhost:80       │────▶│ /opt/boombox/      │
   │  (Chromium) │     │  ┌─────────────────────┐  │     │ current/ui/dist/   │
   │  kiosk mode │     │  │ / → SPA             │  │     │ (Vite build, the   │
   └──────┬──────┘     │  │ /mopidy/      :6680 │  │     │  active release)   │
          │            │  │ /api/         :6681 │  │     └────────────────────┘
   GPIO   │            │  │ /audio/ws     :6682 │  │
   buttons│            │  │ /api/buttons/ :6684 │  │
          │            │  │ /api/update/  :6685 │  │
          │            │  └─────────────────────┘  │
          │            │  LAN :8090 → Basic auth   │
          │            └───────────────────────────┘
          ▼                       │       │      │ │
   ┌──────────────┐               ▼       ▼      │ ▼
   │   Mopidy     │       ┌───────────┐ ┌──────────┐ ┌─────────────┐
   │   :6680      │◀──────│  boombox- │ │ boombox- │ │  boombox-   │
   │   (music)    │       │  state    │ │  audio   │ │  buttons    │
   └──────┬───────┘       │  :6681    │ │  :6682   │ │  :6684+GPIO │
          │               └─────┬─────┘ └─────┬────┘ └──────┬──────┘
          │  alsasink           │             │             │
          ▼                     │  playerctl  │  parec      │ HTTP/RPC
   ┌──────────────┐             ▼             ▼             ▼
   │  PipeWire    │       ┌─────────────────────────────────────────┐
   │  + Wireplumber│      │  shairport-sync  raspotify  bluez A2DP  │
   └──────┬───────┘       └─────────────────────────────────────────┘
          │                        │              │             │
          ▼                  AirPlay receiver  Spotify Connect  Phone (BT)
   ┌──────────────┐
   │ HiFiBerry DAC│
   │ (I²S)        │
   └──────┬───────┘
          ▼
       speakers
```

---

## Processes

| Process | Type | Port | Purpose |
|---------|------|------|---------|
| `nginx` | system | 127.0.0.1:80, LAN 8090 | Reverse proxy; serves the SPA. Local kiosk is unauthenticated; LAN clients require HTTP Basic auth. |
| `smbd` | system | 445 | Password-protected SMB share for the music library |
| `mopidy` | system | 6680 | Music server (local files, Spotify-via-Mopidy, Iris UI, JSON-RPC + WebSocket) |
| `pipewire`, `wireplumber` | user | — | Audio graph |
| `shairport-sync` | system | — | AirPlay receiver (sink → PipeWire) |
| `raspotify` (optional) | system | — | Spotify Connect via librespot |
| `bluetoothd` | system | — | BlueZ; A2DP sink for phones |
| `chromium` (kiosk) | user | 9222 | Touch UI; remote-debug port for the `pi` helper |
| `boombox-state` | user | 6681 | MPRIS aggregator + `/api/*` helpers |
| `boombox-audio` | user | 6682 | PipeWire monitor → FFT/VU → `/audio/ws` WebSocket |
| `boombox-orchestrator` | user | — | Watches PipeWire; pauses other sources when a new one starts |
| `boombox-buttons` | user | 6684 | 17 buttons + encoder over `/dev/gpiochip0`; HTTP `/api/buttons/` for the Settings panel (config / learn / test); hot-reloads `/etc/boombox/buttons.json` |
| `boombox-resume` | user | — | Snapshots Mopidy state, restores after reboot |
| `boombox-bt-volume` | user | — | AVRCP absolute-volume → `bluez_input` node volume |
| `boombox-kiosk-guard` | user | — | DevTools watchdog that keeps Chromium pinned to `http://localhost/` |
| `boombox-updater` | user | 6685 | Polls GitHub Releases; runs scheduled A/B release installs with auto-rollback. See [Updates](#updates). |
| `boombox-uploader` | user | 6683 | Off by default. Toggled from the touchscreen; serves a PIN-gated remote/upload page at `/upload/`. See [ACCESS.md](./ACCESS.md). |
| `boombox-usb-mount@<dev>` | system (template) | — | Triggered by udev. Mounts USB drives R/O under `/media/boombox/<id>` and symlinks them into the Mopidy library at `~/Music/.usb/<id>`. |

**System vs user.** `nginx`, `mopidy`, `smbd`, `shairport-sync`, `bluetoothd`,
`raspotify` are system-wide and start before login. The `boombox-*` services
run as **user** units because they need the desktop session's
`XDG_RUNTIME_DIR` (PipeWire, BlueZ user session, Wayland for the kiosk).
`loginctl enable-linger` lets them come up at boot before any human logs in.

---

## Data flow: "what's playing right now?"

There are two source-of-truth channels, and the UI merges them:

1. **Mopidy** — when music is playing from the local library, internet radio,
   or Spotify-via-Mopidy. The SPA opens a WebSocket to `/mopidy/ws` for
   push events and POSTs JSON-RPC to `/mopidy/rpc` for one-off calls
   (`ui/src/lib/mopidy.ts`).

2. **Non-Mopidy MPRIS** — when AirPlay, Bluetooth A2DP, or
   librespot/raspotify is actively producing audio. `boombox-state` polls
   `playerctl` every 500 ms and exposes the active player at
   `/api/state`. The SPA polls this every 2 s
   (`ui/src/lib/activeSource.ts`).

`App.tsx` decides which one "wins" using `isExternalActive()`: if a
non-Mopidy MPRIS player is in `playing` state, its metadata overrides
Mopidy's. Transport actions (`onToggle`, `onNext`, `onPrev`) route to
whichever source is live: Mopidy's RPC for Mopidy, `/api/control/<action>`
for everything else.

---

## Data flow: "make a new source pause the old one"

`boombox-orchestrator` runs in the background. Every 500 ms it asks
PipeWire (`pw-dump`) which output streams are in the `running` state and
classifies each by the node name:

```
bluez_input.*  → bluetooth
librespot|raspotify → spotify
shairport      → airplay
mopidy         → mopidy
```

When a new source appears alongside an existing one, the orchestrator picks
the newest as the "winner" and pauses the others:

- Mopidy is paused via JSON-RPC.
- AirPlay / Spotify / Bluetooth are paused via `playerctl` against the
  matching MPRIS player.

This is fire-and-forget. There is **no** auto-resume — once paused, a source
stays paused until the user explicitly starts it again. That's a deliberate
choice: trying to coordinate resume across four asynchronous players led to
"AirPlay un-pauses three seconds later because the phone never knew it was
paused" loops.

---

## Data flow: visualizer

`boombox-audio` runs `parec` against the default PipeWire sink's `.monitor`
source — that's whatever's audible regardless of which source produced it.
Every ~46 ms it:

1. Reads a 1024-sample stereo s16le chunk.
2. Builds a 64-bin log-spaced spectrum with a perceptual sqrt curve and
   peak-hold envelope.
3. Computes L/R RMS for VU meters.
4. Broadcasts to all connected WebSocket clients on `/audio/ws`.

The SPA hook `useSpectrum()` (`ui/src/lib/spectrum.ts`) wires the messages
into a singleton state object so any number of skin components can subscribe
without opening more sockets.

PipeWire restarts (rare, but possible during Wireplumber updates) are
detected via a 5-second read timeout that triggers a re-detection of the
default sink and a fresh `parec` invocation.

---

## File-system layout on the Pi

```
/opt/boombox/                  ← release-pointer layout, owned by the desktop user
├── releases/<ref>/            ← one checkout per installed release (tag or sha)
│   ├── services/              ← Python service code (run by user systemd)
│   ├── ui/dist/               ← built SPA — nginx serves the active one directly
│   ├── install/               ← install.sh, apply-release.sh, configs, units
│   └── bin/                   ← boombox-update wrapper
├── current → releases/<ref>   ← symlink to the active release
├── previous → releases/<ref>  ← symlink to the last-known-good release
├── .venv/                     ← shared Python venv (--system-site-packages)
└── state/                     ← updater.json + logs/ (per-install-attempt logs)

/etc/nginx/sites-available/boombox
/etc/mopidy/mopidy.conf
/etc/asound.conf
/etc/boombox/buttons.json
/etc/boombox/updater.json      ← update channel / window / auto toggle
/boot/firmware/usercfg.txt     ← DAC overlay

~/.config/systemd/user/boombox-*.service
~/.local/state/boombox/last.json   ← boombox-resume snapshot
/usr/local/bin/boombox-update
```

`install.sh` migrates a legacy flat `/opt/boombox` checkout into this layout in
place on first run (the old tree becomes `releases/legacy-<sha>/`).

---

## Updates

The `boombox-updater` user service (`:6685`) polls GitHub hourly and installs
new releases A/B style. Two channels: `stable` (latest GitHub Release tag) and
`edge` (`main` HEAD). When a newer version is available, a scheduler runs the
install inside the configured nightly window (default 03:00–04:00) — unless
music is playing, in which case it waits for the next window.

An install drives `install/apply-release.sh` step by step:

1. **fetch** — clone the ref into a fresh `releases/<ref>/`.
2. **build** — `pip install -r` into the shared `.venv`, `npm run build` the UI.
3. **preflight** — sanity-check the new tree (`ui/dist/index.html`, `nginx -t`,
   `systemd-analyze verify` the units).
4. **swap** — point `previous` at the old release, then atomically swap the
   `current` symlink to the new one; sync new systemd units, `daemon-reload`.
5. **restart** — restart the `boombox-*` user units, reload nginx.
6. **verify** — smoke-test: all units active, `http://localhost/`, `/api/state`,
   and `/api/buttons/` answer. On failure the updater **reverts** — flips
   `current` back to `previous` and restarts — so a bad release never sticks.

Because nginx serves the SPA straight from `current/ui/dist/` and the swap is a
single atomic symlink move, the UI is never half-deployed. Channel, window, and
the auto-on/off toggle live in `/etc/boombox/updater.json`; runtime state and
per-attempt logs live under `/opt/boombox/state/`.

`bin/boombox-update` is a thin client of the `:6685` HTTP API (`status`,
`check`, `install [REF]`, `rollback`, `config`). If the service is unreachable
or disabled it falls back to running `apply-release.sh` directly
(fetch→build→preflight→swap→restart→verify) — note that fallback path has **no
auto-rollback**. `install/update.sh` is now just a back-compat shim that
`exec`s `boombox-update`.

---

## Design intentions worth knowing

- **Mopidy is the "library" source.** Anything that needs a queue,
  metadata, or seekable playback should flow through Mopidy. AirPlay /
  Spotify Connect / Bluetooth are intentionally treated as opaque
  inbound audio that we don't try to control beyond start/stop.

- **The SPA never talks directly to the boombox-* services on their TCP
  ports.** Every UI request goes through nginx — that means the same code
  works on the Pi, in the dev server (`npm run dev` proxies `/mopidy`), and
  inside the kiosk Chromium.

- **All persistent state lives in one of two places:** `/etc/boombox/`
  (config you might want to edit by hand) and `~/.local/state/boombox/`
  (machine-managed snapshots). Don't add a third place.

- **Skins must not assume which source is playing.** A skin gets a
  `Track` and a `PlayState` and doesn't care whether the audio is coming
  from a CD-rip on the SD card or an AirPlay session from a guest's phone.

- **Audio mixer is software-side in Mopidy.** `mixer = software` in
  `mopidy.conf` means volume changes happen before the DAC, so they're
  uniform across sources and the touch UI's volume slider can drive
  everything consistently.

Open a PR if any of the above stops being true.
