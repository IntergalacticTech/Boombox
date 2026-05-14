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
# nginx serves the SPA straight from the active release's build directory,
# /opt/boombox/current/ui/dist/. /opt/boombox is owned by the install user,
# so a plain `./pi deploy` rsync works — no sudo, no staging dance:
../pi deploy ui/dist/ /opt/boombox/current/ui/dist/
../pi reload      # soft reload — usually enough
# Hard reload (bypasses the SPA's service-worker cache):
../pi restart-kiosk
# Or, from inside DevTools at http://localhost:9222, call Page.reload
# with {ignoreCache: true}.
```

This drops a build straight into the live release tree — handy for a quick
spot-check, but the next `boombox-update` will replace `current` with a fresh
release checkout and your hand-deployed `dist/` goes with it. For anything you
want to keep, commit and push, then let `boombox-update` install it properly.

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

`boombox-update install` takes any git ref — a tag, a branch name, or a sha —
so installing a feature branch is just:

```bash
./pi ssh "boombox-update install my-feature-branch"
```

It clones that ref into a fresh `releases/<ref>/`, builds it, and swaps
`current` to it (with `previous` left pointing at where you were). To get back,
`./pi ssh "boombox-update rollback"`.

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
- **Configs live in `install/config/` as templates.** `install.sh` installs
  them; a release install reruns the installer and then restarts the
  `boombox-*` units and reloads nginx, so a changed template takes effect on
  the next update.
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
| `./pi deploy ui/dist/ /opt/boombox/current/ui/dist/` fails with `no such file or directory` | `/opt/boombox/current` is a symlink to the active release; it only exists once `install.sh` has run | `./pi ssh "ls -l /opt/boombox/current"` to confirm the layout migrated |
| `./pi shot` prints nothing | `grim` not installed, or you're not in the Wayland session | `./pi ssh "which grim"` |
| Vite dev server loads but Mopidy is offline | `vite.config.ts` proxy points at the wrong IP | Update `target:` to your Pi |
| Hand-deployed UI build vanished after an update | `boombox-update` installs a fresh `releases/<ref>/` checkout and re-points `current` — anything you rsync'd into the old `current/ui/dist/` is left behind on the previous release | Commit + push your change, then `boombox-update install <ref>` so it lands in a real release |
| Visualizer bars stay flat | `parec` lost the default sink | `./pi ssh "systemctl --user restart boombox-audio"` |
