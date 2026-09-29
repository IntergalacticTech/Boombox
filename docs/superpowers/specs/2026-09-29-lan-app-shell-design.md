# LAN app — sub-project 1: app shell, remote control, admin gate

Date: 2026-09-29 · Status: draft for review · Branch: `feat/lan-app`

## Context and goal

The owner wants one web app, served by the boombox on the LAN, that works well
on a **phone and a desktop** and lets people use it as a remote control and
manage the boombox — "everything". Today `http://<boombox>:8090/` serves the
kiosk UI (built for an 800×480 touchscreen); a separate phone PWA lives at
`/remote/` (PIN-paired: Now playing, Library, Playlists, Search, Files); the
Accounts page lives at `/accounts/` behind browser Basic auth.

The whole vision is decomposed into four sub-projects, each with its own spec
→ plan → build:

1. **This spec — app shell + remote control + admin gate** (below).
2. Storage & video: onboard music cache/pins/uploads/free space; video
   downloads from the homelab, video uploads from phone/PC, a play-next watch
   queue on the kiosk.
3. Remotes: pair/unpair CYDs and phones; RFID card bindings.
4. Settings: everything in the kiosk drawer (buttons, skins, sleep/power,
   updates, Wi-Fi, name).

Later sub-projects add sections to the app shell built here.

### What the owner decided
- Build it by **growing the existing `/remote/` app** (approach A).
- **Two tiers:** anyone on the home Wi-Fi who pairs once (PIN on the kiosk)
  can play, queue, browse and search; **admin** sections additionally need
  the boombox web password.
- "Queue videos to load on local storage" means all three of: download from
  the homelab, upload from phone/PC, and a play-next queue — all in
  sub-project 2.

### Success criteria
- On a phone, `http://markii.local:8090/` opens a touch-friendly app; on a
  desktop the same URL shows a sidebar layout with a persistent Now Playing
  / queue panel — no pinch-zoom, no horizontal scrolling at any width
  ≥ 320 px.
- A paired phone can browse and play the owner's 43k-track Home Library
  (Navidrome) and browse the remote Jellyfin and start an episode on the
  kiosk screen, then pause/seek/stop it.
- The Accounts cards work inside the app at desktop width, unlocked with the
  web password (no browser Basic-auth pop-up), and never from the kiosk.

### Non-goals (this sub-project)
Storage/video downloads/uploads/watch queue, remotes & RFID management,
settings — sub-projects 2–4. Changing the kiosk UI. Internet (off-LAN) access.

## Architecture

```
phone / desktop ──:8090──▶ nginx
   /                 → remote-ui build (the LAN app; no Basic auth — pairing gates APIs)
   /remote/, /accounts/ → 301 to / (and /#/accounts)
   /api/remote/*     → boombox-remote :6685   (pair token)  ← + Home Library + Video routes
   /api/accounts/*   → boombox-setup :6689    (admin session) ← Basic auth removed
kiosk ──:80 (loopback)──▶ unchanged kiosk UI at /
```

### nginx
- The kiosk SPA's `location /` moves out of the shared snippet into the
  **loopback** server block; the **LAN** server block gets its own
  `location /` serving `remote-ui/dist` (SPA fallback to `index.html`,
  `auth_basic off`). Everything else on :8090 keeps Basic auth as today.
- `remote-ui` builds with `base: "/"` and a distinct `assetsDir`
  (`app-assets`) so it never collides with the kiosk's `/assets/`.
- `/remote` and `/remote/*` → 301 `/`; `/accounts` and `/accounts/*` → 301
  `/#/accounts`.
- `/api/accounts/` switches to `auth_basic off` (the service now enforces the
  admin session) and keeps forwarding `X-Real-IP`.
- The site file (`/etc/nginx/sites-available/boombox`) is only written by
  `install.sh`; `apply-release.sh swap` gains a narrowly-scoped sudo
  install of the rendered site file, mirroring the existing snippet rule, so
  OTA updates can carry it. First deploy on MarkII does it once by hand.

### Auth
**Household tier (unchanged):** remote-ui's existing PIN pairing →
bearer token stored in the browser; every `/api/remote/*` route checks it
(as today). Requires remote access enabled (as today).

**Admin tier (new, in boombox-setup):**
- `POST /api/accounts/session {password}` → verifies against
  `BOOMBOX_WEB_PASSWORD` in `/etc/boombox/web-auth.env` (bytes,
  constant-time) → `{token, expires_at}`. Tokens are random 32-byte,
  kept in memory (a service restart = log in again), **12 h idle
  expiry**, refreshed on use. `DELETE /api/accounts/session` logs out.
- **Lockout:** 5 failed attempts within 5 minutes → all logins refused
  for 5 minutes (global, not per-IP — the LAN is small); every attempt
  logged (IP + outcome, never the password).
- `check_auth` for all other `/api/accounts/*` routes: valid admin bearer
  token AND non-loopback `X-Real-IP` (missing header = loopback = refused);
  mutations still require JSON + same-origin (`Origin` vs `X-Boombox-Host`).
  `X-Boombox-User` is no longer used.
