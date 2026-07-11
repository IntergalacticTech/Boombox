# Home Servers — running Navidrome + Jellyfin off the boombox

The boombox streams music from a [Navidrome](https://www.navidrome.org/)
(Subsonic API) server and video from a [Jellyfin](https://jellyfin.org/)
server. Out of the box, **Jellyfin runs on the boombox device itself** and
Navidrome is assumed to be some box on your LAN. This guide moves both onto a
real "home server" and makes them reachable from **outside** your house, so the
boombox keeps working when it goes on a trip.

This packaging lives in [`servers/`](../servers/):

| File | What it is |
|---|---|
| [`docker-compose.yml`](../servers/docker-compose.yml) | Navidrome + Jellyfin services, volumes, healthchecks |
| [`.env.example`](../servers/.env.example) | Documented placeholders — copy to `.env` and edit |
| [`docker-compose.cloudflared.yml`](../servers/docker-compose.cloudflared.yml) | Optional Cloudflare Tunnel sidecar (one of two exposure options) |

---

## Why move them off the device

- **Jellyfin on-device is convenient but limited.** Today `install.sh`
  installs Jellyfin on the Pi against `~/Videos` (see [VIDEO.md](./VIDEO.md)).
  A Pi 5 software-transcodes 1080p at best and can't keep up with 4K/HDR.
  A real server (or a VPS with more CPU) transcodes comfortably and doesn't
  fight the audio stack for resources.
- **Navidrome as a random LAN box is fragile.** Moving it into this managed
  stack gives you healthchecks, restart policies, pinned versions, and a single
  place to back up.
- **Off-LAN access.** Once the servers live on a host you can expose safely,
  the boombox streams your library from anywhere — not just your home Wi-Fi.
  The boombox only ever needs **a reachable HTTPS URL + credentials** for each
  server; it does not care where the server physically runs.

> The boombox's **offline cache** still works regardless: pinned albums live on
> the USB cache drive and play with no server at all (see
> [HOME-LIBRARY.md](./HOME-LIBRARY.md)). Externalizing the servers is about the
> *streaming* and *browse* paths, not the offline path.

---

## Choose a host

All three run the exact same `docker-compose.yml`. Pick based on where you want
your media to physically live and who patches the box.

| Host | Good when | Trade-offs |
|---|---|---|
| **Docker on any always-on box** (NAS, mini-PC, old laptop) — *recommended* | You already have a machine at home that's on 24/7 | You own patching + backups; media stays in your house on your disks |
| **Native on a spare Raspberry Pi** | You have a second Pi and prefer no Docker | ARM transcoding is weak (same Pi limits as on-device); you manage two apt installs by hand |
| **Dedicated cloud VPS** | You want it reachable off-LAN with no home-network fiddling, or your home upload is too slow | Monthly cost; **your media leaves your house** — you upload it to the VPS and trust the provider; you patch the VM |

Recommendation: **Docker on a home box.** It's the most reproducible (this repo
ships the compose file), keeps your media on your own disks, and the Cloudflare
Tunnel option below gives you off-LAN access without exposing your home IP.

### Native on a Pi (no Docker)

If you skip Docker, install the servers from their official repos and point them
at your media:

```bash
# Navidrome (music) — download the release binary for your arch, then run it
# against a data dir + your music dir. See navidrome.org/docs.
# Jellyfin (video) — the SAME official installer install.sh already uses:
curl -fsSL https://repo.jellyfin.org/install-debuntu.sh | sudo bash
```

Everything else in this guide (exposure, pointing the boombox, backups) applies
unchanged — only "bring it up" differs. The rest of the doc assumes Docker.

---

## Bring it up (Docker)

```bash
cd servers
cp .env.example .env
$EDITOR .env          # set MUSIC_DIR, VIDEO_DIR, PUID/PGID, TZ, ports
docker compose up -d
docker compose ps     # both should show (healthy) within ~40 s
```

What `.env` controls (full list documented in
[`.env.example`](../servers/.env.example)):

| Var | Meaning |
|---|---|
| `MUSIC_DIR` | Host path to your music tree — bind-mounted read-only into Navidrome |
| `VIDEO_DIR` | Host path to your video tree — bind-mounted read-only into Jellyfin |
| `PUID` / `PGID` | Host user/group that owns the media (`id -u`, `id -g`) |
| `TZ` | IANA timezone for scan schedules + logs |
| `NAVIDROME_PORT` / `JELLYFIN_PORT` | Host ports (default `4533` / `8096`) |
| `JELLYFIN_PUBLISHED_URL` | Jellyfin's public origin, once exposed (else blank) |

**Where media mounts:** your `MUSIC_DIR` appears as `/music` inside Navidrome and
`VIDEO_DIR` as `/media` inside Jellyfin — both **read-only**, so the servers can
never mutate your library. Server *state* (databases, playlists, watch history,
metadata) lives in named Docker volumes (`navidrome-data`, `jellyfin-config`,
`jellyfin-cache`), independent of the media. Those volumes are what you back up.

### First-run admin setup

Neither server is seeded headlessly here — each has its own first-launch wizard.
Do this once, on the LAN, before you expose anything:

1. **Navidrome** — open `http://<host>:4533`. Create the admin user with a
   **strong, unique** password. The first scan of a 5–10k-album library takes a
   few minutes.
2. **Jellyfin** — open `http://<host>:8096`. Run the wizard: create the admin
   user (strong, unique password), add a **Movies** library pointed at `/media`
   (that's your `VIDEO_DIR` inside the container). Video files must be named
   `Title (Year).ext` for the Movies library to index them — see
   [VIDEO.md](./VIDEO.md#file-naming-requirements).

> The on-device installer normally scripts Jellyfin's wizard via
> [`boombox-jellyfin-setup.py`](../services/boombox-jellyfin-setup.py). When
> Jellyfin runs on a separate host you drive the wizard yourself in the browser
> instead — same result, one admin account.

---

## Expose it (your choice — pick ONE)

The boombox needs an **HTTPS URL it can reach + credentials**. How you provide
that is deliberately up to you. Both paths below give you TLS; **never expose
either server as raw HTTP** (see Security).

### Option A — Cloudflare Tunnel (no inbound ports)

`cloudflared` dials **out** to Cloudflare and holds the tunnel open, so you
expose the servers **without opening any port on your router** and without
revealing your home IP. Cloudflare terminates TLS at the edge.

1. In the **Cloudflare Zero Trust** dashboard → **Networks → Tunnels**, create a
   tunnel (type "Cloudflared") and copy its **token**.
2. Put the token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
3. On the tunnel, add two **Public Hostnames**:
   - `music.example.com` → Service `http://navidrome:4533`
   - `video.example.com` → Service `http://jellyfin:8096`
   (Use the Docker *service names* — the sidecar shares the compose network.)
4. Bring the stack up **with** the overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d
```

5. Set `JELLYFIN_PUBLISHED_URL=https://video.example.com` in `.env` and
   `docker compose up -d` again so Jellyfin emits correct links.
6. **Strongly recommended:** add a **Cloudflare Access** policy in front of each
   hostname (email OTP, or your identity provider). This puts a second auth gate
   in front of the servers' own logins. Note: native Jellyfin *apps* don't carry
   Access cookies, so if you gate `video.example.com` with Access you'll use
   service tokens or a bypass for the app path — keep the boombox's server URL on
   an Access policy that permits its credential. For most people, gating the
   music hostname with Access and relying on Jellyfin's own strong login for
   video is the pragmatic split.

### Option B — Router port-forward + reverse proxy + TLS

If you'd rather not depend on Cloudflare, forward a port to a reverse proxy on
the host that terminates Let's Encrypt TLS and proxies to the two containers.

1. Give the host a stable name. Static IP is ideal; otherwise use **DDNS**
   (your router's built-in dynamic-DNS, or a client like `ddclient`).
2. Run a reverse proxy on the host. **Caddy** is the least-effort — automatic
   Let's Encrypt. A minimal `Caddyfile`:

```caddyfile
music.example.com {
    reverse_proxy localhost:4533
}
video.example.com {
    reverse_proxy localhost:8096
}
```

3. Port-forward **443 → the proxy** (and 80 → proxy for the ACME challenge) on
   your router. Forward **only** the proxy's ports — never 4533/8096 directly.
4. Set `JELLYFIN_PUBLISHED_URL=https://video.example.com` in `.env` and re-up.
5. Add **rate-limiting** at the proxy (see Security). nginx works too if you
   prefer, with a certbot-managed cert.

Either way, the outcome is the same contract for the boombox: a reachable
`https://music.example.com` and `https://video.example.com` with working logins.

---

## Point the boombox at them

Two independent config surfaces on the device — one per server.

### Music → Navidrome (Subsonic)

Set it from the touchscreen: **Settings → Home Library** (or the LAN web UI).
Enter the values and tap **Test**, then **Save**:

| Field | Value |
|---|---|
| Source URL | `https://music.example.com` (HTTPS works — the client just appends `/rest/…`) |
| Username | Your Navidrome user |
| Password | Your Navidrome password |

Under the hood this writes `/etc/boombox/library.yml`
([`services/boombox_library/config.py`](../services/boombox_library/config.py)):
`source.url`, `source.username`, and `source.password_encrypted`. The password is
**Fernet-encrypted at rest**, keyed to the Pi's `/etc/machine-id` — moving the SD
card to another Pi makes it unreadable and forces re-entry. Auth to Navidrome uses
Subsonic's **token+salt** scheme (a fresh salt per call; the password is never put
in a URL) — see
[`services/boombox_library/subsonic.py`](../services/boombox_library/subsonic.py).

Nothing about the URL is LAN-locked: point it at a public HTTPS host and sync +
streaming work the same. The sync chip in the chrome goes green when it connects.

### Video → Jellyfin

The boombox talks to Jellyfin server-side through
[`services/jellyfin_client.py`](../services/jellyfin_client.py), which reads two
things:

| Setting | Where | Default |
|---|---|---|
| Base URL | `BOOMBOX_JELLYFIN_BASE` env | `http://127.0.0.1:8096` |
| API key | file at `BOOMBOX_JELLYFIN_KEY` (default `/etc/boombox/jellyfin-api-key`) | written by on-device setup |

To use an **off-device** Jellyfin:

1. Point the base URL at your server. Set `BOOMBOX_JELLYFIN_BASE` for the
   `boombox-remote` service — add it to `/etc/boombox/jellyfin.env` (already
   loaded by the unit) as:

   ```ini
   BOOMBOX_JELLYFIN_BASE=https://video.example.com
   ```

2. Provide an API key for that server. In the remote Jellyfin's
   **Dashboard → API Keys**, create a key and write it (single line) to
   `/etc/boombox/jellyfin-api-key` (mode `0640`, owned so the service can read
   it). This replaces the token the on-device setup script would have minted.

Every Jellyfin address in the boombox now resolves through
`BOOMBOX_JELLYFIN_BASE` — the transport proxy, the **WATCH** button's kiosk
navigation, and both library-refresh triggers (post-upload and USB-mount). Set
the one env var and the whole device — touchscreen included — points at your
server, local or remote. (Both `boombox-remote` and `boombox-buttons` load
`/etc/boombox/jellyfin.env`, so the value reaches every consumer.)

### Getting video onto the system

The address is flexible; where the **files** live is the choice you make. Two
models, and the boombox supports both:

| Model | Where video files live | How you add video | Refresh-on-upload |
|---|---|---|---|
| **Co-located** | A directory the Jellyfin server reads that the boombox can also write to — the on-device `~/Videos`, or a network share/mount the device mounts | Upload through the touchscreen/remote **Settings → Upload**, or drop a USB stick | Works — the boombox's auto-refresh nudges the configured server |
| **Server-managed** | On the server host only (its own disk / the Docker `VIDEO_DIR`) | Add media directly on the server (copy to `VIDEO_DIR`, or a Jellyfin-side uploader) | N/A — the server watches its own dir; the boombox is play-only |

The simplest off-home setup is **co-located via a share**: put your video on the
server, and if you also want the device's upload button to work, mount that same
directory on the boombox (e.g. an NFS/SMB mount) and set `BOOMBOX_VIDEO_DIR` to
it. If you don't need device-side uploads, **server-managed** is the least
moving parts — the boombox just plays what the server has.

---

## Security (read this — non-negotiable)

Exposing a media server to the internet is the higher-risk path in this whole
project. Do it deliberately.

- **Never expose either server without TLS + authentication + rate-limiting.**
  Both exposure options above give you TLS; Jellyfin and Navidrome each bring
  their own login; you must add rate-limiting yourself (Cloudflare does it at the
  edge; on a reverse proxy, configure it — e.g. Caddy's `rate_limit` or nginx
  `limit_req`).
- **Use strong, unique passwords — do NOT reuse the boombox's credential.** The
  boombox's own LAN surface has a documented weakness: a **weak, reused 6-digit
  credential and no rate-limiting** (see
  [ACCESS.md → Security posture](./ACCESS.md#security-posture)). That is fine for
  a friction gate on a trusted LAN; it is **not** acceptable on an
  internet-facing server. Give Navidrome and Jellyfin their own long random
  passwords.
- **Keep the servers patched.** Pin image versions in `docker-compose.yml`
  (this repo does), then bump them on a schedule and re-`up`. Watch Jellyfin and
  Navidrome release notes for security fixes. On a VPS, patch the OS too.
- **Prefer a mesh VPN or Cloudflare Access if you're unsure.** Publishing a media
  server on the open internet is strictly riskier than not exposing it at all. A
  **mesh VPN** (Tailscale / WireGuard) puts the boombox and the servers on one
  private network with no public surface — often the best answer for a single
  appliance you control. If you do go public, put **Cloudflare Access** (or
  equivalent SSO) in front so a login gate stands ahead of the app itself.
- **The boombox transmits credentials to these servers — TLS protects them.**
  Navidrome auth is token+salt (password not sent in the clear), but Jellyfin
  uses an API key and native apps send passwords; without TLS those are exposed.
  This is exactly why raw HTTP exposure is banned above.

Rule of thumb: **mesh VPN > public + Cloudflare Access > public + reverse-proxy
with rate-limiting > raw port-forward (never).**

---

## Backups

A host rebuild must not lose playlists or watch state. The **media** you can
re-copy; the **server state** you cannot. Back up the named volumes (and your
`.env`):

| Back up | What's in it |
|---|---|
| `navidrome-data` volume | Navidrome SQLite DB — users, playlists, stars/favorites, play counts |
| `jellyfin-config` volume | Jellyfin DB + config — users, libraries, **watch history / resume points**, API keys |
| `jellyfin-cache` volume | Regenerable (thumbnails, transcodes) — **skip** to save space |
| `servers/.env` | Your host paths, ports, and the tunnel token — store securely, not in git |

Quick tar snapshot of the two that matter:

```bash
cd servers
docker compose stop            # quiesce for a consistent DB snapshot
docker run --rm \
  -v navidrome-data:/nd -v jellyfin-config:/jf \
  -v "$PWD":/backup alpine \
  tar czf /backup/boombox-servers-backup.tgz -C / nd jf
docker compose start
```

Restore is the reverse: create the volumes, untar into them, `up -d`. Because
media is bind-mounted from `MUSIC_DIR` / `VIDEO_DIR` (not in a volume), point
those at the same host paths on the new box and the libraries reattach.

---

## Related docs

- [HOME-LIBRARY.md](./HOME-LIBRARY.md) — how the boombox syncs + caches from
  Navidrome (the offline path that keeps working with no server).
- [VIDEO.md](./VIDEO.md) — Jellyfin on the device today, file-naming rules,
  native apps, transcoding limits.
- [ACCESS.md](./ACCESS.md) — the boombox's own LAN remote surface and its
  (deliberately un-hardened) security posture.
- [ARCHITECTURE.md](./ARCHITECTURE.md) — how the pieces fit together on-device.
