# Fresh Pi install — DietPi from scratch

A top-to-bottom guide for building a Boombox on a **brand-new Raspberry Pi 5
flashed with [DietPi](https://dietpi.com/) Lite** (64-bit). It takes you from
an unboxed Pi and a blank SD card to a running kiosk with audio out the DAC.

DietPi Lite boots to a bare console — no desktop, no compositor. The Boombox
installer knows this: when it detects DietPi it *creates* the Wayland kiosk
session that Raspberry Pi OS ships out of the box (see
`install/session/dietpi.sh`). Everything OS-specific is handled by
`install/install.sh`; this guide is mostly about getting DietPi itself to a
state where that installer can run.

> Prefer Raspberry Pi OS? The main [README](../README.md) covers that path —
> it is the older, more heavily tested one. DietPi is the leaner base.

---

## 1. Hardware checklist

| Part | Notes | Required? |
|------|-------|-----------|
| **Raspberry Pi 5** | The build targets the Pi 5. A Pi 4 may work but the GPIO/UART pin reclaim in `usercfg.txt` is verified for the Pi 5. | **Yes** |
| **microSD card** | 32 GB+, A1/A2 class. Holds the OS, the repo, and the local `~/Music` cache. | **Yes** |
| **USB-C power supply** | The official 27 W Pi 5 PSU. Under-powering a Pi 5 with a DAC + touchscreen causes brownouts. | **Yes** |
| **HiFiBerry-class I²S DAC** | A PCM5122 / `hifiberry-dacplus`-family HAT (e.g. 52Pi EP-0218). Sits on the GPIO header. | Recommended |
| **Speakers / amp** | Line-out or amplified speakers off the DAC. | Recommended |
| **Touchscreen** | The reference builds use the official Raspberry Pi 7″ DSI Touch Display (800×480, FT5x06 touch); any Wayland-capable DSI/HDMI panel works. | Recommended |
| **USB HID RFID reader** | A keyboard-emulating 125 kHz/13.56 MHz reader. Tap a card to play a bound album/playlist. | Optional |
| **17 GPIO buttons + rotary encoder** | The physical control surface. Wire per [BUTTONS.md](./BUTTONS.md). | Optional |
| **USB stick / drive** | For sideloading music; auto-mounts into the library. | Optional |

### The "any subset works" rule

Boombox has a hard design rule: **every hardware-coupled feature must run
cleanly when its hardware is absent or unwired.** A minimal build — just a Pi,
SD card, and power — installs and boots fine. The buttons service comes up with
no GPIO wired, the RFID service comes up with no reader plugged in, audio falls
back gracefully if the DAC overlay doesn't bind, and the kiosk runs headless if
no display is attached. Install everything now; wire the optional hardware
whenever you like. Nothing below blocks on a part you don't have.

---

## 2. Choose and flash DietPi

### Download

Grab the **DietPi image for Raspberry Pi 5 (ARMv8, 64-bit)** from the official
download page:

- <https://dietpi.com/#download> → *Raspberry Pi 5*

You want the SD-card image (a `.img.xz`). There is one DietPi image per board;
"Lite" is not a separate download — DietPi is minimal by default and you choose
software during first boot.

### Flash

Use whichever tool you have; all three write the raw image fine:

- **Raspberry Pi Imager** — choose *Use custom* and select the downloaded
  `.img.xz`. Do **not** use Imager's OS-customization dialog (hostname/Wi-Fi/SSH)
  — that is a Raspberry Pi OS feature and does nothing for DietPi. Configure
  DietPi via its own text files instead (next step).
- **balenaEtcher** — *Flash from file* → the `.img.xz` → your SD card.
- **`dd`** (macOS/Linux, careful with the target disk):
  ```bash
  xz -dc DietPi_RPi5-ARMv8-Bookworm.img.xz | sudo dd of=/dev/rdiskN bs=4m status=progress
  ```
  Replace `/dev/rdiskN` with your SD card device (`diskutil list` on macOS,
  `lsblk` on Linux). Double-check it — `dd` to the wrong disk erases it.

### Headless first-boot automation (no keyboard needed)

After flashing, the SD card's **boot partition** (FAT, mounts as `boot` on your
laptop) contains two DietPi config files. Edit them **before** first boot so the
Pi comes up on Wi-Fi with SSH enabled and you never need a keyboard or monitor.

> These files are DietPi's own first-boot mechanism — they are not part of the
> Boombox repo. DietPi reads them once on first boot, applies them, then
> deletes/consumes the automation block. Full reference:
> <https://dietpi.com/docs/usage/#how-to-do-an-automatic-base-installation-at-first-boot-dietpi-automation>