- The login endpoint itself is also refused from loopback, so the kiosk can
  never obtain an admin session.

## The app

### Layout
- **Phone (< 900 px):** bottom tab bar (Now, Music, Video, Search, More),
  mini-player above it; "More" holds Playlists, Files, and the admin
  sections.
- **Desktop (≥ 900 px):** left sidebar (all sections + Admin), centre
  content, right **Now Playing + queue** panel (always visible). Music and
  Video grids use as many columns as fit (min tile 160 px).
- Hash routes (`#/now`, `#/music`, `#/video`, `#/search`, `#/playlists`,
  `#/files`, `#/accounts`) so browser back/forward and links work; no
  router dependency needed beyond a tiny hash hook.
- Visual language: the existing remote-ui theme; Accounts cards re-skinned
  to match.

### Sections
- **Now playing, Playlists, Search, Files:** existing screens, made
  responsive (desktop: wider layouts, keyboard-friendly search box).
- **Music:** existing Mopidy library browse **plus Home Library** (Artists,
  Albums, Playlists → drilldown → play / play-all / queue), via new
  token-checked routes (below). Cover art via the library art proxy.
- **Video:** Jellyfin browse — libraries, **Continue watching**, Movies grid,
  Series → Seasons → Episodes, search; poster images proxied. Item detail →
  **Play on the boombox**. While video plays: title, position/duration,
  play/pause, seek (±30 s and scrubber), stop, audio & subtitle track
  pickers, volume.
- **Admin** (locked until the password is entered; lock icon shows state):
  **Accounts** — the four cards from the Accounts page, laid out in a
  2-column grid on desktop. Sub-projects 2–4 add their sections here.

## New backend routes (boombox-remote, pair-token checked)

Home Library (proxy to boombox-library on 127.0.0.1:6687; responses passed
through unchanged except as noted):
- `GET /api/remote/home/browse?type=artists|albums|playlists`
- `GET /api/remote/home/search?q=`
- `GET /api/remote/home/{artist|album|playlist}/{id}`
- `POST /api/remote/home/play {ids:[track ids], mode:"play"|"queue"}` →
  resolves via `POST /api/library/resolve`, drops `offline_miss`, then plays
  or appends through the existing Mopidy queue path (first track first, rest
  in background chunks, as the kiosk does).
- `GET /api/remote/home/art/{art_id}?size=` → library art proxy.

Video (uses the stored Jellyfin base + API key server-side; the key never
reaches the client; the browsing user is the Jellyfin user the kiosk is
signed in as — from the pinned device; if none, `{"error":"kiosk not signed
in"}`):
- `GET /api/remote/video/views` — the user's libraries.
- `GET /api/remote/video/resume` — continue watching.
- `GET /api/remote/video/items?parent_id=&type=&search=&start=&limit=` —
  paged items (id, name, type, year, runtime, series/season/episode numbers,
  has_image, played/progress).
- `GET /api/remote/video/image/{item_id}?max_width=` — proxied poster
  (cached on disk, like cover art).
- `POST /api/remote/video/play {item_id, start_ticks?}` — if no pinned kiosk
  session is active, navigate the kiosk to Jellyfin (existing WATCH action),
  wait up to 20 s for the pinned session, then `PlayNow`. Errors: kiosk not
  signed in / session never appeared / Jellyfin unreachable → clear message.
- Existing `GET /api/remote/video/state` gains `audio_streams`,
  `subtitle_streams`, current indexes; existing `POST
  /api/remote/video/command` gains `seek {seconds}`, `set_audio {index}`,
  `set_subtitle {index|-1}`.

## Error handling
- Every card/section degrades to a message with a Retry button: Jellyfin not
  configured, kiosk not signed in, library service down, pairing revoked
  (→ back to pairing screen), admin session expired (→ lock screen).
- Upstream failures map to 502 JSON, never 500; proxies have 15 s timeouts
  (video play 30 s).
- Old installed PWAs at `/remote/` get redirected; the app shows a one-time
  "reinstall from this address" hint when launched from the old start URL.

## Testing
- Python: admin session (login ok/bad/lockout/expiry/logout, loopback
  refused, token required on every accounts route); Home Library and Video
  routes (token required, API key never in responses, upstream errors →
  502, play flow with fake kiosk/Jellyfin).
- UI (vitest + jsdom, viewport mocked): phone vs desktop layout switch, hash
  routing, admin lock/unlock/expiry, Music Home drilldown + play, Video
  browse → play → controls, error states.
- nginx: static tests for the LAN `location /`, redirects, `/api/accounts/`
  auth off; `nginx -t` on the device.
- On MarkII: screenshots at phone (390×844) and desktop (1440×900) widths;
  play a Home Library album from the phone; play an episode on the kiosk
  from the phone and pause/seek/stop it; unlock Admin and use an Accounts
  card; confirm the kiosk can't reach `/api/accounts/session`.
