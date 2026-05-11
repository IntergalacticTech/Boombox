# Video — Jellyfin on the boombox

A standalone **Jellyfin** server is bundled with the boombox so the same
device that plays music can also play movies — on the touchscreen, in a
phone or tablet app, or from any browser on the LAN. Jellyfin runs as a
system service on port `8096` independent of the music stack; nothing
about Mopidy / Iris / the remote web UI changes.

---

## Three ways to watch

| Surface | URL or app | Notes |
|---|---|---|
| **Touchscreen** | tap **WATCH** in the Settings drawer | The kiosk navigates to `http://localhost:8096/`. A floating "← BOOMBOX" pill in the top-left brings you back. |
| **Browser on the LAN** | `http://<pi-ip>:8096/` | Direct, no proxying. Use Jellyfin's own login. |
| **Phone / tablet / TV app** | Install Jellyfin from your app store | Available on iOS, Android, Apple TV, Android TV, Fire TV, Roku, web TV. Point at `http://<pi-ip>:8096/`. |

The touchscreen swap **pauses Mopidy first** so a video's audio doesn't
fight whatever's playing. Coming back to the boombox UI doesn't auto-resume
the music — that's a deliberate "you decide what plays" stance.

```
                Touchscreen                              Web/native client
            ┌─────────────────┐                       ┌─────────────────────┐
            │  Settings →     │                       │  Jellyfin app       │
            │  Movies         │                       │  ┌────────────┐     │
            │  ┌─────────┐    │   localhost:8096      │  │ Library    │     │
            │  │ WATCH   │────┼────────▶ jellyfin ────┼──┤  • Films   │     │
            │  └─────────┘    │           :8096       │  │  • TV      │     │
            │                 │                       │  │  • USB-DR  │     │
            │  ← BOOMBOX pill │                       │  └────────────┘     │
            │   (top-left)    │                       │                     │
            └─────────────────┘                       └─────────────────────┘
```

---

## How it's wired

- **Server:** `jellyfin` (apt-installed from the project's official repo,
  arm64). Default port `8096`, bound on all interfaces.
- **Library path:** `~/Videos` (the desktop user's home — currently
  `/home/jwc/Videos`). Three top-level subfolders are created at install:
  - `~/Videos/` — curated content goes here
  - `~/Videos/uploads/` — for files dropped via the remote/upload page
  - `~/Videos/.usb/` — auto-populated symlinks to USB drives (see below)
- **USB drives** that get mounted by the existing
  `boombox-usb-mount@<dev>.service` flow now get **two** symlinks: one
  under `~/Music/.usb/<id>` (for Mopidy) and one under `~/Videos/.usb/<id>`
  (for Jellyfin). The same physical drive serves both libraries.
- **Auth:** Jellyfin uses its own account database. It isn't proxied
  behind the nginx HTTP-Basic gate on port 8090 — every Jellyfin app
  expects to talk to a bare server, and Jellyfin's login is the auth gate.

---

## First-run setup — done by `install.sh`

There is no manual Jellyfin wizard. `install.sh` runs
[`services/boombox-jellyfin-setup.py`](../services/boombox-jellyfin-setup.py)
which drives Jellyfin's `/Startup/*` API:

1. Sets locale (en-US, US, en).
2. Creates the admin user using the same credentials as the LAN web
   gate (`BOOMBOX_WEB_USER` / `BOOMBOX_WEB_PASSWORD` from
   `/etc/boombox/web-auth.env` — one credential for everything LAN
   facing).
3. Disables remote access + UPnP (LAN only).
4. Marks the wizard complete.
5. Authenticates, stores the API token at `/etc/boombox/jellyfin.env`
   and `/etc/boombox/jellyfin-api-key` so the USB-mount script and
   future code can drive Jellyfin without re-logging-in.
6. Creates a mixed-collection library at `~/Videos` with real-time
   monitoring on, so the `.usb/<drive>` symlinks added by
   `boombox-usb-mount.sh` show up automatically.