**`dietpi.txt`** — the main config. Set at least:

```ini
# Network / identity
AUTO_SETUP_NET_HOSTNAME=boombox1
AUTO_SETUP_LOCALE=en_US.UTF-8
AUTO_SETUP_KEYBOARD_LAYOUT=us
AUTO_SETUP_TIMEZONE=America/New_York

# Wi-Fi (set to 1 to use the credentials in dietpi-wifi.txt; 0 for Ethernet)
AUTO_SETUP_NET_WIFI_ENABLED=1

# Run first-boot setup unattended and keep going without prompts
AUTO_SETUP_AUTOMATED=1

# SSH server: -1 = Dropbear (light) ; -2 = OpenSSH (recommended for rsync/scp)
AUTO_SETUP_SSH_SERVER_INDEX=-2

# Leave the survey/opt-out where you like; 0 opts out of the anonymous survey
SURVEY_OPTED_IN=0
```

**`dietpi-wifi.txt`** — Wi-Fi credentials (only if `AUTO_SETUP_NET_WIFI_ENABLED=1`):

```ini
aWIFI_SSID[0]='YourNetwork'
aWIFI_KEY[0]='YourPassword'
aWIFI_KEYMGR[0]='WPA-PSK'
```

Save both files, eject the card, put it in the Pi, and power on.

> **Root/user note.** DietPi's default users are `root` and `dietpi`
> (both start with password `dietpi` — change it on first login). The Boombox
> installer runs as the **non-root desktop user** and uses that user's home for
> `~/Music`. Use the `dietpi` user for this (or create your own). This guide
> assumes `dietpi`; substitute your username throughout.

---

## 3. First boot

1. **Wait a few minutes.** DietPi's first boot resizes the filesystem, updates
   itself, applies `dietpi.txt`, joins Wi-Fi, and runs the automated setup.
   The Pi may reboot once or twice.
2. **Find it on the LAN and SSH in:**
   ```bash
   ping boombox1.local          # mDNS, if your network supports it
   ssh dietpi@boombox1.local    # or ssh dietpi@<pi-ip>
   ```
   Default password is `dietpi` unless you changed it. Change it now:
   `passwd`.
3. **Let DietPi finish and update.** If you didn't set `AUTO_SETUP_AUTOMATED=1`,
   the `dietpi-launcher` / first-run survey appears on SSH login — walk through
   it, then run:
   ```bash
   sudo dietpi-update
   ```
4. **SSH is already on** if you set `AUTO_SETUP_SSH_SERVER_INDEX`. To confirm or
   change the SSH server later: `sudo dietpi-software` → *SSH Server*.

### The I²S DAC — handled by the installer, but here's what happens

You do **not** need to hand-edit the device tree. The Boombox installer
(section 4) drops `install/config/usercfg.txt` onto the boot partition and makes
sure `config.txt` includes it. That file contains:

```ini
dtparam=i2s=on
dtparam=audio=off          # disables onboard audio so the DAC is the only sink
dtoverlay=hifiberry-dacplus
```

On DietPi the boot partition is mounted at `/boot` (Raspberry Pi OS Bookworm
uses `/boot/firmware`); the installer auto-detects which and writes to the right
place. After the post-install reboot, `aplay -l` should list
`sndrpihifiberry`.

If your DAC is a different chip and you get no sound, edit
`/boot/usercfg.txt` and swap the overlay — the file lists the common
alternatives (`hifiberry-dac`, `rpi-dac`, `iqaudio-dac`) — then reboot. Onboard
audio disabling (`dtparam=audio=off`) is already in that file, so you don't need
to disable it separately.

> **No DAC attached?** Leave the overlay as-is. The audio stack still starts;
> you just won't have a working output until a DAC is present. This is the
> "any subset works" rule in action.

### The screen — DietPi ships with the display stack *disabled*

Out of the box a DietPi image gives you a **completely dark DSI touchscreen —
not even a boot console**. Two things are missing that Raspberry Pi OS ships by
default:

- `dtoverlay=vc4-kms-v3d` is present but **commented out** in `config.txt`, so
  no KMS/DRM display driver loads at all (`/sys/class/drm` is empty);
- `display_auto_detect=1` is absent, so the firmware never probes the DSI
  ports for the panel (and `dtparam=i2c_arm=on` is off, which the panel's
  touch controller and backlight regulator also need).

The installer's DietPi session bootstrap (`install/session/dietpi.sh`) now
enables all of this in `config.txt` automatically. To bring the screen (and
DAC) up **before** running the full installer — e.g. to sanity-check hardware
on a fresh flash — run the standalone, idempotent script as root:

