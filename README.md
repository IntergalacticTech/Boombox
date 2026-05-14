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
   HiFiBerry I²S DAC         17 GPIO buttons + encoder    nginx localhost:80
   PipeWire mixer            touchscreen                  ├─ / (built SPA)
   Mopidy + Iris             playerctl / MPRIS            ├─ /mopidy/*       → 6680
   shairport-sync (AirPlay)  AVRCP volume (BT)            ├─ /api/*          → 6681
   raspotify (Spotify)       boombox-orchestrator         ├─ /audio/ws       → 6682
   bluez A2DP sink           kiosk overlay events         ├─ /api/buttons/*  → 6684
                                                          └─ LAN :8090 requires auth
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

## Updates

Devices auto-check GitHub for new releases hourly and (by default) install
new **stable** releases inside a nightly window of 03:00–04:00, skipping if
music is playing. Toggle channel, window, and auto-on/off in
**Settings → Updates** on the touchscreen or LAN web page.

Manual control from a shell:

```bash
boombox-update            # check + install latest now
boombox-update status     # current channel, installed/available versions
boombox-update install v0.4.2
boombox-update rollback   # flip back to the previous release
```

Updates are A/B-installed under `/opt/boombox/releases/<ref>/` with the
`current` symlink swapped atomically. A failed install (build error, a
service that won't come back up) auto-reverts to the previous good release.

To disable auto-updates entirely: `systemctl --user disable --now
boombox-updater.service`. `boombox-update` still works with the service
disabled — it falls back to a direct `apply-release.sh` run, though that
**direct fallback path does not auto-rollback** a bad release, so prefer
keeping the service enabled.

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

## Project website

The open-source website lives in [`site/`](./site). It is plain static HTML,
CSS, JavaScript, and image assets, so there is no Node build step for the
website itself.

GitHub Pages publishing is handled by
[`.github/workflows/pages.yml`](./.github/workflows/pages.yml). On a repository
with Pages enabled for **GitHub Actions**, pushes to `main` that touch the site
folder will publish the latest site.

## Services overview

| Service | Port | Role |
|---------|------|------|
| `mopidy`              | 6680 | Music server (HTTP/WS RPC, Iris UI, local + Spotify) |
| `smbd`                | 445  | Password-protected SMB share for `~/Music` |
| `boombox-state`       | 6681 | MPRIS aggregator: non-Mopidy sources at `/api/state`; also `/api/control`, `/api/volume`, `/api/info`, `/api/sinks`, `/api/karaoke`, `/api/lyrics`, `/api/art`, `/api/mopidy/restart` |
| `boombox-audio`       | 6682 | PipeWire monitor → FFT/VU → WebSocket at `/audio/ws` |
| `boombox-orchestrator`| —    | Watches PipeWire; pauses other sources when a new one starts |
| `boombox-buttons`     | 6684 | 17 GPIO buttons + rotary encoder; routes to Mopidy / state API / kiosk overlays; `/api/buttons/` config + learn + test |
| `boombox-resume`      | —    | Snapshots Mopidy state, restores after reboot |
| `boombox-bt-volume`   | —    | AVRCP absolute-volume → `bluez_input` node |
| `boombox-kiosk-guard` | —    | DevTools-driven watchdog that keeps Chromium on `http://localhost/` |

All seven `boombox-*` services run as **user** systemd units (they need the
desktop session's PipeWire / Wayland / BlueZ). `nginx` and `mopidy` are
system services.

## Docs

- **[ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — one-screen picture of how everything fits together
- **[SERVICES.md](./docs/SERVICES.md)** — per-service reference: what each daemon does and how to debug it
- **[BUTTONS.md](./docs/BUTTONS.md)** — wire 17 panel buttons + an encoder, bind pins from the Settings panel, troubleshoot
- **[SKINS.md](./docs/SKINS.md)** — end-to-end guide to creating a new touchscreen skin
- **[ACCESS.md](./docs/ACCESS.md)** — authenticated LAN web access, remote/upload page, SMB share, and USB auto-mount
- **[VIDEO.md](./docs/VIDEO.md)** — Jellyfin server: touchscreen Watch button, native apps, USB videos
- **[ONBOARDING.md](./docs/ONBOARDING.md)** — first-time setup for a new developer (SSH access, `.env`, first dev loop)
- **[DEVELOPMENT.md](./docs/DEVELOPMENT.md)** — dev workflow on a laptop, the `pi` helper, common tasks
- **[CHANGELOG.md](./CHANGELOG.md)** — what shipped when, with links into the design docs

## Roadmap

- [x] Working code on the Pi
- [x] Repo layout + installer scripts for RPi OS
- [x] Self-update from `main`
- [ ] Pre-built SD-card image (dietpi or custom yocto base)
- [x] Versioned releases (signed update channel deferred to a later milestone)
- [ ] Battery / power-management integration
- [ ] Optional hotspot mode for Wi-Fi-less environments

## License

MIT — see [LICENSE](./LICENSE).