After install + reboot, tap **WATCH** in the Settings drawer and you're
at the login screen. Username is `boombox`; password is the 6-digit
number in `/etc/boombox/web-auth.env`. (Touchscreen text entry works
because wvkbd is built from source with `--layer overlay` — see
[SERVICES.md](./SERVICES.md#boombox-osk--on-screen-keyboard).)

Re-running `install.sh` is idempotent: if Jellyfin is already
boombox-managed it skips the setup; if Jellyfin exists but isn't ours
(someone ran the manual wizard), `install.sh` wipes the database and
re-claims it.

### Resetting Jellyfin manually

```bash
sudo systemctl stop jellyfin
sudo rm -f /etc/boombox/jellyfin.env /etc/boombox/jellyfin-api-key
sudo rm -f /var/lib/jellyfin/data/jellyfin.db*
sudo rm -f /etc/jellyfin/system.xml
sudo systemctl start jellyfin
/opt/boombox/install/install.sh    # re-runs the setup
```

### Adding more content paths

The auto-created library is a single mixed-content folder at `~/Videos`.
To split into Movies / TV / etc. or add an extra root, use Dashboard →
Libraries from the Jellyfin admin UI. The boombox doesn't dictate beyond
the first library.

---

## The kiosk return pill

The chromium kiosk launches with a tiny extension (`install/kiosk-extension/`)
that injects a floating **← BOOMBOX** pill in the top-left of any page
whose URL is *not* the boombox SPA (`localhost:80`). The pill:

- Stays put when Jellyfin replaces the DOM (SPA navigation).
- Sits at z-index `2147483647` so it floats above Jellyfin's own UI.
- On tap, hard-navigates back to `http://localhost/`.

The extension is loaded via Chromium's `--load-extension=` flag in
`install/systemd/user/boombox-kiosk.service`. To disable it temporarily,
stop and restart `boombox-kiosk.service` after editing the unit.

The kiosk-guard (`boombox-kiosk-guard.service`) considers `localhost:8096`
to be "home enough" since the hostname is `localhost`, so it won't fight
the navigation.

---

## Connecting native apps

### iOS / Android
Install **Jellyfin Mobile** (App Store / Play Store). On first launch:

1. Tap "Add Server".
2. Server address: `http://<pi-ip>:8096/`. Example: `http://192.168.1.176:8096/`.
3. Log in with the admin account you created in the wizard (or any user
   you've added in Dashboard → Users).

The app supports background audio, AirPlay, casting, downloads, and
PIP — none of which the boombox itself has to provide.

### Apple TV / Android TV / Fire TV / Roku
Search "Jellyfin" in the platform's store, install the official client,
add the server the same way. Use the LAN IP, not `boombox.local`, on
TVs that don't have mDNS.

### DLNA / UPnP (older TVs and stereo receivers)
Jellyfin's DLNA module is on by default. Dashboard → Plugins → DLNA shows
the active profiles. Most modern TVs will see a `Jellyfin (boombox)` entry
in their "Network" or "Media Server" list and can browse + stream
directly.

---

## Adding video content

| How | Where it lands |
|---|---|
| Copy over SMB | `smb://<pi-ip>/boombox-music/...` — wait, that's the **music** share. The music share doesn't include `~/Videos`. Add a similar share if you want SMB-based video uploads, or use one of the methods below. |
| Drag-and-drop via the remote page | The existing `/upload` page targets `~/Music/uploads/` today. Videos through this path is a near-term TODO. |
| `scp` / `rsync` from a laptop | `rsync -avz ~/Movies/Inception.mkv jwc@<pi-ip>:Videos/Films/` |
| USB drive | Plug it in. Drive auto-symlinks into `~/Videos/.usb/<label>` and Jellyfin's real-time monitoring picks it up. |

A future iteration will broaden the upload page to accept video MIME types
and land them in `~/Videos/uploads/`.

---

## Performance notes (Pi 5)

- **Direct play (no transcoding) is best.** Pi 5 has limited GPU-accelerated
  decode; software transcoding 1080p is workable, 4K is not.
- **Encode your library in H.264 / AAC** in MKV or MP4 containers and most
  clients (Jellyfin web, iOS app, AppleTV) will direct-play.
- HDR / 10-bit HEVC / Dolby Vision will force a software transcode and a
  Pi 5 won't keep up — expect stuttering. Use a remux tool to drop those.
- The HiFiBerry DAC is the default audio output, so video audio goes
  through the boombox speakers like everything else.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `WATCH` taps but kiosk doesn't navigate | Jellyfin service down or still starting | `./pi ssh "sudo systemctl status jellyfin"`. First boot can take ~30s. |
| Login loop or "server unreachable" in iOS app | Wrong server URL or firewall | Check `curl http://<pi-ip>:8096/health` returns `Healthy`. |
| ← BOOMBOX pill missing on Jellyfin | Extension didn't load | `./pi ssh "ls /opt/boombox/install/kiosk-extension"`, then restart `boombox-kiosk.service`. |
| Pill is there but tapping it doesn't return | Chromium's history mode | Reload the kiosk: `./pi reload`. |
| Plugged in a USB drive, video not appearing | Symlink wasn't created or Jellyfin scan stale | `./pi ssh "ls -la ~/Videos/.usb/"`. If empty, check `journalctl -u boombox-usb-mount@*`. Hit Dashboard → Scheduled Tasks → Scan Media Library if the symlink is there. |
| Audio plays through HDMI instead of the DAC | PipeWire default sink got remapped | Settings drawer → Output → pick the HiFiBerry sink. |
| Video stutters | Software transcode in progress | Dashboard → Activity → check transcoding status. Re-encode the source to H.264 + AAC if it keeps happening. |