```bash
install/bin/dietpi-hardware-setup.sh
reboot
```

After the reboot the panel shows the boot console, and:

```bash
cat /sys/class/drm/card*-DSI-1/status   # → connected
tr '\0' '\n' < /proc/device-tree/panel_disp@0/compatible  # → raspberrypi,7inch-dsi
```

No panel attached? The settings are harmless — `display_auto_detect` simply
finds nothing and HDMI/headless still works. "Any subset works."

---

## 4. Install Boombox

SSH'd in as `dietpi` (your non-root desktop user), run:

```bash
sudo apt update && sudo apt install -y git
sudo git clone https://github.com/IntergalacticTech/Boombox.git /opt/boombox
sudo chown -R "$USER:$USER" /opt/boombox
/opt/boombox/install/install.sh
```

That's it. The installer:

- installs all apt dependencies (Mopidy, nginx, PipeWire, Chromium, Samba,
  shairport-sync, BlueZ, Jellyfin, Node, and more);
- **auto-detects DietPi** via `detect_os` (it looks for the `/boot/dietpi`
  marker) and runs the DietPi session bootstrap, which apt-installs the
  **labwc** Wayland compositor + `kanshi`, sets **tty1 autologin** for your
  user, and execs `labwc` from `~/.bash_profile` on the console login only;
- writes the **DAC overlay** and ALSA default device;
- builds the React kiosk UI and the phone PWA in place;
- installs and enables all `boombox-*` **user** systemd units plus the `nginx`,
  `mopidy`, `smbd`, and `jellyfin` **system** services;
- enables **linger** for your user so the user services start at boot before
  anyone logs in;
- generates a remote LAN/SMB password and prints it at the end.

**If autodetect is wrong**, force it:

```bash
BOOMBOX_OS=dietpi /opt/boombox/install/install.sh   # force DietPi path
BOOMBOX_OS=rpi-os /opt/boombox/install/install.sh   # force RPi OS path
```

**Run as your desktop user, not root.** The installer refuses to run as root —
it needs to install *user* systemd units into your home. It self-escalates with
`sudo` for the parts that need it (apt, `/boot`, system services), so expect a
sudo prompt.

When it finishes it prints the remote web password and Jellyfin URL. **Reboot:**

```bash
sudo reboot
```

