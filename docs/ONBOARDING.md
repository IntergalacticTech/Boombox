# Onboarding — Boombox remote dev

You're picking up dev on the Boombox. This doc gets you from zero to "I can
edit the UI / a Python service, see it on the Pi, and ship a PR" in about
20 minutes.

Already familiar with the day-to-day commands? Skip to
[DEVELOPMENT.md](./DEVELOPMENT.md). Looking for the system-level picture?
[ARCHITECTURE.md](./ARCHITECTURE.md).

---

## What you need on your laptop

- **macOS or Linux** (the dev helper is bash; tested on macOS arm64.)
- **Node 20+** and **npm** — for the UI (`ui/`).
- **Python 3.11+** — only needed if you want to lint/typecheck Python
  locally; everything actually *runs* on the Pi.
- **rsync** (preinstalled on macOS).
- **A working SSH key** (`~/.ssh/id_ed25519.pub` or similar). If you don't
  have one yet: `ssh-keygen -t ed25519`.

## Network access — same LAN

Right now access is **LAN-only**. You have to be on the same Wi-Fi as the
Pi to reach it. (There's no VPN, no public hostname, no port-forward.) If
you're remote, you need either to be on the project owner's network or
ask the owner to add Tailscale / Cloudflare Tunnel — both are tracked in
the roadmap but aren't set up yet.

### Find the Pi on the LAN

```bash
# Option 1: ask the maintainer for the current IP.
# Option 2: mDNS — works on most Macs and modern Linux:
ping boombox1.local
# Option 3: scan the subnet
nmap -sn 192.168.1.0/24 | grep -i boombox -B 2
```

Confirm: `ping <pi-ip>` should respond.

## Get your SSH key onto the Pi

You'll log in as the existing `jwc` user (the boombox is a single-user
appliance for now; per-developer accounts aren't set up). The maintainer
needs to append your public key to `/home/jwc/.ssh/authorized_keys`.

Send your public key to the maintainer:

```bash
cat ~/.ssh/id_ed25519.pub
# paste the one line they print
```

They'll run (on the Pi):

```bash
echo "<your-key-line>" >> ~/.ssh/authorized_keys
```

Once that's done, `ssh jwc@<pi-ip>` should work without a password.

## SSH config alias

The `./pi` dev helper assumes there's a `boombox` SSH alias. Add this to
`~/.ssh/config`:

```
Host boombox
  HostName 10.0.5.178            # <- your pi's LAN IP
  User jwc
  IdentityFile ~/.ssh/id_ed25519
  ServerAliveInterval 30
```

Test it:

```bash
ssh boombox        # drops you into the Pi
exit
```

## Clone the repo and configure local env

```bash
git clone git@github.com:IntergalacticTech/Boombox.git
cd Boombox
cp .env.example .env
```

Edit `.env` — at minimum set:

- `BOOMBOX_HOST` — your SSH alias from above (`boombox`)
- `BOOMBOX_DEV_TARGET` — `http://<pi-ip>:8090` (authenticated LAN nginx)
- `BOOMBOX_WEB_USER` / `BOOMBOX_WEB_PASSWORD` — generated on the Pi by
  `install.sh`; read with `./pi ssh "sudo cat /etc/boombox/web-auth.env"`

`.env` is gitignored. The `./pi` helper and `ui/vite.config.ts` both
auto-load it; you don't have to `export` anything.

Sanity check:

```bash
./pi status
```

You should see service health and "now playing" output. If you do, you're
wired up correctly.

## Read these next

- **[DEVELOPMENT.md](./DEVELOPMENT.md)** — daily commands, `./pi` reference, troubleshooting.
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — what the boombox actually is.
- **[SERVICES.md](./SERVICES.md)** — per-daemon reference for the seven `boombox-*` services.
- **[ACCESS.md](./ACCESS.md)** — the web-remote / upload mode + USB story.
- **[SKINS.md](./SKINS.md)** — how to add a new touchscreen skin.

## The shortest possible dev loop

### Editing the UI

```bash
cd ui
npm install
npm run dev          # http://localhost:5173 with live Pi state
```

The Vite proxy forwards `/mopidy`, `/api`, and `/audio` straight to the
Pi's nginx (target from `BOOMBOX_DEV_TARGET` in `.env`, with Basic auth
injected by Vite), so the page sees the same routes the kiosk does.

Ship it:

```bash
cd ui && npm run build
../pi deploy ui/dist/ /opt/boombox/current/ui/dist/
../pi reload
```

(That's a quick spot-check straight into the live release tree — the next
`boombox-update` replaces it. Commit + push for anything you want to keep.)

### Editing a Python service

```bash
./pi deploy services/ /opt/boombox/services/
./pi ssh "systemctl --user restart boombox-state"
./pi ssh "journalctl --user -u boombox-state -f"
```

Or commit + push to `main` and run `boombox-update` on the Pi — same
effect, with a paper trail.

### Touchscreen screenshots into your repo

```bash
./pi shot before
# … make a change, deploy …
./pi shot after
```

Files land in `./screenshots/` (gitignored, attach them to PRs as needed).

### Don't fight the kiosk guard

`boombox-kiosk-guard` snaps Chromium back to `http://localhost/` every
15 s. When you want to drive it elsewhere via `./pi goto <url>`:

```bash
./pi guard pause     # …work…   ./pi guard resume
```

## Where to push code

- Branch from `main` (no protected-branch enforcement yet — just don't
  force-push or rewrite history on `main`).
- PRs against `IntergalacticTech/Boombox`.
- Commit message style: imperative, scoped (`feat(uploader): ...`,
  `fix(udev): ...`). See `git log --oneline` for examples.
- Keep commits small enough that a revert wouldn't hurt.

## What you do NOT need to set up

- Don't run the boombox services on your laptop. They depend on PipeWire,
  Wayland, BlueZ, a real DAC, and GPIO. Run them on the Pi.
- Don't reproduce the full kiosk Chromium. Use `npm run dev` in your
  normal browser — same routes, same data, faster reload.
- Don't install Mopidy locally. The Vite proxy gives you live Pi data.

## Trouble

| Symptom | Fix |
|---|---|
| `./pi ssh` times out | You're not on the same Wi-Fi as the Pi. |
| `./pi ssh` says "Permission denied (publickey)" | Your key isn't in `/home/jwc/.ssh/authorized_keys`. Ask the maintainer. |
| `npm run dev` loads the page but Mopidy is offline | `.env` has the wrong `BOOMBOX_DEV_TARGET` or web password. Try `curl -u "$BOOMBOX_WEB_USER:$BOOMBOX_WEB_PASSWORD" "$BOOMBOX_DEV_TARGET/mopidy/rpc"` and check you can reach nginx. |
| `./pi reload` says "no devtools page found" | The kiosk Chromium isn't running, or was started without `--remote-debugging-port=9222`. Run `./pi restart-kiosk`. |
| You hand-deployed a `dist/` to the Pi and it vanished after an update | `boombox-update` installs a fresh `releases/<ref>/` checkout and re-points `current` — hand-deployed files are left on the old release. Commit + push, then `boombox-update install <ref>`. |
| The page on the kiosk doesn't show your build | You deployed `dist/` but Chromium has a stale hash. `./pi reload` (or just wait — index.html is `no-cache`, JS is hash-named so it refetches on rebuild). |
