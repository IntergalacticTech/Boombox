# Accounts page — design

Date: 2026-09-29 · Status: draft for review · Branch: `feat/accounts-page`

## Goal

A permanent **Accounts** page in the boombox's LAN web UI where the owner can
add, change and check every service account the boombox uses — without the
first-run wizard, the kiosk, or SSH. Success looks like: from a phone or laptop
on the home network, open `http://<boombox>:8090/accounts/`, and in one place
see each service's live status and fix it; in particular, pointing the boombox
at a remote Jellyfin also signs the kiosk in, so WATCH just works.

### What the owner asked for
- Location: a persistent page on the LAN web UI (not the phone remote, not the
  kiosk, not only the wizard).
- Scope v1: **Music server**, **Video server + kiosk sign-in**, **Streaming
  receivers** (AirPlay, Spotify Connect), **Boombox web login**.
- Jellyfin sign-in: pick a Jellyfin user from a list; the boombox signs the
  kiosk in via Quick Connect — no Jellyfin password typed or stored.

### Assumptions (from the codebase, open to correction)
- LAN users already authenticate to `:8090` with nginx Basic auth
  (`/etc/nginx/boombox.htpasswd`); that is the admin gate.
- One music server and one video server per boombox (as today).
- Installing Spotify Connect (raspotify) is out of scope; the page manages it
  only when it is installed.

### Non-goals
Multiple servers per type; access from outside the LAN; installing packages
from the web; BLE command authentication; signed updates (tracked separately).

## Architecture (approach A)

Grow the existing first-run pieces instead of adding a new app/service:

```
phone/laptop ──:8090 (Basic auth)──▶ nginx ──▶ /accounts/      setup-ui build, 2nd entry
                                            └▶ /api/accounts/* boombox-setup :6689
kiosk ──:80 (loopback, no auth)────▶ nginx ──▶ /api/accounts/* → 403 (never allowed)

boombox-setup ──loopback──▶ boombox-library (music), jellyfin_env (video)
              ──sudo──────▶ boombox-setup-apply (root helper, new narrow actions)
              ──CDP 9222──▶ kiosk Chromium (Jellyfin session injection)
```

- **setup-ui** gets a second entry point, `/accounts/` (Vite multi-page build,
  same package, same `dist/`). The wizard's Music and Video steps are refactored
  into shared *cards* used by both the wizard and the Accounts page, so there is
  one form per service.
- **boombox-setup** gains an `/api/accounts/*` route group in a new module
  `services/boombox_setup/accounts.py`, registered by `build_app`. It reuses the
  existing Context proxies (`music_get/test/save`, `apply`, `restart_units`).
- **boombox-setup-apply** (root helper) gains narrowly-validated actions for
  anything needing root: `streaming` and `web_password`. Existing `jellyfin`
  action is extended to write the pinned device id.

### Auth for `/api/accounts/*`
The wizard's token/code scheme is **not** used here. Instead:
1. nginx: a `location /api/accounts/` block that does **not** turn Basic auth
   off (so on `:8090` it inherits `auth_basic`), and forwards
   `X-Real-IP $remote_addr` and `X-Boombox-User $remote_user`
   (`proxy_set_header` overwrites any client-supplied header of that name).
2. Service middleware accepts a request only if `X-Boombox-User` is non-empty
   **and** the client IP is not loopback. The kiosk (loopback, no Basic auth)
   is therefore always refused — a web page open in the kiosk can never change
   credentials.
3. CSRF (the browser caches Basic credentials): mutating requests require
   `Content-Type: application/json` (forces a CORS preflight the service never
   approves) **and** an `Origin`/`Host` match.
4. Secrets are **write-only**: GET responses carry `configured: true/false`,
   never passwords, API keys or tokens; logs never contain them.

## The page

A single scrolling page of four cards. Each card shows a status pill
(**Connected** / **Problem: <reason>** / **Not set up** / **Not installed**),
a **Test** button, and an **Edit** form that saves only on explicit Save.

### 1. Music server (Navidrome / Subsonic)
- Fields: URL, username, password (blank = keep current).
- Test → existing `music_test`; Save → existing `music_save` (writes
  `library.yml` 0600 and triggers a sync).
- Status from `/api/library/health`: reachable, last sync time, track count,
  `prune_deferred` warning if set.
- Hint shown: "use a dedicated, non-admin Navidrome user for this boombox".

### 2. Video server + kiosk sign-in (Jellyfin)
- Server: mode `builtin` | `remote`; for remote: base URL + API key (blank =
  keep). Test → `GET {base}/System/Info` with the key. Save → helper
  `jellyfin` action (writes `/etc/boombox/jellyfin.env`, restarts consumers).
