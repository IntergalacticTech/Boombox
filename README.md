# Boombox

A touchscreen-driven retro boombox built on Raspberry Pi 5 + HiFiBerry-class
I²S DAC. Mopidy handles local + streaming music; a React kiosk UI runs in
Chromium; a small fleet of Python services unifies Bluetooth / AirPlay /
Spotify Connect playback, drives GPIO buttons, runs a live audio visualizer,
and keeps the kiosk pinned to its UI.

```
                    ┌─────────────────────────────┐
                    │      Pi 5 (RPi OS 64)       │
                    │   1280×800 touchscreen      │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼─────────────────────────┐
        │                          │                         │
   Audio path                Control path                 UI / web
   ──────────                ────────────                 ────────
   HiFiBerry I²S DAC         GPIO buttons                 nginx localhost:80
   PipeWire mixer            touchscreen                  ├─ / (built SPA)
   Mopidy + Iris             playerctl / MPRIS            ├─ /mopidy/* → 6680
   shairport-sync (AirPlay)  AVRCP volume (BT)            ├─ /api/*    → 6681
   raspotify (Spotify)       boombox-orchestrator         ├─ /audio/ws → 6682
   bluez A2DP sink                                        └─ LAN :8090 requires auth
```

## Repo layout

| Path | What lives here |
|------|-----------------|
| `services/` | Python services (state aggregator, audio visualizer, source orchestrator, GPIO buttons, resume snapshotter, BT volume bridge, kiosk guard) |
| `ui/` | Vite + React + TypeScript SPA — the touchscreen front-end |
| `skins/` | Designer source-of-truth: tokens, JSX mockups, font licenses |
| `install/` | First-time installer, systemd units, config templates, self-update script |
| `install/legacy/` | Earlier setup scripts kept for reference |
| `bin/` | Helpers shipped onto the Pi (e.g. `boombox-update`) |
| `docs/` | Design notes, PRD, conversation history |

## Quick start — install on a fresh Pi

1. Flash Raspberry Pi OS 64-bit (Bookworm or newer) with Imager. In the
   advanced options set hostname, user, SSH, Wi-Fi, locale.
2. Boot, log in over SSH, then:
   ```bash
   sudo apt update && sudo apt install -y git
   sudo git clone https://github.com/IntergalacticTech/Boombox.git /opt/boombox
   sudo chown -R "$USER:$USER" /opt/boombox
   /opt/boombox/install/install.sh
   sudo reboot
   ```
3. After reboot, Chromium launches in kiosk mode and shows the boombox UI.
   Audio is routed through the HiFiBerry DAC.

The installer is idempotent: re-running it picks up changes to configs,
systemd units, and the UI build.

## Self-update on the Pi

```bash
boombox-update
```

Pulls `main`, reinstalls anything that drifted (deps, configs, units),
rebuilds the SPA, and restarts the affected services. Roughly 60 seconds on
a Pi 5 once dependencies are cached.

## Dev loop from a Mac

`./pi` wraps SSH, rsync, Wayland screenshots, Chromium DevTools navigation,
and log tailing.

```bash
./pi status               # services + now-playing summary
./pi shot                 # Wayland screenshot pulled to ./screenshots/
./pi deploy ui/dist /var/www/boombox/
./pi reload               # reload the kiosk tab
./pi guard pause          # let agents drive the kiosk without the watchdog fighting
./pi logs mopidy
```

Set `BOOMBOX_HOST` (or define a `boombox` host in `~/.ssh/config`) to point
it at your Pi.

## Services overview

| Service | Port | Role |
|---------|------|------|
| `mopidy`              | 6680 | Music server (HTTP/WS RPC, Iris UI, local + Spotify) |
| `smbd`                | 445  | Password-protected SMB share for `~/Music` |
| `boombox-state`       | 6681 | MPRIS aggregator: non-Mopidy sources at `/api/state`; also `/api/control`, `/api/volume`, `/api/info`, `/api/sinks`, `/api/karaoke`, `/api/lyrics`, `/api/art`, `/api/mopidy/restart` |
| `boombox-audio`       | 6682 | PipeWire monitor → FFT/VU → WebSocket at `/audio/ws` |
| `boombox-orchestrator`| —    | Watches PipeWire; pauses other sources when a new one starts |
| `boombox-buttons`     | —    | GPIO falling-edge → Mopidy transport |
| `boombox-resume`      | —    | Snapshots Mopidy state, restores after reboot |
| `boombox-bt-volume`   | —    | AVRCP absolute-volume → `bluez_input` node |
| `boombox-kiosk-guard` | —    | DevTools-driven watchdog that keeps Chromium on `http://localhost/` |

All seven `boombox-*` services run as **user** systemd units (they need the
desktop session's PipeWire / Wayland / BlueZ). `nginx` and `mopidy` are
system services.

## Docs

- **[ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — one-screen picture of how everything fits together
- **[SERVICES.md](./docs/SERVICES.md)** — per-service reference: what each daemon does and how to debug it
- **[SKINS.md](./docs/SKINS.md)** — end-to-end guide to creating a new touchscreen skin
- **[ACCESS.md](./docs/ACCESS.md)** — authenticated LAN web access, remote/upload page, SMB share, and USB auto-mount
- **[VIDEO.md](./docs/VIDEO.md)** — Jellyfin server: touchscreen Watch button, native apps, USB videos
- **[ONBOARDING.md](./docs/ONBOARDING.md)** — first-time setup for a new developer (SSH access, `.env`, first dev loop)
- **[DEVELOPMENT.md](./docs/DEVELOPMENT.md)** — dev workflow on a laptop, the `pi` helper, common tasks

## Roadmap

- [x] Working code on the Pi
- [x] Repo layout + installer scripts for RPi OS
- [x] Self-update from `main`
- [ ] Pre-built SD-card image (dietpi or custom yocto base)
- [ ] Versioned releases + signed update channel
- [ ] Battery / power-management integration
- [ ] Optional hotspot mode for Wi-Fi-less environments

## License

MIT — see [LICENSE](./LICENSE).
