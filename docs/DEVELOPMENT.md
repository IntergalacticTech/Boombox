# Development

How to work on the boombox from a Mac (or any other dev machine) without
having to constantly SSH in.

---

## One-time setup

### 1. SSH alias for the Pi

Add to `~/.ssh/config`:

```
Host boombox
  HostName 10.0.5.178       # or boombox.local / your DHCP-assigned IP
  User jwc
```

Verify: `ssh boombox` should drop you into a shell.

### 2. `pi` helper on your PATH (optional)

The `pi` script at the repo root is the only thing you need to control the
boombox from your laptop. Either run it as `./pi <cmd>` from the repo, or
symlink it onto your PATH:

```bash
ln -s "$PWD/pi" ~/bin/boombox
boombox status
```

Env vars it understands:

| Variable | Default | What it does |
|----------|---------|--------------|
| `BOOMBOX_HOST` | `boombox` | The SSH alias (or `user@host`) |
| `BOOMBOX_DEBUG_PORT` | `9222` | DevTools port on the Pi |
| `BOOMBOX_SHOTS_DIR` | `<repo>/screenshots` | Where `./pi shot` saves to |
| `KIOSK_URL` | `http://localhost/` | Default URL for `./pi goto` / `./pi restart-kiosk` |

---

## Dev loops

### Editing the UI

The cleanest loop runs Vite on your laptop with the Mopidy WebSocket
proxied to the Pi. Live boombox state, hot reload, no SSH round-trip.

```bash
cd ui
npm install
npm run dev          # http://localhost:5173
```

Point the Vite proxy at your Pi's nginx server:

```bash
BOOMBOX_DEV_TARGET=http://10.0.5.178:8090 BOOMBOX_WEB_USER=boombox BOOMBOX_WEB_PASSWORD=123456 npm run dev
```

The dev server proxies `/mopidy`, `/api`, and `/audio` through that target and
injects the Basic auth header from `BOOMBOX_WEB_USER` / `BOOMBOX_WEB_PASSWORD`,
so Mopidy RPC, boombox-state endpoints, and the visualizer WebSocket all work
from the laptop browser. Read the real password with
`./pi ssh "sudo cat /etc/boombox/web-auth.env"`.

When you're happy, push to the Pi:

```bash
cd ui && npm run build
# /var/www/boombox is owned by www-data, so a plain `./pi deploy` rsync
# fails. Stage to /tmp then sudo-rsync into place:
../pi deploy ui/dist/ /tmp/boombox-dist/
../pi ssh "sudo rsync -a --delete /tmp/boombox-dist/ /var/www/boombox/ && \
          sudo chown -R www-data:www-data /var/www/boombox"
../pi reload      # soft reload — usually enough
# Hard reload (bypasses the SPA's service-worker cache):
../pi restart-kiosk
# Or, from inside DevTools at http://localhost:9222, call Page.reload
# with {ignoreCache: true}.
```

`boombox-update` on the Pi does both steps (rsync as root, restart kiosk)
in one shot if your change is committed and pushed — prefer it for anything
beyond a quick spot-check.

### Editing a Python service

The Python services run as user systemd units; the easiest loop is:

```bash
./pi deploy services/ /opt/boombox/services/
./pi ssh "systemctl --user restart boombox-state"
./pi logs mopidy      # or: ssh boombox 'journalctl --user -u boombox-state -f'
```

For something more interactive, stop the service and run the script in the
foreground:

```bash
./pi ssh "systemctl --user stop boombox-state"
./pi ssh "/opt/boombox/.venv/bin/python /opt/boombox/services/boombox-state.py"
```

Re-enable the service when you're done.

### Editing a skin

See [SKINS.md](./SKINS.md). The cycle is: edit `ui/src/skins/<id>/...tsx`,
verify in the dev server, build, deploy, reload.

---

## The `pi` helper, in detail

```
./pi ssh [cmd]                   open shell or run a command on the Pi
./pi run <cmd>                   alias for ssh
./pi deploy <local> <remote>     rsync a path to the Pi (deletes orphans!)
./pi shot [name]                 Wayland screenshot → ./screenshots/
./pi reload                      reload current kiosk tab via DevTools
./pi goto <url>                  navigate the kiosk to a URL
./pi browse [args...]            connect agent-browser to the kiosk
./pi tunnel                      open SSH tunnel to DevTools (:9222)
./pi kill-tunnel                 tear it down
./pi guard [pause|resume|status] toggle the kiosk auto-recover watchdog
./pi restart-kiosk [url]         relaunch Chromium with debug flags
./pi restart-mopidy
./pi logs [mopidy|chrome|nginx]
./pi status                      services + now-playing summary
```