- **Kiosk sign-in** (shown once the server tests OK):
  - `GET /api/accounts/video/users` lists the server's users (name, id, admin
    flag) using the API key.
  - Owner picks a user → `POST /api/accounts/video/kiosk-signin {user_id}`:
    1. boombox-setup calls `POST {base}/QuickConnect/Initiate` itself, with an
       `Authorization: MediaBrowser Client="Jellyfin Web", Device="<Name> kiosk",
       DeviceId="<BOOMBOX_ID>-kiosk", Version="<boombox version>"` header → `{Secret, Code}`.
    2. `POST {base}/QuickConnect/Authorize?code=…&userId=…` with the API key.
    3. `POST {base}/Users/AuthenticateWithQuickConnect {Secret}` → `AccessToken`.
    4. Inject into the kiosk over CDP: open `{base}/web/` in the kiosk tab, set
       `localStorage._deviceId2 = "<BOOMBOX_ID>-kiosk"` and
       `localStorage.jellyfin_credentials` (server entry with `Id`,
       `ManualAddress`, `UserId`, `AccessToken`), then return the tab to
       `http://localhost/`.
    5. Helper writes `BOOMBOX_JELLYFIN_DEVICE_ID=<BOOMBOX_ID>-kiosk` to
       `jellyfin.env`; restart boombox-remote.
  - A **stable, boombox-chosen DeviceId** replaces today's browser-random one,
    so phone-remote pinning survives a Chromium profile reset and is set
    automatically.
  - Status: "Kiosk signed in as <user>" by matching `/Sessions` /
    `/Devices` for our DeviceId; **Sign out** revokes that device
    (`DELETE /Devices?id=`) and clears the kiosk's localStorage.
  - If Quick Connect is disabled on the server: clear error with the fix
    ("enable Quick Connect in Jellyfin Dashboard → General").
  - Builtin mode keeps today's behaviour (bootstrapper-created admin); no user
    picker needed.

### 3. Streaming receivers
- **AirPlay** (shairport-sync): device name, optional password (set / clear).
  Helper locates the config (`/etc/shairport-sync.conf` or
  `/usr/local/etc/shairport-sync.conf` — DietPi's build uses the latter, which
  the current rename code misses) and restarts the unit.
- **Spotify Connect** (raspotify/librespot): device name; card shows
  **Not installed** when the unit is absent (hardware/optional rule).
- Status: unit active + advertised name.
- Default names follow the boombox name; editing here overrides per service.

### 4. Boombox web login
- Change the `:8090` login password: current password + new password (×2).
- Policy: ≥ 10 characters (replaces the 6-digit code); strength hint.
- Helper `web_password` action atomically updates `boombox.htpasswd`
  (bcrypt), Samba (`smbpasswd`), `web-auth.env`, and — builtin Jellyfin only —
  the bootstrapped Jellyfin admin password. Partial failure rolls back the
  steps already applied and reports which one failed.
- The page warns that the browser will ask for the new password immediately.

## Data flow & files

| Change | Where |
|---|---|
| Routes, auth middleware, card logic | `services/boombox_setup/accounts.py` (new), `api.py` registers it |
| Jellyfin QC sign-in + CDP injection | `services/boombox_setup/jellyfin_signin.py` (new; pure HTTP helpers + a small CDP client) |
| Root actions `streaming`, `web_password`; `jellyfin` gains device id | `install/bin/boombox-setup-apply` |
| nginx `/api/accounts/` + `/accounts/` blocks | `install/config/nginx-boombox-common.conf` |
| UI entry + shared cards | `setup-ui/accounts.html`, `setup-ui/src/accounts/*`, `setup-ui/src/cards/*`; wizard steps reuse cards |
| Link from kiosk Settings and README | small |

## Error handling
- Every outbound call has a timeout (connect 5 s, total 15 s; QC flow 30 s)
  and maps failures to a card-level reason string; no 500s for upstream errors.
- Saves are validate → test → write; a failed test never overwrites working
  config unless the owner explicitly chooses "Save anyway".
- Helper actions are idempotent, validate every field (control chars, quotes,
  lengths) and write atomically with explicit modes.
- CDP injection failure (kiosk not running) leaves credentials unsaved and says
  "kiosk not reachable — try again when the screen is on"; the Jellyfin device
  created in step 1–3 is revoked.

## Testing
- pytest: auth middleware matrix (LAN+user ok; loopback refused; missing user
  refused; wrong content-type/origin refused), each card's GET redaction,
  save/test paths with fake upstreams, Jellyfin QC flow against a fake server
  (initiate/authorize/authenticate/devices), helper validation + atomic writes
  (shairport path detection, htpasswd/smbpasswd rollback with stubs).
- vitest: each card's states (not set up / connected / problem / not
  installed), write-only secret fields, error rendering; wizard still passes.
- On-device (MarkII, via CDP screenshots): full Accounts page walk-through,
  kiosk Jellyfin sign-in via user picker, WATCH opens signed in, phone-remote
  video control targets the kiosk, AirPlay rename visible, password change
  with re-login.

## Out of scope / follow-ups noticed
- DietPi's shairport-sync build outputs to ALSA directly while PipeWire holds
  the DAC — AirPlay audio may fail on MarkII; investigate separately.
- The TAPE//SHIFT skin has no library entry while a queue exists.