After reboot, Chromium comes up in kiosk mode on the touchscreen. On a
**fresh** device it opens the **setup wizard** instead of the player: name the
boombox, join Wi-Fi, connect your music library and video server, and pair a
remote — all from the touchscreen, or scan the QR it shows to finish from your
phone or laptop. When you tap Finish it drops into the Boombox UI with audio
routed through the DAC. Everything the wizard sets is also editable later from
**Settings**, and the [Setup & connecting services](https://intergalactictech.github.io/Boombox/setup.html)
guide documents each step for doing it by hand.

> **Idempotent + re-runnable.** Re-running `install.sh` is safe — every step
> checks before it acts. Re-run it after `git pull` to pick up config, systemd,
> and UI changes. It replaces its own DietPi session block rather than
> appending duplicates.

### DietPi-specific gotchas

- **Autologin conflict.** The installer sets up its own `getty@tty1` autologin
  drop-in. Leave DietPi's own autologin (`dietpi-autostart`) at the default
  *console* option — don't set DietPi to autostart a desktop or Chromium, or two
  session managers will fight. The installer's getty drop-in wins on `tty1`.
- **Compositor packages.** `labwc` and `kanshi` come from Debian's repos and are
  installed by the DietPi session bootstrap. `wlrctl` is best-effort (not
  packaged everywhere) — its only job is parking the cursor off-screen, so its
  absence is cosmetic.
- **Group membership needs a reboot.** The installer adds your user to
  `gpio`, `audio`, `video`, `render`, `bluetooth`, `plugdev`, and `input`. Those
  take effect after the reboot you're already doing.
- **`systemd-logind` is masked on DietPi.** User systemd units, linger, and
  `loginctl` all need logind, and DietPi ships it masked. The installer
  unmasks and starts it automatically (and exports `XDG_RUNTIME_DIR` /
  `DBUS_SESSION_BUS_ADDRESS` so `systemctl --user` works even from a bare
  SSH/nohup shell). If you see *"Could not enable linger: Unit
  dbus-org.freedesktop.login1.service failed to load properly"*, that's this —
  `sudo systemctl unmask systemd-logind dbus && sudo systemctl enable --now
  dbus systemd-logind`.

---

## 5. Verification

After the reboot, SSH back in and confirm each layer.

### User services

```bash
systemctl --user status 'boombox-*' --no-pager
```

All enabled units should be `active (running)`. The full set:
`boombox-state`, `boombox-audio`, `boombox-orchestrator`, `boombox-buttons`,
`boombox-remote`, `boombox-resume`, `boombox-bt-volume`, `boombox-kiosk`,
`boombox-kiosk-guard`, `boombox-osk`, `boombox-updater`, `boombox-library`,
`boombox-rfid`.

> If `systemctl --user` says *"Failed to connect to bus"* over SSH, the user
> manager needs linger (the installer enables it) or run it against your UID:
> `export XDG_RUNTIME_DIR=/run/user/$(id -u)` first.

### System services

```bash
systemctl status nginx mopidy smbd jellyfin --no-pager
```

### Health endpoints

nginx serves these on loopback port 80; curl them from the Pi:

```bash
curl -s localhost/api/state          | jq .   # aggregated player state (boombox-state, 6681)
curl -s localhost/api/library/health | jq .   # Navidrome sync + cache-drive status (boombox-library, 6687)
curl -s localhost/api/rfid/status    | jq .   # RFID reader present? last tap? (boombox-rfid, 6688)
curl -s localhost/api/buttons/config | jq .   # GPIO button bindings (boombox-buttons, 6684)
```

Each should return JSON, **including when the matching hardware is absent** —
`/api/rfid/status` reports no reader rather than erroring, `/api/buttons/config`
returns the binding schema with nothing wired, and `/api/library/health` reports
the cache drive as absent if there's no USB cache. That is the expected "any
subset works" behavior, not a failure.

### Audio out the DAC

```bash
aplay -l                                  # should list card 'sndrpihifiberry'
speaker-test -D default -c 2 -t wav -l 1  # pink-noise/voice out both channels
```

Then drop a track in `~/Music` and scan it:

```bash
cp sometrack.flac ~/Music/
sudo mopidyctl local scan
```

It should now appear in the touchscreen library and play through the speakers.

### Kiosk + touchscreen

- The 1280×800 panel shows the Boombox UI (not a console or a black desktop).
- Touch registers — tap transport controls and the Settings drawer.
- From your laptop, `./pi shot` (see [DEVELOPMENT.md](./DEVELOPMENT.md)) pulls a
  Wayland screenshot to confirm what's on screen.

### Remote access

The installer printed a generated password (also at
`sudo cat /etc/boombox/web-auth.env`):

```text
Web UI:   http://<pi-ip>:8090/     user: boombox
SMB:      smb://<pi-ip>/boombox-music
Video:    http://<pi-ip>:8096/     (Jellyfin)
```

---

### Troubleshooting

| Symptom | Where to look / fix |
|---|---|
| **Screen dark from power-on (never shows a console)** | The KMS display stack is disabled — DietPi's default. Check `ls /sys/class/drm/` (empty ⇒ no DRM driver). Run `install/bin/dietpi-hardware-setup.sh` (or re-run `install.sh`) and reboot; it enables `dtoverlay=vc4-kms-v3d`, `display_auto_detect=1`, and `dtparam=i2c_arm=on` in `config.txt`. |
| **DietPi first-run loops "DietPi has not fully been installed"** | The automated first-run was interrupted (e.g. `dietpi-update` rebooted mid-way); DietPi's error handler then resets `AUTO_SETUP_AUTOMATED=0` and waits for an interactive session. Fix: `rm -f /tmp/.dietpi-login_firstrun_setup_err`, set `AUTO_SETUP_AUTOMATED=1` in `/boot/dietpi.txt` again, and re-run `/boot/dietpi/dietpi-login`. Done when `/boot/dietpi/.install_stage` reads `2`. |
| **No audio** | `aplay -l` — is `sndrpihifiberry` listed? If not, the overlay didn't bind: check `/boot/usercfg.txt` has `dtoverlay=hifiberry-dacplus` and `/boot/config.txt` includes `usercfg.txt`, try an alternate overlay from the comments in that file, reboot. If the card lists but is silent, `alsamixer` and unmute/raise. Verify `/etc/asound.conf` points `default` at `hw:sndrpihifiberry`. |
| **Kiosk black screen** | The compositor or Chromium didn't come up. `systemctl --user status boombox-kiosk` and `journalctl --user -u boombox-kiosk -n 100`. Confirm `labwc` launched: it execs from `~/.bash_profile` **only on the tty1 console login** — check the `>>> boombox session >>>` block is present in `~/.bash_profile` and that DietPi didn't override tty1 autologin. `boombox-kiosk-guard` should be re-pinning the tab to `http://localhost/`. |
| **A service won't start** | `journalctl --user -u boombox-<svc> -n 100 --no-pager` for user units; `journalctl -u <svc>` (no `--user`) for nginx/mopidy/smbd/jellyfin. Many `boombox-*` services need the desktop session's PipeWire/Wayland/`/dev/input`, so a service failing right after boot often just needs the graphical session up — re-check after the kiosk appears. |
| **`Failed to connect to bus`** over SSH | User-manager not reachable in your SSH env: `export XDG_RUNTIME_DIR=/run/user/$(id -u)`, or confirm linger: `loginctl show-user "$USER" | grep Linger`. |
| **RFID reader not detected** | It must enumerate as a USB HID keyboard under `/dev/input/by-id/*-event-kbd`, and your user must be in the `input` group (installer adds it; needs a reboot/re-login). `journalctl --user -u boombox-rfid`. See [RFID.md](./RFID.md). |
| **Buttons do nothing** | GPIO wiring + pin bindings. `journalctl --user -u boombox-buttons`, then bind pins from the touchscreen Settings drawer. See [BUTTONS.md](./BUTTONS.md). |
| **Wrong OS path taken** | `install/session/detect-os.sh` keys on the `/boot/dietpi` marker. Force with `BOOMBOX_OS=dietpi`. |
| **General state/logs** | Persistent state lives under `/opt/boombox/state`; the release tree is `/opt/boombox/current`. Service logs are in the journal (above), not flat files. |

---

## 6. Next steps

- **Enable the phone remote.** It's **off by default**. Flip it on from the
  touchscreen **Settings → Phone remote**, then scan the QR / redeem the PIN on
  your phone. Details and the security model are in [ACCESS.md](./ACCESS.md).
- **Point at home servers.** To stream from an external **Navidrome** music
  library and a **Jellyfin** video server so the boombox works away from its
  home network, follow **[HOME-SERVERS.md](./HOME-SERVERS.md)**. That covers
  aiming `boombox-library` at a remote Subsonic/Navidrome endpoint and the
  Jellyfin client at an external server.
- **Wire the optional hardware** whenever you're ready — buttons
  ([BUTTONS.md](./BUTTONS.md)), RFID ([RFID.md](./RFID.md)), USB drives
  ([ACCESS.md](./ACCESS.md)). Re-run `install/install.sh` after wiring if you
  want it to re-check group membership and configs; nothing needs a reinstall to
  start working.
- **Updates.** The device auto-checks GitHub hourly and installs stable releases
  in a nightly window. Manage the channel/window in **Settings → Updates**, or
  from a shell with `boombox-update` (see the [README](../README.md#updates)).

---

## Where DietPi differs from Raspberry Pi OS

For maintainers, the DietPi path is thinner than the RPi OS path in a few
places worth knowing:

- **The whole graphical session is synthesized.** RPi OS boots into the
  `rpd-labwc` desktop and the installer just *tweaks* it. DietPi has no
  compositor at all, so `install/session/dietpi.sh` installs labwc, wires tty1
  autologin, and launches the compositor from `~/.bash_profile`. If the kiosk
  misbehaves on DietPi, this file is the first place to look.
- **The display stack is off by default.** DietPi comments out
  `dtoverlay=vc4-kms-v3d` and omits `display_auto_detect` / `dtparam=i2c_arm`,
  so there is no DRM device and a DSI panel stays dark. `dietpi.sh` enables
  them in `config.txt`; `install/bin/dietpi-hardware-setup.sh` does the same
  standalone. RPi OS ships all of it enabled.
- **Boot partition path.** Newer DietPi images (v10+, Trixie) mount it at
  `/boot/firmware` like RPi OS Bookworm; older DietPi used `/boot`. The
  installer probes for `/boot/firmware` and falls back to `/boot`, so the DAC
  overlay lands correctly on both. (DietPi's own files — `dietpi.txt`, the
  `dietpi/` scripts — stay under `/boot` either way.)
- **First-boot config is DietPi's, not ours.** `dietpi.txt` / `dietpi-wifi.txt`
  are DietPi features; the repo carries no first-boot image automation (a
  pre-built SD image is still on the roadmap). Everything Boombox-specific
  happens in `install.sh`, after the OS is already reachable.
- **Autologin ownership.** Both DietPi (`dietpi-autostart`) and the installer
  can configure tty1 autologin; the installer's `getty@tty1` drop-in is the one
  that must win. Keep DietPi's autostart on plain console.
</content>
</invoke>