### When to pause the kiosk guard

`boombox-kiosk-guard` fights you if you `./pi goto` somewhere off-localhost:
its 15-second poll will snap the tab back. Two ways around it:

```bash
./pi guard pause      # for the duration of a dev session
# … hack on stuff …
./pi guard resume
```

Or accept the fight and resync deliberately:

```bash
./pi goto http://localhost/?skin=retro80
# the guard sees localhost, so it leaves you alone
```

### Screenshotting

`./pi shot` saves a Wayland-native PNG of the current display to
`./screenshots/`. The repo `.gitignore` excludes that folder so screenshots
don't pile up in git.

For a sequence of debug shots:

```bash
./pi shot before
./pi reload
sleep 2
./pi shot after
```

---

## Common dev tasks

### Forcing a fresh install on the Pi

If something has drifted past the point of `boombox-update`:

```bash
./pi ssh "rm -rf /opt/boombox && \
          sudo git clone https://github.com/IntergalacticTech/Boombox.git /opt/boombox && \
          sudo chown -R \$USER:\$USER /opt/boombox && \
          /opt/boombox/install/install.sh && \
          sudo reboot"
```

### Trying out a feature branch

```bash
./pi ssh "cd /opt/boombox && git fetch && git checkout my-feature-branch && \
          /opt/boombox/install/update.sh --force"
```

### Resetting the Mopidy library scan

```bash
./pi ssh "sudo rm -rf /var/lib/mopidy/local && \
          sudo systemctl restart mopidy && \
          sudo mopidyctl local scan"
```

### Looking at a service's log without SSH

```bash
./pi ssh "journalctl --user -u boombox-state -n 200 --no-pager"
```

### Verifying the visualizer WebSocket

```bash
# From the Pi
curl 127.0.0.1:6682/health
# Should print: {"ok": true, "clients": N}
```

---

## Repo conventions

- **Don't commit `ui/dist/` or `ui/node_modules/`.** `.gitignore` handles
  this. The Pi builds the SPA in place; we never ship `dist/` as an
  artifact.
- **Python services target Python 3.11+** (RPi OS Bookworm/Trixie ship
  3.11 / 3.12). Don't reach for typing features newer than that.
- **Configs live in `install/config/` as templates.** If you change one,
  also bump `update.sh` if a special restart is required after the new
  config lands.
- **systemd units in `install/systemd/user/`** assume `/opt/boombox`. If
  you check out elsewhere, you're on your own for unit paths.
- **No secret values in the repo.** Spotify / Last.fm / etc. credentials
  belong in `/etc/mopidy/extensions.d/*.conf` on the Pi, not in
  `install/config/mopidy.conf`.

---

## Troubleshooting the dev loop itself

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `./pi reload` says "no devtools page found" | Kiosk Chromium isn't running, or wasn't launched with `--remote-debugging-port=9222` | `./pi restart-kiosk` |
| `./pi reload` ran but the SPA still shows old code | `./pi reload` is a soft reload — the service worker can hand back cached JS. Run `location.reload(true)` from DevTools or `./pi restart-kiosk` to force-fetch. | DevTools or restart |
| `./pi deploy ui/dist /var/www/boombox/` fails with `permission denied` | `/var/www/boombox` is `www-data`-owned; plain rsync over SSH runs as you. | Stage to `/tmp/boombox-dist/` then `./pi ssh "sudo rsync -a --delete /tmp/boombox-dist/ /var/www/boombox/ && sudo chown -R www-data:www-data /var/www/boombox"` |
| `./pi shot` prints nothing | `grim` not installed, or you're not in the Wayland session | `./pi ssh "which grim"` |
| Vite dev server loads but Mopidy is offline | `vite.config.ts` proxy points at the wrong IP | Update `target:` to your Pi |
| `boombox-update` says "local changes present" | Someone edited a file directly on the Pi | `./pi ssh "cd /opt/boombox && git status"`, decide if you want to keep, then `boombox-update --force` |
| Visualizer bars stay flat | `parec` lost the default sink | `./pi ssh "systemctl --user restart boombox-audio"` |
