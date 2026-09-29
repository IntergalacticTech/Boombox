# LAN App Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One web app at `http://<boombox>:8090/` that works on a phone and a desktop: the paired household can play, queue, browse (Mopidy + the Navidrome Home Library) and start/steer Jellyfin video on the kiosk, and the owner can unlock an Admin → Accounts section with the web password (no Basic-auth pop-up, never from the kiosk).

**Architecture:** Grow the existing `remote-ui` PWA (approach A). nginx's LAN server block gets its own `location /` serving `remote-ui/dist` (`base: "/"`, bundles under `/app-assets/`), while the kiosk's `location /` moves from the shared snippet into the loopback server block; `/remote/*` and `/accounts/*` redirect into the app. `boombox-remote` (pair-token gated) gains Home Library pass-through routes (`remote_home.py`) and Jellyfin browse/poster/play routes (`remote_video.py`), plus richer video state/commands in `jellyfin_client.py`. `boombox-setup` swaps nginx Basic auth for an in-memory admin session (`admin_session.py`) on `/api/accounts/*`. The four Accounts cards move from `setup-ui` into `remote-ui/src/admin/`. OTA releases keep nginx consistent through a new root-helper action `nginx-sync` that installs the rendered site file and snippet together.

**Tech Stack:** Python 3.11+ (aiohttp, pytest + pytest-aiohttp), stdlib-only root helper, bash (`apply-release.sh`), nginx, React 19 + TypeScript + Vite 8 + Vitest 4 + vite-plugin-pwa (`remote-ui`), `setup-ui` (same stack, touched only to remove the old Accounts entry).

**Spec:** `docs/superpowers/specs/2026-09-29-lan-app-shell-design.md`

## Global Constraints

- Branch `feat/lan-app` (already checked out); never switch branches.
- LAN app URL `http://<boombox>:8090/` (the port is `BOOMBOX_WEB_PORT` from `/etc/boombox/web-auth.env`, default `8090`); the kiosk keeps `http://localhost/` on the loopback `:80` server, unchanged.
- nginx LAN server: `location /` serves `/opt/boombox/current/remote-ui/dist` with SPA fallback to `index.html` and `auth_basic off`; everything else on `:8090` keeps Basic auth as today.
- `remote-ui` builds with `base: "/"` and `assetsDir: "app-assets"` (never collides with the kiosk's `/assets/`).
- Redirects: `/remote` and `/remote/*` → 301 `/` (this plan sends `/?from=remote`, see Task 5); `/accounts` and `/accounts/*` → 301 `/#/accounts`.
- `/api/accounts/` → `auth_basic off`, keeps forwarding `X-Real-IP` (and `X-Boombox-Host`); `X-Boombox-User` is no longer sent or read; `Authorization` is passed through (it now carries the admin token).
- Services: `boombox-remote` `127.0.0.1:6685` (`/api/remote/*`, pair token), `boombox-setup` `127.0.0.1:6689` (`/api/accounts/*`, admin session), `boombox-library` `127.0.0.1:6687` (Home Library upstream).
- Household tier unchanged: PIN pairing → bearer token in the browser; every `/api/remote/*` route checks it (`require_auth`) and requires remote access enabled (`require_remote_enabled`).
- Admin login: `POST /api/accounts/session {password}` verifies against `BOOMBOX_WEB_PASSWORD` in `/etc/boombox/web-auth.env` (UTF-8 bytes, constant-time) → `{token, expires_at}`; token = random 32 bytes (64 hex chars), in memory only (service restart = log in again), **12 h idle expiry**, refreshed on use; `DELETE /api/accounts/session` logs out.
- Lockout: **5 failed attempts within 5 minutes → all logins refused for 5 minutes** (global, not per-IP); every attempt logged with IP + outcome, never the password.
- Every other `/api/accounts/*` route: valid admin bearer token **and** non-loopback `X-Real-IP` (`127.0.0.1`, `::1`, `localhost`; missing header = loopback = refused). Mutations need `Content-Type: application/json` and, if `Origin` is present, its host:port must equal `X-Boombox-Host`.
- The login endpoint is refused from loopback too: **the kiosk can never obtain an admin session**.
- Jellyfin: the stored API key is used server-side only (`X-Emby-Token`); it never appears in a response body, a client-visible URL, or a log line. Browsing user = `LastUserId` of the pinned kiosk device (`BOOMBOX_JELLYFIN_DEVICE_ID`, via `GET /Devices/Info?id=`); none → `{"ok": false, "error": "kiosk not signed in"}`.
- Timeouts: upstream proxies **15 s**; video play **30 s** overall; kiosk-session wait after the WATCH navigation **20 s**.
- Upstream failures map to **502 JSON**, never 500. Not configured → 503, kiosk not signed in → 409, session never appeared → 504, all with `{"ok": false, "error": "<human message>"}`.
- Layout: phone **< 900 px** = bottom tabs **Now, Music, Video, Search, More** with the mini-player above them (More holds Playlists, Files, Admin → Accounts, Settings); desktop **≥ 900 px** = left sidebar (all sections + Admin) + centre content + right **Now Playing + queue** panel (always visible). Music/Video grids: as many columns as fit, **min tile 160 px**. No horizontal scrolling at any width **≥ 320 px**.
- Hash routes `#/now`, `#/music`, `#/video`, `#/search`, `#/playlists`, `#/files`, `#/accounts` (plus `#/more`, the phone More tab); sub-paths for drill-downs (`#/music/home/album/<id>`, `#/video/lib/<id>/<type>`, `#/video/folder/<id>`); no router dependency.
- Every section degrades to a message with a Retry button: Jellyfin not configured, kiosk not signed in, library service down, pairing revoked (→ "no longer paired" → pairing screen), admin session expired (→ lock screen).
- Old installed PWAs at `/remote/` are redirected; the app shows a one-time "reinstall from this address" hint when launched from the old start URL.
- Hardware-optional rule: absent services/hardware (no Jellyfin, no library, no kiosk CDP, no Mopidy) degrade to a message, never a 500 or a crash.
- Python: `.venv/bin/python -m pytest -q services/tests`, `~/.local/bin/ruff check services`, `~/.local/bin/mypy` **and** explicit mypy on touched `services/boombox_setup` files (`~/.local/bin/mypy services/boombox_setup/admin_session.py services/boombox_setup/accounts.py services/boombox_setup/api.py` — the repo config's `files` omits that package) and on new single-file services with `--follow-imports=silent`.
- UI: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`; also `cd setup-ui && npx tsc -b && npx vitest run && npm run build` when setup-ui is touched (Task 9). The kiosk `ui/` is not touched (spec non-goal).
- Deploy: build every UI on the Mac, never on the Pi; deploy to MarkII only when it is < 65 °C and not within 2 minutes of `:38` (hourly library sync).
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Kiosk-origin admin access** — `POST /api/accounts/session` with `X-Real-IP: 127.0.0.1`, `::1` or no header must be 403 even with the right password, and a valid token presented from loopback must still be 403. (Task 1 `test_login_refused_from_loopback_even_with_right_password`, `test_accounts_refuses_loopback_even_with_token`.)
2. **Wrong-password bursts** — the 5th failure inside 5 minutes locks logins; during the lock even the correct password gets 429 with `retry_after`; after 5 minutes it works again; failures older than 5 minutes don't count. (Task 1 `test_lockout_refuses_correct_password_until_window_passes`, `test_old_failures_age_out`.)
3. **Home Library play with partial/total offline tracks and long lists** — `offline_miss` rows are dropped and reported as `skipped`; all-offline → 409 with a clear message (no Mopidy call); library down → 502; a 200-track album starts the first track at once and queues the rest in the background, and a new play cancels the old tail. (Task 2 `test_play_drops_offline_miss_and_reports_skipped`, `test_play_all_offline_is_409_and_never_touches_mopidy`, `test_long_play_queues_tail_in_background_and_new_play_cancels_it`.)
4. **"Play on the boombox" while the kiosk shows the music UI / is signed out** — no live remote-controllable kiosk session → navigate the kiosk (WATCH), wait ≤ 20 s for the pinned session, then `PlayNow`; never appears → 504 message; kiosk not signed in → 409 without navigating; a stale session without a live remote-control socket is not trusted. (Task 4 `test_play_wakes_kiosk_and_waits_for_session`, `test_play_session_never_appears_is_504`, `test_play_ignores_session_without_remote_control`, `test_play_not_signed_in_is_409_and_does_not_wake`.)
5. **Returning users with the old `/remote/` PWA, and the new service worker's reach** — an installed old PWA gets a kill-switch `sw.js` at `/remote/sw.js` that unregisters itself and sends the tab to `/?from=remote`; the new root-scoped service worker must never answer navigations to `/setup/`, `/api/`, `/remote`, `/accounts`, `/mopidy/`, `/local/`, `/audio/` with the app shell (the setup wizard would break). (Task 5 `test_old_pwa_service_worker_gets_kill_switch`, Task 6 `test_service_worker_never_hijacks_other_paths`, Task 10 `test_legacy_remote_sw_unregisters_itself` + `MovedHint` tests.)

---

## File Structure

| File | Responsibility |
|---|---|
| `services/boombox_setup/admin_session.py` (create) | `AdminSessions` (issue/verify/revoke, 12 h idle, global lockout), `password_matches`, `read_web_password`. |
| `services/boombox_setup/accounts.py` (modify) | `check_auth` = non-loopback + admin bearer token (+ JSON/Origin for writes); `POST`/`DELETE /api/accounts/session`; `ADMIN_KEY`. |
| `services/boombox_setup/api.py` (modify) | `Context` protocol gains `web_password()`; docstring. |
| `services/boombox-setup.py` (modify) | `ServiceContext.web_password()` reads `web-auth.env` fresh. |
| `services/tests/test_admin_session.py` (create), `services/tests/test_accounts_api.py` (modify) | Session unit tests; accounts tests migrate from `X-Boombox-User` to admin tokens + login/lockout/expiry/logout/loopback tests. |
| `services/remote_home.py` (create) | `/api/remote/home/*` pass-through to boombox-library + `HomePlayer` (resolve → play/append via `boombox_rfid.mopidy_client`). |
| `services/remote_video.py` (create) | `JellyfinBrowser` (kiosk user, views, resume, items, poster cache, kiosk session, play) + `/api/remote/video/{views,resume,items,image,play}`. |
| `services/jellyfin_client.py` (modify) | State gains `item_id`, `audio_streams`, `subtitle_streams`, `audio_index`, `subtitle_index`; commands gain `set_audio`, `set_subtitle`; value validation; 15 s timeouts. |
| `services/boombox-remote.py` (modify) | `main()` wires `remote_home` and `remote_video` (with the WATCH wake callback). |
| `services/tests/test_remote_home.py`, `test_remote_video_browse.py`, `test_remote_video_play.py` (create); `test_jellyfin_client.py`, `test_remote_video.py` (modify) | Backend route tests with fake library / Jellyfin servers. |
| `install/config/nginx.conf` (modify) | Kiosk `root` + `location /` + asset regex in the loopback block; LAN block serves the app, `/app-assets/`, redirects, `/remote/sw.js` kill-switch. |
| `install/config/nginx-boombox-common.conf` (modify) | Drops `root`/`index`/`location /`/asset regex and `/remote/` + `/accounts/` blocks; `/api/accounts/` → `auth_basic off`, no user header, no Authorization stripping. |
| `install/bin/boombox-setup-apply` (modify) | New `nginx-sync` action: render site (port from root-owned `web-auth.env`) + snippet, install together, `nginx -t`, restore both on failure. |
| `install/apply-release.sh` (modify) | `nginx_sync()` via the helper in `swap` and `revert`; `verify` probes the LAN app instead of `/remote/`. |
| `install/sudoers/boombox` (modify) | Remove the snippet-only `install` grant (would desync the pair). |
| `services/tests/test_nginx_lan_app.py`, `test_setup_helper_nginx.py`, `test_apply_release_nginx.py` (create); `test_nginx_accounts.py` (delete) | Static nginx/sudoers/script tests + helper action tests. |
| `remote-ui/vite.config.ts`, `remote-ui/index.html` (modify) | `base: "/"`, `assetsDir: "app-assets"`, root-scoped manifest, SW navigate-fallback denylist. |
| `remote-ui/src/lib/route.ts`, `useIsDesktop.ts` (create) | Hash router hook + 900 px breakpoint hook. |
| `remote-ui/src/lib/api.ts` (modify) | `onUnauthorized` callback, optional `getBlob`, `apiErrorMessage`. |
| `remote-ui/src/components/{AppShell,Sidebar,NowPanel,SectionMessage,AuthedImg,MovedHint}.tsx`, `grid.ts` (create); `TabBar.tsx` (rewrite) | Responsive shell, desktop sidebar + Now panel, error/retry message, token-authed images, moved-app hint, tile grid. |
| `remote-ui/src/screens/{More,Music,HomeLibrary,Video}.tsx`, `components/VideoControls.tsx`, `lib/homeLibrary.ts`, `lib/video.ts` (create); `Search.tsx`, `Pairing.tsx`, `App.tsx` (modify) | Sections. |
| `remote-ui/src/admin/{session.ts,LockScreen.tsx,AccountsSection.tsx,ui.tsx}`, `admin/forms/*`, `admin/accounts/*` (create / moved from setup-ui) | Admin lock + Accounts cards. |
| `remote-ui/public/legacy-remote-sw.js` (create) | Kill-switch service worker served at `/remote/sw.js`. |
| `remote-ui/src/test/setup.ts` (modify), `src/test/viewport.ts` (create) | Phone viewport default, `sessionStorage` stub, `setViewport()`. |
| `services/tests/test_remote_ui_config.py` (create) | Static checks of the Vite/PWA config and the kill-switch SW. |
| `setup-ui/accounts.html`, `setup-ui/src/accounts/{AccountsApp,api,main}.tsx` (delete); `setup-ui/vite.config.ts` (modify) | Old Accounts page entry removed (cards moved). |
| `docs/SERVICES.md`, `docs/ACCESS.md`, `docs/HOME-SERVERS.md`, `docs/ARCHITECTURE.md`, `README.md` (modify) | New URLs, routes, auth. |

---

### Task 1: Admin session + accounts auth switch (boombox-setup)

**Files:**
- Create: `services/boombox_setup/admin_session.py`
- Modify: `services/boombox_setup/accounts.py` (module docstring + imports + `check_auth`, lines 1–53; new handlers before `add_routes`; `add_routes` lines 456–470)
- Modify: `services/boombox_setup/api.py` (`Context` protocol, lines 41–64)
- Modify: `services/boombox-setup.py` (constants ~line 43; `ServiceContext`, after `jellyfin_env` ~line 127)
- Test: `services/tests/test_admin_session.py` (create), `services/tests/test_accounts_api.py` (modify lines 1–11, 27, 55, 66–75, 78–88; append new tests)

**Interfaces:**
- Produces (Python, `boombox_setup.admin_session`):
  - `IDLE_TTL_S = 43200`, `LOCKOUT_ATTEMPTS = 5`, `LOCKOUT_WINDOW_S = 300`, `LOCKOUT_S = 300`
  - `password_matches(supplied: object, expected: str) -> bool`
  - `read_web_password(path: pathlib.Path) -> str | None`
  - `class AdminSessions(clock: Callable[[], float] = time.time)`: `issue() -> tuple[str, float]` (token, expires_at epoch s), `verify(token: str) -> bool` (refreshes), `revoke(token: str) -> None`, `record_failure() -> bool` (True = this failure started a lockout), `locked_for() -> float` (seconds left, 0 when open)
- Produces (`boombox_setup.accounts`): `ADMIN_KEY = "admin"` (app key holding the `AdminSessions`), `SESSION_PATH = "/api/accounts/session"`, `check_auth(req) -> web.Response | None`.
- Produces (HTTP, via nginx `/api/accounts/`):
  - `POST /api/accounts/session` body `{"password": str}` → 200 `{"ok": true, "token": "<64 hex>", "expires_at": <float epoch s>}` | 401 `{"ok": false, "error": "wrong password"}` | 429 `{"ok": false, "error": "too many wrong passwords — try again later", "retry_after": <int s>}` | 503 `{"ok": false, "error": "no web password is set on this boombox"}` | 403 from loopback | 415 non-JSON | 400 non-object body
  - `DELETE /api/accounts/session` (JSON body `{}`, `Authorization: Bearer <token>`) → 200 `{"ok": true}` (idempotent)
  - Every other `/api/accounts/*`: 403 `{"error": "accounts can only be changed from another device"}` from loopback/missing `X-Real-IP`; 401 `{"error": "admin session required"}` without a live token; otherwise unchanged behaviour.
- Consumes: `Context.web_password() -> str | None` (new; `ServiceContext` reads `BOOMBOX_WEB_AUTH_ENV`, default `/etc/boombox/web-auth.env`, fresh on every call).

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_admin_session.py`:

```python
"""AdminSessions: token lifetime + global lockout; web password parsing."""
from __future__ import annotations

import pytest
from boombox_setup import admin_session as a
from boombox_setup.admin_session import AdminSessions


class Clock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_issue_and_verify_refreshes_idle_timer():
    clock = Clock()
    s = AdminSessions(clock=clock)
    token, expires_at = s.issue()
    assert len(token) == 64 and expires_at == clock.t + a.IDLE_TTL_S
    clock.t += a.IDLE_TTL_S - 1
    assert s.verify(token)            # used just before expiry → refreshed
    clock.t += a.IDLE_TTL_S - 1
    assert s.verify(token)
    clock.t += a.IDLE_TTL_S
    assert not s.verify(token)        # 12 h idle → gone
    assert not s.verify(token)


def test_verify_rejects_unknown_and_empty():
    s = AdminSessions(clock=Clock())
    s.issue()
    assert not s.verify("")
    assert not s.verify("0" * 64)


def test_revoke():
    s = AdminSessions(clock=Clock())
    token, _ = s.issue()
    s.revoke(token)
    assert not s.verify(token)
    s.revoke("never-issued")          # no error


def test_lockout_after_five_failures_within_window():
    clock = Clock()
    s = AdminSessions(clock=clock)
    for _ in range(4):
        assert s.record_failure() is False
        clock.t += 10
    assert s.locked_for() == 0
    assert s.record_failure() is True
    assert s.locked_for() == a.LOCKOUT_S
    clock.t += a.LOCKOUT_S - 1
    assert s.locked_for() == 1
    clock.t += 1
    assert s.locked_for() == 0


def test_old_failures_age_out():
    clock = Clock()
    s = AdminSessions(clock=clock)
    for _ in range(4):
        s.record_failure()
    clock.t += a.LOCKOUT_WINDOW_S     # the four are now 5 minutes old
    assert s.record_failure() is False
    assert s.locked_for() == 0


@pytest.mark.parametrize("supplied,expected,ok", [
    ("correct horse", "correct horse", True),
    ("correct horsE", "correct horse", False),
    ("pässwörd", "pässwörd", True),   # non-ASCII must not raise
    ("", "", False),                  # an unset password never matches
    (None, "x", False),
    (123, "123", False),
])
def test_password_matches(supplied, expected, ok):
    assert a.password_matches(supplied, expected) is ok


def test_read_web_password(tmp_path):
    env = tmp_path / "web-auth.env"
    assert a.read_web_password(env) is None
    env.write_text("BOOMBOX_WEB_PORT=8090\nBOOMBOX_WEB_USER=boombox\n"
                   "BOOMBOX_WEB_PASSWORD= s3cret=with=equals \n")
    assert a.read_web_password(env) == "s3cret=with=equals"
    env.write_text("BOOMBOX_WEB_PASSWORD=\n")
    assert a.read_web_password(env) is None
```

In `services/tests/test_accounts_api.py`, replace lines 1–11 (docstring, imports, `LAN`) with:

```python
"""/api/accounts/* — admin-session gate and card endpoints."""
from __future__ import annotations

import logging

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from boombox_setup.accounts import ADMIN_KEY
from boombox_setup.admin_session import IDLE_TTL_S, LOCKOUT_S, AdminSessions
from boombox_setup.api import build_app

WEB_PASSWORD = "correct horse battery"
LAN_NO_TOKEN = {"X-Real-IP": "192.168.1.50", "X-Boombox-Host": "192.168.1.81:8090"}
# The `client` fixture adds a fresh admin "Authorization: Bearer …" per test.
LAN: dict[str, str] = dict(LAN_NO_TOKEN)
```

In `FakeAccountsContext.__init__`, after `self._http_session: aiohttp.ClientSession | None = None` (line 27), add:

```python
        self.web_pw: str | None = WEB_PASSWORD
```

and after `def jellyfin_env(self): return dict(self.jf_env)` (line 55) add:

```python
    def web_password(self): return self.web_pw
```

Replace the `client` fixture (lines 66–75) with:

```python
@pytest.fixture
async def client(ctx):
    app = build_app(ctx)
    token, _ = app[ADMIN_KEY].issue()
    LAN.clear()
    LAN.update(LAN_NO_TOKEN, Authorization=f"Bearer {token}")
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c
    await c.close()
    if ctx._http_session is not None:
        await ctx._http_session.close()
```

Replace `test_accounts_requires_basic_auth_user` and `test_accounts_refuses_loopback_even_with_user` (lines 78–88) with:

```python
async def test_accounts_requires_admin_token(client):
    r = await client.get("/api/accounts/summary", headers=LAN_NO_TOKEN)
    assert r.status == 401
    assert (await r.json())["error"] == "admin session required"
    r = await client.get("/api/accounts/summary",
                         headers={**LAN_NO_TOKEN, "X-Boombox-User": "boombox"})
    assert r.status == 401            # the old Basic-auth user header opens nothing


async def test_accounts_refuses_loopback_even_with_token(client):
    r = await client.get("/api/accounts/summary", headers={**LAN, "X-Real-IP": "127.0.0.1"})
    assert r.status == 403
    no_ip = {k: v for k, v in LAN.items() if k != "X-Real-IP"}
    r = await client.get("/api/accounts/summary", headers=no_ip)
    assert r.status == 403            # no X-Real-IP = direct on-box call
```

Append to the end of `services/tests/test_accounts_api.py`:

```python
# ---- admin session ---------------------------------------------------------

async def _login(c, password, headers=None):
    return await c.post("/api/accounts/session", json={"password": password},
                        headers=LAN_NO_TOKEN if headers is None else headers)


async def _client_with_clock(ctx, clock):
    app = build_app(ctx)
    app[ADMIN_KEY] = AdminSessions(clock=lambda: clock[0])
    c = TestClient(TestServer(app))
    await c.start_server()
    return app, c


async def test_login_ok_returns_token_that_opens_accounts(client):
    r = await _login(client, WEB_PASSWORD)
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True and len(body["token"]) == 64 and body["expires_at"] > 0
    r = await client.get("/api/accounts/summary",
                         headers={**LAN_NO_TOKEN, "Authorization": f"Bearer {body['token']}"})
    assert r.status == 200


async def test_login_wrong_password_is_401_and_logged_without_the_password(client, caplog):
    with caplog.at_level(logging.INFO, logger="boombox-setup.accounts"):
        r = await _login(client, "hunter2-wrong")
        ok = await _login(client, WEB_PASSWORD)
    assert r.status == 401 and (await r.json())["error"] == "wrong password"
    assert ok.status == 200
    assert "hunter2-wrong" not in caplog.text and WEB_PASSWORD not in caplog.text
    assert "admin login from 192.168.1.50: wrong password" in caplog.text
    assert "admin login from 192.168.1.50: ok" in caplog.text


async def test_login_refused_from_loopback_even_with_right_password(client):
    for headers in ({"X-Real-IP": "127.0.0.1"}, {"X-Real-IP": "::1"},
                    {"X-Real-IP": "localhost"}, {}):
        r = await _login(client, WEB_PASSWORD, headers=headers)
        assert r.status == 403, headers


async def test_login_needs_json_and_same_origin(client):
    r = await client.post("/api/accounts/session", data="password=x", headers=LAN_NO_TOKEN)
    assert r.status == 415
    r = await client.post("/api/accounts/session", json={"password": WEB_PASSWORD},
                          headers={**LAN_NO_TOKEN, "Origin": "http://evil.example"})
    assert r.status == 403
    r = await client.post("/api/accounts/session", json=["x"], headers=LAN_NO_TOKEN)
    assert r.status == 400


async def test_login_without_web_password_is_503(client, ctx):
    ctx.web_pw = None
    r = await _login(client, "anything")
    assert r.status == 503


async def test_lockout_refuses_correct_password_until_window_passes(ctx):
    clock = [1_000_000.0]
    _app, c = await _client_with_clock(ctx, clock)
    try:
        for _ in range(5):
            assert (await _login(c, "nope")).status == 401
            clock[0] += 5
        # Failures at t0, t0+5 … t0+20; the 5th locks until t0+320; now t0+25.
        r = await _login(c, WEB_PASSWORD)
        assert r.status == 429
        assert (await r.json())["retry_after"] == LOCKOUT_S - 5
        clock[0] += LOCKOUT_S - 10                               # t0+315: 5 s to go
        assert (await _login(c, WEB_PASSWORD)).status == 429
        clock[0] += 5                                            # t0+320: open again
        assert (await _login(c, WEB_PASSWORD)).status == 200
    finally:
        await c.close()


async def test_admin_token_expires_after_12h_idle(ctx):
    clock = [1_000_000.0]
    app, c = await _client_with_clock(ctx, clock)
    try:
        token, _ = app[ADMIN_KEY].issue()
        hdr = {**LAN_NO_TOKEN, "Authorization": f"Bearer {token}"}
        assert (await c.get("/api/accounts/summary", headers=hdr)).status == 200
        clock[0] += IDLE_TTL_S - 1
        assert (await c.get("/api/accounts/summary", headers=hdr)).status == 200
        clock[0] += IDLE_TTL_S
        assert (await c.get("/api/accounts/summary", headers=hdr)).status == 401
    finally:
        await c.close()


async def test_logout_revokes_token(client):
    r = await client.delete("/api/accounts/session", json={}, headers=LAN)
    assert r.status == 200 and (await r.json()) == {"ok": True}
    assert (await client.get("/api/accounts/summary", headers=LAN)).status == 401
    r = await client.delete("/api/accounts/session", json={}, headers=LAN)
    assert r.status == 200            # idempotent


async def test_every_accounts_route_requires_admin_token(ctx):
    app = build_app(ctx)
    routes = sorted({(r.method, r.resource.canonical) for r in app.router.routes()
                     if r.resource is not None
                     and r.resource.canonical.startswith("/api/accounts/")
                     and r.resource.canonical != "/api/accounts/session"
                     and r.method != "HEAD"})
    assert len(routes) >= 13
    c = TestClient(TestServer(app))
    await c.start_server()
    try:
        for method, path in routes:
            r = await c.request(method, path, json={}, headers=LAN_NO_TOKEN)
            assert r.status == 401, (method, path)
    finally:
        await c.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_admin_session.py services/tests/test_accounts_api.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'boombox_setup.admin_session'` (collection error in both files).

- [ ] **Step 3: Implement**

Create `services/boombox_setup/admin_session.py`:

```python
"""Admin session for the LAN app's Admin sections (/api/accounts/*).

The boombox web password (BOOMBOX_WEB_PASSWORD in /etc/boombox/web-auth.env)
unlocks an in-memory bearer token: 32 random bytes as hex, 12 h idle expiry
refreshed on every use, gone when boombox-setup restarts. Tokens are kept
only as SHA-256 digests and never logged.

Lockout: LOCKOUT_ATTEMPTS failed logins within LOCKOUT_WINDOW_S refuse ALL
logins — the right password included — for LOCKOUT_S. Global, not per-IP:
the LAN is small and a per-IP limit is trivially sidestepped on it.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path
from typing import Callable

IDLE_TTL_S = 12 * 3600
LOCKOUT_ATTEMPTS = 5
LOCKOUT_WINDOW_S = 5 * 60
LOCKOUT_S = 5 * 60


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_matches(supplied: object, expected: str) -> bool:
    """Constant-time compare of UTF-8 bytes (compare_digest on str raises for
    non-ASCII). An empty stored password never matches anything."""
    if not isinstance(supplied, str) or not expected:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def read_web_password(path: Path) -> str | None:
    """BOOMBOX_WEB_PASSWORD from web-auth.env, read fresh on every call (the
    Accounts page can rotate it at runtime; the unit's EnvironmentFile copy
    goes stale), or None when unreadable/unset. Same parsing as the root
    helper: strip the line, split on the first '=', strip the value."""
    try:
        text = path.read_text()
    except (OSError, ValueError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("BOOMBOX_WEB_PASSWORD="):
            return line.split("=", 1)[1].strip() or None
    return None


class AdminSessions:
    """Live admin tokens (by digest → last use) and the login lockout."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._last_used: dict[str, float] = {}
        self._failures: list[float] = []
        self._locked_until = 0.0

    def _prune(self, now: float) -> None:
        for digest, last in list(self._last_used.items()):
            if now - last >= IDLE_TTL_S:
                del self._last_used[digest]

    def issue(self) -> tuple[str, float]:
        now = self._clock()
        self._prune(now)
        token = secrets.token_hex(32)
        self._last_used[_digest(token)] = now
        return token, now + IDLE_TTL_S

    def verify(self, token: str) -> bool:
        """True for a live token, refreshing its idle timer. The lookup is by
        SHA-256 of a 256-bit random token, so its timing reveals nothing."""
        if not token:
            return False
        now = self._clock()
        digest = _digest(token)
        last = self._last_used.get(digest)
        if last is None:
            return False
        if now - last >= IDLE_TTL_S:
            del self._last_used[digest]
            return False
        self._last_used[digest] = now
        return True

    def revoke(self, token: str) -> None:
        if token:
            self._last_used.pop(_digest(token), None)

    def locked_for(self) -> float:
        return max(0.0, self._locked_until - self._clock())

    def record_failure(self) -> bool:
        """Count a failed login; True when this failure started a lockout."""
        now = self._clock()
        self._failures = [t for t in self._failures if now - t < LOCKOUT_WINDOW_S]
        self._failures.append(now)
        if len(self._failures) >= LOCKOUT_ATTEMPTS:
            self._failures.clear()
            self._locked_until = now + LOCKOUT_S
            return True
        return False
```

In `services/boombox_setup/accounts.py`, replace lines 1–53 (docstring through the end of `check_auth`) with:

```python
"""/api/accounts/* — Admin → Accounts in the LAN app (served at / on :8090).

Auth is the admin session (admin_session.py), not nginx Basic auth: the app
POSTs the boombox web password to /api/accounts/session and sends the
returned bearer token on every other call. Every request must also come from
a non-loopback client — nginx's `X-Real-IP`; a missing header is a direct
on-box call and counts as loopback — so the kiosk (or any page open in it)
can neither log in nor use a token. Mutations also need JSON and, when the
browser sends Origin, a same-origin match against `X-Boombox-Host`
($http_host). Secrets are write-only: no response carries a password, API
key or token other than the caller's own new admin token, and no log line
contains one.
"""
from __future__ import annotations

import logging
import math
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

from . import jellyfin_signin as jf
from .admin_session import AdminSessions, password_matches

log = logging.getLogger("boombox-setup.accounts")

PREFIX = "/api/accounts/"
SESSION_PATH = "/api/accounts/session"
ADMIN_KEY = "admin"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BASE_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(/[A-Za-z0-9._~%/+-]*)?$")
_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")
_BUILTIN_BASE = "http://127.0.0.1:8096"
_DEFAULT_PORTS = {"http": 80, "https": 443}
CDP_BASE = os.environ.get("BOOMBOX_KIOSK_CDP", "http://127.0.0.1:9222")
_VIDEO_UNITS = ["boombox-remote.service", "boombox-kiosk-guard.service",
                "boombox-buttons.service"]


def _client_ip(req: web.Request) -> str:
    return req.headers.get("X-Real-IP", "").strip()


def _bearer(req: web.Request) -> str:
    auth = req.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else ""


def check_auth(req: web.Request) -> web.Response | None:
    """None when the request may proceed, else the refusal response.

    Order: loopback first (the kiosk is refused whatever it sends), then the
    admin token (not needed to log in or out), then the JSON/Origin checks
    for writes — which also cover the login POST."""
    ip = _client_ip(req)
    if not ip or ip in _LOOPBACK:
        return web.json_response(
            {"error": "accounts can only be changed from another device"}, status=403)
    if req.path != SESSION_PATH:
        admin: AdminSessions = req.app[ADMIN_KEY]
        if not admin.verify(_bearer(req)):
            return web.json_response({"error": "admin session required"}, status=401)
    if req.method in _MUTATING:
        if req.content_type != "application/json":
            return web.json_response(
                {"error": "Content-Type must be application/json"}, status=415)
        origin = req.headers.get("Origin")
        if origin and urlsplit(origin).netloc != req.headers.get("X-Boombox-Host", ""):
            return web.json_response({"error": "cross-origin request refused"}, status=403)
    return None
```

Immediately before `def add_routes(app: web.Application) -> None:` (line 456) insert:

```python
async def _session_login(req: web.Request) -> web.Response:
    """Exchange the web password for an admin token. check_auth has already
    refused loopback clients and non-JSON / cross-origin posts. Every attempt
    is logged with the client IP and outcome — never the password."""
    ctx: Any = req.app["ctx"]
    admin: AdminSessions = req.app[ADMIN_KEY]
    ip = _client_ip(req)
    wait = admin.locked_for()
    if wait > 0:
        log.warning("admin login from %s: refused, locked out", ip)
        return web.json_response(
            {"ok": False, "error": "too many wrong passwords — try again later",
             "retry_after": math.ceil(wait)}, status=429)
    b = await _json_body(req)
    if b is None:
        log.warning("admin login from %s: malformed request", ip)
        return _bad_body()
    try:
        expected = ctx.web_password()
    except Exception:
        log.exception("admin login: web password unreadable")
        expected = None
    if not expected:
        log.warning("admin login from %s: no web password configured", ip)
        return _err("no web password is set on this boombox", 503)
    if not password_matches(b.get("password"), expected):
        locked = admin.record_failure()
        log.warning("admin login from %s: wrong password%s", ip,
                    " — logins locked for 5 minutes" if locked else "")
        return _err("wrong password", 401)
    token, expires_at = admin.issue()
    log.info("admin login from %s: ok", ip)
    return web.json_response({"ok": True, "token": token, "expires_at": expires_at})


async def _session_logout(req: web.Request) -> web.Response:
    admin: AdminSessions = req.app[ADMIN_KEY]
    admin.revoke(_bearer(req))
    log.info("admin logout from %s", _client_ip(req))
    return web.json_response({"ok": True})


```

Replace `add_routes` (lines 456–470) with:

```python
def add_routes(app: web.Application) -> None:
    app[ADMIN_KEY] = AdminSessions()
    r = app.router
    r.add_post("/api/accounts/session", _session_login)
    r.add_delete("/api/accounts/session", _session_logout)
    r.add_get("/api/accounts/summary", _summary)
    r.add_get("/api/accounts/music", _music_get)
    r.add_post("/api/accounts/music/test", _music_test)
    r.add_put("/api/accounts/music", _music_put)
    r.add_get("/api/accounts/video", _video_get)
    r.add_post("/api/accounts/video/test", _video_test)
    r.add_put("/api/accounts/video", _video_put)
    r.add_get("/api/accounts/video/users", _video_users)
    r.add_post("/api/accounts/video/kiosk-signin", _kiosk_signin)
    r.add_post("/api/accounts/video/kiosk-signout", _kiosk_signout)
    r.add_get("/api/accounts/streaming", _streaming_get)
    r.add_put("/api/accounts/streaming", _streaming_put)
    r.add_put("/api/accounts/web-login", _web_login_put)
```

(`time` stays imported — `_kiosk_signin` uses it.)

In `services/boombox_setup/api.py`, inside `class Context(Protocol)` after `def set_skin(self, skin_id: str) -> bool: ...` (line 52) add:

```python
    # the boombox web password (Admin unlock), read fresh; None when unset
    def web_password(self) -> str | None: ...
```

In `services/boombox-setup.py`:
- after `from boombox_setup import __version__` (line 31) add `from boombox_setup.admin_session import read_web_password`
- after the `JELLYFIN_ENV = …` line (line 43) add:

```python
WEB_AUTH_ENV = Path(os.environ.get("BOOMBOX_WEB_AUTH_ENV", "/etc/boombox/web-auth.env"))
```

- after `def jellyfin_env(self) -> dict[str, str]: return _read_env_file(JELLYFIN_ENV)` (lines 126–127) add:

```python
    def web_password(self) -> str | None:
        # Read the file, not os.environ: the unit's EnvironmentFile copy goes
        # stale when the Accounts page changes the password.
        return read_web_password(WEB_AUTH_ENV)
```

- [ ] **Step 4: Run the tests and checks**

Run: `.venv/bin/python -m pytest -q services/tests/test_admin_session.py services/tests/test_accounts_api.py`
Expected: PASS (all old card tests plus the new session tests).

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy && ~/.local/bin/mypy services/boombox_setup/admin_session.py services/boombox_setup/accounts.py services/boombox_setup/api.py`
Expected: all tests pass (the nginx static tests are untouched until Task 5); ruff `All checks passed!`; mypy `Success: no issues found` twice.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_setup/admin_session.py services/boombox_setup/accounts.py \
  services/boombox_setup/api.py services/boombox-setup.py \
  services/tests/test_admin_session.py services/tests/test_accounts_api.py
git commit -m "feat(accounts): admin session (web password → 12 h token, lockout) replaces Basic-auth user gate

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Home Library pass-through routes (boombox-remote)

**Files:**
- Create: `services/remote_home.py`
- Modify: `services/boombox-remote.py` (`main()`, after the `jellyfin_client.add_routes(...)` call, ~line 668)
- Test: `services/tests/test_remote_home.py` (create)

**Interfaces:**
- Consumes (boombox-library on `BOOMBOX_LIBRARY_BASE`, default `http://127.0.0.1:6687`): `GET /api/library/browse?type=` → `{"items": [...]}` (+ `ETag`, 304 on `If-None-Match`); `GET /api/library/search?q=` → `{"results": [{content_type, id, title}]}`; `GET /api/library/{artist|album|playlist}/{id}`; `GET /api/library/art/{art_id}?size=`; `POST /api/library/resolve {"ids": [...]}` → `{"items": [{id, source: "cache"|"stream"|"offline_miss", uri, cache_status}]}` (request order, max 1000 ids).
- Consumes: `boombox_rfid.mopidy_client.MopidyClient(rpc_url)` (async context manager; `play_uris(uris) -> PendingTail | None`, `append_tail(tail) -> int`), `PendingTail(uris, after_tlid)`, `queue_intent.write_intent(uris) -> str`, `queue_intent.clear_intent(token=None)`.
- Produces (HTTP, pair-token checked by the existing middleware):
  - `GET /api/remote/home/browse?type=artists|albums|playlists` → library body unchanged (ETag/Cache-Control passed through; `If-None-Match` forwarded; 304 passed through); bad type → 400 `{"ok": false, "error": "type must be artists, albums or playlists"}`
  - `GET /api/remote/home/search?q=` → library body unchanged; empty `q` → `{"results": []}`; `q` > 200 chars → 400
  - `GET /api/remote/home/{artist|album|playlist}/{id}` → library body unchanged (404 passed through); id not `^[A-Za-z0-9._-]{1,128}$` → 400
  - `GET /api/remote/home/art/{art_id}?size=N` → image bytes + `Content-Type` + `Cache-Control` + `ETag` passed through; 404 passed through
  - `POST /api/remote/home/play {"ids": [str, ...1000], "mode": "play"|"queue"}` → 200 `{"ok": true, "count": <queued>, "skipped": <offline_miss/uri-less>}` | 409 `{"ok": false, "error": "none of these tracks can play right now — they aren't cached and the Home Library server is unreachable"}` | 400 bad body | 502 `{"ok": false, "error": "the music player isn't answering"}`
  - Any upstream connection error / timeout (15 s) / 5xx / non-JSON resolve → 502 `{"ok": false, "error": "library service not answering"}`
- Produces (Python): `remote_home.add_routes(app, session: aiohttp.ClientSession, player: HomePlayer, base: str = LIBRARY_BASE) -> None`; `class HomePlayer(rpc_url: str = MOPIDY_RPC, client_factory = MopidyClient)` with `async play(uris: list[str]) -> None`, `async queue(uris: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_remote_home.py`:

```python
"""/api/remote/home/* — Home Library pass-through + play (remote_home.py)."""
from __future__ import annotations

import asyncio
import contextlib
import json

import aiohttp
import pytest
from aiohttp import web
from boombox_rfid.mopidy_client import PendingTail

AUTH = {"Authorization": "Bearer t"}


class FakeLibrary:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.resolve_items: list[dict] = []
        self.resolved_ids: list[str] | None = None
        self.force_status: int | None = None

    def app(self) -> web.Application:
        async def handle(req: web.Request) -> web.StreamResponse:
            self.requests.append((req.method, req.path_qs, dict(req.headers)))
            if self.force_status:
                return web.json_response({"error": "boom"}, status=self.force_status)
            p = req.path
            if p == "/api/library/browse":
                if req.headers.get("If-None-Match") == '"v1"':
                    return web.Response(status=304, headers={"ETag": '"v1"'})
                return web.json_response(
                    {"items": [{"id": "al1", "name": "Blue", "art_id": "al-1"}]},
                    headers={"ETag": '"v1"', "Cache-Control": "no-cache"})
            if p == "/api/library/search":
                return web.json_response({"results": [
                    {"content_type": "album", "id": "al1", "title": "Blue"}]})
            if p == "/api/library/album/al1":
                return web.json_response({"album": {"id": "al1", "name": "Blue"},
                                          "tracks": [{"id": "t1"}, {"id": "t2"}]})
            if p == "/api/library/art/al-1":
                return web.Response(body=b"\xff\xd8jpeg", content_type="image/jpeg",
                                    headers={"Cache-Control": "public, max-age=31536000, immutable",
                                             "ETag": '"al-1-320"'})
            if p == "/api/library/resolve":
                self.resolved_ids = (await req.json())["ids"]
                return web.json_response({"items": self.resolve_items})
            return web.json_response({"error": "not found"}, status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        return app


class FakePlayer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail = False

    async def play(self, uris):
        if self.fail:
            raise RuntimeError("mopidy down")
        self.calls.append(("play", list(uris)))

    async def queue(self, uris):
        self.calls.append(("queue", list(uris)))


@pytest.fixture
async def home(aiohttp_server, aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    lib = FakeLibrary()
    srv = await aiohttp_server(lib.app())
    import boombox_remote
    import remote_home
    app = boombox_remote.create_app()
    player = FakePlayer()
    session = aiohttp.ClientSession()
    remote_home.add_routes(app, session, player, base=str(srv.make_url("")).rstrip("/"))
    client = await aiohttp_client(app)
    yield client, lib, player
    await session.close()


async def test_routes_require_pair_token(home):
    client, _lib, _player = home
    for path in ("/api/remote/home/browse?type=albums", "/api/remote/home/album/al1",
                 "/api/remote/home/art/al-1", "/api/remote/home/search?q=blue"):
        assert (await client.get(path)).status == 401, path
    assert (await client.post("/api/remote/home/play", json={"ids": ["t1"]})).status == 401


async def test_browse_passes_body_and_etag_through(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/browse?type=albums", headers=AUTH)
    assert r.status == 200 and r.headers["ETag"] == '"v1"'
    assert (await r.json())["items"][0]["name"] == "Blue"
    r = await client.get("/api/remote/home/browse?type=albums",
                         headers={**AUTH, "If-None-Match": '"v1"'})
    assert r.status == 304
    assert lib.requests[-1][2].get("If-None-Match") == '"v1"'


async def test_browse_rejects_unknown_type(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/browse?type=tracks", headers=AUTH)
    assert r.status == 400 and lib.requests == []


async def test_search_and_detail_pass_through(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/search?q=blue%20moon", headers=AUTH)
    assert (await r.json())["results"][0]["id"] == "al1"
    assert lib.requests[-1][1] == "/api/library/search?q=blue%20moon"
    r = await client.get("/api/remote/home/search?q=", headers=AUTH)
    assert (await r.json()) == {"results": []}
    r = await client.get("/api/remote/home/album/al1", headers=AUTH)
    assert [t["id"] for t in (await r.json())["tracks"]] == ["t1", "t2"]
    r = await client.get("/api/remote/home/album/nope", headers=AUTH)
    assert r.status == 404


async def test_detail_rejects_bad_kind_and_id(home):
    client, lib, _ = home
    assert (await client.get("/api/remote/home/track/t1", headers=AUTH)).status == 404
    assert (await client.get("/api/remote/home/album/a%20b", headers=AUTH)).status == 400
    assert lib.requests == []


async def test_art_bytes_and_cache_headers(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/art/al-1?size=320", headers=AUTH)
    assert r.status == 200 and r.content_type == "image/jpeg"
    assert await r.read() == b"\xff\xd8jpeg"
    assert "immutable" in r.headers["Cache-Control"]
    assert lib.requests[-1][1] == "/api/library/art/al-1?size=320"
    r = await client.get("/api/remote/home/art/missing", headers=AUTH)
    assert r.status == 404


async def test_upstream_5xx_is_502(home):
    client, lib, _ = home
    lib.force_status = 500
    r = await client.get("/api/remote/home/browse?type=albums", headers=AUTH)
    assert r.status == 502
    assert (await r.json()) == {"ok": False, "error": "library service not answering"}


async def test_library_down_is_502(aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    import remote_home
    app = boombox_remote.create_app()
    async with aiohttp.ClientSession() as session:
        remote_home.add_routes(app, session, FakePlayer(), base="http://127.0.0.1:1")
        client = await aiohttp_client(app)
        for method, path, body in (("GET", "/api/remote/home/browse?type=artists", None),
                                   ("POST", "/api/remote/home/play", {"ids": ["t1"]})):
            r = await client.request(method, path, json=body, headers=AUTH)
            assert r.status == 502, path


async def test_play_drops_offline_miss_and_reports_skipped(home):
    client, lib, player = home
    lib.resolve_items = [
        {"id": "t1", "source": "cache", "uri": "file:///m/t1.flac", "cache_status": "present"},
        {"id": "t2", "source": "offline_miss", "uri": None, "cache_status": "absent"},
        {"id": "t3", "source": "stream", "uri": "http://127.0.0.1:6687/api/library/stream/t3",
         "cache_status": "absent"},
    ]
    r = await client.post("/api/remote/home/play",
                          json={"ids": ["t1", "t2", "t3"], "mode": "play"}, headers=AUTH)
    assert r.status == 200
    assert (await r.json()) == {"ok": True, "count": 2, "skipped": 1}
    assert lib.resolved_ids == ["t1", "t2", "t3"]
    assert player.calls == [("play", ["file:///m/t1.flac",
                                      "http://127.0.0.1:6687/api/library/stream/t3"])]


async def test_queue_mode_appends(home):
    client, lib, player = home
    lib.resolve_items = [{"id": "t1", "source": "cache", "uri": "file:///m/t1.flac"}]
    r = await client.post("/api/remote/home/play", json={"ids": ["t1"], "mode": "queue"},
                          headers=AUTH)
    assert r.status == 200 and player.calls == [("queue", ["file:///m/t1.flac"])]


async def test_play_all_offline_is_409_and_never_touches_mopidy(home):
    client, lib, player = home
    lib.resolve_items = [{"id": "t1", "source": "offline_miss", "uri": None}]
    r = await client.post("/api/remote/home/play", json={"ids": ["t1"]}, headers=AUTH)
    assert r.status == 409
    assert "can play right now" in (await r.json())["error"]
    assert player.calls == []


@pytest.mark.parametrize("body", [
    {}, {"ids": []}, {"ids": "t1"}, {"ids": [1]}, {"ids": ["a b"]},
    {"ids": ["t1"], "mode": "shuffle"}, {"ids": ["t"] * 1001}, ["t1"],
])
async def test_play_rejects_bad_bodies(home, body):
    client, lib, player = home
    r = await client.post("/api/remote/home/play", json=body, headers=AUTH)
    assert r.status == 400
    assert lib.resolved_ids is None and player.calls == []


async def test_player_failure_is_502(home):
    client, lib, player = home
    lib.resolve_items = [{"id": "t1", "source": "cache", "uri": "file:///m/t1.flac"}]
    player.fail = True
    r = await client.post("/api/remote/home/play", json={"ids": ["t1"]}, headers=AUTH)
    assert r.status == 502
    assert (await r.json())["error"] == "the music player isn't answering"


# ---- HomePlayer ------------------------------------------------------------

class FakeMopidyClient:
    instances: list["FakeMopidyClient"] = []
    gate: asyncio.Event | None = None

    def __init__(self, url: str) -> None:
        self.url = url
        self.played: list[str] | None = None
        self.appended: list[PendingTail] = []
        FakeMopidyClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def play_uris(self, uris):
        self.played = list(uris)
        return PendingTail(uris=list(uris[1:]), after_tlid=7) if len(uris) > 5 else None

    async def append_tail(self, tail):
        self.appended.append(tail)
        if FakeMopidyClient.gate is not None:
            await FakeMopidyClient.gate.wait()
        return len(tail.uris)


@pytest.fixture
def fake_mopidy():
    FakeMopidyClient.instances = []
    FakeMopidyClient.gate = None
    return FakeMopidyClient


async def test_long_play_queues_tail_in_background_and_new_play_cancels_it(fake_mopidy):
    import queue_intent
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=fake_mopidy)
    fake_mopidy.gate = asyncio.Event()
    uris = [f"http://127.0.0.1:6687/api/library/stream/t{i}" for i in range(200)]
    await player.play(uris)
    assert fake_mopidy.instances[0].played == uris
    await asyncio.sleep(0)
    tail = fake_mopidy.instances[1].appended[0]
    assert tail.uris == uris[1:] and tail.after_tlid == 7
    assert queue_intent.read_intent() == uris        # resume snapshots the whole list
    first_task = player._tail_task
    assert first_task is not None
    await player.play(["file:///m/a.flac"])          # a new play supersedes the tail
    with contextlib.suppress(asyncio.CancelledError):
        await first_task
    assert first_task.cancelled()
    assert queue_intent.read_intent() is None


async def test_short_play_has_no_tail(fake_mopidy):
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=fake_mopidy)
    await player.play(["file:///m/a.flac", "file:///m/b.flac"])
    assert player._tail_task is None and len(fake_mopidy.instances) == 1


async def test_queue_appends_at_end(fake_mopidy):
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=fake_mopidy)
    await player.queue(["file:///m/a.flac"])
    tail = fake_mopidy.instances[0].appended[0]
    assert tail.uris == ["file:///m/a.flac"] and tail.after_tlid is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_home.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'remote_home'`.

- [ ] **Step 3: Implement**

Create `services/remote_home.py`:

```python
"""Home Library (boombox-library) routes for the LAN app: /api/remote/home/*.

GET routes pass boombox-library's JSON/images through unchanged — the phone
never talks to :6687 itself (loopback-only, no auth). POST /play resolves
track ids to playable URIs (cache file or the library's stream proxy), drops
offline misses, and plays or appends them through Mopidy the same way an
RFID card does: first track now, the rest in background chunks
(boombox_rfid.mopidy_client), with the full list recorded as the queue
intent so boombox-resume never snapshots a half-built queue.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Callable
from urllib.parse import quote

import aiohttp
from aiohttp import web
from boombox_rfid.mopidy_client import MopidyClient, PendingTail
from queue_intent import clear_intent, write_intent

log = logging.getLogger("boombox-remote")

LIBRARY_BASE = os.environ.get("BOOMBOX_LIBRARY_BASE", "http://127.0.0.1:6687")
MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
TIMEOUT = aiohttp.ClientTimeout(total=15)
BROWSE_TYPES = frozenset({"artists", "albums", "playlists"})
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MAX_PLAY_IDS = 1000           # boombox-library's RESOLVE_BATCH_MAX
SYNC_QUEUE_MAX = 10           # queue lists this short finish before we answer
MAX_QUERY = 200
_PASS_HEADERS = ("ETag", "Cache-Control")
LIBRARY_DOWN = "library service not answering"
NOTHING_PLAYABLE = ("none of these tracks can play right now — they aren't cached "
                    "and the Home Library server is unreachable")
PLAYER_DOWN = "the music player isn't answering"


def _fail(status: int, error: str) -> web.Response:
    return web.json_response({"ok": False, "error": error}, status=status)


class HomePlayer:
    """Plays or appends resolved URIs. One background tail at a time for
    plays: a new play cancels the previous play's tail, as a new RFID tap
    does. Long queue-appends run in the background too (kept referenced)."""

    def __init__(self, rpc_url: str = MOPIDY_RPC,
                 client_factory: Callable[[str], Any] = MopidyClient) -> None:
        self._rpc = rpc_url
        self._factory = client_factory
        self._tail_task: asyncio.Task | None = None
        self._queue_tasks: set[asyncio.Task] = set()

    def _cancel_tail(self) -> None:
        if self._tail_task and not self._tail_task.done():
            self._tail_task.cancel()
        self._tail_task = None

    async def play(self, uris: list[str]) -> None:
        self._cancel_tail()
        clear_intent()
        async with self._factory(self._rpc) as m:
            tail = await m.play_uris(uris)
        if tail:
            token: str | None = None
            try:
                token = write_intent(uris)
            except OSError as e:
                log.warning("could not record queue intent: %s", e)
            self._tail_task = asyncio.create_task(self._append(tail, token))

    async def queue(self, uris: list[str]) -> None:
        tail = PendingTail(uris=list(uris), after_tlid=None)
        if len(uris) <= SYNC_QUEUE_MAX:
            async with self._factory(self._rpc) as m:
                await m.append_tail(tail)
            return
        task = asyncio.create_task(self._append(tail, None))
        self._queue_tasks.add(task)
        task.add_done_callback(self._queue_tasks.discard)

    async def _append(self, tail: PendingTail, token: str | None) -> None:
        try:
            async with self._factory(self._rpc) as m:
                n = await m.append_tail(tail)
            log.info("home library: queued %d/%d remaining tracks", n, len(tail.uris))
        except asyncio.CancelledError:
            log.info("home library: background queueing superseded")
            raise
        except Exception as e:
            log.warning("home library: background queueing failed: %s", e)
        if token is not None:
            clear_intent(token)


async def _proxy_get(session: aiohttp.ClientSession, url: str,
                     req: web.Request) -> web.Response:
    headers: dict[str, str] = {}
    inm = req.headers.get("If-None-Match")
    if inm:
        headers["If-None-Match"] = inm
    try:
        async with session.get(url, headers=headers, timeout=TIMEOUT) as r:
            body = await r.read()
            status = r.status
            ctype = r.content_type
            passthrough = {h: r.headers[h] for h in _PASS_HEADERS if h in r.headers}
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.warning("home library GET %s failed: %s", url, type(e).__name__)
        return _fail(502, LIBRARY_DOWN)
    if status >= 500:
        log.warning("home library GET %s → HTTP %s", url, status)
        return _fail(502, LIBRARY_DOWN)
    if status == 304:
        return web.Response(status=304, headers=passthrough)
    return web.Response(status=status, body=body, content_type=ctype, headers=passthrough)


def _make_handlers(session: aiohttp.ClientSession, base: str, player: HomePlayer):
    async def browse(req: web.Request) -> web.Response:
        t = req.query.get("type", "")
        if t not in BROWSE_TYPES:
            return _fail(400, "type must be artists, albums or playlists")
        return await _proxy_get(session, f"{base}/api/library/browse?type={t}", req)

    async def search(req: web.Request) -> web.Response:
        q = req.query.get("q", "").strip()
        if not q:
            return web.json_response({"results": []})
        if len(q) > MAX_QUERY:
            return _fail(400, "search text is too long")
        return await _proxy_get(session, f"{base}/api/library/search?q={quote(q)}", req)

    async def detail(req: web.Request) -> web.Response:
        kind = req.match_info["kind"]
        item_id = req.match_info["item_id"]
        if not _ID_RE.match(item_id):
            return _fail(400, "bad id")
        return await _proxy_get(
            session, f"{base}/api/library/{kind}/{quote(item_id, safe='')}", req)

    async def art(req: web.Request) -> web.Response:
        art_id = req.match_info["art_id"]
        if not _ID_RE.match(art_id):
            return _fail(400, "bad id")
        size = req.query.get("size", "")
        qs = f"?size={int(size)}" if size.isdigit() and 0 < int(size) <= 2000 else ""
        return await _proxy_get(
            session, f"{base}/api/library/art/{quote(art_id, safe='')}{qs}", req)

    async def play(req: web.Request) -> web.Response:
        try:
            body = await req.json()
        except Exception:
            return _fail(400, "invalid_json")
        if not isinstance(body, dict):
            return _fail(400, "expected a JSON object")
        ids = body.get("ids")
        mode = body.get("mode", "play")
        if (not isinstance(ids, list) or not ids or len(ids) > MAX_PLAY_IDS
                or not all(isinstance(i, str) and _ID_RE.match(i) for i in ids)):
            return _fail(400, f"ids must be 1-{MAX_PLAY_IDS} track ids")
        if mode not in ("play", "queue"):
            return _fail(400, "mode must be play or queue")
        try:
            async with session.post(f"{base}/api/library/resolve", json={"ids": ids},
                                    timeout=TIMEOUT) as r:
                if r.status != 200:
                    log.warning("home library resolve → HTTP %s", r.status)
                    return _fail(502, LIBRARY_DOWN)
                data = await r.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.warning("home library resolve failed: %s", type(e).__name__)
            return _fail(502, LIBRARY_DOWN)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return _fail(502, LIBRARY_DOWN)
        uris = [it["uri"] for it in items
                if isinstance(it, dict) and it.get("source") != "offline_miss"
                and isinstance(it.get("uri"), str) and it["uri"]]
        if not uris:
            return _fail(409, NOTHING_PLAYABLE)
        try:
            if mode == "play":
                await player.play(uris)
            else:
                await player.queue(uris)
        except Exception as e:
            log.warning("home library %s failed: %s", mode, e)
            return _fail(502, PLAYER_DOWN)
        return web.json_response({"ok": True, "count": len(uris),
                                  "skipped": len(ids) - len(uris)})

    return browse, search, detail, art, play


def add_routes(app: web.Application, session: aiohttp.ClientSession,
               player: HomePlayer, base: str = LIBRARY_BASE) -> None:
    """Register /api/remote/home/*. `session` is the service's shared client
    session (per-request 15 s timeouts override its default)."""
    browse, search, detail, art, play = _make_handlers(session, base.rstrip("/"), player)
    app.router.add_get("/api/remote/home/browse", browse)
    app.router.add_get("/api/remote/home/search", search)
    app.router.add_get("/api/remote/home/art/{art_id}", art)
    app.router.add_get("/api/remote/home/{kind:artist|album|playlist}/{item_id}", detail)
    app.router.add_post("/api/remote/home/play", play)
```

In `services/boombox-remote.py` `main()`, directly after

```python
        jellyfin_client.add_routes(
            app, jellyfin_client.JellyfinClient(session))
```

add:

```python
        # Home Library (boombox-library) browse/art pass-through + play.
        import remote_home
        remote_home.add_routes(app, session, remote_home.HomePlayer())
```

- [ ] **Step 4: Run the tests and checks**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_home.py`
Expected: PASS.

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy && ~/.local/bin/mypy --follow-imports=silent services/remote_home.py`
Expected: all pass; `All checks passed!`; `Success: no issues found` twice.

- [ ] **Step 5: Commit**

```bash
git add services/remote_home.py services/boombox-remote.py services/tests/test_remote_home.py
git commit -m "feat(remote): Home Library pass-through routes + play/queue via the RFID queueing path

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Video browse + poster routes (boombox-remote)

**Files:**
- Create: `services/remote_video.py`
- Modify: `services/boombox-remote.py` (`main()`, after the Task 2 `remote_home.add_routes(...)` lines)
- Test: `services/tests/test_remote_video_browse.py` (create)

**Interfaces:**
- Consumes: `jellyfin_env.jellyfin_base() -> str`, `jellyfin_env.jellyfin_token() -> str | None`, `jellyfin_client.DEVICE_ID_ENV` (`"BOOMBOX_JELLYFIN_DEVICE_ID"`), `jellyfin_client.server_is_loopback(base) -> bool`; env `JELLYFIN_USER_ID` (bootstrapped built-in admin, from `jellyfin.env`); env `BOOMBOX_REMOTE_VIDEO_CACHE` (poster cache dir, default `~/.cache/boombox-remote/video`).
- Consumes (Jellyfin 10.10, header `X-Emby-Token: <key>`): `GET /Devices/Info?id=` → `{LastUserId}`; `GET /UserViews?userId=` (fallback `GET /Users/{uid}/Views` on 404); `GET /UserItems/Resume?userId=` (fallback `GET /Users/{uid}/Items/Resume` on 404); `GET /Items?userId=&parentId=&includeItemTypes=&searchTerm=&startIndex=&limit=&recursive=&fields=&sortBy=`; `GET /Items/{id}/Images/Primary?maxWidth=&format=Jpg&quality=85`.
- Produces (Python): `class VideoError(Exception)` with `.status: int`, `.message: str`; `normalize_item(i: dict) -> dict`; `image_width(raw: str | None) -> int`; `class JellyfinBrowser(session: aiohttp.ClientSession)` with `async kiosk_user() -> str`, `async views() -> list[dict]`, `async resume() -> list[dict]`, `async items(*, parent_id: str, types: str, search: str, start: int, limit: int) -> dict`, `async image(item_id: str, max_width: int) -> bytes | None`, and helpers `_target()`, `_request(method, path, params) -> tuple[int, bytes, str]`, `_get_json(path, params) -> Any | None` (Task 4 builds on these); `add_routes(app: web.Application, browser: JellyfinBrowser) -> None`.
- Produces (HTTP, pair-token checked; every error body `{"ok": false, "error": "<message>"}`):
  - `GET /api/remote/video/views` → `{"ok": true, "items": [Item]}`
  - `GET /api/remote/video/resume` → `{"ok": true, "items": [Item]}`
  - `GET /api/remote/video/items?parent_id=&type=&search=&start=&limit=` → `{"ok": true, "items": [Item], "total": int, "start": int}` (`limit` default 60, max 200; `type` = comma list of Jellyfin item types; `recursive` when `type` or `search` is given)
  - `GET /api/remote/video/image/{item_id}?max_width=` → `image/jpeg` bytes (`Cache-Control: private, max-age=86400`), 404 when Jellyfin has no poster
  - `Item` = `{"id", "name", "type", "collection_type", "is_folder", "year", "runtime_s", "series_name", "season", "episode", "overview", "has_image", "played", "progress", "resume_s"}`
  - Errors: 503 `"video server not configured"` (no API key), 409 `"kiosk not signed in"`, 502 `"video server unreachable"` / `"video server refused the stored API key"`, 400 `"bad query"` / `"bad item id"`.

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_remote_video_browse.py`:

```python
"""/api/remote/video/{views,resume,items,image} — remote_video.JellyfinBrowser."""
from __future__ import annotations

import json

import aiohttp
import pytest
from aiohttp import web

AUTH = {"Authorization": "Bearer t"}
KEY = "sekrit-key-0123456789abcdef"
DEVICE = "boombox-markii-kiosk"
MOVIE = {"Id": "aa11", "Name": "Big Buck Bunny", "Type": "Movie", "ProductionYear": 2008,
         "RunTimeTicks": 5_960_000_000, "ImageTags": {"Primary": "tag"},
         "UserData": {"Played": False, "PlayedPercentage": 12.345,
                      "PlaybackPositionTicks": 736_000_000}}
EPISODE = {"Id": "bb22", "Name": "Pilot", "Type": "Episode", "SeriesName": "Show",
           "ParentIndexNumber": 1, "IndexNumber": 2, "RunTimeTicks": 26_000_000_000,
           "UserData": {"PlaybackPositionTicks": 7_540_000_000}}


class FakeJF:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str | None]] = []
        self.device_user: str | None = "u1"
        self.new_endpoints = True
        self.image_hits = 0
        self.items_status = 200

    def app(self) -> web.Application:
        async def handle(req: web.Request) -> web.StreamResponse:
            self.seen.append((req.method, req.path_qs, req.headers.get("X-Emby-Token")))
            p = req.path
            if p == "/Devices/Info":
                if req.query.get("id") != DEVICE:
                    return web.Response(status=404)
                return web.json_response({"Id": DEVICE, "LastUserId": self.device_user})
            if p == "/UserViews" and self.new_endpoints:
                return web.json_response({"Items": [
                    {"Id": "a1b2", "Name": "Movies", "Type": "CollectionFolder",
                     "CollectionType": "movies", "IsFolder": True,
                     "ImageTags": {"Primary": "x"}}]})
            if p == "/Users/u1/Views":
                return web.json_response({"Items": [
                    {"Id": "a9b9", "Name": "Old Movies", "CollectionType": "movies",
                     "IsFolder": True}]})
            if p == "/UserItems/Resume" and self.new_endpoints:
                return web.json_response({"Items": [EPISODE]})
            if p == "/Users/u1/Items/Resume":
                return web.json_response({"Items": [MOVIE]})
            if p == "/Items":
                if self.items_status != 200:
                    return web.Response(status=self.items_status)
                return web.json_response({"Items": [MOVIE], "TotalRecordCount": 131})
            if p == "/Items/aa11/Images/Primary":
                self.image_hits += 1
                return web.Response(body=b"\xff\xd8poster", content_type="image/jpeg")
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        return app


@pytest.fixture
async def video(aiohttp_server, aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    key = tmp_path / "jellyfin-api-key"
    key.write_text(KEY + "\n")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", DEVICE)
    monkeypatch.delenv("JELLYFIN_USER_ID", raising=False)
    monkeypatch.setenv("BOOMBOX_REMOTE_VIDEO_CACHE", str(tmp_path / "video-cache"))
    jf = FakeJF()
    srv = await aiohttp_server(jf.app())
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", str(srv.make_url("")).rstrip("/"))
    import boombox_remote
    import remote_video
    app = boombox_remote.create_app()
    session = aiohttp.ClientSession()
    remote_video.add_routes(app, remote_video.JellyfinBrowser(session))
    client = await aiohttp_client(app)
    yield client, jf, key
    await session.close()


async def test_routes_require_pair_token(video):
    client, _jf, _key = video
    for path in ("/api/remote/video/views", "/api/remote/video/resume",
                 "/api/remote/video/items", "/api/remote/video/image/aa11"):
        assert (await client.get(path)).status == 401, path


async def test_views_browse_as_the_kiosk_user(video):
    client, jf, _ = video
    r = await client.get("/api/remote/video/views", headers=AUTH)
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    assert body["items"][0]["name"] == "Movies"
    assert body["items"][0]["collection_type"] == "movies"
    assert body["items"][0]["has_image"] is True
    assert ("GET", f"/Devices/Info?id={DEVICE}", KEY) in jf.seen
    assert ("GET", "/UserViews?userId=u1", KEY) in jf.seen


async def test_kiosk_user_is_cached(video):
    client, jf, _ = video
    await client.get("/api/remote/video/views", headers=AUTH)
    await client.get("/api/remote/video/views", headers=AUTH)
    assert sum(1 for s in jf.seen if s[1].startswith("/Devices/Info")) == 1


async def test_old_endpoints_are_used_when_new_ones_404(video):
    client, jf, _ = video
    jf.new_endpoints = False
    views = await (await client.get("/api/remote/video/views", headers=AUTH)).json()
    resume = await (await client.get("/api/remote/video/resume", headers=AUTH)).json()
    assert views["items"][0]["name"] == "Old Movies"
    assert resume["items"][0]["id"] == "aa11"


async def test_resume_items_are_normalized(video):
    client, _jf, _ = video
    body = await (await client.get("/api/remote/video/resume", headers=AUTH)).json()
    ep = body["items"][0]
    assert ep == {"id": "bb22", "name": "Pilot", "type": "Episode", "collection_type": None,
                  "is_folder": False, "year": None, "runtime_s": 2600,
                  "series_name": "Show", "season": 1, "episode": 2, "overview": None,
                  "has_image": False, "played": False, "progress": None, "resume_s": 754}


async def test_items_passes_paging_filters_and_search(video):
    client, jf, _ = video
    r = await client.get("/api/remote/video/items?parent_id=a1b2&type=Movie&start=60&limit=30",
                         headers=AUTH)
    body = await r.json()
    assert body["total"] == 131 and body["start"] == 60
    assert body["items"][0]["progress"] == 12.3 and body["items"][0]["resume_s"] == 73
    path = [s[1] for s in jf.seen if s[1].startswith("/Items?")][-1]
    for part in ("userId=u1", "parentId=a1b2", "includeItemTypes=Movie", "startIndex=60",
                 "limit=30", "recursive=true"):
        assert part in path, part
    await client.get("/api/remote/video/items?search=bunny", headers=AUTH)
    path = [s[1] for s in jf.seen if s[1].startswith("/Items?")][-1]
    assert "searchTerm=bunny" in path and "recursive=true" in path
    await client.get("/api/remote/video/items?parent_id=c3d4", headers=AUTH)
    path = [s[1] for s in jf.seen if s[1].startswith("/Items?")][-1]
    assert "recursive" not in path    # series → seasons is a plain folder listing


@pytest.mark.parametrize("qs", ["parent_id=../x", "type=Movie;drop", "limit=0", "limit=201",
                                "start=-1", "start=x", "search=" + "a" * 101])
async def test_items_rejects_bad_params(video, qs):
    client, jf, _ = video
    r = await client.get(f"/api/remote/video/items?{qs}", headers=AUTH)
    assert r.status == 400
    assert not any(s[1].startswith("/Items?") for s in jf.seen)


async def test_kiosk_not_signed_in_without_pin(video, monkeypatch):
    client, jf, _ = video
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    r = await client.get("/api/remote/video/views", headers=AUTH)
    assert r.status == 409
    assert (await r.json()) == {"ok": False, "error": "kiosk not signed in"}
    assert jf.seen == []


async def test_device_without_user_is_not_signed_in(video):
    client, jf, _ = video
    jf.device_user = None
    r = await client.get("/api/remote/video/views", headers=AUTH)
    assert r.status == 409


async def test_builtin_server_falls_back_to_bootstrapped_user(video, monkeypatch):
    import remote_video
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    monkeypatch.setenv("JELLYFIN_USER_ID", "u1")
    async with aiohttp.ClientSession() as s:
        assert await remote_video.JellyfinBrowser(s).kiosk_user() == "u1"  # fake is on 127.0.0.1
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")
    async with aiohttp.ClientSession() as s:
        with pytest.raises(remote_video.VideoError) as e:
            await remote_video.JellyfinBrowser(s).kiosk_user()
    assert e.value.status == 409


async def test_not_configured_is_503(video):
    client, jf, key = video
    key.write_text("")
    r = await client.get("/api/remote/video/resume", headers=AUTH)
    assert r.status == 503
    assert (await r.json())["error"] == "video server not configured"
    assert jf.seen == []


async def test_upstream_error_is_502(video):
    client, jf, _ = video
    jf.items_status = 500
    r = await client.get("/api/remote/video/items", headers=AUTH)
    assert r.status == 502
    jf.items_status = 401
    r = await client.get("/api/remote/video/items", headers=AUTH)
    assert r.status == 502
    assert (await r.json())["error"] == "video server refused the stored API key"


async def test_unreachable_server_is_502(video, monkeypatch):
    client, _jf, _ = video
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://127.0.0.1:1")
    import remote_video
    async with aiohttp.ClientSession() as s:
        with pytest.raises(remote_video.VideoError) as e:
            await remote_video.JellyfinBrowser(s).views()
    assert e.value.status == 502 and e.value.message == "video server unreachable"


async def test_image_is_proxied_and_cached(video, tmp_path):
    client, jf, _ = video
    for _ in range(2):
        r = await client.get("/api/remote/video/image/aa11?max_width=300", headers=AUTH)
        assert r.status == 200 and r.content_type == "image/jpeg"
        assert await r.read() == b"\xff\xd8poster"
    assert jf.image_hits == 1                        # second one came from disk
    assert (tmp_path / "video-cache" / "aa11-320.jpg").exists()   # 300 → 320 bucket
    path = [s[1] for s in jf.seen if "/Images/Primary" in s[1]][0]
    assert "maxWidth=320" in path and "format=Jpg" in path


async def test_image_missing_is_404_and_bad_id_400(video):
    client, _jf, _ = video
    assert (await client.get("/api/remote/video/image/ffff", headers=AUTH)).status == 404
    assert (await client.get("/api/remote/video/image/xyz", headers=AUTH)).status == 400


@pytest.mark.parametrize("raw,width", [(None, 320), ("", 320), ("1", 80), ("300", 320),
                                       ("320", 320), ("321", 400), ("99999", 1280), ("x", 320)])
def test_image_width_buckets(raw, width):
    import remote_video
    assert remote_video.image_width(raw) == width


async def test_api_key_never_in_responses(video, monkeypatch):
    client, jf, _ = video
    texts = []
    for path in ("/api/remote/video/views", "/api/remote/video/resume",
                 "/api/remote/video/items?search=x", "/api/remote/video/image/aa11"):
        r = await client.get(path, headers=AUTH)
        texts.append((await r.read()).decode("latin-1") + json.dumps(dict(r.headers)))
    jf.items_status = 500
    r = await client.get("/api/remote/video/items", headers=AUTH)
    texts.append(await r.text())
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    r = await client.get("/api/remote/video/views", headers=AUTH)
    texts.append(await r.text())
    assert all(KEY not in t for t in texts)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_video_browse.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'remote_video'`.

- [ ] **Step 3: Implement**

Create `services/remote_video.py`:

```python
"""Jellyfin browsing for the LAN app: /api/remote/video/*.

Server-side only: the stored API key (jellyfin_env) goes out in an
X-Emby-Token header and never into a response, a client-visible URL or a log
line. Browsing is as the Jellyfin user the kiosk is signed in as — the
LastUserId of the pinned kiosk device (BOOMBOX_JELLYFIN_DEVICE_ID, set by
Admin → Accounts → Video server → Sign kiosk in). With no pin only an
on-device server falls back to the bootstrapped JELLYFIN_USER_ID; anything
else answers "kiosk not signed in".
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp
from aiohttp import web
from jellyfin_client import DEVICE_ID_ENV, server_is_loopback
from jellyfin_env import jellyfin_base, jellyfin_token

log = logging.getLogger("boombox-remote")

TICKS_PER_SECOND = 10_000_000
TIMEOUT = aiohttp.ClientTimeout(total=15)
USER_CACHE_S = 60.0
DEFAULT_IMAGE_CACHE = Path.home() / ".cache" / "boombox-remote" / "video"
ITEM_FIELDS = "ProductionYear,Overview"
DEFAULT_LIMIT = 60
MAX_LIMIT = 200
MAX_SEARCH = 100
_ITEM_ID_RE = re.compile(r"^[0-9A-Fa-f-]{1,64}$")
_TYPES_RE = re.compile(r"^[A-Za-z]{1,32}(,[A-Za-z]{1,32}){0,5}$")

NOT_CONFIGURED = "video server not configured"
NOT_SIGNED_IN = "kiosk not signed in"
UNREACHABLE = "video server unreachable"
KEY_REFUSED = "video server refused the stored API key"


class VideoError(Exception):
    """A user-facing failure; `status` is the HTTP status for the phone."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _image_cache_dir() -> Path:
    path = Path(os.environ.get("BOOMBOX_REMOTE_VIDEO_CACHE", str(DEFAULT_IMAGE_CACHE)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secs(ticks: object) -> int:
    return int(ticks) // TICKS_PER_SECOND if isinstance(ticks, (int, float)) else 0


def normalize_item(i: dict) -> dict:
    ud = i.get("UserData") if isinstance(i.get("UserData"), dict) else {}
    tags = i.get("ImageTags") if isinstance(i.get("ImageTags"), dict) else {}
    pct = ud.get("PlayedPercentage")
    return {
        "id": i.get("Id"),
        "name": i.get("Name"),
        "type": i.get("Type"),
        "collection_type": i.get("CollectionType"),
        "is_folder": bool(i.get("IsFolder")),
        "year": i.get("ProductionYear"),
        "runtime_s": _secs(i.get("RunTimeTicks")),
        "series_name": i.get("SeriesName"),
        "season": i.get("ParentIndexNumber"),
        "episode": i.get("IndexNumber"),
        "overview": i.get("Overview"),
        "has_image": bool(tags.get("Primary")),
        "played": bool(ud.get("Played")),
        "progress": round(float(pct), 1) if isinstance(pct, (int, float)) else None,
        "resume_s": _secs(ud.get("PlaybackPositionTicks")),
    }


def _items_of(data: Any) -> list[dict]:
    items = data.get("Items") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def image_width(raw: str | None) -> int:
    """Clamp to 80..1280 and round UP to a multiple of 80, so the poster
    cache holds a handful of sizes per item instead of one per request."""
    try:
        w = int(raw) if raw else 320
    except ValueError:
        w = 320
    w = max(80, min(1280, w))
    return -(-w // 80) * 80


class JellyfinBrowser:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._sess = session
        self._user: tuple[str, str, float] | None = None   # (device, user, fetched)

    def _target(self) -> tuple[str, dict[str, str]]:
        key = jellyfin_token()
        if not key:
            raise VideoError(503, NOT_CONFIGURED)
        return jellyfin_base(), {"X-Emby-Token": key}

    async def _request(self, method: str, path: str,
                       params: dict[str, str] | None = None) -> tuple[int, bytes, str]:
        base, headers = self._target()
        try:
            async with self._sess.request(method, f"{base}{path}", params=params,
                                          headers=headers, timeout=TIMEOUT) as r:
                return r.status, await r.read(), r.content_type
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Type name only: some aiohttp errors echo request details.
            log.warning("jellyfin %s %s failed: %s", method, path, type(e).__name__)
            raise VideoError(502, UNREACHABLE) from None

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> Any | None:
        """Parsed JSON; None on 404; VideoError(502) on any other failure."""
        status, body, _ctype = await self._request("GET", path, params)
        if status == 404:
            return None
        if status in (401, 403):
            log.warning("jellyfin GET %s → HTTP %s (API key rejected?)", path, status)
            raise VideoError(502, KEY_REFUSED)
        if not 200 <= status < 300:
            log.warning("jellyfin GET %s → HTTP %s", path, status)
            raise VideoError(502, UNREACHABLE)
        try:
            return json.loads(body)
        except ValueError:
            raise VideoError(502, UNREACHABLE) from None

    async def kiosk_user(self) -> str:
        device_id = os.environ.get(DEVICE_ID_ENV, "").strip()
        if not device_id:
            self._target()                 # unconfigured → 503 before 409
            fallback = os.environ.get("JELLYFIN_USER_ID", "").strip()
            if fallback and server_is_loopback(jellyfin_base()):
                return fallback
            raise VideoError(409, NOT_SIGNED_IN)
        now = time.monotonic()
        if self._user and self._user[0] == device_id and now - self._user[2] < USER_CACHE_S:
            return self._user[1]
        info = await self._get_json("/Devices/Info", {"id": device_id})
        user_id = info.get("LastUserId") if isinstance(info, dict) else None
        if not isinstance(user_id, str) or not user_id:
            raise VideoError(409, NOT_SIGNED_IN)
        self._user = (device_id, user_id, now)
        return user_id

    async def _get_new_or_old(self, new_path: str, old_path: str,
                              params: dict[str, str]) -> Any | None:
        data = await self._get_json(new_path, params)
        if data is None:
            data = await self._get_json(old_path, params)
        return data

    async def views(self) -> list[dict]:
        uid = await self.kiosk_user()
        data = await self._get_new_or_old("/UserViews", f"/Users/{uid}/Views", {"userId": uid})
        return [normalize_item(i) for i in _items_of(data)]

    async def resume(self) -> list[dict]:
        uid = await self.kiosk_user()
        params = {"userId": uid, "limit": "24", "mediaTypes": "Video", "fields": ITEM_FIELDS}
        data = await self._get_new_or_old("/UserItems/Resume", f"/Users/{uid}/Items/Resume",
                                          params)
        return [normalize_item(i) for i in _items_of(data)]

    async def items(self, *, parent_id: str, types: str, search: str,
                    start: int, limit: int) -> dict:
        uid = await self.kiosk_user()
        params = {"userId": uid, "startIndex": str(start), "limit": str(limit),
                  "fields": ITEM_FIELDS, "sortBy": "ParentIndexNumber,IndexNumber,SortName",
                  "sortOrder": "Ascending"}
        if parent_id:
            params["parentId"] = parent_id
        if types:
            params["includeItemTypes"] = types
        if search:
            params["searchTerm"] = search
        if types or search:
            params["recursive"] = "true"
        data = await self._get_json("/Items", params)
        items = _items_of(data)
        total = data.get("TotalRecordCount") if isinstance(data, dict) else None
        return {"items": [normalize_item(i) for i in items],
                "total": total if isinstance(total, int) else len(items), "start": start}

    async def image(self, item_id: str, max_width: int) -> bytes | None:
        path = _image_cache_dir() / f"{item_id.lower()}-{max_width}.jpg"
        try:
            return path.read_bytes()
        except FileNotFoundError:
            pass
        status, body, ctype = await self._request(
            "GET", f"/Items/{item_id}/Images/Primary",
            {"maxWidth": str(max_width), "format": "Jpg", "quality": "85"})
        if status == 404:
            return None
        if not 200 <= status < 300 or not ctype.startswith("image/"):
            log.warning("jellyfin poster %s → HTTP %s %s", item_id, status, ctype)
            raise VideoError(502, UNREACHABLE)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return body


def _fail(status: int, message: str) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _guard(fn: Handler) -> Handler:
    """VideoError → its status + message; anything unexpected → 502, never 500."""
    @functools.wraps(fn)
    async def wrapper(req: web.Request) -> web.StreamResponse:
        try:
            return await fn(req)
        except VideoError as e:
            return _fail(e.status, e.message)
        except Exception:
            log.exception("video route %s failed", req.path)
            return _fail(502, UNREACHABLE)
    return wrapper


def _int_param(raw: str | None, default: int, lo: int, hi: int) -> int | None:
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        return None
    return v if lo <= v <= hi else None


def _make_handlers(browser: JellyfinBrowser) -> dict[str, Handler]:
    async def views(_req: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "items": await browser.views()})

    async def resume(_req: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "items": await browser.resume()})

    async def items(req: web.Request) -> web.StreamResponse:
        q = req.query
        parent_id = q.get("parent_id", "")
        types = q.get("type", "")
        search = q.get("search", "").strip()
        start = _int_param(q.get("start"), 0, 0, 1_000_000)
        limit = _int_param(q.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
        if ((parent_id and not _ITEM_ID_RE.match(parent_id))
                or (types and not _TYPES_RE.match(types))
                or len(search) > MAX_SEARCH or start is None or limit is None):
            return _fail(400, "bad query")
        page = await browser.items(parent_id=parent_id, types=types, search=search,
                                   start=start, limit=limit)
        return web.json_response({"ok": True, **page})

    async def image(req: web.Request) -> web.StreamResponse:
        item_id = req.match_info["item_id"]
        if not _ITEM_ID_RE.match(item_id):
            return _fail(400, "bad item id")
        data = await browser.image(item_id, image_width(req.query.get("max_width")))
        if data is None:
            return web.Response(status=404)
        return web.Response(body=data, content_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=86400"})

    return {"views": views, "resume": resume, "items": items, "image": image}


def add_routes(app: web.Application, browser: JellyfinBrowser) -> None:
    """Register the browse/poster routes. /video/state and /video/command stay
    in jellyfin_client.py."""
    h = {name: _guard(fn) for name, fn in _make_handlers(browser).items()}
    app.router.add_get("/api/remote/video/views", h["views"])
    app.router.add_get("/api/remote/video/resume", h["resume"])
    app.router.add_get("/api/remote/video/items", h["items"])
    app.router.add_get("/api/remote/video/image/{item_id}", h["image"])
```

In `services/boombox-remote.py` `main()`, after the Task 2 lines add:

```python
        # Jellyfin browse + posters for the LAN app's Video section.
        import remote_video
        video_browser = remote_video.JellyfinBrowser(session)
        remote_video.add_routes(app, video_browser)
```

- [ ] **Step 4: Run the tests and checks**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_video_browse.py services/tests/test_remote_video.py`
Expected: PASS.

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy && ~/.local/bin/mypy --follow-imports=silent services/remote_video.py`
Expected: all pass; `All checks passed!`; `Success: no issues found` twice.

- [ ] **Step 5: Commit**

```bash
git add services/remote_video.py services/boombox-remote.py services/tests/test_remote_video_browse.py
git commit -m "feat(remote): Jellyfin browse + poster proxy as the kiosk's signed-in user

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Video play on the kiosk + track pickers / seek in state and commands

**Files:**
- Modify: `services/remote_video.py` (Task 3 file: imports, constants, `JellyfinBrowser.__init__`, new `kiosk_session`/`play`, `_make_handlers`, `add_routes`)
- Modify: `services/jellyfin_client.py` (constants lines 46–55; `local_session_state` lines 187–204; `_post` lines 206–211; `command` lines 213–247; handler `command` lines 254–266; `_local_session` timeout line 133)
- Modify: `services/boombox-remote.py` (`main()`, the Task 3 `remote_video.add_routes(app, video_browser)` line)
- Test: `services/tests/test_remote_video_play.py` (create); `services/tests/test_jellyfin_client.py`, `services/tests/test_remote_video.py` (append)

**Interfaces:**
- Consumes: Task 3 `JellyfinBrowser._request/_get_json/kiosk_user`, `VideoError`, `_fail`, `_guard`, `_ITEM_ID_RE`; `jellyfin_client._is_loopback_endpoint(endpoint) -> bool`; `actions.fire(dispatcher, "movies", source=...)` (pauses Mopidy and navigates the kiosk to `{jellyfin_base()}/web/index.html#/home` — the existing WATCH action); Jellyfin `GET /Sessions?deviceId=`, `POST /Sessions/{id}/Playing?playCommand=PlayNow&itemIds=&startPositionTicks=`, `POST /Sessions/{id}/Command {"Name": "SetAudioStreamIndex"|"SetSubtitleStreamIndex", "Arguments": {"Index": "<n>"}}`.
- Produces (Python): `JellyfinBrowser(session, *, session_wait_s: float = 20.0, poll_s: float = 1.0)`; `async kiosk_session() -> dict | None` (pinned device's session whose `SupportsRemoteControl is True`; unpinned only on a loopback server, by loopback `RemoteEndPoint`); `async play(item_id: str, start_ticks: int, wake: Callable[[], Awaitable[object]]) -> None`; `add_routes(app, browser, *, wake_kiosk: Callable[[], Awaitable[object]] | None = None)`; `jellyfin_client.value_ok(action: str, value: object) -> bool`.
- Produces (HTTP):
  - `POST /api/remote/video/play {"item_id": "<hex id>", "start_ticks"?: int ≥ 0}` → 200 `{"ok": true}` | 409 `"kiosk not signed in"` (no navigation) | 503 `"video server not configured"` / `"the boombox screen can't be controlled"` | 504 `"the boombox's video player didn't open — try again"` (no live session 20 s after the WATCH navigation) / `"the boombox took too long to start the video — try again"` (30 s overall) | 502 `"video server unreachable"` / `"video server refused to start playback"` | 400 bad body.
  - `GET /api/remote/video/state` (existing) adds `"item_id"`, `"audio_streams": [{"index": int, "label": str}]`, `"subtitle_streams": [...]`, `"audio_index": int | null`, `"subtitle_index": int | null` (`-1`/`null` = off) when `active`.
  - `POST /api/remote/video/command` (existing `{action, value?}`) adds `set_audio {value: index ≥ 0}`, `set_subtitle {value: index ≥ -1}`; `seek {value: seconds ≥ 0}` (absolute; the ±30 s buttons compute it) and `volume {value: 0–100}` are now validated; bad value → 400 `{"ok": false, "error": "bad_value"}` before any Jellyfin call. Upstream timeout 15 s.

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_remote_video_play.py`:

```python
"""POST /api/remote/video/play — kiosk session discovery, WATCH wake, PlayNow."""
from __future__ import annotations

import json

import aiohttp
import pytest
from aiohttp import web

AUTH = {"Authorization": "Bearer t"}
KEY = "sekrit-key-0123456789abcdef"
DEVICE = "boombox-markii-kiosk"
LIVE = {"Id": "5e55", "DeviceId": DEVICE, "SupportsRemoteControl": True,
        "LastActivityDate": "2026-09-29T20:00:00Z"}


class FakeJF:
    def __init__(self) -> None:
        self.device_user: str | None = "u1"
        self.sessions: list[dict] = []
        self.session_queries: list[str] = []
        self.plays: list[tuple[str, dict[str, str]]] = []
        self.play_status = 204
        self.ignore_wake = False

    def app(self) -> web.Application:
        async def handle(req: web.Request) -> web.StreamResponse:
            p = req.path
            if p == "/Devices/Info":
                return web.json_response({"LastUserId": self.device_user})
            if p == "/Sessions":
                self.session_queries.append(req.query_string)
                return web.json_response(self.sessions)
            if p.startswith("/Sessions/") and p.endswith("/Playing"):
                self.plays.append((p, dict(req.query)))
                return web.Response(status=self.play_status)
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        return app


@pytest.fixture
async def play_env(aiohttp_server, aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    key = tmp_path / "jellyfin-api-key"
    key.write_text(KEY)
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", DEVICE)
    monkeypatch.setenv("BOOMBOX_REMOTE_VIDEO_CACHE", str(tmp_path / "video-cache"))
    jf = FakeJF()
    srv = await aiohttp_server(jf.app())
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", str(srv.make_url("")).rstrip("/"))
    woke: list[int] = []

    async def wake() -> None:
        woke.append(1)
        if not jf.ignore_wake:
            jf.sessions = [dict(LIVE)]

    import boombox_remote
    import remote_video
    app = boombox_remote.create_app()
    session = aiohttp.ClientSession()
    browser = remote_video.JellyfinBrowser(session, session_wait_s=0.5, poll_s=0.01)
    remote_video.add_routes(app, browser, wake_kiosk=wake)
    client = await aiohttp_client(app)
    yield client, jf, woke
    await session.close()


async def _play(client, body):
    return await client.post("/api/remote/video/play", json=body, headers=AUTH)


async def test_play_requires_pair_token(play_env):
    client, _jf, _woke = play_env
    r = await client.post("/api/remote/video/play", json={"item_id": "aa11"})
    assert r.status == 401


async def test_play_uses_live_session_without_waking(play_env):
    client, jf, woke = play_env
    jf.sessions = [dict(LIVE)]
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and (await r.json()) == {"ok": True}
    assert woke == []
    assert jf.plays == [("/Sessions/5e55/Playing", {"playCommand": "PlayNow", "itemIds": "aa11"})]
    assert f"deviceId={DEVICE}" in jf.session_queries[0]


async def test_play_passes_start_ticks(play_env):
    client, jf, _woke = play_env
    jf.sessions = [dict(LIVE)]
    r = await _play(client, {"item_id": "aa11", "start_ticks": 7_540_000_000})
    assert r.status == 200
    assert jf.plays[0][1]["startPositionTicks"] == "7540000000"


async def test_play_wakes_kiosk_and_waits_for_session(play_env):
    client, jf, woke = play_env
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200
    assert woke == [1]
    assert jf.plays and jf.plays[0][0] == "/Sessions/5e55/Playing"
    assert len(jf.session_queries) >= 2           # checked, woke, polled


async def test_play_ignores_session_without_remote_control(play_env):
    client, jf, woke = play_env
    jf.sessions = [{**LIVE, "SupportsRemoteControl": False}]   # tab gone, socket closed
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and woke == [1]


async def test_play_ignores_other_devices_sessions(play_env):
    client, jf, woke = play_env
    jf.sessions = [{**LIVE, "Id": "7a7a", "DeviceId": "living-room-tv"}]
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and woke == [1]
    assert all(path == "/Sessions/5e55/Playing" for path, _q in jf.plays)


async def test_play_session_never_appears_is_504(play_env):
    client, jf, woke = play_env
    jf.ignore_wake = True
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 504
    assert (await r.json())["error"] == "the boombox's video player didn't open — try again"
    assert woke == [1] and jf.plays == []


async def test_play_overall_timeout_is_504(play_env, monkeypatch):
    import remote_video
    client, jf, _woke = play_env
    jf.ignore_wake = True
    monkeypatch.setattr(remote_video, "PLAY_TIMEOUT_S", 0.05)
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 504
    assert "took too long" in (await r.json())["error"]


async def test_play_not_signed_in_is_409_and_does_not_wake(play_env):
    client, jf, woke = play_env
    jf.device_user = None
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 409
    assert (await r.json())["error"] == "kiosk not signed in"
    assert woke == [] and jf.plays == []


async def test_play_refused_by_server_is_502(play_env):
    client, jf, _woke = play_env
    jf.sessions = [dict(LIVE)]
    jf.play_status = 500
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 502
    assert (await r.json())["error"] == "video server refused to start playback"


@pytest.mark.parametrize("body", [{}, {"item_id": "../x"}, {"item_id": "aa11", "start_ticks": -1},
                                  {"item_id": "aa11", "start_ticks": "5"},
                                  {"item_id": "aa11", "start_ticks": True}, ["aa11"]])
async def test_play_rejects_bad_bodies(play_env, body):
    client, jf, woke = play_env
    r = await _play(client, body)
    assert r.status == 400 and woke == [] and jf.plays == []


async def test_play_without_kiosk_control_is_503(play_env, aiohttp_client):
    import boombox_remote
    import remote_video
    _client, jf, _woke = play_env
    app = boombox_remote.create_app()
    async with aiohttp.ClientSession() as s:
        remote_video.add_routes(app, remote_video.JellyfinBrowser(s))   # no wake callback
        c = await aiohttp_client(app)
        r = await _play(c, {"item_id": "aa11"})
    assert r.status == 503
    assert (await r.json())["error"] == "the boombox screen can't be controlled"
    assert jf.plays == []


async def test_unpinned_builtin_server_uses_loopback_session(play_env, monkeypatch):
    client, jf, woke = play_env
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    monkeypatch.setenv("JELLYFIN_USER_ID", "u1")
    jf.sessions = [{**LIVE, "Id": "7a7a", "DeviceId": "tv", "RemoteEndPoint": "192.168.1.9"},
                   {**LIVE, "Id": "5e55", "DeviceId": "x", "RemoteEndPoint": "127.0.0.1"}]
    r = await _play(client, {"item_id": "aa11"})
    assert r.status == 200 and woke == []
    assert jf.plays[0][0] == "/Sessions/5e55/Playing"
```

Append to `services/tests/test_jellyfin_client.py` (add `import json` to its imports):

```python
async def test_state_reports_streams_and_indexes(fake_jf):
    s = _sess("kiosk", ep="127.0.0.1")
    s["NowPlayingItem"] = {
        "Id": "bb22", "Name": "Pilot", "RunTimeTicks": 26_000_000_000,
        "MediaStreams": [
            {"Type": "Video", "Index": 0, "DisplayTitle": "1080p H264"},
            {"Type": "Audio", "Index": 1, "DisplayTitle": "English - AAC - Stereo"},
            {"Type": "Audio", "Index": 2, "Language": "fre"},
            {"Type": "Subtitle", "Index": 3, "DisplayTitle": "English - SUBRIP"},
            {"Type": "Subtitle", "Index": 4},
        ]}
    s["PlayState"] = {"PositionTicks": 120_000_000, "IsPaused": True,
                      "AudioStreamIndex": 1, "SubtitleStreamIndex": -1}
    fake_jf["sessions"] = [s]
    async with aiohttp.ClientSession() as http:
        st = await JellyfinClient(http).local_session_state()
    assert st["item_id"] == "bb22" and st["playing"] is False and st["position_s"] == 12
    assert st["audio_streams"] == [{"index": 1, "label": "English - AAC - Stereo"},
                                   {"index": 2, "label": "fre"}]
    assert st["subtitle_streams"] == [{"index": 3, "label": "English - SUBRIP"},
                                      {"index": 4, "label": "Track 4"}]
    assert st["audio_index"] == 1 and st["subtitle_index"] == -1


async def test_set_audio_and_subtitle_commands(fake_jf):
    async with aiohttp.ClientSession() as http:
        c = JellyfinClient(http)
        assert await c.command("set_audio", 2) == {"ok": True}
        assert await c.command("set_subtitle", -1) == {"ok": True}
    assert [p for p, _q, _b in fake_jf["posts"]] == ["/Sessions/kiosk/Command"] * 2
    assert [json.loads(b) for _p, _q, b in fake_jf["posts"]] == [
        {"Name": "SetAudioStreamIndex", "Arguments": {"Index": "2"}},
        {"Name": "SetSubtitleStreamIndex", "Arguments": {"Index": "-1"}},
    ]


@pytest.mark.parametrize("action,value", [
    ("set_audio", -1), ("set_audio", "2"), ("set_audio", True), ("set_subtitle", -2),
    ("seek", -5), ("seek", None), ("volume", 101), ("volume", None),
])
async def test_bad_values_never_reach_jellyfin(fake_jf, action, value):
    async with aiohttp.ClientSession() as http:
        res = await JellyfinClient(http).command(action, value)
    assert res == {"ok": False, "error": "bad_value"}
    assert fake_jf["posts"] == []
```

Append to `services/tests/test_remote_video.py`:

```python
@pytest.mark.asyncio
async def test_command_handler_validates_values(video_app, aiohttp_client):
    import jellyfin_client
    fake = FakeJellyfin()
    jellyfin_client.add_routes(video_app, fake)
    client = await aiohttp_client(video_app)
    for body in ({"action": "set_subtitle", "value": -2},
                 {"action": "set_audio", "value": "1"},
                 {"action": "seek", "value": -1}):
        resp = await client.post("/api/remote/video/command", json=body,
                                 headers={"Authorization": "Bearer t"})
        assert resp.status == 400, body
        assert (await resp.json())["error"] == "bad_value"
    resp = await client.post("/api/remote/video/command",
                             json={"action": "set_subtitle", "value": -1},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert fake.commands == [("set_subtitle", -1)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_video_play.py services/tests/test_jellyfin_client.py services/tests/test_remote_video.py`
Expected: FAIL — `TypeError: add_routes() got an unexpected keyword argument 'wake_kiosk'` / `JellyfinBrowser.__init__() got an unexpected keyword argument 'session_wait_s'`, `KeyError: 'item_id'`, and `bad_value` assertion failures.

- [ ] **Step 3: Implement**

`services/jellyfin_client.py`:

Replace lines 46–55 (from `_TICKS_PER_SECOND = 10_000_000` through `_VALID_ACTIONS = …`) with:

```python
_TICKS_PER_SECOND = 10_000_000
# Upstream timeout for every Jellyfin call (spec: proxies time out at 15 s).
_TIMEOUT = aiohttp.ClientTimeout(total=15)

# action → (HTTP path suffix under /Sessions/{id}/Playing, or "Command")
_PLAYING_ACTIONS = {
    "play_pause": "PlayPause",
    "stop": "Stop",
    "next": "NextTrack",
    "previous": "PreviousTrack",
}
_STREAM_COMMANDS = {"set_audio": "SetAudioStreamIndex",
                    "set_subtitle": "SetSubtitleStreamIndex"}
_VALID_ACTIONS = set(_PLAYING_ACTIONS) | {"seek", "volume", "mute"} | set(_STREAM_COMMANDS)


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def value_ok(action: str, value: object) -> bool:
    """Per-action value check, done before any Jellyfin call. Subtitle -1
    turns subtitles off (Jellyfin's convention)."""
    n = _num(value)
    if action == "seek":
        return n is not None and n >= 0
    if action == "volume":
        return n is not None and 0 <= n <= 100
    if action == "set_audio":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if action == "set_subtitle":
        return isinstance(value, int) and not isinstance(value, bool) and value >= -1
    return True


def _streams(item: dict, kind: str) -> list[dict]:
    out: list[dict] = []
    for s in item.get("MediaStreams") or []:
        if isinstance(s, dict) and s.get("Type") == kind and isinstance(s.get("Index"), int):
            label = s.get("DisplayTitle") or s.get("Language") or f"Track {s['Index']}"
            out.append({"index": s["Index"], "label": str(label)})
    return out
```

In `_local_session` (line 133) change `timeout=aiohttp.ClientTimeout(total=2)` to `timeout=_TIMEOUT`.

Replace the `return {...}` of `local_session_state` (lines 196–204) with:

```python
        return {
            "active": True,
            "playing": not play.get("IsPaused", False),
            "title": item.get("Name"),
            "item_id": item.get("Id"),
            "position_s": position_ticks // _TICKS_PER_SECOND,
            "duration_s": runtime_ticks // _TICKS_PER_SECOND,
            "volume": play.get("VolumeLevel"),
            "muted": bool(play.get("IsMuted", False)),
            "audio_streams": _streams(item, "Audio"),
            "subtitle_streams": _streams(item, "Subtitle"),
            "audio_index": play.get("AudioStreamIndex"),
            "subtitle_index": play.get("SubtitleStreamIndex"),
        }
```

In `_post` (line 210) change `timeout=aiohttp.ClientTimeout(total=2)` to `timeout=_TIMEOUT`.

Replace `command` (lines 213–247) with:

```python
    async def command(self, action: str, value=None) -> dict:
        """Map a remote command onto the Jellyfin session API."""
        if action not in _VALID_ACTIONS:
            return {"ok": False, "error": f"unknown_action:{action}"}
        if not value_ok(action, value):
            return {"ok": False, "error": "bad_value"}
        headers = self._headers()
        if headers is None:
            return {"ok": False, "error": "jellyfin_unconfigured"}
        s = await self._local_session()
        if s is None:
            return {"ok": False, "error": "no_session"}
        sid = s.get("Id")
        base = f"{jellyfin_base()}/Sessions/{sid}"
        try:
            if action in _PLAYING_ACTIONS:
                status = await self._post(
                    f"{base}/Playing/{_PLAYING_ACTIONS[action]}", headers)
            elif action == "seek":
                ticks = int(float(value) * _TICKS_PER_SECOND)
                status = await self._post(
                    f"{base}/Playing/Seek?seekPositionTicks={ticks}", headers)
            elif action == "volume":
                status = await self._post(
                    f"{base}/Command", headers,
                    {"Name": "SetVolume", "Arguments": {"Volume": str(int(value))}})
            elif action in _STREAM_COMMANDS:
                status = await self._post(
                    f"{base}/Command", headers,
                    {"Name": _STREAM_COMMANDS[action], "Arguments": {"Index": str(int(value))}})
            else:  # mute
                status = await self._post(
                    f"{base}/Command", headers, {"Name": "ToggleMute"})
        except Exception as e:
            log.warning("jellyfin command %s failed: %s", action, e)
            return {"ok": False, "error": "jellyfin_unreachable"}
        if not 200 <= status < 300:
            log.warning("jellyfin command %s → HTTP %s", action, status)
            return {"ok": False, "error": f"jellyfin_http_{status}"}
        return {"ok": True}
```

In the handler `command` (inside `_make_handlers`, lines 254–266), replace the body after the `bad_action` check with:

```python
        value = (body or {}).get("value")
        if not value_ok(action, value):
            return web.json_response({"ok": False, "error": "bad_value"}, status=400)
        result = await client.command(action, value)
        status = 200 if result.get("ok") else 502
        return web.json_response(result, status=status)
```

`services/remote_video.py`:

Change the `jellyfin_client` import line to:

```python
from jellyfin_client import DEVICE_ID_ENV, _is_loopback_endpoint, server_is_loopback
```

After `KEY_REFUSED = …` add:

```python
PLAY_TIMEOUT_S = 30.0          # whole POST /play, wake + wait included
SESSION_WAIT_S = 20.0          # kiosk session to appear after the WATCH navigation
SESSION_POLL_S = 1.0
NO_SESSION = "the boombox's video player didn't open — try again"
NO_KIOSK = "the boombox screen can't be controlled"
PLAY_REFUSED = "video server refused to start playback"
TIMED_OUT = "the boombox took too long to start the video — try again"
_SESSION_ID_RE = re.compile(r"^[0-9A-Za-z-]{1,64}$")
WakeKiosk = Callable[[], Awaitable[object]]
```

Replace `JellyfinBrowser.__init__` with:

```python
    def __init__(self, session: aiohttp.ClientSession, *,
                 session_wait_s: float = SESSION_WAIT_S,
                 poll_s: float = SESSION_POLL_S) -> None:
        self._sess = session
        self._user: tuple[str, str, float] | None = None   # (device, user, fetched)
        self._session_wait_s = session_wait_s
        self._poll_s = poll_s
```

Add these methods at the end of `JellyfinBrowser`:

```python
    async def kiosk_session(self) -> dict | None:
        """The kiosk's Jellyfin session, only while its web client holds a live
        remote-control socket (SupportsRemoteControl is True). A session left
        behind when the kiosk navigated away has lost its socket, so it is not
        trusted with PlayNow. Unpinned, only an on-device server may pick a
        loopback client; otherwise nothing."""
        device_id = os.environ.get(DEVICE_ID_ENV, "").strip()
        data = await self._get_json("/Sessions", {"deviceId": device_id} if device_id else None)
        sessions = [s for s in data if isinstance(s, dict)] if isinstance(data, list) else []
        if device_id:
            pool = [s for s in sessions if s.get("DeviceId") == device_id]
        elif server_is_loopback(jellyfin_base()):
            pool = [s for s in sessions if _is_loopback_endpoint(s.get("RemoteEndPoint"))]
        else:
            pool = []
        pool = [s for s in pool if s.get("SupportsRemoteControl") is True
                and isinstance(s.get("Id"), str) and _SESSION_ID_RE.match(s["Id"])]
        if not pool:
            return None
        return max(pool, key=lambda s: str(s.get("LastActivityDate") or ""))

    async def play(self, item_id: str, start_ticks: int, wake: WakeKiosk) -> None:
        """PlayNow on the kiosk. If its video player isn't up, run the WATCH
        action (navigate the kiosk to Jellyfin) and wait for the session."""
        await self.kiosk_user()                        # 503 / 409 before touching the kiosk
        sess = await self.kiosk_session()
        if sess is None:
            await wake()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._session_wait_s
            while sess is None and loop.time() < deadline:
                await asyncio.sleep(self._poll_s)
                sess = await self.kiosk_session()
            if sess is None:
                raise VideoError(504, NO_SESSION)
        params = {"playCommand": "PlayNow", "itemIds": item_id}
        if start_ticks > 0:
            params["startPositionTicks"] = str(start_ticks)
        status, _body, _ctype = await self._request("POST", f"/Sessions/{sess['Id']}/Playing",
                                                    params)
        if not 200 <= status < 300:
            log.warning("jellyfin PlayNow → HTTP %s", status)
            raise VideoError(502, PLAY_REFUSED)
```

Replace `_make_handlers` and `add_routes` with:

```python
async def _cannot_wake() -> object:
    raise VideoError(503, NO_KIOSK)


def _make_handlers(browser: JellyfinBrowser, wake: WakeKiosk) -> dict[str, Handler]:
    async def views(_req: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "items": await browser.views()})

    async def resume(_req: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "items": await browser.resume()})

    async def items(req: web.Request) -> web.StreamResponse:
        q = req.query
        parent_id = q.get("parent_id", "")
        types = q.get("type", "")
        search = q.get("search", "").strip()
        start = _int_param(q.get("start"), 0, 0, 1_000_000)
        limit = _int_param(q.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
        if ((parent_id and not _ITEM_ID_RE.match(parent_id))
                or (types and not _TYPES_RE.match(types))
                or len(search) > MAX_SEARCH or start is None or limit is None):
            return _fail(400, "bad query")
        page = await browser.items(parent_id=parent_id, types=types, search=search,
                                   start=start, limit=limit)
        return web.json_response({"ok": True, **page})

    async def image(req: web.Request) -> web.StreamResponse:
        item_id = req.match_info["item_id"]
        if not _ITEM_ID_RE.match(item_id):
            return _fail(400, "bad item id")
        data = await browser.image(item_id, image_width(req.query.get("max_width")))
        if data is None:
            return web.Response(status=404)
        return web.Response(body=data, content_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=86400"})

    async def play(req: web.Request) -> web.StreamResponse:
        try:
            body = await req.json()
        except Exception:
            return _fail(400, "invalid_json")
        if not isinstance(body, dict):
            return _fail(400, "expected a JSON object")
        item_id = body.get("item_id")
        start = body.get("start_ticks", 0)
        if not isinstance(item_id, str) or not _ITEM_ID_RE.match(item_id):
            return _fail(400, "bad item id")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            return _fail(400, "start_ticks must be a non-negative integer")
        try:
            await asyncio.wait_for(browser.play(item_id, start, wake), PLAY_TIMEOUT_S)
        except asyncio.TimeoutError:
            return _fail(504, TIMED_OUT)
        return web.json_response({"ok": True})

    return {"views": views, "resume": resume, "items": items, "image": image, "play": play}


def add_routes(app: web.Application, browser: JellyfinBrowser, *,
               wake_kiosk: WakeKiosk | None = None) -> None:
    """Register browse/poster/play. `wake_kiosk` runs the WATCH action (kiosk →
    Jellyfin); without it, play only works while the player is already up.
    /video/state and /video/command stay in jellyfin_client.py."""
    handlers = _make_handlers(browser, wake_kiosk or _cannot_wake)
    h = {name: _guard(fn) for name, fn in handlers.items()}
    app.router.add_get("/api/remote/video/views", h["views"])
    app.router.add_get("/api/remote/video/resume", h["resume"])
    app.router.add_get("/api/remote/video/items", h["items"])
    app.router.add_get("/api/remote/video/image/{item_id}", h["image"])
    app.router.add_post("/api/remote/video/play", h["play"])
```

(`PLAY_TIMEOUT_S` is read at call time, so the test can shrink it.)

In `services/boombox-remote.py` `main()` replace `remote_video.add_routes(app, video_browser)` with:

```python
        remote_video.add_routes(
            app, video_browser,
            # "Play on the boombox" with the kiosk on the music UI: run the
            # WATCH action (pause Mopidy, navigate the kiosk to Jellyfin).
            wake_kiosk=lambda: actions.fire(dispatcher, "movies",
                                            source="remote:video-play"))
```

- [ ] **Step 4: Run the tests and checks**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_video_play.py services/tests/test_remote_video_browse.py services/tests/test_jellyfin_client.py services/tests/test_remote_video.py`
Expected: PASS.

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy && ~/.local/bin/mypy --follow-imports=silent services/remote_video.py services/remote_home.py services/jellyfin_client.py`
Expected: all pass; `All checks passed!`; `Success: no issues found` twice.

- [ ] **Step 5: Commit**

```bash
git add services/remote_video.py services/jellyfin_client.py services/boombox-remote.py \
  services/tests/test_remote_video_play.py services/tests/test_jellyfin_client.py \
  services/tests/test_remote_video.py
git commit -m "feat(remote): play Jellyfin items on the kiosk (WATCH wake + wait) and audio/subtitle/seek control

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: nginx split, OTA-safe site + snippet sync, sudoers

**Why a helper action, not a sudoers `install` rule for the site file:** the site file needs `__REMOTE_WEB_PORT__` rendered. A sudoers rule would have to name a user-writable rendered path (the boombox user could put anything there) and could only install one file at a time. The root helper (`/usr/local/sbin/boombox-setup-apply`, already NOPASSWD, stdin-JSON only, no argv) reads the port from the root-owned `/etc/boombox/web-auth.env` (validated 1–65535), renders from the fixed `/opt/boombox/current/install/config/` templates (the same trust the existing snippet rule already gives the release tree), installs the site file **and** the snippet together, runs `nginx -t`, and restores both previous files if it fails. That matters because the kiosk's `location /` now lives in the site file: a new snippet next to an old site file leaves the kiosk without a UI, and an old snippet next to a new site file duplicates `location /` (nginx -t fails; the next nginx restart would fail). For the same reason the old snippet-only sudoers `install` grant is **removed** — an older release's `swap` would otherwise install its snippet next to this release's site file. Cost: the helper is root-owned and only refreshed by `install.sh` (or by hand, Task 11), so a device with an old helper keeps its old nginx pair (kiosk intact) and the new `verify` probe fails → the updater rolls the release back instead of half-applying it.

**Files:**
- Modify: `install/config/nginx.conf` (whole file)
- Modify: `install/config/nginx-boombox-common.conf` (whole file)
- Modify: `install/bin/boombox-setup-apply` (header action list ~line 17–29; constants after `HTPASSWD` line 51; new functions before `ACTIONS` line 881; `ACTIONS`)
- Modify: `install/apply-release.sh` (new `nginx_sync()` after `fail()` line 34; `swap` lines 162–177; `verify` probes lines 292–293; `revert` after `systemctl --user daemon-reload` ~line 332)
- Modify: `install/sudoers/boombox` (nginx comment + rule, lines 19–23)
- Delete: `services/tests/test_nginx_accounts.py`
- Test: `services/tests/test_nginx_lan_app.py`, `services/tests/test_setup_helper_nginx.py`, `services/tests/test_apply_release_nginx.py` (create)

**Interfaces:**
- Produces (helper): `{"action": "nginx-sync"}` → `{"ok": true, "changed": bool}` | `{"ok": false, "error": "nginx rejected the new config; the previous one was restored", "detail": "<last nginx -t line>"}` | `{"ok": false, "error": "BOOMBOX_WEB_PORT in web-auth.env is not a port number"}`. Pure: `web_port() -> str`, `render_site(template: str, port: str) -> str`. Constants `NGINX_SITE`, `NGINX_SNIPPET`, `RELEASE_CONFIG_DIR`, `NGINX_BIN`.
- Produces (nginx, LAN server): `GET /` + any unmatched path → `remote-ui/dist` (`index.html` fallback, `no-cache`, no auth); `/app-assets/*` → hashed bundles (`immutable`, no auth); `/remote`, `/remote/*` → `301 /?from=remote`; `/remote/sw.js` → `remote-ui/dist/legacy-remote-sw.js` (created in Task 10; 404 until then); `/accounts`, `/accounts/*` → `301 /#/accounts`. Loopback server: `/` → kiosk `ui/dist` as before.
- Produces (apply-release.sh): `nginx_sync` shell function used by `swap` and `revert`; `verify` probes `http://127.0.0.1:<BOOMBOX_WEB_PORT>/`.
- Consumes: Task 1 (the service now enforces the admin session, so `/api/accounts/` can drop Basic auth).

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_nginx_lan_app.py`:

```python
"""Static checks: kiosk vs LAN app server blocks, redirects, shared snippet."""
from __future__ import annotations

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "install" / "config"
SITE = (CONFIG / "nginx.conf").read_text()
SNIPPET = (CONFIG / "nginx-boombox-common.conf").read_text()


def _block_at(text: str, start: int) -> str:
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise ValueError("unbalanced braces")


def _servers() -> tuple[str, str]:
    starts = [m.start() for m in re.finditer(r"^server \{", SITE, re.M)]
    kiosk, lan = (_block_at(SITE, s) for s in starts)
    return kiosk, lan


def _location(block: str, header: str) -> str:
    return _block_at(block, block.index(header))


def test_kiosk_server_serves_kiosk_ui_at_root():
    kiosk, _ = _servers()
    assert "listen 127.0.0.1:80 default_server;" in kiosk
    assert "root /opt/boombox/current/ui/dist;" in kiosk
    assert "try_files $uri $uri/ /index.html;" in _location(kiosk, "location / {")
    assert "try_files $uri =404;" in _location(kiosk, r"location ~* \.(?:js|css")
    assert "include /etc/nginx/snippets/boombox-common.conf;" in kiosk
    assert "auth_basic" not in kiosk


def test_lan_server_serves_the_app_without_basic_auth():
    _, lan = _servers()
    assert "listen __REMOTE_WEB_PORT__ default_server;" in lan
    assert 'auth_basic "Boombox";' in lan              # everything else keeps it
    assert "root /opt/boombox/current/remote-ui/dist;" in lan
    root = _location(lan, "location / {")
    assert "auth_basic off;" in root and "try_files $uri $uri/ /index.html;" in root
    assert 'add_header Cache-Control "no-cache" always;' in root
    assets = _location(lan, "location ^~ /app-assets/ {")
    assert "auth_basic off;" in assets and "immutable" in assets
    assert "try_files $uri =404;" in assets
    assert "include /etc/nginx/snippets/boombox-common.conf;" in lan


def test_lan_redirects_old_urls_into_the_app():
    _, lan = _servers()
    for header in ("location = /remote {", "location ^~ /remote/ {"):
        loc = _location(lan, header)
        assert "auth_basic off;" in loc and "return 301 /?from=remote;" in loc
    for header in ("location = /accounts {", "location ^~ /accounts/ {"):
        loc = _location(lan, header)
        assert "auth_basic off;" in loc and "return 301 /#/accounts;" in loc


def test_old_pwa_service_worker_gets_kill_switch():
    _, lan = _servers()
    loc = _location(lan, "location = /remote/sw.js {")
    assert "auth_basic off;" in loc
    assert "try_files /legacy-remote-sw.js =404;" in loc
    assert 'add_header Cache-Control "no-cache" always;' in loc


def test_snippet_no_longer_owns_the_root_or_old_pages():
    assert not re.search(r"^root ", SNIPPET, re.M)
    assert "location / {" not in SNIPPET
    assert r"location ~* \.(?:js" not in SNIPPET
    assert "/remote/" not in re.sub(r"/api/remote/", "", SNIPPET)
    assert "location ^~ /accounts/" not in SNIPPET
    assert "accounts.html" not in SNIPPET


def test_api_accounts_relies_on_the_admin_session():
    b = _location(SNIPPET, "location /api/accounts/ {")
    assert "auth_basic off;" in b
    assert "proxy_pass http://127.0.0.1:6689/api/accounts/;" in b
    assert "proxy_set_header X-Real-IP $remote_addr;" in b
    assert "proxy_set_header X-Boombox-Host $http_host;" in b
    assert "X-Boombox-User" not in b
    assert "Authorization" not in b                    # the admin bearer token must pass


def test_other_lan_routes_keep_basic_auth():
    for header in ("location /api/ {", "location /mopidy/ {", "location /api/library/ {",
                   "location /api/update/ {", "location /api/buttons/ {"):
        assert "auth_basic off" not in _location(SNIPPET, header), header
    for header in ("location /api/remote/ {", "location /api/setup/ {",
                   "location ^~ /setup/ {", "location ^~ /local/ {"):
        assert "auth_basic off;" in _location(SNIPPET, header), header
```

Create `services/tests/test_setup_helper_nginx.py`:

```python
"""boombox-setup-apply nginx-sync: site + snippet installed together."""
from __future__ import annotations

import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    loader = SourceFileLoader("boombox_setup_apply_nginx", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()


@pytest.fixture
def box(tmp_path, monkeypatch):
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / "nginx.conf").write_text("server { listen __REMOTE_WEB_PORT__; }\n")
    (rel / "nginx-boombox-common.conf").write_text("location /api/ {}\n")
    etc = tmp_path / "etc"
    (etc / "sites-available").mkdir(parents=True)
    (etc / "snippets").mkdir()
    site = etc / "sites-available" / "boombox"
    snip = etc / "snippets" / "boombox-common.conf"
    site.write_text("OLD SITE\n")
    snip.write_text("OLD SNIPPET\n")
    auth = tmp_path / "web-auth.env"
    auth.write_text("BOOMBOX_WEB_PORT=8091\nBOOMBOX_WEB_PASSWORD=x\n")
    monkeypatch.setattr(helper, "RELEASE_CONFIG_DIR", str(rel))
    monkeypatch.setattr(helper, "NGINX_SITE", str(site))
    monkeypatch.setattr(helper, "NGINX_SNIPPET", str(snip))
    monkeypatch.setattr(helper, "WEB_AUTH_ENV", str(auth))
    runs: list[list[str]] = []
    result = {"rc": 0, "err": ""}

    def fake_run(cmd, timeout=25, check=False, inp=None):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, result["rc"], "", result["err"])

    monkeypatch.setattr(helper, "_run", fake_run)
    return {"site": site, "snip": snip, "auth": auth, "runs": runs, "result": result}


def test_installs_rendered_site_and_snippet_together(box):
    r = helper.action_nginx_sync({})
    assert r == {"ok": True, "changed": True}
    assert box["site"].read_text() == "server { listen 8091; }\n"
    assert box["snip"].read_text() == "location /api/ {}\n"
    assert box["runs"] == [[helper.NGINX_BIN, "-t"]]


def test_unchanged_pair_is_a_noop(box):
    helper.action_nginx_sync({})
    box["runs"].clear()
    assert helper.action_nginx_sync({}) == {"ok": True, "changed": False}
    assert box["runs"] == []


def test_restores_both_files_when_nginx_t_fails(box):
    box["result"].update(rc=1, err='nginx: [emerg] duplicate location "/" in x:3\n')
    r = helper.action_nginx_sync({})
    assert r["ok"] is False and "restored" in r["error"]
    assert "duplicate location" in r["detail"]
    assert box["site"].read_text() == "OLD SITE\n"
    assert box["snip"].read_text() == "OLD SNIPPET\n"


def test_restore_removes_a_file_that_did_not_exist(box):
    box["site"].unlink()
    box["result"].update(rc=1, err="bad")
    helper.action_nginx_sync({})
    assert not box["site"].exists()
    assert box["snip"].read_text() == "OLD SNIPPET\n"


def test_port_defaults_to_8090(box):
    box["auth"].write_text("BOOMBOX_WEB_PASSWORD=x\n")
    helper.action_nginx_sync({})
    assert "listen 8090;" in box["site"].read_text()


@pytest.mark.parametrize("bad", ["80;evil", "0", "65536", "80 443", "-1", "abc"])
def test_rejects_bad_port_and_touches_nothing(box, bad):
    box["auth"].write_text(f"BOOMBOX_WEB_PORT={bad}\n")
    with pytest.raises(ValueError):
        helper.action_nginx_sync({})
    assert box["site"].read_text() == "OLD SITE\n" and box["runs"] == []


def test_action_is_registered():
    assert helper.ACTIONS["nginx-sync"] is helper.action_nginx_sync
```

Create `services/tests/test_apply_release_nginx.py`:

```python
"""apply-release.sh keeps the nginx site + snippet in step; sudoers can't desync them."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "install" / "apply-release.sh").read_text()
SUDOERS = (ROOT / "install" / "sudoers" / "boombox").read_text()


def _case(name: str) -> str:
    start = SCRIPT.index(f"\n  {name})\n")
    return SCRIPT[start:SCRIPT.index("\n    ;;\n", start)]


def _function(name: str) -> str:
    start = SCRIPT.index(f"\n{name}() {{\n")
    return SCRIPT[start:SCRIPT.index("\n}\n", start)]


def test_nginx_sync_goes_through_the_root_helper():
    fn = _function("nginx_sync")
    assert '{"action":"nginx-sync"}' in fn
    assert "sudo -n /usr/local/sbin/boombox-setup-apply" in fn


def test_swap_and_revert_sync_the_pair_never_the_snippet_alone():
    for name in ("swap", "revert"):
        body = _case(name)
        assert "nginx_sync" in body, name
        assert "/etc/nginx/snippets/boombox-common.conf" not in body, name


def test_verify_probes_the_lan_app_not_remote():
    body = _case("verify")
    assert "http://localhost/remote/" not in body
    assert 'probe "http://127.0.0.1:$lan_port/"' in body
    assert "BOOMBOX_WEB_PORT" in body


def test_sudoers_has_no_snippet_only_install_grant():
    assert "boombox-common.conf" not in SUDOERS
    assert "/usr/sbin/nginx -t" in SUDOERS
    assert "NOPASSWD: /usr/local/sbin/boombox-setup-apply" in SUDOERS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_nginx_lan_app.py services/tests/test_setup_helper_nginx.py services/tests/test_apply_release_nginx.py`
Expected: FAIL — `ValueError: not enough values to unpack` / `substring not found` (nginx), `AttributeError: … has no attribute 'RELEASE_CONFIG_DIR'` (helper), `ValueError: substring not found` for `nginx_sync` (script).

- [ ] **Step 3: Implement**

Replace `install/config/nginx.conf` with:

```nginx
# /etc/nginx/sites-available/boombox  (installed by install.sh; re-synced on
# every release swap/revert by `boombox-setup-apply` action `nginx-sync`,
# together with the shared snippet — the two must always match)
#
# Local kiosk (loopback :80, no auth):
#   /                   → the kiosk UI (ui/dist)
#
# LAN (:__REMOTE_WEB_PORT__):
#   /, /app-assets/     → the LAN app (remote-ui/dist), no Basic auth: pairing
#                         gates /api/remote/, the admin session /api/accounts/
#   /remote/*, /accounts/* → redirects into the app
#   everything else     → HTTP Basic auth, as before
#
# Routes both servers share live in /etc/nginx/snippets/boombox-common.conf.

map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 127.0.0.1:80 default_server;
    listen [::1]:80 default_server;
    server_name localhost;

    # The kiosk SPA. Lives here, not in the snippet, since the LAN server
    # serves the LAN app at / instead.
    root /opt/boombox/current/ui/dist;
    index index.html;

    # SPA: every unmatched path returns index.html so client routing works.
    location / {
        try_files $uri $uri/ /index.html;
        # No HTML caching — UI updates land instantly after a deploy.
        add_header Cache-Control "no-cache" always;
    }

    # Hashed Vite assets get an aggressive cache.
    location ~* \.(?:js|css|woff2?|ttf|otf|svg|png|jpg|jpeg|gif|webp)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    include /etc/nginx/snippets/boombox-common.conf;
}

server {
    listen __REMOTE_WEB_PORT__ default_server;
    listen [::]:__REMOTE_WEB_PORT__ default_server;
    server_name _;

    auth_basic "Boombox";
    auth_basic_user_file /etc/nginx/boombox.htpasswd;

    # The LAN app (remote-ui, built with base "/" and assetsDir "app-assets").
    # auth_basic off: phones/desktops land straight on the app; its APIs are
    # gated by pairing (/api/remote/) and the admin session (/api/accounts/).
    root /opt/boombox/current/remote-ui/dist;
    index index.html;

    location / {
        auth_basic off;
        try_files $uri $uri/ /index.html;
        # index.html, sw.js and the manifest must be refetched after a deploy.
        add_header Cache-Control "no-cache" always;
    }

    # Hashed bundles. `^~` keeps them away from any regex location.
    location ^~ /app-assets/ {
        auth_basic off;
        expires 7d;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # The phone remote moved from /remote/ to /. `from=remote` lets the app
    # show a one-time "reinstall from this address" hint.
    location = /remote {
        auth_basic off;
        return 301 /?from=remote;
    }

    # An installed old PWA keeps its /remote/ service worker, which would
    # serve the cached old app forever (a redirected sw.js update fails). A
    # kill-switch worker at the same URL unregisters it and sends the tab to
    # the new app. `=` beats the `^~ /remote/` redirect below.
    location = /remote/sw.js {
        auth_basic off;
        default_type application/javascript;
        add_header Cache-Control "no-cache" always;
        try_files /legacy-remote-sw.js =404;
    }

    location ^~ /remote/ {
        auth_basic off;
        return 301 /?from=remote;
    }

    # The Accounts page is now Admin → Accounts inside the app.
    location = /accounts {
        auth_basic off;
        return 301 /#/accounts;
    }

    location ^~ /accounts/ {
        auth_basic off;
        return 301 /#/accounts;
    }

    include /etc/nginx/snippets/boombox-common.conf;
}
```

Replace `install/config/nginx-boombox-common.conf` with:

```nginx
# /etc/nginx/snippets/boombox-common.conf — routes shared by the kiosk
# (loopback :80) and LAN (:8090) server blocks in sites-available/boombox.
# `root` and `location /` are NOT here: each server block serves its own app
# at / (kiosk UI vs the LAN app). Installed together with the site file by
# `boombox-setup-apply nginx-sync` — never on its own.

# Compress JSON/JS/CSS/SVG. The library browse response is ~700 KB raw
# for a Navidrome catalog of ~8.7 k albums and shrinks to ~80 KB gzipped;
# every UI render previously paid the full uncompressed transfer.
# Skip images/audio (already compressed). min_length avoids the
# gzip-header overhead on tiny bodies.
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_proxied any;
gzip_comp_level 5;
gzip_types
    application/json
    application/javascript
    application/xml
    text/css
    text/plain
    text/xml
    image/svg+xml;

# Mopidy HTTP + WebSocket (Iris + JSON-RPC).
location /mopidy/ {
    proxy_pass http://127.0.0.1:6680/mopidy/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
}

# boombox-state aggregator (MPRIS + /api/* helpers).
location /api/ {
    proxy_pass http://127.0.0.1:6681/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 30s;
}

# boombox-buttons settings API (config, learn, test).
location /api/buttons/ {
    proxy_pass http://127.0.0.1:6684/;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_read_timeout 30s;
}

# boombox-updater HTTP API (status, config, install, rollback, log).
location /api/update/ {
    proxy_pass http://127.0.0.1:6686/;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_read_timeout 5m;
    # SSE streams the install log on POST /api/update/install.
    proxy_buffering off;
}

# boombox-library HTTP API (catalog browse/search, pin, sync, resolver).
location /api/library/ {
    proxy_pass http://127.0.0.1:6687/api/library/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 30s;
}

# boombox-rfid HTTP API (bindings CRUD + last-unbound-tap polling).
location /api/rfid/ {
    proxy_pass http://127.0.0.1:6688/api/rfid/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 10s;
}

# boombox-setup first-run wizard API. auth_basic off so the setup page works
# from a phone before the user knows the LAN password; the service itself gates
# mutating routes on a setup token (minted on the kiosk, shown as a QR) or a
# localhost origin — hence X-Real-IP is forwarded so the service can tell the
# kiosk apart from a LAN client. The service also refuses non-JSON mutations
# (CSRF) and, once setup is complete, every write until the kiosk re-opens
# setup; see services/boombox_setup/api.py. wifi scans can take ~30s.
location /api/setup/ {
    auth_basic off;
    proxy_pass http://127.0.0.1:6689/api/setup/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 90s;
}

# The setup wizard SPA — static build served from the release tree.
# auth_basic off + `^~` so no regex location hijacks /setup/assets/*.js.
# Reachable from the kiosk on :80 and from a phone/laptop on :8090.
location = /setup {
    auth_basic off;
    return 301 /setup/;
}

location ^~ /setup/ {
    auth_basic off;
    alias /opt/boombox/current/setup-ui/dist/;
    # URI-form fallback: a /-prefixed last arg is an internal-redirect URI,
    # not a filesystem path.
    try_files $uri $uri/ /setup/index.html;
    add_header Cache-Control "no-cache" always;
}

# Admin → Accounts API (boombox-setup). auth_basic off: the service enforces
# the admin session itself (bearer token from POST /api/accounts/session,
# which checks the web password) and refuses every loopback client — so the
# kiosk, whose requests arrive here with $remote_addr 127.0.0.1, can never
# log in or change accounts. Authorization is passed through untouched (it
# carries the admin token). $http_host (with port) lets the service
# same-origin-check writes.
location /api/accounts/ {
    auth_basic off;
    proxy_pass http://127.0.0.1:6689/api/accounts/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Boombox-Host $http_host;
    proxy_read_timeout 60s;
}

# boombox-remote: phone/desktop app + wireless remotes (state, command,
# WebSocket, art, files, library, Home Library, video).
#
# The remote service authenticates with its own bearer tokens (PIN-paired),
# so LAN Basic auth is off here.
location /api/remote/ {
    auth_basic off;
    proxy_pass http://127.0.0.1:6685/api/remote/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # matches remote_files.MAX_FILE_BYTES — the 4 GB in-handler per-file cap
    client_max_body_size 4096M;
    proxy_request_buffering off;     # stream uploads, don't buffer to /tmp
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
}

# Mopidy's /local/ asset endpoint serves embedded album art via
# core.library.get_images. The app loads these as <img src="/local/...">.
# No auth — they're already gated by the /api/remote/ token flow on the
# upstream state read. `^~` keeps the kiosk server's image regex away.
location ^~ /local/ {
    auth_basic off;
    proxy_pass http://127.0.0.1:6680/local/;
    proxy_set_header Host $host;
    expires 1d;
    add_header Cache-Control "public, immutable";
}

# boombox-audio visualizer WebSocket.
location /audio/ {
    proxy_pass http://127.0.0.1:6682/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
}
```

`install/bin/boombox-setup-apply`:

In the header action list (after the `web-password` entry) add:

```
#   nginx-sync {}                     → install the active release's nginx site
#                                       (port from web-auth.env) + shared snippet
#                                       together; nginx -t; restore both on failure
```

After `HTPASSWD = "/etc/nginx/boombox.htpasswd"` (line 51) add:

```python
NGINX_SITE = "/etc/nginx/sites-available/boombox"
NGINX_SNIPPET = "/etc/nginx/snippets/boombox-common.conf"
# The release being activated. Templates are read from here and nowhere
# else — no path comes from the caller.
RELEASE_CONFIG_DIR = "/opt/boombox/current/install/config"
NGINX_BIN = "/usr/sbin/nginx"
DEFAULT_WEB_PORT = "8090"
```

Immediately before `ACTIONS = {` add:

```python
def web_port() -> str:
    """BOOMBOX_WEB_PORT from the root-owned web-auth.env (default 8090)."""
    raw = _read_env_file(WEB_AUTH_ENV).get("BOOMBOX_WEB_PORT", "") or DEFAULT_WEB_PORT
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise ValueError("BOOMBOX_WEB_PORT in web-auth.env is not a port number")
    return str(int(raw))


def render_site(template: str, port: str) -> str:
    return template.replace("__REMOTE_WEB_PORT__", port)


def _read_or_none(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def action_nginx_sync(_body: dict) -> dict:
    """Install the active release's nginx site + shared snippet as ONE unit.

    The kiosk's `location /` lives in the site file, so a new snippet with an
    old site file (or the reverse) is broken or duplicated. Runs `nginx -t`
    and restores both previous files if it fails. Does not reload — the
    apply-release restart step does."""
    port = web_port()
    with open(os.path.join(RELEASE_CONFIG_DIR, "nginx.conf")) as f:
        site = render_site(f.read(), port)
    with open(os.path.join(RELEASE_CONFIG_DIR, "nginx-boombox-common.conf")) as f:
        snippet = f.read()
    old = {NGINX_SITE: _read_or_none(NGINX_SITE), NGINX_SNIPPET: _read_or_none(NGINX_SNIPPET)}
    if old[NGINX_SITE] == site and old[NGINX_SNIPPET] == snippet:
        return {"ok": True, "changed": False}
    _atomic_write(NGINX_SNIPPET, snippet, 0o644)
    _atomic_write(NGINX_SITE, site, 0o644)
    r = _run([NGINX_BIN, "-t"], timeout=30)
    if r.returncode == 0:
        return {"ok": True, "changed": True}
    for path, text in old.items():
        if text is None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        else:
            _atomic_write(path, text, 0o644)
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    return {"ok": False,
            "error": "nginx rejected the new config; the previous one was restored",
            "detail": lines[-1][:300] if lines else ""}


```

Add `"nginx-sync": action_nginx_sync,` as the last entry of `ACTIONS`.

`install/apply-release.sh`:

After the `fail()` line (line 34) add:

```bash

# Re-sync the nginx site file + shared snippet from $CURRENT through the root
# helper: it renders the LAN port from the root-owned web-auth.env, installs
# both files together, runs `nginx -t` and restores the previous pair if that
# fails. Never install the snippet alone — the kiosk's `location /` lives in
# the site file. A helper too old to know the action changes nothing (and
# verify's LAN-app probe then fails, so the release is rolled back).
nginx_sync() {
  local out
  out="$(printf '{"action":"nginx-sync"}' | sudo -n /usr/local/sbin/boombox-setup-apply 2>&1)" || true
  if [[ "$out" == *'"ok": true'* ]]; then
    log "nginx site + snippet in sync with $(readlink "$CURRENT")"
  else
    warn "nginx config not synced: ${out:-no output} — reinstall /usr/local/sbin/boombox-setup-apply (install.sh) to enable per-deploy nginx sync"
  fi
}
```

In `swap`, replace the whole block from the comment `# Sync the nginx snippet so source-controlled location blocks …` through its closing `fi` (lines 162–177) with:

```bash
    # Site file + snippet move together (see nginx_sync). The reload happens
    # in the `restart` step; this only stages the files.
    nginx_sync
```

In `revert`, directly after its `systemctl --user daemon-reload` line add:

```bash
    # Put the reverted release's nginx pair back before the reload below.
    nginx_sync
```

In `verify`, replace

```bash
    probe http://localhost/                  "nginx /"
    probe http://localhost/remote/           "/remote/"
```

with

```bash
    probe http://localhost/                  "nginx / (kiosk UI)"
    # The LAN app at / on the LAN port, without Basic auth. A 401 here means
    # the nginx pair wasn't synced (old boombox-setup-apply) — fail so the
    # release rolls back instead of leaving the LAN on the old config.
    lan_port="$(sed -n 's/^BOOMBOX_WEB_PORT=//p' /etc/boombox/web-auth.env 2>/dev/null | head -n1)" || true
    lan_port="${lan_port:-8090}"
    probe "http://127.0.0.1:$lan_port/"      "LAN app / (nginx site not synced? reinstall boombox-setup-apply)"
```

`install/sudoers/boombox`: replace lines 19–23 (the nginx comment and rule) with:

```
# nginx test + reload from apply-release.sh after a release swap. The site
# file and shared snippet are NOT installed through a sudo `install` rule:
# they must change together (the kiosk's `location /` lives in the site
# file), so the swap asks the root helper's `nginx-sync` action (below),
# which renders the port from the root-owned web-auth.env, installs both,
# runs `nginx -t` and restores the old pair on failure. The former
# snippet-only grant is gone on purpose: an older release's swap would
# otherwise install its snippet next to this release's site file.
%BOOMBOX_USER% ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /bin/systemctl reload nginx, /usr/bin/systemctl reload nginx
```

Delete the superseded static test: `git rm services/tests/test_nginx_accounts.py`.

- [ ] **Step 4: Run the tests and checks**

Run: `.venv/bin/python -m pytest -q services/tests/test_nginx_lan_app.py services/tests/test_setup_helper_nginx.py services/tests/test_apply_release_nginx.py services/tests/test_setup_helper.py services/tests/test_setup_helper_streaming.py services/tests/test_setup_helper_webpw.py`
Expected: PASS.

Run: `bash -n install/apply-release.sh && echo syntax-ok`
Expected: `syntax-ok`

Run (only if nginx is installed on the Mac, e.g. `brew install nginx`; otherwise the device check in Task 11 covers it):
```bash
T=$(mktemp -d); mkdir -p "$T/snippets" "$T/logs"
sed "s|__REMOTE_WEB_PORT__|18090|g; s|/etc/nginx/snippets/boombox-common.conf|$T/snippets/common.conf|g; s|/etc/nginx/boombox.htpasswd|$T/htpasswd|g" install/config/nginx.conf > "$T/site.conf"
cp install/config/nginx-boombox-common.conf "$T/snippets/common.conf"; : > "$T/htpasswd"
printf 'events {}\nhttp {\ninclude %s/site.conf;\n}\n' "$T" > "$T/nginx.conf"
nginx -t -c "$T/nginx.conf" -p "$T" 2>&1 | tail -2
```
Expected: `… syntax is ok` (a `bind()`/permission warning for port 80 is fine; `test failed` only if it names a directive).

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: all pass; `All checks passed!`; `Success: no issues found`.

- [ ] **Step 5: Commit**

```bash
git add install/config/nginx.conf install/config/nginx-boombox-common.conf \
  install/bin/boombox-setup-apply install/apply-release.sh install/sudoers/boombox \
  services/tests/test_nginx_lan_app.py services/tests/test_setup_helper_nginx.py \
  services/tests/test_apply_release_nginx.py
git commit -m "feat(nginx): LAN app at / on :8090, kiosk / on loopback, redirects; sync site + snippet together via the root helper

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(`git rm` already staged the deleted `test_nginx_accounts.py`.)

---

### Task 6: remote-ui at `/` — build config, hash router, responsive shell

**Files:**
- Modify: `remote-ui/vite.config.ts` (whole file), `remote-ui/index.html` (title), `remote-ui/src/index.css` (append)
- Modify: `remote-ui/src/test/setup.ts` (append); Create: `remote-ui/src/test/viewport.ts`
- Create: `remote-ui/src/lib/route.ts`, `remote-ui/src/lib/route.test.ts`, `remote-ui/src/lib/useIsDesktop.ts`
- Modify: `remote-ui/src/lib/api.ts` (whole file); Create: `remote-ui/src/lib/api.test.ts`
- Rewrite: `remote-ui/src/components/TabBar.tsx`, `remote-ui/src/components/TabBar.test.tsx`
- Create: `remote-ui/src/components/{Sidebar,NowPanel,SectionMessage,AppShell}.tsx`, `remote-ui/src/components/AppShell.test.tsx`, `remote-ui/src/screens/More.tsx`
- Modify: `remote-ui/src/screens/Search.tsx` (signature line 56, input ~line 192), `remote-ui/src/screens/Search.test.tsx` (append), `remote-ui/src/screens/Pairing.tsx` (line 16–17), `remote-ui/src/screens/Pairing.test.tsx` (append)
- Rewrite: `remote-ui/src/App.tsx`; Modify: `remote-ui/src/App.test.tsx` (append)
- Test: `services/tests/test_remote_ui_config.py` (create)

**Interfaces:**
- Produces (TS):
  - `lib/route.ts`: `type Route = "now"|"music"|"video"|"search"|"playlists"|"files"|"accounts"|"more"`; `ROUTES`; `interface HashLocation { route: Route; params: string[] }`; `parseHash(hash: string): HashLocation` (unknown → `{route: "now", params: []}`); `hashFor(route, params?): string`; `type Navigate = (route: Route, params?: string[]) => void`; `useHashRoute(): HashLocation & { navigate: Navigate }`.
  - `lib/useIsDesktop.ts`: `DESKTOP_MIN_PX = 900`; `useIsDesktop(): boolean` (`window.innerWidth >= 900`, live on `resize`).
  - `lib/api.ts`: `RemoteApi` gains optional `getBlob?(path: string): Promise<Blob>`; `makeApi(base, token, onUnauthorized?: () => void)` (called on any 401, before the `ApiError` is thrown); `apiErrorMessage(e: unknown, fallback: string): string` (server JSON `error` if present, else `"<fallback> (HTTP n)"`, network → `"Couldn't reach the boombox."`).
  - `components/TabBar.tsx`: `type Tab = "now"|"music"|"video"|"search"|"more"`; `tabForRoute(route: Route): Tab`; `TabBar({active, onChange})` (`nav[aria-label=Primary]`, buttons labelled Now/Music/Video/Search/More).
  - `components/Sidebar.tsx`: `Sidebar({active: Route, onNavigate: (r: Route) => void, onOpenSettings: () => void, adminLocked?: boolean})` (`nav[aria-label=Sections]`).
  - `components/NowPanel.tsx`: `NowPanel()` (`aside[aria-label="Now playing panel"]`: art, title, prev/play/next, volume, `QueueView`).
  - `components/SectionMessage.tsx`: `SectionMessage({title?, message, hint?, onRetry?})` (`role="status"`, Retry button when `onRetry`).
  - `components/AppShell.tsx`: `interface SectionProps { params: string[]; navigate: Navigate; desktop: boolean }`; `AppShell({onOpenSettings})`; exported `renderSection(route, props, onOpenSettings)` switch that Tasks 7–9 edit.
  - `screens/More.tsx`: `More({navigate, onOpenSettings, adminLocked?})`.
  - `screens/Search.tsx`: `Search({autoFocus?: boolean} = {})`.
  - `screens/Pairing.tsx`: `defaultHost(dev?: boolean): string`.
  - `App.tsx`: `apiBase(pairing: Pairing, dev?: boolean): string`.
  - Test helper `src/test/viewport.ts`: `setViewport(width: number, height?: number): void`.
- Consumes: existing `NowPlaying`, `Library`, `Playlists`, `Search`, `Files`, `QueueView`, `MiniPlayer`, `SettingsSheet`, `InstallBanner`, `useRemote`, `RemoteContextHarness`.

- [ ] **Step 1: Write the failing tests**

Create `services/tests/test_remote_ui_config.py`:

```python
"""remote-ui build config: served at /, own asset dir, a SW that stays in its lane."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VITE = (ROOT / "remote-ui" / "vite.config.ts").read_text()
DENYLIST = r"navigateFallbackDenylist: [/^\/(?:setup|api|remote|accounts|mopidy|local|audio)(?:\/|$)/]"


def test_served_from_root_with_distinct_assets_dir():
    assert 'base: "/"' in VITE
    assert 'assetsDir: "app-assets"' in VITE
    assert "/remote/" not in VITE.replace("|remote|", "")


def test_manifest_is_scoped_to_the_whole_app():
    for s in ('id: "/"', 'start_url: "/"', 'scope: "/"'):
        assert s in VITE, s


def test_service_worker_never_hijacks_other_paths():
    assert DENYLIST in VITE
    deny = re.compile(r"^/(?:setup|api|remote|accounts|mopidy|local|audio)(?:/|$)")
    for path in ("/setup", "/setup/", "/api/remote/state", "/remote/", "/accounts",
                 "/mopidy/rpc", "/local/x.jpg", "/audio/ws"):
        assert deny.match(path), path
    for path in ("/", "/index.html", "/settings", "/apis"):
        assert not deny.match(path), path
```

Create `remote-ui/src/lib/route.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseHash, hashFor } from "./route";

describe("hash routes", () => {
  it("parses the spec's section routes", () => {
    for (const r of ["now", "music", "video", "search", "playlists", "files", "accounts", "more"]) {
      expect(parseHash(`#/${r}`)).toEqual({ route: r, params: [] });
    }
  });

  it("keeps drill-down params, decoded", () => {
    expect(parseHash("#/music/home/album/al%201")).toEqual(
      { route: "music", params: ["home", "album", "al 1"] });
  });

  it("falls back to now for empty or unknown hashes", () => {
    expect(parseHash("")).toEqual({ route: "now", params: [] });
    expect(parseHash("#/")).toEqual({ route: "now", params: [] });
    expect(parseHash("#/nope/x")).toEqual({ route: "now", params: [] });
  });

  it("survives malformed escapes", () => {
    expect(parseHash("#/video/folder/%E0%A4%A")).toEqual(
      { route: "video", params: ["folder", "%E0%A4%A"] });
  });

  it("round-trips params that contain slashes", () => {
    expect(hashFor("video", ["lib", "abc", "movies"])).toBe("#/video/lib/abc/movies");
    expect(parseHash(hashFor("music", ["home", "album", "a/b"]))).toEqual(
      { route: "music", params: ["home", "album", "a/b"] });
  });
});
```

Create `remote-ui/src/lib/api.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { makeApi, ApiError, apiErrorMessage } from "./api";

afterEach(() => vi.unstubAllGlobals());

function reply(status: number, body: string) {
  return { ok: status >= 200 && status < 300, status,
    text: async () => body, json: async () => JSON.parse(body),
    blob: async () => new Blob([body]) };
}

describe("makeApi", () => {
  it("calls onUnauthorized on a 401 and still throws ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(401, '{"error":"bad_token"}')));
    const on = vi.fn();
    const api = makeApi("http://pi:8090", "t", on);
    await expect(api.get("api/remote/queue")).rejects.toBeInstanceOf(ApiError);
    await expect(api.post("api/remote/queue", {})).rejects.toBeInstanceOf(ApiError);
    expect(on).toHaveBeenCalledTimes(2);
  });

  it("does not call onUnauthorized for other errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(502, "{}")));
    const on = vi.fn();
    await expect(makeApi("http://pi:8090/", "t", on).get("x")).rejects.toBeInstanceOf(ApiError);
    expect(on).not.toHaveBeenCalled();
  });

  it("getBlob sends the bearer token", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, "img"));
    vi.stubGlobal("fetch", f);
    const blob = await makeApi("http://pi:8090", "tok").getBlob!("api/remote/home/art/a?size=320");
    expect(await blob.text()).toBe("img");
    expect(f).toHaveBeenCalledWith("http://pi:8090/api/remote/home/art/a?size=320",
      { headers: { Authorization: "Bearer tok" } });
  });
});

describe("apiErrorMessage", () => {
  it("prefers the server's error text", () => {
    expect(apiErrorMessage(new ApiError(409, '{"ok":false,"error":"kiosk not signed in"}'), "x"))
      .toBe("kiosk not signed in");
  });
  it("falls back with the status, or says unreachable for network errors", () => {
    expect(apiErrorMessage(new ApiError(502, "<html>"), "The Home Library isn't answering"))
      .toBe("The Home Library isn't answering (HTTP 502)");
    expect(apiErrorMessage(new TypeError("offline"), "x")).toBe("Couldn't reach the boombox.");
  });
});
```

Replace `remote-ui/src/components/TabBar.test.tsx` with:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TabBar, tabForRoute } from "./TabBar";

describe("TabBar", () => {
  it("renders the five phone tabs in order and marks the active one", () => {
    render(<TabBar active="video" onChange={vi.fn()} />);
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label")))
      .toEqual(["Now", "Music", "Video", "Search", "More"]);
    expect(screen.getByRole("button", { name: "Video" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Now" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("clicking a tab fires onChange with its id", () => {
    const onChange = vi.fn();
    render(<TabBar active="now" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(onChange).toHaveBeenCalledWith("more");
  });

  it("lights More for the sections it holds", () => {
    for (const r of ["playlists", "files", "accounts", "more"] as const) {
      expect(tabForRoute(r)).toBe("more");
    }
    expect(tabForRoute("music")).toBe("music");
    expect(tabForRoute("now")).toBe("now");
  });
});
```

Create `remote-ui/src/components/AppShell.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { AppShell } from "./AppShell";
import { ApiProvider, type RemoteApi } from "../lib/api";
import { RemoteContextHarness } from "../state/store";
import { setViewport } from "../test/viewport";
import type { RemoteState } from "../transport/types";

const state: RemoteState = {
  boombox: { id: "b", name: "Kitchen", version: 1 },
  source: "mopidy", playing: true,
  track: { title: "Hey Jude", artist: "The Beatles", album: "1967-1970",
           duration_s: 431, position_s: 60 },
  art_hash: null, art_url: null, volume: 0.5, muted: false,
  sources_available: ["mopidy"], sleep_timer_s: null, recording: false,
  mic_on: false, skin: null, theme: {},
};

function stubApi(): RemoteApi {
  return {
    base: "http://pi:8090/",
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/queue") return { ok: true, tracks: [] };
      if (p.startsWith("api/remote/library/browse")) return { ok: true, refs: [] };
      if (p.startsWith("api/remote/playlists")) return { ok: true, playlists: [] };
      if (p.startsWith("api/remote/files")) return { ok: true, entries: [], path: "" };
      return { ok: true };
    }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
  };
}

function renderShell(onOpenSettings = vi.fn()) {
  return render(
    <ApiProvider api={stubApi()}>
      <RemoteContextHarness state={state} command={vi.fn().mockResolvedValue({ ok: true })}>
        <AppShell onOpenSettings={onOpenSettings} />
      </RemoteContextHarness>
    </ApiProvider>,
  );
}

beforeEach(() => {
  window.location.hash = "";
  setViewport(390, 844);
});

describe("AppShell", () => {
  it("phone: bottom tabs, no sidebar, no side panel", () => {
    renderShell();
    const tabs = screen.getByRole("navigation", { name: "Primary" });
    expect(Array.from(tabs.querySelectorAll("button")).map((b) => b.getAttribute("aria-label")))
      .toEqual(["Now", "Music", "Video", "Search", "More"]);
    expect(screen.queryByRole("navigation", { name: "Sections" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: /now playing panel/i })).toBeNull();
  });

  it("desktop: sidebar + always-visible Now Playing panel, no tab bar", () => {
    setViewport(1440, 900);
    window.location.hash = "#/search";
    renderShell();
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeTruthy();
    const panel = screen.getByRole("complementary", { name: /now playing panel/i });
    expect(panel.textContent).toContain("Hey Jude");
    expect(screen.queryByRole("navigation", { name: "Primary" })).toBeNull();
  });

  it("switches layout live when the window crosses 900 px", () => {
    renderShell();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    setViewport(900, 800);
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeTruthy();
    setViewport(899, 800);
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
  });

  it("routes by hash; tab and sidebar taps update the hash", async () => {
    window.location.hash = "#/search";
    renderShell();
    expect(screen.getByLabelText("Search query")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    await waitFor(() => expect(window.location.hash).toBe("#/more"));
    fireEvent.click(await screen.findByRole("button", { name: "Playlists" }));
    await waitFor(() => expect(window.location.hash).toBe("#/playlists"));
    setViewport(1440, 900);
    fireEvent.click(screen.getByRole("button", { name: "Video" }));
    await waitFor(() => expect(window.location.hash).toBe("#/video"));
  });

  it("shows the mini player on phones everywhere but Now", async () => {
    renderShell();
    expect(screen.queryByRole("region", { name: /mini player/i })).toBeNull();
    window.location.hash = "#/music";
    expect(await screen.findByRole("region", { name: /mini player/i })).toBeTruthy();
  });

  it("opens Settings from More and from the sidebar", async () => {
    const onOpenSettings = vi.fn();
    window.location.hash = "#/more";
    renderShell(onOpenSettings);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    setViewport(1440, 900);
    const sidebar = screen.getByRole("navigation", { name: "Sections" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(onOpenSettings).toHaveBeenCalledTimes(2);
  });
});
```

Append to `remote-ui/src/screens/Search.test.tsx` (it already imports `describe/it/expect/vi`, `render/screen`, `Search` and `ApiProvider`/`RemoteApi`):

```tsx
describe("Search autofocus", () => {
  it("focuses the query box when asked (desktop)", () => {
    const api: RemoteApi = { base: "http://pi/", get: vi.fn(), post: vi.fn(), uploadFiles: vi.fn() };
    render(<ApiProvider api={api}><Search autoFocus /></ApiProvider>);
    expect(document.activeElement).toBe(screen.getByLabelText("Search query"));
  });
});
```

In `remote-ui/src/screens/Pairing.test.tsx` change line 3 to `import { Pairing, defaultHost } from "./Pairing";` and append:

```tsx
describe("defaultHost", () => {
  it("prefills the page's own host when served by a boombox, nothing in dev", () => {
    expect(defaultHost(false)).toBe(window.location.host);
    expect(defaultHost(true)).toBe("");
  });
});
```

In `remote-ui/src/App.test.tsx` change line 3 to `import App, { apiBase } from "./App";` and append:

```tsx
describe("App shell wiring", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("talks to its own origin outside dev", () => {
    const p = { base: "http://192.168.1.81:8090", token: "t", name: "MarkII" };
    expect(apiBase(p, false)).toBe(window.location.origin);
    expect(apiBase(p, true)).toBe("http://192.168.1.81:8090");
  });

  it("a 401 from any API call shows the re-pair screen", async () => {
    localStorage.setItem("boombox-remote-pairing", JSON.stringify({
      base: "http://pi:8090", token: "t", name: "Kitchen",
    }));
    class StubWS {
      onopen: (() => void) | null = null;
      onmessage: unknown = null; onclose: unknown = null; onerror: unknown = null;
      constructor() { setTimeout(() => this.onopen?.(), 0); }
      close() {}
    }
    vi.stubGlobal("WebSocket", StubWS as unknown as typeof WebSocket);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 401, text: async () => '{"error":"bad_token"}', json: async () => ({}),
    }));
    render(<App />);
    expect(await screen.findByText(/no longer paired/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_ui_config.py`
Expected: FAIL — `assert 'base: "/"' in VITE`.

Run: `cd remote-ui && npx vitest run`
Expected: FAIL — `Failed to resolve import "./route"`, `"./AppShell"`, `"../test/viewport"`; `tabForRoute is not a function`; `apiBase`/`defaultHost`/`apiErrorMessage` not exported.

- [ ] **Step 3: Implement**

Replace `remote-ui/vite.config.ts` with:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// The LAN app, served by nginx at / on the LAN port (the kiosk UI is a
// separate server block on loopback :80). Hashed bundles go to /app-assets/
// so they can never be confused with the kiosk UI's /assets/.
export default defineConfig({
  base: "/",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        id: "/",
        name: "Boombox",
        short_name: "Boombox",
        description: "Play, browse and manage your Boombox from a phone or computer",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#07060c",
        theme_color: "#07060c",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
        categories: ["music", "entertainment"],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,png,woff2}"],
        // The worker's scope is the whole LAN origin. Only the app's own
        // navigations may fall back to its index.html — the setup wizard,
        // the APIs and the old remote/accounts redirects must reach nginx.
        navigateFallbackDenylist: [/^\/(?:setup|api|remote|accounts|mopidy|local|audio)(?:\/|$)/],
      },
    }),
  ],
  build: {
    outDir: "dist",
    assetsDir: "app-assets",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

In `remote-ui/index.html` change `<title>Boombox Remote</title>` to `<title>Boombox</title>`.

Append to `remote-ui/src/index.css`:

```css
/* Nothing may push the page sideways at any width >= 320 px. */
img, video, canvas { max-width: 100%; }
```

Append to `remote-ui/src/test/setup.ts`:

```ts
// sessionStorage gets the same treatment (the admin token lives there).
const session = new MemoryStorage();
Object.defineProperty(globalThis, "sessionStorage", {
  value: session, writable: true, configurable: true,
});
Object.defineProperty(window, "sessionStorage", {
  value: session, writable: true, configurable: true,
});

// jsdom's window is 1024 px wide — the desktop side of the 900 px
// breakpoint. Default every test to a phone; use setViewport() to switch.
beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 390 });
  Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: 844 });
});
```

Create `remote-ui/src/test/viewport.ts`:

```ts
import { act } from "@testing-library/react";

/** Pretend the window is `width` × `height` and tell resize listeners. */
export function setViewport(width: number, height = 800): void {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: height });
  act(() => { window.dispatchEvent(new Event("resize")); });
}
```

Create `remote-ui/src/lib/route.ts`:

```ts
import { useCallback, useEffect, useState } from "react";

/** App sections, addressed by the URL hash (#/music/…) so browser back /
 *  forward and links work without a router dependency. `more` is the
 *  phone's More tab. */
export type Route =
  | "now" | "music" | "video" | "search" | "playlists" | "files" | "accounts" | "more";

export const ROUTES: readonly Route[] = [
  "now", "music", "video", "search", "playlists", "files", "accounts", "more",
];

export interface HashLocation { route: Route; params: string[] }

export type Navigate = (route: Route, params?: string[]) => void;

function decode(part: string): string {
  try { return decodeURIComponent(part); } catch { return part; }
}

export function parseHash(hash: string): HashLocation {
  const parts = hash.replace(/^#\/?/, "").split("/").filter((p) => p !== "").map(decode);
  const head = parts[0] ?? "";
  if ((ROUTES as readonly string[]).includes(head)) {
    return { route: head as Route, params: parts.slice(1) };
  }
  return { route: "now", params: [] };
}

export function hashFor(route: Route, params: string[] = []): string {
  return "#/" + [route, ...params.map((p) => encodeURIComponent(p))].join("/");
}

export function useHashRoute(): HashLocation & { navigate: Navigate } {
  const [loc, setLoc] = useState<HashLocation>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setLoc(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    onChange();
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback<Navigate>((route, params = []) => {
    const next = hashFor(route, params);
    // Assigning the hash pushes a history entry and fires `hashchange`.
    if (window.location.hash !== next) window.location.hash = next;
  }, []);
  return { ...loc, navigate };
}
```

Create `remote-ui/src/lib/useIsDesktop.ts`:

```ts
import { useEffect, useState } from "react";

/** Phones below this width get bottom tabs; wider windows get the sidebar +
 *  Now Playing panel layout. */
export const DESKTOP_MIN_PX = 900;

function isDesktop(): boolean {
  return window.innerWidth >= DESKTOP_MIN_PX;
}

export function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState(isDesktop);
  useEffect(() => {
    const onResize = () => setDesktop(isDesktop());
    window.addEventListener("resize", onResize);
    onResize();
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return desktop;
}
```

Replace `remote-ui/src/lib/api.ts` with:

```ts
// Bearer-token-aware HTTP helpers for everything that isn't the state /
// command transport: library, playlists, files, Home Library, video.

import { createContext, useContext, type ReactNode, createElement } from "react";

export interface RemoteApi {
  /** Base URL with trailing slash, e.g. "http://192.168.1.176:8090/". */
  readonly base: string;
  /** GET <base><path> with the bearer token. JSON body, throws on non-2xx. */
  get<T = unknown>(path: string): Promise<T>;
  /** POST <base><path> with JSON body + bearer token. JSON response. */
  post<T = unknown>(path: string, body?: unknown): Promise<T>;
  /** POST multipart upload under field "file". Parsed JSON response. */
  uploadFiles<T = unknown>(path: string, files: File[]): Promise<T>;
  /** GET binary (posters, cover art) with the bearer token — <img src> can't
   *  send one. Optional so test doubles needn't implement it. */
  getBlob?(path: string): Promise<Blob>;
}

class HttpApi implements RemoteApi {
  readonly base: string;
  private readonly token: string;
  private readonly onUnauthorized?: () => void;

  constructor(base: string, token: string, onUnauthorized?: () => void) {
    this.base = base;
    this.token = token;
    this.onUnauthorized = onUnauthorized;
  }

  private authHeader(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` };
  }

  private url(path: string): string {
    return this.base + path.replace(/^\//, "");
  }

  /** 401 = this device's pairing was revoked: tell the app, then throw. */
  private async check(r: Response): Promise<Response> {
    if (r.status === 401) this.onUnauthorized?.();
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r;
  }

  async get<T>(path: string): Promise<T> {
    const r = await this.check(await fetch(this.url(path), { headers: this.authHeader() }));
    return r.json() as Promise<T>;
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const r = await this.check(await fetch(this.url(path), {
      method: "POST",
      headers: { ...this.authHeader(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }));
    return r.json() as Promise<T>;
  }

  async uploadFiles<T>(path: string, files: File[]): Promise<T> {
    const form = new FormData();
    for (const f of files) form.append("file", f, f.name);
    const r = await this.check(await fetch(this.url(path), {
      method: "POST", headers: this.authHeader(), body: form,
    }));
    return r.json() as Promise<T>;
  }

  async getBlob(path: string): Promise<Blob> {
    const r = await this.check(await fetch(this.url(path), { headers: this.authHeader() }));
    return r.blob();
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: string;
  constructor(status: number, body: string) {
    super(`HTTP ${status}: ${body.slice(0, 200)}`);
    this.status = status;
    this.body = body;
  }
}

export function makeApi(base: string, token: string, onUnauthorized?: () => void): RemoteApi {
  // Normalize to a trailing slash so path concatenation works for both
  // "http://host" and "http://host:port".
  return new HttpApi(base.endsWith("/") ? base : base + "/", token, onUnauthorized);
}

/** A message for the user: the server's JSON `error` when it sent one,
 *  otherwise `fallback` with the status; network failures say so. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    try {
      const b = JSON.parse(e.body) as { error?: unknown };
      if (typeof b.error === "string" && b.error) return b.error;
    } catch { /* not JSON */ }
    return `${fallback} (HTTP ${e.status})`;
  }
  return "Couldn't reach the boombox.";
}

const ApiContext = createContext<RemoteApi | null>(null);

export function ApiProvider(
  { api, children }: { api: RemoteApi; children: ReactNode },
) {
  return createElement(ApiContext.Provider, { value: api }, children);
}

export function useApi(): RemoteApi {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error("useApi must be used within an ApiProvider");
  return ctx;
}
```

Replace `remote-ui/src/components/TabBar.tsx` with:

```tsx
import type { Route } from "../lib/route";

export type Tab = "now" | "music" | "video" | "search" | "more";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "now",    label: "Now",    icon: "▶" },
  { id: "music",  label: "Music",  icon: "♫" },
  { id: "video",  label: "Video",  icon: "🎬" },
  { id: "search", label: "Search", icon: "⌕" },
  { id: "more",   label: "More",   icon: "⋯" },
];

/** Which tab lights up for a route: Playlists, Files and Admin live under More. */
export function tabForRoute(route: Route): Tab {
  return route === "now" || route === "music" || route === "video" || route === "search"
    ? route : "more";
}

/** Phone bottom nav (< 900 px). Home-indicator phones get the safe-area inset. */
export function TabBar(
  { active, onChange }: { active: Tab; onChange: (t: Tab) => void },
) {
  return (
    <nav
      aria-label="Primary"
      style={{
        position: "fixed", left: 0, right: 0, bottom: 0,
        display: "flex", justifyContent: "space-around",
        background: "var(--panel)", borderTop: "1px solid var(--rule)",
        paddingBottom: "max(8px, env(safe-area-inset-bottom))",
        paddingTop: 8, zIndex: 10,
      }}
    >
      {TABS.map((t) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            type="button"
            aria-pressed={selected}
            aria-label={t.label}
            onClick={() => onChange(t.id)}
            style={{
              flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
              alignItems: "center", gap: 2,
              padding: "6px 4px", border: 0, background: "transparent",
              color: selected ? "var(--accent)" : "var(--ink2)",
              fontSize: 11, cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 22, lineHeight: 1 }}>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
```

Create `remote-ui/src/components/Sidebar.tsx`:

```tsx
import type { CSSProperties } from "react";
import type { Route } from "../lib/route";

const SECTIONS: { route: Route; label: string; icon: string }[] = [
  { route: "now",       label: "Now playing", icon: "▶" },
  { route: "music",     label: "Music",       icon: "♫" },
  { route: "video",     label: "Video",       icon: "🎬" },
  { route: "search",    label: "Search",      icon: "⌕" },
  { route: "playlists", label: "Playlists",   icon: "≡" },
  { route: "files",     label: "Files",       icon: "📁" },
];

const itemStyle = (active: boolean): CSSProperties => ({
  display: "flex", alignItems: "center", gap: 10, width: "100%",
  padding: "10px 12px", borderRadius: 10, border: 0, textAlign: "left",
  background: active ? "rgba(139,92,246,0.16)" : "transparent",
  color: active ? "var(--ink)" : "var(--ink2)", fontSize: 15, cursor: "pointer",
});

/** Desktop (≥ 900 px) navigation: every section, then Admin, then Settings. */
export function Sidebar({ active, onNavigate, onOpenSettings, adminLocked = true }: {
  active: Route;
  onNavigate: (r: Route) => void;
  onOpenSettings: () => void;
  adminLocked?: boolean;
}) {
  const item = (route: Route, label: string, icon: string) => (
    <button key={route} type="button" onClick={() => onNavigate(route)}
            aria-current={active === route ? "page" : undefined}
            style={itemStyle(active === route)}>
      <span aria-hidden="true" style={{ width: 22, textAlign: "center" }}>{icon}</span>
      {label}
    </button>
  );
  return (
    <nav aria-label="Sections" style={{
      borderRight: "1px solid var(--rule)", background: "var(--panel)",
      padding: "16px 10px", display: "flex", flexDirection: "column", gap: 4,
      overflowY: "auto", minWidth: 0,
    }}>
      <div style={{ fontWeight: 800, fontSize: 18, padding: "4px 12px 12px" }}>Boombox</div>
      {SECTIONS.map((s) => item(s.route, s.label, s.icon))}
      <div style={{ margin: "16px 12px 4px", fontSize: 11, textTransform: "uppercase",
                    letterSpacing: "0.08em", color: "var(--ink2)" }}>Admin</div>
      {item("accounts", "Accounts", adminLocked ? "🔒" : "🔓")}
      <div style={{ flex: 1 }} />
      <button type="button" onClick={onOpenSettings} style={itemStyle(false)}>
        <span aria-hidden="true" style={{ width: 22, textAlign: "center" }}>⚙</span>
        Settings
      </button>
    </nav>
  );
}
```

Create `remote-ui/src/components/NowPanel.tsx`:

```tsx
import { useEffect, useState, type CSSProperties } from "react";
import { useRemote } from "../state/store";
import { QueueView } from "./QueueView";

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const roundBtn: CSSProperties = {
  width: 40, height: 40, borderRadius: 20, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", cursor: "pointer", fontSize: 14,
};

/** Desktop right column: always-visible Now Playing + the live queue. */
export function NowPanel() {
  const { state, command } = useRemote();
  const track = state?.track ?? null;
  const playing = !!state?.playing;
  const title = track?.title ?? null;
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => { setRefreshKey((k) => k + 1); }, [title, playing]);
  const subtitle = [track?.artist, track?.album].filter(Boolean).join(" · ");

  return (
    <aside aria-label="Now playing panel" style={{
      borderLeft: "1px solid var(--rule)", overflowY: "auto", minWidth: 0,
      padding: 16, display: "flex", flexDirection: "column", gap: 12,
    }}>
      {state?.art_url
        ? <img src={state.art_url} alt="" style={{ width: "100%", aspectRatio: "1",
                                                   objectFit: "cover", borderRadius: 12 }} />
        : <div style={{ width: "100%", aspectRatio: "1", borderRadius: 12,
                        background: "var(--panel)" }} />}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 16, ...ellipsis }}>{title ?? "Nothing playing"}</div>
        {subtitle && <div style={{ color: "var(--ink2)", fontSize: 13, ...ellipsis }}>{subtitle}</div>}
      </div>
      <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
        <button type="button" aria-label="Previous" onClick={() => command("previous")}
                style={roundBtn}>‹‹</button>
        <button type="button" aria-label={playing ? "Pause" : "Play"}
                onClick={() => command("play_pause")}
                style={{ ...roundBtn, width: 48, height: 48, borderRadius: 24, border: 0,
                         background: "var(--accent)", color: "var(--bg)" }}>
          {playing ? "❚❚" : "▶"}
        </button>
        <button type="button" aria-label="Next" onClick={() => command("next")}
                style={roundBtn}>››</button>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12,
                      color: "var(--ink2)" }}>
        Volume
        <input type="range" aria-label="Volume" min={0} max={1} step={0.01}
               value={state?.volume ?? 0}
               onChange={(e) => command("volume", Number(e.target.value))}
               style={{ flex: 1, minWidth: 0 }} />
      </label>
      <h3 style={{ margin: "8px 0 0", fontSize: 12, color: "var(--ink2)",
                   textTransform: "uppercase", letterSpacing: "0.06em" }}>Up next</h3>
      <QueueView refreshKey={refreshKey} />
    </aside>
  );
}
```

Create `remote-ui/src/components/SectionMessage.tsx`:

```tsx
/** The one way a section says "can't show this right now": a message, an
 *  optional hint, and Retry. Used for library down, video server not set
 *  up, kiosk not signed in, and sections not available yet. */
export function SectionMessage({ title, message, hint, onRetry }: {
  title?: string; message: string; hint?: string; onRetry?: () => void;
}) {
  return (
    <div role="status" style={{
      padding: 24, textAlign: "center", color: "var(--ink2)",
      display: "flex", flexDirection: "column", gap: 10, alignItems: "center",
    }}>
      {title && <h2 style={{ margin: 0, color: "var(--ink)", fontSize: 18 }}>{title}</h2>}
      <p style={{ margin: 0 }}>{message}</p>
      {hint && <p style={{ margin: 0, fontSize: 13 }}>{hint}</p>}
      {onRetry && (
        <button type="button" onClick={onRetry} style={{
          padding: "10px 18px", borderRadius: 10, border: "1px solid var(--rule)",
          background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
        }}>Retry</button>
      )}
    </div>
  );
}
```

Create `remote-ui/src/screens/More.tsx`:

```tsx
import type { CSSProperties } from "react";
import type { Navigate } from "../lib/route";

const rowStyle: CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, width: "100%", minHeight: 52,
  padding: "12px 8px", border: 0, borderBottom: "1px solid var(--rule)",
  background: "transparent", color: "var(--ink)", fontSize: 16, cursor: "pointer",
  textAlign: "left",
};

/** The phone's More tab: Playlists, Files, Admin → Accounts, Settings. */
export function More({ navigate, onOpenSettings, adminLocked = true }: {
  navigate: Navigate; onOpenSettings: () => void; adminLocked?: boolean;
}) {
  const rows: { label: string; icon: string; hint?: string; onClick: () => void }[] = [
    { label: "Playlists", icon: "≡", onClick: () => navigate("playlists") },
    { label: "Files", icon: "📁", onClick: () => navigate("files") },
    { label: "Accounts", icon: adminLocked ? "🔒" : "🔓", hint: "Admin",
      onClick: () => navigate("accounts") },
    { label: "Settings", icon: "⚙", onClick: onOpenSettings },
  ];
  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <h1 style={{ fontSize: 22, margin: "0 0 12px" }}>More</h1>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {rows.map((r) => (
          <li key={r.label}>
            <button type="button" onClick={r.onClick} style={rowStyle}>
              <span aria-hidden="true" style={{ width: 24, textAlign: "center" }}>{r.icon}</span>
              <span style={{ flex: 1 }}>{r.label}</span>
              {r.hint && <span aria-hidden="true" style={{ fontSize: 12, color: "var(--ink2)" }}>
                {r.hint}</span>}
              <span aria-hidden="true" style={{ color: "var(--ink2)" }}>›</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

Create `remote-ui/src/components/AppShell.tsx`:

```tsx
import type { ReactNode } from "react";
import { useHashRoute, type Navigate, type Route } from "../lib/route";
import { useIsDesktop } from "../lib/useIsDesktop";
import { TabBar, tabForRoute } from "./TabBar";
import { Sidebar } from "./Sidebar";
import { NowPanel } from "./NowPanel";
import { MiniPlayer } from "./MiniPlayer";
import { SectionMessage } from "./SectionMessage";
import { NowPlaying } from "../screens/NowPlaying";
import { Library } from "../screens/Library";
import { Playlists } from "../screens/Playlists";
import { Search } from "../screens/Search";
import { Files } from "../screens/Files";
import { More } from "../screens/More";

export interface SectionProps { params: string[]; navigate: Navigate; desktop: boolean }

/** Route → section. Tasks for Music, Video and Accounts replace their cases. */
export function renderSection(route: Route, p: SectionProps, onOpenSettings: () => void,
                              adminLocked: boolean): ReactNode {
  switch (route) {
    case "now": return <NowPlaying onOpenLibrary={() => p.navigate("music")} />;
    case "music": return <Library />;
    case "video":
      return <SectionMessage title="Video" message="Video isn't available in this version yet." />;
    case "search": return <Search autoFocus={p.desktop} />;
    case "playlists": return <Playlists />;
    case "files": return <Files />;
    case "accounts":
      return <SectionMessage title="Accounts" message="Admin isn't available in this version yet." />;
    case "more":
      return <More navigate={p.navigate} onOpenSettings={onOpenSettings} adminLocked={adminLocked} />;
  }
}

/** Phone (< 900 px): section + mini-player + bottom tabs.
 *  Desktop (≥ 900 px): sidebar | section | Now Playing + queue panel. */
export function AppShell({ onOpenSettings }: { onOpenSettings: () => void }) {
  const desktop = useIsDesktop();
  const { route, params, navigate } = useHashRoute();
  const adminLocked = true;
  const content = renderSection(route, { params, navigate, desktop }, onOpenSettings, adminLocked);

  if (desktop) {
    return (
      <div data-layout="desktop" style={{
        display: "grid", gridTemplateColumns: "220px minmax(0, 1fr) 360px", height: "100%",
      }}>
        <Sidebar active={route} onNavigate={(r) => navigate(r)}
                 onOpenSettings={onOpenSettings} adminLocked={adminLocked} />
        <main style={{ overflowY: "auto", minWidth: 0 }}>
          <div style={{ maxWidth: 1200, margin: "0 auto" }}>{content}</div>
        </main>
        <NowPanel />
      </div>
    );
  }
  return (
    <div data-layout="phone">
      <main style={{ minWidth: 0 }}>{content}</main>
      {route !== "now" && <MiniPlayer onOpenNow={() => navigate("now")} />}
      <TabBar active={tabForRoute(route)} onChange={(t) => navigate(t)} />
    </div>
  );
}
```

(`adminLocked` is a constant `true` until Task 9 wires the admin session in.)

`remote-ui/src/screens/Search.tsx`: change line 56 `export function Search() {` to

```tsx
export function Search({ autoFocus = false }: { autoFocus?: boolean } = {}) {
```

and add `autoFocus={autoFocus}` to the `<input type="search" aria-label="Search query" …>` element (after `aria-label="Search query"`).

`remote-ui/src/screens/Pairing.tsx`: before `export function Pairing(` add

```tsx
/** Served by a boombox, prefill its own address so pairing is PIN-only.
 *  (Empty in `vite dev`, where the page isn't on the boombox.) */
export function defaultHost(dev: boolean = import.meta.env.DEV): string {
  return dev ? "" : window.location.host;
}
```

and change `const [host, setHost] = useState("");` to `const [host, setHost] = useState(() => defaultHost());`.

Replace `remote-ui/src/App.tsx` with:

```tsx
import { useCallback, useMemo, useState } from "react";
import { loadPairing, clearPairing } from "./lib/pairing";
import type { Pairing } from "./lib/pairing";
import { makeHttpTransport } from "./transport/select";
import { TransportProvider, useRemote } from "./state/store";
import { ApiProvider, makeApi } from "./lib/api";
import { Pairing as PairingScreen } from "./screens/Pairing";
import { AppShell } from "./components/AppShell";
import { SettingsSheet } from "./components/SettingsSheet";
import { InstallBanner } from "./components/InstallBanner";

/** Where the API lives. Served by a boombox, the app always talks to its own
 *  origin (same-origin: no CORS, and an IP-vs-.local choice made at pairing
 *  can't strand it); the stored pairing base only matters under `vite dev`. */
export function apiBase(pairing: Pairing, dev: boolean = import.meta.env.DEV): string {
  return dev ? pairing.base : window.location.origin;
}

function NoLongerPaired({ onUnpair }: { onUnpair: () => void }) {
  return (
    <Centered>
      <h2>This phone is no longer paired</h2>
      <p style={{ color: "var(--ink2)" }}>
        It was unpaired from the boombox. Pair again to reconnect.
      </p>
      <button onClick={onUnpair} style={linkBtn}>Pair again</button>
    </Centered>
  );
}

/** Inside the providers: connection status first, then the app shell. */
function Remote({ base, onUnpair }: { base: string; onUnpair: () => void }) {
  const { state, status } = useRemote();
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (status === "disabled") {
    return (
      <Centered>
        <h2>Remote access is off</h2>
        <p style={{ color: "var(--ink2)" }}>
          Turn it on in the boombox's Settings → Phone remote, then this will
          reconnect automatically.
        </p>
      </Centered>
    );
  }
  if (status === "unauthorized") return <NoLongerPaired onUnpair={onUnpair} />;

  const hasState = state !== null;
  if (!hasState && (status === "connecting" || status === "error" ||
                    status === "unavailable")) {
    return (
      <Centered>
        <p style={{ color: "var(--ink2)" }}>
          {status === "connecting" ? "Connecting…"
            : status === "unavailable" ? "Boombox temporarily unavailable…"
            : "Can't reach the boombox."}
        </p>
      </Centered>
    );
  }

  return (
    <>
      {(status === "connecting" || status === "unavailable" ||
        status === "error") && (
        <div role="status" style={{
          position: "fixed", top: 0, left: 0, right: 0, zIndex: 20,
          padding: "6px 12px", textAlign: "center", fontSize: 12,
          background: "var(--panel)", color: "var(--ink2)",
          borderBottom: "1px solid var(--rule)",
        }}>
          {status === "connecting" ? "Reconnecting…"
            : status === "unavailable" ? "Boombox restarting — will reconnect"
            : "Connection lost — retrying"}
        </div>
      )}
      <InstallBanner />
      <AppShell onOpenSettings={() => setSettingsOpen(true)} />
      {settingsOpen && (
        <SettingsSheet base={base}
                       onClose={() => setSettingsOpen(false)}
                       onUnpair={() => { setSettingsOpen(false); onUnpair(); }} />
      )}
    </>
  );
}

export default function App() {
  const [pairing, setPairing] = useState<Pairing | null>(() => loadPairing());
  // Any API call answering 401 = this device was unpaired on the boombox.
  const [revoked, setRevoked] = useState(false);
  const unpair = useCallback(() => {
    clearPairing();
    setRevoked(false);
    setPairing(null);
  }, []);
  const base = pairing ? apiBase(pairing) : "";
  const api = useMemo(
    () => (pairing ? makeApi(base, pairing.token, () => setRevoked(true)) : null),
    [base, pairing]);
  const transport = useMemo(
    () => (pairing ? makeHttpTransport(base, pairing.token) : null), [base, pairing]);

  if (!pairing || !api || !transport) {
    return <PairingScreen onPaired={(p) => { setRevoked(false); setPairing(p); }} />;
  }
  if (revoked) return <NoLongerPaired onUnpair={unpair} />;

  // `key` forces a fresh TransportProvider when the pairing changes.
  return (
    <ApiProvider api={api}>
      <TransportProvider key={pairing.token} transport={transport}>
        <Remote base={base} onUnpair={unpair} />
      </TransportProvider>
    </ApiProvider>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: "100%", display: "grid", placeItems: "center",
      padding: 24, textAlign: "center",
    }}>
      <div style={{ maxWidth: 420 }}>{children}</div>
    </div>
  );
}

const linkBtn: React.CSSProperties = {
  marginTop: 12, padding: "10px 18px", borderRadius: 10,
  border: "1px solid var(--rule)", background: "var(--panel)",
  color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
```

- [ ] **Step 4: Run the tests and build**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_ui_config.py`
Expected: PASS.

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build && ls dist/app-assets | head -3 && grep -c '/app-assets/' dist/index.html; grep -c '/remote/' dist/index.html`
Expected: tsc silent; all vitest files pass; build succeeds; `dist/app-assets/` lists `index-*.js` / `index-*.css`; the first grep prints a count ≥ 1, the second prints `0`.

- [ ] **Step 5: Commit**

```bash
git add remote-ui/vite.config.ts remote-ui/index.html remote-ui/src/index.css \
  remote-ui/src/test/setup.ts remote-ui/src/test/viewport.ts \
  remote-ui/src/lib/route.ts remote-ui/src/lib/route.test.ts remote-ui/src/lib/useIsDesktop.ts \
  remote-ui/src/lib/api.ts remote-ui/src/lib/api.test.ts \
  remote-ui/src/components/TabBar.tsx remote-ui/src/components/TabBar.test.tsx \
  remote-ui/src/components/Sidebar.tsx remote-ui/src/components/NowPanel.tsx \
  remote-ui/src/components/SectionMessage.tsx remote-ui/src/components/AppShell.tsx \
  remote-ui/src/components/AppShell.test.tsx remote-ui/src/screens/More.tsx \
  remote-ui/src/screens/Search.tsx remote-ui/src/screens/Search.test.tsx \
  remote-ui/src/screens/Pairing.tsx remote-ui/src/screens/Pairing.test.tsx \
  remote-ui/src/App.tsx remote-ui/src/App.test.tsx services/tests/test_remote_ui_config.py
git commit -m "feat(remote-ui): LAN app at / — hash routes, phone tabs vs desktop sidebar + Now Playing panel

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Music section with the Home Library

**Files:**
- Create: `remote-ui/src/components/grid.ts`, `remote-ui/src/components/AuthedImg.tsx`, `remote-ui/src/components/AuthedImg.test.tsx`
- Create: `remote-ui/src/lib/homeLibrary.ts`, `remote-ui/src/screens/HomeLibrary.tsx`, `remote-ui/src/screens/HomeLibrary.test.tsx`, `remote-ui/src/screens/Music.tsx`
- Modify: `remote-ui/src/components/AppShell.tsx` (import of `Library`; `case "music"`)

**Interfaces:**
- Consumes: Task 2 HTTP routes (`GET api/remote/home/browse?type=`, `…/search?q=`, `…/{artist|album|playlist}/{id}`, `…/art/{art_id}?size=`, `POST api/remote/home/play {ids, mode}` → `{ok, count, skipped}` / 409 / 502); Task 6 `useApi`, `RemoteApi.getBlob?`, `apiErrorMessage`, `Navigate`, `SectionMessage`, `renderSection`.
- Produces (TS):
  - `components/grid.ts`: `TILE_MIN_PX = 160`, `TILE_GRID: CSSProperties` (`repeat(auto-fill, minmax(min(160px, 100%), 1fr))`).
  - `components/AuthedImg.tsx`: `AuthedImg({path: string | null, alt: string, style?})` — fetches `path` via `api.getBlob` when scrolled near view, shows an object URL, revokes it on unmount; placeholder otherwise.
  - `lib/homeLibrary.ts`: types `HomeList`, `HomeKind`, `HomeItem`, `HomeTrack`, `HomeAlbumDetail`, `HomeArtistDetail`, `HomePlaylistDetail`, `HomeSearchResult`, `PlayResult`; `MAX_EXPANDED_TRACKS = 500`; `browseHome(api, list)` (session-cached), `clearHomeCache()`, `searchHome(api, q)`, `homeDetail<T>(api, kind, id)`, `playHome(api, ids, mode)`, `artistTrackIds(api, artistId)`, `artPath(artId, size?)`.
  - `screens/HomeLibrary.tsx`: `HomeLibrary({params, navigate})` — params `[]|["albums"]|["artists"]|["playlists"]` = lists, `["album"|"artist"|"playlist", id]` = detail.
  - `screens/Music.tsx`: `Music({params, navigate})` — `params[0] === "boombox"` → Mopidy `Library`; otherwise Home Library with `params.slice(1)`. Hash scheme `#/music/home/…`, `#/music/boombox`.

- [ ] **Step 1: Write the failing tests**

Create `remote-ui/src/components/AuthedImg.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { AuthedImg } from "./AuthedImg";
import { TILE_GRID } from "./grid";
import { ApiProvider, type RemoteApi } from "../lib/api";

let create: ReturnType<typeof vi.fn>;
let revoke: ReturnType<typeof vi.fn>;

beforeEach(() => {
  create = vi.fn(() => "blob:poster");
  revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true, writable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: revoke, configurable: true, writable: true });
});

function api(getBlob?: RemoteApi["getBlob"]): RemoteApi {
  return { base: "http://pi/", get: vi.fn(), post: vi.fn(), uploadFiles: vi.fn(), getBlob };
}

describe("AuthedImg", () => {
  it("fetches with the token, shows an object URL and revokes it on unmount", async () => {
    const getBlob = vi.fn().mockResolvedValue(new Blob(["x"]));
    const { container, unmount } = render(
      <ApiProvider api={api(getBlob)}><AuthedImg path="api/remote/home/art/a?size=320" alt="" /></ApiProvider>);
    await waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:poster"));
    expect(getBlob).toHaveBeenCalledWith("api/remote/home/art/a?size=320");
    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:poster");
  });

  it("stays a placeholder without a path, without getBlob, or on failure", async () => {
    const failing = vi.fn().mockRejectedValue(new Error("404"));
    const { container } = render(
      <ApiProvider api={api(failing)}><AuthedImg path="api/x" alt="" /></ApiProvider>);
    await waitFor(() => expect(failing).toHaveBeenCalled());
    expect(container.querySelector("img")).toBeNull();
    const none = render(<ApiProvider api={api()}><AuthedImg path="api/x" alt="" /></ApiProvider>);
    expect(none.container.querySelector("img")).toBeNull();
    const noPath = vi.fn();
    render(<ApiProvider api={api(noPath)}><AuthedImg path={null} alt="" /></ApiProvider>);
    expect(noPath).not.toHaveBeenCalled();
  });

  it("tile grid never goes below 160 px columns", () => {
    expect(String(TILE_GRID.gridTemplateColumns)).toContain("160px");
  });
});
```

Create `remote-ui/src/screens/HomeLibrary.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HomeLibrary } from "./HomeLibrary";
import { Music } from "./Music";
import { ApiProvider, ApiError, type RemoteApi } from "../lib/api";
import { clearHomeCache } from "../lib/homeLibrary";

const ALBUMS = { items: [
  { id: "al1", name: "Blue", artist_id: "ar1", year: 1971, art_id: "al-1" },
  { id: "al2", name: "Court and Spark", artist_id: "ar1", year: 1974 },
] };
const ARTISTS = { items: [{ id: "ar1", name: "Joni Mitchell", album_count: 2 }] };
const ALBUM = { album: { id: "al1", name: "Blue", artist: "Joni Mitchell", year: 1971, art_id: "al-1" },
  tracks: [
    { id: "t1", title: "All I Want", duration: 214 },
    { id: "t2", title: "My Old Man", duration: 213 },
    { id: "t3", title: "Little Green", duration: 206 },
  ] };
const ARTIST = { artist: { id: "ar1", name: "Joni Mitchell" },
  albums: [{ id: "al1", name: "Blue" }, { id: "al2", name: "Court and Spark" }] };
const ALBUM2 = { album: { id: "al2", name: "Court and Spark" }, tracks: [{ id: "t9", title: "Help Me" }] };

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://pi/",
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/home/browse?type=albums") return ALBUMS;
      if (p === "api/remote/home/browse?type=artists") return ARTISTS;
      if (p === "api/remote/home/album/al1") return ALBUM;
      if (p === "api/remote/home/album/al2") return ALBUM2;
      if (p === "api/remote/home/artist/ar1") return ARTIST;
      if (p.startsWith("api/remote/home/search")) {
        return { results: [{ content_type: "track", id: "t2", title: "My Old Man" }] };
      }
      throw new Error(`unmocked ${p}`);
    }),
    post: vi.fn().mockResolvedValue({ ok: true, count: 3, skipped: 0 }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function wrap(api: RemoteApi, params: string[], navigate = vi.fn()) {
  return render(<ApiProvider api={api}><HomeLibrary params={params} navigate={navigate} /></ApiProvider>);
}

beforeEach(() => clearHomeCache());

describe("HomeLibrary", () => {
  it("lists albums as tiles and opens one", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), [], navigate);
    fireEvent.click(await screen.findByRole("button", { name: /Blue/ }));
    expect(navigate).toHaveBeenCalledWith("music", ["home", "album", "al1"]);
  });

  it("switches lists through the hash", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), ["artists"], navigate);
    expect(await screen.findByText("Joni Mitchell")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Playlists" }));
    expect(navigate).toHaveBeenCalledWith("music", ["home", "playlists"]);
  });

  it("filters the loaded list as you type", async () => {
    wrap(mockApi(), []);
    await screen.findByText("Court and Spark");
    fireEvent.change(screen.getByLabelText("Search the Home Library"), { target: { value: "cou" } });
    expect(screen.queryByRole("button", { name: /^Blue/ })).toBeNull();
    expect(screen.getByText("Court and Spark")).toBeTruthy();
  });

  it("album: Play all, play from a track, queue one track", async () => {
    const api = mockApi();
    wrap(api, ["album", "al1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t1", "t2", "t3"], mode: "play" }));
    expect(await screen.findByText("Playing Blue — 3 tracks.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Play from My Old Man" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t2", "t3"], mode: "play" }));
    fireEvent.click(screen.getByRole("button", { name: "Queue My Old Man" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t2"], mode: "queue" }));
  });

  it("artist: Play all expands every album's tracks", async () => {
    const api = mockApi();
    wrap(api, ["artist", "ar1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t1", "t2", "t3", "t9"], mode: "play" }));
  });

  it("reports skipped offline tracks and the server's all-offline message", async () => {
    const post = vi.fn()
      .mockResolvedValueOnce({ ok: true, count: 2, skipped: 1 })
      .mockRejectedValueOnce(new ApiError(409,
        '{"ok":false,"error":"none of these tracks can play right now — they aren\'t cached and the Home Library server is unreachable"}'));
    wrap(mockApi({ post }), ["album", "al1"]);
    fireEvent.click(await screen.findByRole("button", { name: "Play all" }));
    expect(await screen.findByText("Playing Blue — 2 tracks (1 not available offline).")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Queue all" }));
    expect(await screen.findByText(/none of these tracks can play right now/)).toBeTruthy();
  });

  it("library down shows a message with Retry", async () => {
    const get = vi.fn()
      .mockRejectedValueOnce(new ApiError(502, '{"ok":false,"error":"library service not answering"}'))
      .mockResolvedValue(ALBUMS);
    wrap(mockApi({ get }), []);
    expect(await screen.findByText("library service not answering")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Court and Spark")).toBeTruthy();
  });

  it("server search results play a track", async () => {
    const api = mockApi();
    wrap(api, []);
    await screen.findByText("Blue");
    fireEvent.change(screen.getByLabelText("Search the Home Library"), { target: { value: "old man" } });
    fireEvent.click(await screen.findByRole("button", { name: "Play My Old Man" }, { timeout: 2000 }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/home/play", { ids: ["t2"], mode: "play" }));
  });
});

describe("Music", () => {
  it("switches between the Home Library and this boombox's library", async () => {
    const navigate = vi.fn();
    const api = mockApi();
    render(<ApiProvider api={api}><Music params={[]} navigate={navigate} /></ApiProvider>);
    expect(await screen.findByText("Blue")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "On this boombox" }));
    expect(navigate).toHaveBeenCalledWith("music", ["boombox"]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd remote-ui && npx vitest run src/components/AuthedImg.test.tsx src/screens/HomeLibrary.test.tsx`
Expected: FAIL — `Failed to resolve import "./AuthedImg"` / `"./HomeLibrary"`.

- [ ] **Step 3: Implement**

Create `remote-ui/src/components/grid.ts`:

```ts
import type { CSSProperties } from "react";

/** Music / Video tile grid: as many columns as fit, never narrower than
 *  160 px (min() keeps a single column from overflowing a narrower pane). */
export const TILE_MIN_PX = 160;

export const TILE_GRID: CSSProperties = {
  display: "grid",
  gap: 14,
  gridTemplateColumns: `repeat(auto-fill, minmax(min(${TILE_MIN_PX}px, 100%), 1fr))`,
};
```

Create `remote-ui/src/components/AuthedImg.tsx`:

```tsx
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useApi } from "../lib/api";

/** An image from a pair-token-gated route. <img src> can't send the bearer
 *  token (and putting it in the URL would land it in nginx logs), so fetch
 *  the bytes and show an object URL. Loads once the tile is near the
 *  viewport; a placeholder panel otherwise or on failure. */
export function AuthedImg({ path, alt, style }: {
  path: string | null; alt: string; style?: CSSProperties;
}) {
  const api = useApi();
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (visible || !ref.current) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setVisible(true);
        io.disconnect();
      }
    }, { rootMargin: "300px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible || !path || !api.getBlob) return;
    let url: string | null = null;
    let cancelled = false;
    api.getBlob(path).then((blob) => {
      if (cancelled) return;
      url = URL.createObjectURL(blob);
      setSrc(url);
    }).catch(() => { /* keep the placeholder */ });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
      setSrc(null);
    };
  }, [visible, path, api]);

  return (
    <div ref={ref} style={{ background: "var(--panel)", overflow: "hidden", ...style }}>
      {src && <img src={src} alt={alt}
                   style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />}
    </div>
  );
}
```

Create `remote-ui/src/lib/homeLibrary.ts`:

```ts
// Client for /api/remote/home/* — the Home Library (Navidrome, via
// boombox-library) as seen through boombox-remote's pair-token routes.
import type { RemoteApi } from "./api";

export type HomeList = "artists" | "albums" | "playlists";
export type HomeKind = "artist" | "album" | "playlist";

export interface HomeItem {
  id: string; name: string; artist_id?: string | null; year?: number | null;
  album_count?: number | null; song_count?: number | null; art_id?: string | null;
}
export interface HomeTrack {
  id: string; title: string; artist?: string | null; duration?: number | null;
  cache_status?: string;
}
export interface HomeAlbumDetail {
  album: { id: string; name: string; artist?: string | null; year?: number | null;
           art_id?: string | null };
  tracks: HomeTrack[];
}
export interface HomeArtistDetail {
  artist: { id: string; name: string; art_id?: string | null };
  albums: { id: string; name: string; year?: number | null; art_id?: string | null }[];
}
export interface HomePlaylistDetail { playlist: { id: string; name: string }; tracks: HomeTrack[] }
export interface HomeSearchResult { content_type: string; id: string; title: string }
export interface PlayResult { ok: boolean; count: number; skipped: number }

/** Cap for one "play artist", as on the kiosk. */
export const MAX_EXPANDED_TRACKS = 500;

// The albums list is ~700 KB for 8.7k albums; keep it for the session so
// moving between tabs and details doesn't refetch it.
const listCache = new Map<HomeList, HomeItem[]>();

export async function browseHome(api: RemoteApi, list: HomeList): Promise<HomeItem[]> {
  const hit = listCache.get(list);
  if (hit) return hit;
  const r = await api.get<{ items?: HomeItem[] }>(`api/remote/home/browse?type=${list}`);
  const items = Array.isArray(r.items) ? r.items : [];
  listCache.set(list, items);
  return items;
}

export function clearHomeCache(): void {
  listCache.clear();
}

export async function searchHome(api: RemoteApi, q: string): Promise<HomeSearchResult[]> {
  const r = await api.get<{ results?: HomeSearchResult[] }>(
    `api/remote/home/search?q=${encodeURIComponent(q)}`);
  return Array.isArray(r.results) ? r.results : [];
}

export function homeDetail<T>(api: RemoteApi, kind: HomeKind, id: string): Promise<T> {
  return api.get<T>(`api/remote/home/${kind}/${encodeURIComponent(id)}`);
}

export function playHome(api: RemoteApi, ids: string[], mode: "play" | "queue"): Promise<PlayResult> {
  return api.post<PlayResult>("api/remote/home/play", { ids, mode });
}

/** Every track of an artist, album by album in the order the library lists
 *  them, capped at MAX_EXPANDED_TRACKS. */
export async function artistTrackIds(api: RemoteApi, artistId: string): Promise<string[]> {
  const a = await homeDetail<HomeArtistDetail>(api, "artist", artistId);
  const ids: string[] = [];
  for (const al of a.albums) {
    if (ids.length >= MAX_EXPANDED_TRACKS) break;
    const d = await homeDetail<HomeAlbumDetail>(api, "album", al.id);
    ids.push(...d.tracks.map((t) => t.id));
  }
  return ids.slice(0, MAX_EXPANDED_TRACKS);
}

export function artPath(artId: string | null | undefined, size = 320): string | null {
  return artId ? `api/remote/home/art/${encodeURIComponent(artId)}?size=${size}` : null;
}
```

Create `remote-ui/src/screens/HomeLibrary.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { AuthedImg } from "../components/AuthedImg";
import { SectionMessage } from "../components/SectionMessage";
import { SkeletonRows } from "../components/Skeleton";
import { TILE_GRID } from "../components/grid";
import {
  artPath, artistTrackIds, browseHome, homeDetail, playHome, searchHome,
  type HomeAlbumDetail, type HomeArtistDetail, type HomeItem, type HomeKind,
  type HomeList, type HomePlaylistDetail, type HomeSearchResult, type HomeTrack,
} from "../lib/homeLibrary";

const PAGE = 120;
const LIBRARY_DOWN = "The Home Library isn't answering";
const LISTS: { id: HomeList; label: string }[] = [
  { id: "albums", label: "Albums" }, { id: "artists", label: "Artists" },
  { id: "playlists", label: "Playlists" },
];

type PlayFn = (ids: string[] | (() => Promise<string[]>), mode: "play" | "queue",
               label: string) => Promise<void>;

function usePlay(): { toast: string | null; play: PlayFn } {
  const api = useApi();
  const [toast, setToast] = useState<string | null>(null);
  const play = useCallback<PlayFn>(async (ids, mode, label) => {
    setToast(mode === "play" ? `Starting ${label}…` : `Queueing ${label}…`);
    try {
      const list = typeof ids === "function" ? await ids() : ids;
      if (list.length === 0) { setToast(`${label}: nothing to play.`); return; }
      const r = await playHome(api, list, mode);
      const n = `${r.count} track${r.count === 1 ? "" : "s"}`;
      const skipped = r.skipped ? ` (${r.skipped} not available offline)` : "";
      setToast(`${mode === "play" ? "Playing" : "Queued"} ${label} — ${n}${skipped}.`);
    } catch (e) {
      setToast(apiErrorMessage(e, "Couldn't play that"));
    }
  }, [api]);
  return { toast, play };
}

function mmss(sec: number | null | undefined): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Home Library browser. Lists (albums / artists / playlists) and details
 *  (album / artist / playlist) are hash routes: #/music/home/<list> and
 *  #/music/home/<kind>/<id>, so the phone's back button walks back out. */
export function HomeLibrary({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const [a, b] = params;
  if ((a === "artist" || a === "album" || a === "playlist") && b) {
    return <HomeDetail key={`${a}/${b}`} kind={a} id={b} navigate={navigate} />;
  }
  const list: HomeList = a === "artists" || a === "playlists" ? a : "albums";
  return <HomeBrowse key={list} list={list} navigate={navigate} />;
}

function HomeBrowse({ list, navigate }: { list: HomeList; navigate: Navigate }) {
  const api = useApi();
  const [items, setItems] = useState<HomeItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState("");
  const [results, setResults] = useState<HomeSearchResult[] | null>(null);
  const [shown, setShown] = useState(PAGE);
  const { toast, play } = usePlay();

  useEffect(() => {
    let live = true;
    setError(null);
    browseHome(api, list)
      .then((r) => { if (live) setItems(r); })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, list, attempt]);

  useEffect(() => {
    const q = filter.trim();
    if (q.length < 2) { setResults(null); return; }
    let live = true;
    const t = window.setTimeout(() => {
      searchHome(api, q)
        .then((r) => { if (live) setResults(r); })
        .catch(() => { if (live) setResults([]); });
    }, 300);
    return () => { live = false; window.clearTimeout(t); };
  }, [api, filter]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!items) return [];
    return q ? items.filter((i) => i.name.toLowerCase().includes(q)) : items;
  }, [items, filter]);

  const openKind: HomeKind = list === "artists" ? "artist" : list === "albums" ? "album" : "playlist";

  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      <div role="tablist" aria-label="Home Library lists" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {LISTS.map((l) => (
          <button key={l.id} type="button" role="tab" aria-selected={l.id === list}
                  onClick={() => navigate("music", ["home", l.id])} style={pill(l.id === list)}>
            {l.label}
          </button>
        ))}
      </div>
      <input type="search" aria-label="Search the Home Library" value={filter}
             onChange={(e) => { setFilter(e.target.value); setShown(PAGE); }}
             placeholder="Search artists, albums, tracks…" style={searchInput} />
      {toast && <div role="status" style={banner}>{toast}</div>}
      {results && results.length > 0 && (
        <section aria-label="Search results">
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {results.slice(0, 30).map((r) => (
              <li key={`${r.content_type}:${r.id}`} style={row}>
                <span aria-hidden="true" style={{ width: 20 }}>
                  {r.content_type === "track" ? "🎵" : r.content_type === "album" ? "💿" : "👤"}
                </span>
                <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{r.title}</span>
                {r.content_type === "track" ? (
                  <button type="button" aria-label={`Play ${r.title}`} style={smallBtn}
                          onClick={() => void play([r.id], "play", r.title)}>▶</button>
                ) : (
                  <button type="button" aria-label={`Open ${r.title}`} style={smallBtn}
                          onClick={() => navigate("music", ["home",
                            r.content_type === "artist" ? "artist" : "album", r.id])}>›</button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {error ? (
        <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : !items ? (
        <SkeletonRows count={8} />
      ) : list === "playlists" ? (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {filtered.slice(0, shown).map((p) => (
            <li key={p.id} style={row}>
              <button type="button" onClick={() => navigate("music", ["home", "playlist", p.id])}
                      style={{ ...rowBtn, flex: 1, minWidth: 0 }}>
                <span style={ellipsis}>{p.name}</span>
                {p.song_count != null && (
                  <span style={{ color: "var(--ink2)", fontSize: 12, flexShrink: 0 }}>
                    {p.song_count} tracks</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div style={TILE_GRID}>
          {filtered.slice(0, shown).map((i) => (
            <button key={i.id} type="button" onClick={() => navigate("music", ["home", openKind, i.id])}
                    style={tileBtn}>
              <AuthedImg path={artPath(i.art_id)} alt=""
                         style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
              <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{i.name}</span>
              {list === "albums" && i.year != null && (
                <span style={{ fontSize: 12, color: "var(--ink2)" }}>{i.year}</span>
              )}
            </button>
          ))}
        </div>
      )}
      {items && filtered.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + PAGE)} style={moreBtn}>
          Show more ({filtered.length - shown} left)
        </button>
      )}
    </div>
  );
}

function HomeDetail({ kind, id, navigate }: { kind: HomeKind; id: string; navigate: Navigate }) {
  const api = useApi();
  const [data, setData] = useState<HomeAlbumDetail | HomeArtistDetail | HomePlaylistDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const { toast, play } = usePlay();

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    homeDetail<HomeAlbumDetail | HomeArtistDetail | HomePlaylistDetail>(api, kind, id)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(apiErrorMessage(e, LIBRARY_DOWN)); });
    return () => { live = false; };
  }, [api, kind, id, attempt]);

  const backList: HomeList = kind === "artist" ? "artists" : kind === "album" ? "albums" : "playlists";
  const back = (
    <button type="button" onClick={() => navigate("music", ["home", backList])} style={backBtn}>
      ‹ Home Library
    </button>
  );
  if (error) {
    return <div style={{ padding: 16 }}>{back}
      <SectionMessage message={error} onRetry={() => setAttempt((n) => n + 1)} /></div>;
  }
  if (!data) return <div style={{ padding: 16 }}>{back}<SkeletonRows count={8} /></div>;

  if (kind === "artist") {
    const d = data as HomeArtistDetail;
    return (
      <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
        {back}
        <h1 style={{ margin: 0, fontSize: 24 }}>{d.artist.name}</h1>
        <Actions onPlay={() => void play(() => artistTrackIds(api, id), "play", d.artist.name)}
                 onQueue={() => void play(() => artistTrackIds(api, id), "queue", d.artist.name)} />
        {toast && <div role="status" style={banner}>{toast}</div>}
        <div style={TILE_GRID}>
          {d.albums.map((al) => (
            <button key={al.id} type="button" onClick={() => navigate("music", ["home", "album", al.id])}
                    style={tileBtn}>
              <AuthedImg path={artPath(al.art_id)} alt=""
                         style={{ width: "100%", aspectRatio: "1", borderRadius: 10 }} />
              <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{al.name}</span>
              {al.year != null && <span style={{ fontSize: 12, color: "var(--ink2)" }}>{al.year}</span>}
            </button>
          ))}
        </div>
      </div>
    );
  }

  const album = kind === "album" ? (data as HomeAlbumDetail).album : null;
  const title = album ? album.name : (data as HomePlaylistDetail).playlist.name;
  const tracks: HomeTrack[] = (data as HomeAlbumDetail | HomePlaylistDetail).tracks;
  const ids = tracks.map((t) => t.id);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 12 }}>
      {back}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
        {album && <AuthedImg path={artPath(album.art_id, 480)} alt=""
                             style={{ width: 160, height: 160, borderRadius: 12, flexShrink: 0 }} />}
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 24 }}>{title}</h1>
          {album && (album.artist || album.year) && (
            <div style={{ color: "var(--ink2)" }}>
              {[album.artist, album.year].filter(Boolean).join(" · ")}</div>
          )}
        </div>
      </div>
      <Actions onPlay={() => void play(ids, "play", title)} onQueue={() => void play(ids, "queue", title)} />
      {toast && <div role="status" style={banner}>{toast}</div>}
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {tracks.map((t, i) => (
          <li key={`${t.id}:${i}`} style={row}>
            <span style={{ width: 24, color: "var(--ink2)", fontSize: 12 }}>{i + 1}</span>
            <span style={{ flex: 1, minWidth: 0, ...ellipsis }}>{t.title}</span>
            {t.duration ? <span style={{ color: "var(--ink2)", fontSize: 12 }}>{mmss(t.duration)}</span> : null}
            <button type="button" aria-label={`Play from ${t.title}`} style={smallBtn}
                    onClick={() => void play(ids.slice(i), "play", title)}>▶</button>
            <button type="button" aria-label={`Queue ${t.title}`} style={smallBtn}
                    onClick={() => void play([t.id], "queue", t.title)}>+Q</button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Actions({ onPlay, onQueue }: { onPlay: () => void; onQueue: () => void }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button type="button" onClick={onPlay} style={primaryBtn}>Play all</button>
      <button type="button" onClick={onQueue} style={moreBtn}>Queue all</button>
    </div>
  );
}

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const pill = (active: boolean): CSSProperties => ({
  padding: "6px 14px", borderRadius: 999, fontSize: 13, border: "1px solid var(--rule)",
  background: active ? "var(--accent)" : "var(--panel)",
  color: active ? "var(--bg)" : "var(--ink)", cursor: "pointer",
});
const searchInput: CSSProperties = {
  padding: "10px 12px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, width: "100%",
};
const banner: CSSProperties = {
  padding: "8px 12px", borderRadius: 8, background: "var(--panel)",
  color: "var(--ink2)", fontSize: 13,
};
const row: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "10px 4px",
  borderBottom: "1px solid var(--rule)", minWidth: 0,
};
const rowBtn: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, background: "transparent", border: 0,
  color: "var(--ink)", fontSize: 15, padding: "4px 0", cursor: "pointer", textAlign: "left",
};
const tileBtn: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 6, minWidth: 0, padding: 0,
  background: "transparent", border: 0, color: "var(--ink)", textAlign: "left", cursor: "pointer",
};
const smallBtn: CSSProperties = {
  padding: "6px 10px", borderRadius: 6, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 13, cursor: "pointer", flexShrink: 0,
};
const primaryBtn: CSSProperties = {
  padding: "10px 18px", borderRadius: 10, border: 0, background: "var(--accent)",
  color: "var(--bg)", fontWeight: 700, fontSize: 15, cursor: "pointer",
};
const moreBtn: CSSProperties = {
  padding: "10px 18px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
const backBtn: CSSProperties = {
  alignSelf: "flex-start", background: "transparent", border: 0, color: "var(--ink2)",
  fontSize: 14, cursor: "pointer", padding: "4px 0",
};
```

Create `remote-ui/src/screens/Music.tsx`:

```tsx
import type { CSSProperties } from "react";
import type { Navigate } from "../lib/route";
import { HomeLibrary } from "./HomeLibrary";
import { Library } from "./Library";

const tab = (active: boolean): CSSProperties => ({
  padding: "8px 16px", borderRadius: 999, fontSize: 14, border: "1px solid var(--rule)",
  background: active ? "var(--ink)" : "transparent",
  color: active ? "var(--bg)" : "var(--ink2)", cursor: "pointer",
});

/** Music: the Navidrome Home Library (default) or this boombox's own Mopidy
 *  library. #/music/home/… and #/music/boombox. */
export function Music({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const source = params[0] === "boombox" ? "boombox" : "home";
  return (
    <div>
      <div role="tablist" aria-label="Music source"
           style={{ display: "flex", gap: 8, padding: "16px 16px 0", flexWrap: "wrap" }}>
        <button type="button" role="tab" aria-selected={source === "home"}
                onClick={() => navigate("music", ["home"])} style={tab(source === "home")}>
          Home Library
        </button>
        <button type="button" role="tab" aria-selected={source === "boombox"}
                onClick={() => navigate("music", ["boombox"])} style={tab(source === "boombox")}>
          On this boombox
        </button>
      </div>
      {source === "home"
        ? <HomeLibrary params={params.slice(1)} navigate={navigate} />
        : <Library />}
    </div>
  );
}
```

In `remote-ui/src/components/AppShell.tsx`: replace `import { Library } from "../screens/Library";` with `import { Music } from "../screens/Music";` and replace `case "music": return <Library />;` with:

```tsx
    case "music": return <Music params={p.params} navigate={p.navigate} />;
```

- [ ] **Step 4: Run the tests and build**

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`
Expected: tsc silent; all test files pass (AppShell's mini-player test now renders Music → Home Library; its stub answers `{ ok: true }` for the browse call, which the screen treats as an empty list); build succeeds.

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/components/grid.ts remote-ui/src/components/AuthedImg.tsx \
  remote-ui/src/components/AuthedImg.test.tsx remote-ui/src/lib/homeLibrary.ts \
  remote-ui/src/screens/HomeLibrary.tsx remote-ui/src/screens/HomeLibrary.test.tsx \
  remote-ui/src/screens/Music.tsx remote-ui/src/components/AppShell.tsx
git commit -m "feat(remote-ui): Music section — Home Library browse/search, album/artist/playlist play and queue

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Video section — browse, play on the boombox, controls

**Files:**
- Create: `remote-ui/src/lib/video.ts`, `remote-ui/src/components/VideoControls.tsx`, `remote-ui/src/components/VideoControls.test.tsx`, `remote-ui/src/screens/Video.tsx`, `remote-ui/src/screens/Video.test.tsx`
- Modify: `remote-ui/src/components/AppShell.tsx` (`case "video"`; import)

**Interfaces:**
- Consumes: Task 3/4 HTTP routes (`GET api/remote/video/views|resume` → `{ok, items}`; `GET api/remote/video/items?parent_id=&type=&search=&start=&limit=` → `{ok, items, total, start}`; `GET api/remote/video/image/{id}?max_width=`; `POST api/remote/video/play {item_id, start_ticks?}`; `GET api/remote/video/state` → `{active, playing, title, item_id, position_s, duration_s, audio_streams, subtitle_streams, audio_index, subtitle_index}`; `POST api/remote/video/command {action, value?}` with `play_pause`, `stop`, `seek` (absolute seconds), `set_audio`, `set_subtitle` (-1 = off)); Task 6/7 `useApi`, `apiErrorMessage`, `Navigate`, `SectionMessage`, `AuthedImg`, `TILE_GRID`; `useRemote().command("volume", 0..1)` (system volume, same as the music slider and the hardware knob).
- Produces (TS):
  - `lib/video.ts`: `interface VideoItem` (the Task 3 `Item` shape), `interface VideoStream {index, label}`, `interface VideoState`, `PAGE_SIZE = 60`, `TICKS_PER_SECOND = 10_000_000`, `isPlayable(item)`, `typesFor(collectionType)`, `imagePath(item, width?)`, `itemsPath({parentId?, types?, search?, start?})`, `itemSubtitle(item)`, `clock(seconds)`.
  - `components/VideoControls.tsx`: `VideoControls({pollMs?: number})` — renders nothing unless a video is active; `section[aria-label="Video playing on the boombox"]`.
  - `screens/Video.tsx`: `Video({params, navigate})` — `[]` = home (Continue watching + libraries + search), `["lib", id, collectionType]`, `["folder", id]`; playable tiles open an item sheet (`role="dialog"`).

- [ ] **Step 1: Write the failing tests**

Create `remote-ui/src/components/VideoControls.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { VideoControls } from "./VideoControls";
import { ApiProvider, type RemoteApi } from "../lib/api";
import { RemoteContextHarness } from "../state/store";
import type { RemoteState } from "../transport/types";
import type { VideoState } from "../lib/video";

const ACTIVE: VideoState = {
  active: true, playing: false, title: "Pilot", item_id: "bb22",
  position_s: 12, duration_s: 888,
  audio_streams: [{ index: 1, label: "English - AAC" }, { index: 2, label: "Commentary" }],
  subtitle_streams: [{ index: 3, label: "English" }],
  audio_index: 1, subtitle_index: -1,
};
const REMOTE: RemoteState = {
  boombox: { id: "b", name: "Box", version: 1 }, source: "movies", playing: false,
  track: null, art_hash: null, art_url: null, volume: 0.3, muted: false,
  sources_available: [], sleep_timer_s: null, recording: false, mic_on: false,
  skin: null, theme: {},
};

function setup(state: VideoState = ACTIVE) {
  const api: RemoteApi = {
    base: "http://pi/",
    get: vi.fn().mockResolvedValue(state),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
  };
  const command = vi.fn().mockResolvedValue({ ok: true });
  render(
    <ApiProvider api={api}>
      <RemoteContextHarness state={REMOTE} command={command}>
        <VideoControls pollMs={60_000} />
      </RemoteContextHarness>
    </ApiProvider>,
  );
  return { api, command };
}

describe("VideoControls", () => {
  it("renders nothing when no video is playing", async () => {
    const { api } = setup({ active: false });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("api/remote/video/state"));
    expect(screen.queryByRole("region", { name: /video playing/i })).toBeNull();
  });

  it("shows title and time; transport buttons send commands", async () => {
    const { api } = setup();
    expect(await screen.findByText("Pilot")).toBeTruthy();
    expect(screen.getByText("0:12 / 14:48")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Forward 30 seconds" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "seek", value: 42 }));
    fireEvent.click(screen.getByRole("button", { name: "Play video" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "play_pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Stop video" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "stop" }));
  });

  it("back 30 s never seeks below zero", async () => {
    const { api } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Back 30 seconds" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "seek", value: 0 }));
  });

  it("picks an audio track and turns subtitles on", async () => {
    const { api } = setup();
    fireEvent.change(await screen.findByLabelText("Audio track"), { target: { value: "2" } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "set_audio", value: 2 }));
    fireEvent.change(screen.getByLabelText("Subtitles"), { target: { value: "3" } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "set_subtitle", value: 3 }));
  });

  it("turns subtitles off with -1", async () => {
    const { api } = setup({ ...ACTIVE, subtitle_index: 3 });
    fireEvent.change(await screen.findByLabelText("Subtitles"), { target: { value: "-1" } });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "set_subtitle", value: -1 }));
  });

  it("the scrubber seeks when released", async () => {
    const { api } = setup();
    const slider = await screen.findByLabelText("Position");
    fireEvent.change(slider, { target: { value: "300" } });
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.pointerUp(slider);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/command", { action: "seek", value: 300 }));
  });

  it("volume drives the boombox volume", async () => {
    const { command } = setup();
    fireEvent.change(await screen.findByLabelText("Boombox volume"), { target: { value: "0.4" } });
    expect(command).toHaveBeenCalledWith("volume", 0.4);
  });

  it("shows a command failure", async () => {
    const { api } = setup();
    (api.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(await screen.findByRole("button", { name: "Stop video" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
```

Create `remote-ui/src/screens/Video.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Video } from "./Video";
import { ApiProvider, ApiError, type RemoteApi } from "../lib/api";
import { RemoteContextHarness } from "../state/store";
import type { VideoItem } from "../lib/video";

function item(o: Partial<VideoItem>): VideoItem {
  return { id: "0", name: "", type: "Movie", collection_type: null, is_folder: false,
    year: null, runtime_s: 0, series_name: null, season: null, episode: null,
    overview: null, has_image: false, played: false, progress: null, resume_s: 0, ...o };
}

const MOVIES_LIB = item({ id: "a1b2", name: "Movies", type: "CollectionFolder",
                          collection_type: "movies", is_folder: true });
const SHOWS_LIB = item({ id: "a3b4", name: "Shows", type: "CollectionFolder",
                         collection_type: "tvshows", is_folder: true });
const EPISODE = item({ id: "bb22", name: "Pilot", type: "Episode", series_name: "Show",
                       season: 1, episode: 2, runtime_s: 2600, resume_s: 754, progress: 29 });
const MOVIE = item({ id: "aa11", name: "Big Buck Bunny", year: 2008, runtime_s: 596,
                     overview: "A giant rabbit." });
const SERIES = item({ id: "c3d4", name: "Show", type: "Series", is_folder: true });

function mockApi(overrides: Partial<RemoteApi> = {}): RemoteApi {
  return {
    base: "http://pi/",
    get: vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/video/state") return { active: false };
      if (p === "api/remote/video/views") return { ok: true, items: [MOVIES_LIB, SHOWS_LIB] };
      if (p === "api/remote/video/resume") return { ok: true, items: [EPISODE] };
      if (p === "api/remote/video/items?parent_id=a1b2&type=Movie&start=0&limit=60") {
        return { ok: true, items: [MOVIE], total: 61, start: 0 };
      }
      if (p === "api/remote/video/items?parent_id=a1b2&type=Movie&start=60&limit=60") {
        return { ok: true, items: [item({ id: "aa12", name: "Sintel" })], total: 61, start: 60 };
      }
      if (p === "api/remote/video/items?parent_id=a3b4&type=Series&start=0&limit=60") {
        return { ok: true, items: [SERIES], total: 1, start: 0 };
      }
      throw new Error(`unmocked ${p}`);
    }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    uploadFiles: vi.fn(),
    ...overrides,
  };
}

function wrap(api: RemoteApi, params: string[], navigate = vi.fn()) {
  return render(
    <ApiProvider api={api}>
      <RemoteContextHarness state={null} command={vi.fn()}>
        <Video params={params} navigate={navigate} />
      </RemoteContextHarness>
    </ApiProvider>,
  );
}

describe("Video", () => {
  it("home shows Continue watching and libraries; a library opens its grid", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), [], navigate);
    expect(await screen.findByText("Continue watching")).toBeTruthy();
    expect(screen.getByText("Pilot")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Movies/ }));
    expect(navigate).toHaveBeenCalledWith("video", ["lib", "a1b2", "movies"]);
  });

  it("a library grid pages with Load more", async () => {
    wrap(mockApi(), ["lib", "a1b2", "movies"]);
    expect(await screen.findByText("Big Buck Bunny")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Load more/ }));
    expect(await screen.findByText("Sintel")).toBeTruthy();
    expect(screen.getByText("Big Buck Bunny")).toBeTruthy();
  });

  it("series open as folders", async () => {
    const navigate = vi.fn();
    wrap(mockApi(), ["lib", "a3b4", "tvshows"], navigate);
    fireEvent.click(await screen.findByRole("button", { name: /Show/ }));
    expect(navigate).toHaveBeenCalledWith("video", ["folder", "c3d4"]);
  });

  it("a movie opens a sheet; Play on the boombox posts the item", async () => {
    const api = mockApi();
    wrap(api, ["lib", "a1b2", "movies"]);
    fireEvent.click(await screen.findByRole("button", { name: /Big Buck Bunny/ }));
    const sheet = await screen.findByRole("dialog", { name: "Big Buck Bunny" });
    expect(sheet.textContent).toContain("A giant rabbit.");
    fireEvent.click(screen.getByRole("button", { name: "Play on the boombox" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/play", { item_id: "aa11" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("resume starts at the saved position", async () => {
    const api = mockApi();
    wrap(api, []);
    fireEvent.click(await screen.findByRole("button", { name: /Pilot/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Resume from 12:34" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "api/remote/video/play", { item_id: "bb22", start_ticks: 7_540_000_000 }));
  });

  it("a play failure shows the server's message and keeps the sheet", async () => {
    const post = vi.fn().mockRejectedValue(new ApiError(504,
      '{"ok":false,"error":"the boombox\'s video player didn\'t open — try again"}'));
    wrap(mockApi({ post }), ["lib", "a1b2", "movies"]);
    fireEvent.click(await screen.findByRole("button", { name: /Big Buck Bunny/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Play on the boombox" }));
    expect(await screen.findByText(/video player didn't open/)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("kiosk not signed in: message, Accounts hint, Retry", async () => {
    let fail = true;
    const base = mockApi();
    const get = vi.fn().mockImplementation(async (p: string) => {
      if (fail && (p === "api/remote/video/views" || p === "api/remote/video/resume")) {
        throw new ApiError(409, '{"ok":false,"error":"kiosk not signed in"}');
      }
      return (base.get as (p: string) => Promise<unknown>)(p);
    });
    wrap(mockApi({ get }), []);
    expect(await screen.findByText("kiosk not signed in")).toBeTruthy();
    expect(screen.getByText(/Admin → Accounts/)).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Continue watching")).toBeTruthy();
  });

  it("video server not configured shows a message", async () => {
    const get = vi.fn().mockImplementation(async (p: string) => {
      if (p === "api/remote/video/state") return { active: false };
      throw new ApiError(503, '{"ok":false,"error":"video server not configured"}');
    });
    wrap(mockApi({ get }), []);
    expect(await screen.findByText("video server not configured")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd remote-ui && npx vitest run src/components/VideoControls.test.tsx src/screens/Video.test.tsx`
Expected: FAIL — `Failed to resolve import "./VideoControls"` / `"./Video"`.

- [ ] **Step 3: Implement**

Create `remote-ui/src/lib/video.ts`:

```ts
// Types + helpers for /api/remote/video/* (see services/remote_video.py).

export interface VideoItem {
  id: string; name: string; type: string; collection_type: string | null;
  is_folder: boolean; year: number | null; runtime_s: number;
  series_name: string | null; season: number | null; episode: number | null;
  overview: string | null; has_image: boolean; played: boolean;
  progress: number | null; resume_s: number;
}
export interface VideoPage { ok: boolean; items: VideoItem[]; total: number; start: number }
export interface VideoStream { index: number; label: string }
export interface VideoState {
  active: boolean; playing?: boolean; title?: string | null; item_id?: string | null;
  position_s?: number; duration_s?: number;
  audio_streams?: VideoStream[]; subtitle_streams?: VideoStream[];
  audio_index?: number | null; subtitle_index?: number | null;
}

export const PAGE_SIZE = 60;
export const TICKS_PER_SECOND = 10_000_000;
const PLAYABLE = new Set(["Movie", "Episode", "Video", "MusicVideo", "Trailer"]);

export function isPlayable(i: VideoItem): boolean {
  return PLAYABLE.has(i.type) && !i.is_folder;
}

/** Item types a library view lists at its top level. */
export function typesFor(collectionType: string | null | undefined): string {
  return collectionType === "movies" ? "Movie" : collectionType === "tvshows" ? "Series" : "";
}

export function imagePath(i: VideoItem, width = 320): string | null {
  return i.has_image ? `api/remote/video/image/${i.id}?max_width=${width}` : null;
}

export function itemsPath(o: { parentId?: string; types?: string; search?: string;
                               start?: number }): string {
  const q = new URLSearchParams();
  if (o.parentId) q.set("parent_id", o.parentId);
  if (o.types) q.set("type", o.types);
  if (o.search) q.set("search", o.search);
  q.set("start", String(o.start ?? 0));
  q.set("limit", String(PAGE_SIZE));
  return `api/remote/video/items?${q.toString()}`;
}

export function clock(sec: number | null | undefined): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function itemSubtitle(i: VideoItem): string {
  const parts: string[] = [];
  if (i.type === "Episode") {
    const se = i.season != null && i.episode != null ? `S${i.season}E${i.episode}` : "";
    parts.push([i.series_name, se].filter(Boolean).join(" · "));
  }
  if (i.year) parts.push(String(i.year));
  if (i.runtime_s) {
    const m = Math.round(i.runtime_s / 60);
    parts.push(m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);
  }
  return parts.filter(Boolean).join(" · ");
}
```

Create `remote-ui/src/components/VideoControls.tsx`:

```tsx
import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import { useRemote } from "../state/store";
import { clock, type VideoState } from "../lib/video";

const btn: CSSProperties = {
  minWidth: 44, height: 44, borderRadius: 22, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 14, cursor: "pointer",
  padding: "0 12px",
};
const select: CSSProperties = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, maxWidth: "100%",
};

/** Controls for the video playing on the boombox's screen: title, time,
 *  ±30 s, play/pause, stop, scrubber, audio + subtitle tracks, volume.
 *  Polls /video/state while mounted; hidden when nothing is playing. */
export function VideoControls({ pollMs = 2000 }: { pollMs?: number }) {
  const api = useApi();
  const { state: remote, command: remoteCommand } = useRemote();
  const [st, setSt] = useState<VideoState | null>(null);
  const [pos, setPos] = useState(0);
  const [scrub, setScrub] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.get<VideoState>("api/remote/video/state");
      setSt(s);
      setPos(s.position_s ?? 0);
    } catch {
      /* keep the last state; the next poll retries */
    }
  }, [api]);

  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const loop = async () => {
      await refresh();
      if (live) timer = window.setTimeout(loop, pollMs);
    };
    void loop();
    return () => { live = false; window.clearTimeout(timer); };
  }, [refresh, pollMs]);

  // Tick the clock locally between polls while playing.
  useEffect(() => {
    if (!st?.active || !st.playing) return;
    const dur = st.duration_s || Infinity;
    const id = window.setInterval(() => setPos((p) => Math.min(dur, p + 1)), 1000);
    return () => window.clearInterval(id);
  }, [st]);

  if (!st?.active) return null;

  const send = async (action: string, value?: number) => {
    setError(null);
    try {
      await api.post("api/remote/video/command",
        value === undefined ? { action } : { action, value });
    } catch (e) {
      setError(apiErrorMessage(e, "The boombox didn't take that"));
    }
    void refresh();
  };
  const dur = st.duration_s ?? 0;
  const seekTo = (s: number) => {
    const v = Math.max(0, Math.round(dur ? Math.min(dur, s) : s));
    setPos(v);
    void send("seek", v);
  };
  const commitScrub = () => {
    if (scrub !== null) { seekTo(scrub); setScrub(null); }
  };
  const audio = st.audio_streams ?? [];
  const subs = st.subtitle_streams ?? [];

  return (
    <section aria-label="Video playing on the boombox" style={{
      border: "1px solid var(--rule)", borderRadius: 14, padding: 14, marginBottom: 16,
      display: "flex", flexDirection: "column", gap: 10, background: "var(--panel)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, minWidth: 0 }}>
        <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {st.title ?? "Video"}</strong>
        <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--ink2)", flexShrink: 0 }}>
          {clock(scrub ?? pos)} / {clock(dur)}</span>
      </div>
      <input type="range" aria-label="Position" min={0} max={Math.max(dur, 1)} step={1}
             value={scrub ?? pos}
             onChange={(e) => setScrub(Number(e.target.value))}
             onPointerUp={commitScrub} onKeyUp={commitScrub}
             style={{ width: "100%" }} />
      <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
        <button type="button" aria-label="Back 30 seconds" onClick={() => seekTo(pos - 30)}
                style={btn}>−30 s</button>
        <button type="button" aria-label={st.playing ? "Pause video" : "Play video"}
                onClick={() => void send("play_pause")}
                style={{ ...btn, background: "var(--accent)", color: "var(--bg)", border: 0 }}>
          {st.playing ? "❚❚" : "▶"}</button>
        <button type="button" aria-label="Forward 30 seconds" onClick={() => seekTo(pos + 30)}
                style={btn}>+30 s</button>
        <button type="button" aria-label="Stop video" onClick={() => void send("stop")}
                style={btn}>■</button>
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {audio.length > 0 && (
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
            Audio
            <select aria-label="Audio track" value={String(st.audio_index ?? audio[0].index)}
                    onChange={(e) => void send("set_audio", Number(e.target.value))} style={select}>
              {audio.map((a) => <option key={a.index} value={String(a.index)}>{a.label}</option>)}
            </select>
          </label>
        )}
        {subs.length > 0 && (
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
            Subtitles
            <select aria-label="Subtitles" value={String(st.subtitle_index ?? -1)}
                    onChange={(e) => void send("set_subtitle", Number(e.target.value))} style={select}>
              <option value="-1">Off</option>
              {subs.map((s) => <option key={s.index} value={String(s.index)}>{s.label}</option>)}
            </select>
          </label>
        )}
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
        Volume
        <input type="range" aria-label="Boombox volume" min={0} max={1} step={0.01}
               value={remote?.volume ?? 0}
               onChange={(e) => void remoteCommand("volume", Number(e.target.value))}
               style={{ flex: 1, minWidth: 0 }} />
      </label>
      {error && <div role="alert" style={{ color: "#ff7878", fontSize: 13 }}>{error}</div>}
    </section>
  );
}
```

Create `remote-ui/src/screens/Video.tsx`:

```tsx
import { useEffect, useState, type CSSProperties } from "react";
import { useApi, apiErrorMessage } from "../lib/api";
import type { Navigate } from "../lib/route";
import { AuthedImg } from "../components/AuthedImg";
import { SectionMessage } from "../components/SectionMessage";
import { SkeletonRows } from "../components/Skeleton";
import { TILE_GRID } from "../components/grid";
import { VideoControls } from "../components/VideoControls";
import {
  TICKS_PER_SECOND, clock, imagePath, isPlayable, itemSubtitle, itemsPath, typesFor,
  type VideoItem, type VideoPage,
} from "../lib/video";

const VIDEO_DOWN = "The video server isn't answering";
const SIGN_IN_HINT = "Sign the boombox screen in under Admin → Accounts → Video server.";

function hintFor(message: string): string | undefined {
  return message === "kiosk not signed in" ? SIGN_IN_HINT : undefined;
}

/** Jellyfin, browsed as the user the boombox screen is signed in as.
 *  #/video = home, #/video/lib/<id>/<collectionType>, #/video/folder/<id>. */
export function Video({ params, navigate }: { params: string[]; navigate: Navigate }) {
  const [a, b, c] = params;
  const [sheet, setSheet] = useState<VideoItem | null>(null);
  const open = (i: VideoItem) => {
    if (isPlayable(i)) setSheet(i);
    else if (i.collection_type) navigate("video", ["lib", i.id, i.collection_type]);
    else navigate("video", ["folder", i.id]);
  };
  return (
    <div style={{ padding: 16, paddingBottom: 96 }}>
      <VideoControls />
      {a === "lib" && b ? (
        <>
          <Back navigate={navigate} />
          <VideoGrid key={`lib/${b}`} parentId={b} types={typesFor(c)} onOpen={open} />
        </>
      ) : a === "folder" && b ? (
        <>
          <Back navigate={navigate} />
          <VideoGrid key={`folder/${b}`} parentId={b} types="" onOpen={open} />
        </>
      ) : (
        <VideoHome onOpen={open} />
      )}
      {sheet && <ItemSheet item={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}

function Back({ navigate }: { navigate: Navigate }) {
  return (
    <button type="button" onClick={() => navigate("video")} style={backBtn}>‹ Video</button>
  );
}

function VideoHome({ onOpen }: { onOpen: (i: VideoItem) => void }) {
  const api = useApi();
  const [views, setViews] = useState<VideoItem[] | null>(null);
  const [resume, setResume] = useState<VideoItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");

  useEffect(() => {
    let live = true;
    setError(null);
    Promise.all([
      api.get<{ items: VideoItem[] }>("api/remote/video/views"),
      api.get<{ items: VideoItem[] }>("api/remote/video/resume"),
    ]).then(([v, r]) => {
      if (!live) return;
      setViews(v.items ?? []);
      setResume(r.items ?? []);
    }).catch((e) => { if (live) setError(apiErrorMessage(e, VIDEO_DOWN)); });
    return () => { live = false; };
  }, [api, attempt]);

  useEffect(() => {
    const t = window.setTimeout(() => setTerm(search.trim().length >= 2 ? search.trim() : ""), 350);
    return () => window.clearTimeout(t);
  }, [search]);

  if (error) {
    return <SectionMessage title="Video" message={error} hint={hintFor(error)}
                           onRetry={() => setAttempt((n) => n + 1)} />;
  }
  if (!views) return <SkeletonRows count={6} />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <input type="search" aria-label="Search videos" value={search}
             onChange={(e) => setSearch(e.target.value)}
             placeholder="Search movies and shows…" style={searchInput} />
      {term ? (
        <VideoGrid key={`search/${term}`} search={term} types="Movie,Series,Episode" onOpen={onOpen} />
      ) : (
        <>
          {resume.length > 0 && (
            <section>
              <h2 style={h2}>Continue watching</h2>
              <div style={TILE_GRID}>
                {resume.map((i) => <Tile key={i.id} item={i} onOpen={onOpen} />)}
              </div>
            </section>
          )}
          <section>
            <h2 style={h2}>Libraries</h2>
            <div style={TILE_GRID}>
              {views.map((i) => <Tile key={i.id} item={i} onOpen={onOpen} />)}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function VideoGrid({ parentId, types, search, onOpen }: {
  parentId?: string; types: string; search?: string; onOpen: (i: VideoItem) => void;
}) {
  const api = useApi();
  const [items, setItems] = useState<VideoItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    let live = true;
    setError(null);
    api.get<VideoPage>(itemsPath({ parentId, types, search, start: 0 }))
      .then((p) => { if (live) { setItems(p.items ?? []); setTotal(p.total ?? 0); } })
      .catch((e) => { if (live) setError(apiErrorMessage(e, VIDEO_DOWN)); });
    return () => { live = false; };
  }, [api, parentId, types, search, attempt]);

  const more = async () => {
    if (!items) return;
    setLoadingMore(true);
    try {
      const p = await api.get<VideoPage>(itemsPath({ parentId, types, search, start: items.length }));
      setItems([...items, ...(p.items ?? [])]);
      setTotal(p.total ?? total);
    } catch (e) {
      setError(apiErrorMessage(e, VIDEO_DOWN));
    } finally {
      setLoadingMore(false);
    }
  };

  if (error) {
    return <SectionMessage message={error} hint={hintFor(error)}
                           onRetry={() => setAttempt((n) => n + 1)} />;
  }
  if (!items) return <SkeletonRows count={6} />;
  if (items.length === 0) return <p style={{ color: "var(--ink2)" }}>Nothing here.</p>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={TILE_GRID}>
        {items.map((i) => <Tile key={i.id} item={i} onOpen={onOpen} />)}
      </div>
      {items.length < total && (
        <button type="button" onClick={() => void more()} disabled={loadingMore} style={secondary}>
          {loadingMore ? "Loading…" : `Load more (${total - items.length} left)`}
        </button>
      )}
    </div>
  );
}

function Tile({ item, onOpen }: { item: VideoItem; onOpen: (i: VideoItem) => void }) {
  const sub = itemSubtitle(item);
  return (
    <button type="button" onClick={() => onOpen(item)} style={tileBtn}>
      <div style={{ position: "relative" }}>
        <AuthedImg path={imagePath(item)} alt=""
                   style={{ width: "100%", aspectRatio: "2 / 3", borderRadius: 10 }} />
        {item.progress != null && item.progress > 0 && (
          <div aria-hidden="true" style={{ position: "absolute", left: 6, right: 6, bottom: 6,
            height: 4, borderRadius: 2, background: "rgba(0,0,0,0.5)" }}>
            <div style={{ width: `${Math.min(100, item.progress)}%`, height: "100%",
                          borderRadius: 2, background: "var(--accent)" }} />
          </div>
        )}
      </div>
      <span style={{ fontWeight: 600, fontSize: 14, ...ellipsis }}>{item.name}</span>
      {sub && <span style={{ fontSize: 12, color: "var(--ink2)", ...ellipsis }}>{sub}</span>}
    </button>
  );
}

function ItemSheet({ item, onClose }: { item: VideoItem; onClose: () => void }) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const start = async (fromSeconds: number) => {
    setBusy(true);
    setMsg("Starting on the boombox…");
    try {
      await api.post("api/remote/video/play", fromSeconds > 0
        ? { item_id: item.id, start_ticks: fromSeconds * TICKS_PER_SECOND }
        : { item_id: item.id });
      onClose();
    } catch (e) {
      setMsg(apiErrorMessage(e, "Couldn't start it on the boombox"));
      setBusy(false);
    }
  };
  return (
    <div role="dialog" aria-label={item.name} onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 520, maxHeight: "90vh", overflowY: "auto",
        background: "var(--panel)", border: "1px solid var(--rule)", borderRadius: 14,
        padding: 16, display: "flex", flexDirection: "column", gap: 12,
      }}>
        <div style={{ display: "flex", gap: 14, minWidth: 0 }}>
          <AuthedImg path={imagePath(item, 480)} alt=""
                     style={{ width: 120, aspectRatio: "2 / 3", borderRadius: 10, flexShrink: 0 }} />
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: "0 0 6px", fontSize: 20 }}>{item.name}</h2>
            <div style={{ color: "var(--ink2)", fontSize: 13 }}>{itemSubtitle(item)}</div>
          </div>
        </div>
        {item.overview && <p style={{ margin: 0, fontSize: 14, lineHeight: 1.45 }}>{item.overview}</p>}
        <button type="button" onClick={() => void start(0)} disabled={busy} style={primary}>
          Play on the boombox</button>
        {item.resume_s > 0 && (
          <button type="button" onClick={() => void start(item.resume_s)} disabled={busy}
                  style={secondary}>Resume from {clock(item.resume_s)}</button>
        )}
        {msg && <p role="status" style={{ margin: 0, color: "var(--ink2)", fontSize: 14 }}>{msg}</p>}
        <button type="button" onClick={onClose} style={secondary}>Close</button>
      </div>
    </div>
  );
}

const ellipsis: CSSProperties = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const h2: CSSProperties = { fontSize: 16, margin: "0 0 10px" };
const searchInput: CSSProperties = {
  padding: "10px 12px", borderRadius: 10, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 16, width: "100%",
};
const tileBtn: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 6, minWidth: 0, padding: 0,
  background: "transparent", border: 0, color: "var(--ink)", textAlign: "left", cursor: "pointer",
};
const primary: CSSProperties = {
  padding: "13px 18px", borderRadius: 12, border: 0, minHeight: 48,
  background: "var(--accent)", color: "var(--bg)", fontSize: 16, fontWeight: 700, cursor: "pointer",
};
const secondary: CSSProperties = {
  padding: "12px 18px", borderRadius: 12, minHeight: 48, border: "1px solid var(--rule)",
  background: "var(--panel)", color: "var(--ink)", fontSize: 15, cursor: "pointer",
};
const backBtn: CSSProperties = {
  background: "transparent", border: 0, color: "var(--ink2)", fontSize: 14,
  cursor: "pointer", padding: "4px 0", marginBottom: 8,
};
```

In `remote-ui/src/components/AppShell.tsx`: add `import { Video } from "../screens/Video";` and replace the `case "video":` (two lines, returning the `SectionMessage`) with:

```tsx
    case "video": return <Video params={p.params} navigate={p.navigate} />;
```

- [ ] **Step 4: Run the tests and build**

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`
Expected: tsc silent; all test files pass; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add remote-ui/src/lib/video.ts remote-ui/src/components/VideoControls.tsx \
  remote-ui/src/components/VideoControls.test.tsx remote-ui/src/screens/Video.tsx \
  remote-ui/src/screens/Video.test.tsx remote-ui/src/components/AppShell.tsx
git commit -m "feat(remote-ui): Video section — Jellyfin browse, play on the boombox, seek/track/volume controls

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Admin lock + Accounts section (cards move from setup-ui)

**Import across packages or copy? — Move the cards, copy the two shared forms.** `remote-ui` and `setup-ui` are separate Vite packages with their own `node_modules`, `tsconfig` roots (`"include": ["src"]`) and CI jobs (`npm ci` per package). Importing `../setup-ui/src/...` from remote-ui would resolve `react` from `setup-ui/node_modules` (a second React copy → "Invalid hook call" unless `resolve.dedupe` is added), needs `server.fs.allow`, and breaks remote-ui's CI job whenever setup-ui's dependencies aren't installed. The Accounts page itself is retired (`/accounts/*` now redirects into the app, and its Basic-auth API contract is gone after Task 1), so its cards, types, status pill and tests **move** (`git mv`) to `remote-ui/src/admin/accounts/` — no duplication. Only `MusicForm`, `VideoServerForm` (still used by the setup wizard) and the `ui.tsx` primitives they need are **copied** into `remote-ui/src/admin/`, each with a header naming its twin. They are small, presentational and stable.

**Files:**
- Create: `remote-ui/src/admin/session.ts`, `remote-ui/src/admin/session.test.ts`, `remote-ui/src/admin/LockScreen.tsx`, `remote-ui/src/admin/AccountsSection.tsx`
- Copy: `setup-ui/src/components/ui.tsx` → `remote-ui/src/admin/ui.tsx`; `setup-ui/src/shared/{MusicForm,VideoServerForm,forms.test}.tsx` → `remote-ui/src/admin/forms/`
- Move (`git mv`): `setup-ui/src/accounts/{types.ts,StatusPill.tsx,MusicCard.tsx,VideoCard.tsx,StreamingCard.tsx,WebLoginCard.tsx,accounts.test.tsx}` → `remote-ui/src/admin/accounts/`
- Rewrite: `remote-ui/src/admin/accounts/api.ts` (new file; replaces setup-ui's `api.ts`)
- Modify (moved files): card import paths; `WebLoginCard.tsx` lines 26–29, 40–41, 44–45; `accounts.test.tsx` line 3, top-level `beforeEach`, every `render(<AccountsApp />)`, new tests appended
- Delete: `setup-ui/accounts.html`, `setup-ui/src/accounts/AccountsApp.tsx`, `setup-ui/src/accounts/api.ts`, `setup-ui/src/accounts/main.tsx`
- Modify: `setup-ui/vite.config.ts` (single entry)
- Modify: `remote-ui/src/components/AppShell.tsx` (imports, `adminLocked`, `case "accounts"`), `remote-ui/src/components/AppShell.test.tsx` (append)

**Interfaces:**
- Consumes: Task 1 HTTP (`POST /api/accounts/session {password}` → `{ok, token, expires_at}` / 401 / 403 / 429 `{retry_after}` / 503; `DELETE /api/accounts/session`; every other `/api/accounts/*` needs `Authorization: Bearer <token>`, 401 `admin session required` when expired); Task 6 `renderSection`, `Sidebar`/`More` `adminLocked` props.
- Produces (TS, `admin/session.ts`): `SESSION_KEY = "boombox-admin-session"` (sessionStorage); `adminSession` store `{ token(): string | null; expired(): boolean; set(token: string): void; clear(reason: "logout" | "expired"): void; subscribe(fn): () => void }`; `useAdminSession(): { unlocked: boolean; expired: boolean }`; `unlock(password: string): Promise<{ok: true} | {ok: false; error: string}>`; `lock(): Promise<void>`.
- Produces (TS): `admin/accounts/api.ts` `accountsApi.get/post/put` (same signatures as setup-ui's, plus bearer token; a 401 calls `adminSession.clear("expired")`); `AccountsSection({desktop: boolean})` (lock screen when locked; 4 cards in a `data-testid="accounts-grid"` grid with `data-columns` 2 on desktop / 1 on phones; "Lock admin" button); `LockScreen({expired: boolean})`.

- [ ] **Step 1: Move / copy the files (no behaviour change yet)**

```bash
mkdir -p remote-ui/src/admin/accounts remote-ui/src/admin/forms
for f in types.ts StatusPill.tsx MusicCard.tsx VideoCard.tsx StreamingCard.tsx WebLoginCard.tsx accounts.test.tsx; do
  git mv "setup-ui/src/accounts/$f" "remote-ui/src/admin/accounts/$f"
done
git rm -q setup-ui/accounts.html setup-ui/src/accounts/AccountsApp.tsx \
  setup-ui/src/accounts/api.ts setup-ui/src/accounts/main.tsx
cp setup-ui/src/components/ui.tsx remote-ui/src/admin/ui.tsx
for f in MusicForm.tsx VideoServerForm.tsx forms.test.tsx; do
  cp "setup-ui/src/shared/$f" "remote-ui/src/admin/forms/$f"
done
# Moved cards: ../components/ui → ../ui, ../shared/* → ../forms/*; copied forms: ../components/ui → ../ui
sed -i '' -e 's#"../components/ui"#"../ui"#' -e 's#"../shared/#"../forms/#' \
  remote-ui/src/admin/accounts/*.tsx remote-ui/src/admin/forms/*.tsx
```

Prepend to `remote-ui/src/admin/ui.tsx`:

```tsx
// Copied from setup-ui/src/components/ui.tsx (the setup wizard keeps its
// own copy; remote-ui and setup-ui are separate Vite packages). Keep the two
// in step when changing shared primitives.
```

Prepend to `remote-ui/src/admin/forms/MusicForm.tsx` and `remote-ui/src/admin/forms/VideoServerForm.tsx` respectively:

```tsx
// Copied from setup-ui/src/shared/MusicForm.tsx — the wizard's twin. Keep in step.
```

```tsx
// Copied from setup-ui/src/shared/VideoServerForm.tsx — the wizard's twin. Keep in step.
```

Replace `setup-ui/vite.config.ts` with:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // The setup wizard, served by nginx at /setup/. (The old Accounts page
  // entry moved into the LAN app — remote-ui, Admin → Accounts.)
  base: "/setup/",
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

- [ ] **Step 2: Write the failing tests**

Create `remote-ui/src/admin/session.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { adminSession, unlock, lock, SESSION_KEY } from "./session";

function reply(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => adminSession.clear("logout"));
afterEach(() => vi.unstubAllGlobals());

describe("admin session", () => {
  it("unlock stores the token for this tab only", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, { ok: true, token: "tok", expires_at: 1 }));
    vi.stubGlobal("fetch", f);
    expect(await unlock("correct horse battery")).toEqual({ ok: true });
    expect(adminSession.token()).toBe("tok");
    expect(sessionStorage.getItem(SESSION_KEY)).toBe("tok");
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(f).toHaveBeenCalledWith("/api/accounts/session", expect.objectContaining({
      method: "POST", body: JSON.stringify({ password: "correct horse battery" }) }));
  });

  it.each([
    [401, {}, "Wrong password."],
    [429, { retry_after: 61 }, "Too many wrong passwords — try again in 2 minutes."],
    [403, {}, "Admin can't be unlocked from the boombox's own screen."],
    [503, { error: "no web password is set on this boombox" }, "no web password is set on this boombox"],
  ])("explains a %s", async (status, body, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(status as number, body)));
    expect(await unlock("x")).toEqual({ ok: false, error: message });
    expect(adminSession.token()).toBeNull();
  });

  it("a network failure says so", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    expect(await unlock("x")).toEqual({ ok: false, error: "Couldn't reach the Boombox." });
  });

  it("lock forgets the token and tells the server", async () => {
    adminSession.set("tok");
    const f = vi.fn().mockResolvedValue(reply(200, { ok: true }));
    vi.stubGlobal("fetch", f);
    await lock();
    expect(adminSession.token()).toBeNull();
    expect(adminSession.expired()).toBe(false);
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(f).toHaveBeenCalledWith("/api/accounts/session", expect.objectContaining({
      method: "DELETE",
      headers: { "Content-Type": "application/json", Authorization: "Bearer tok" } }));
  });

  it("clear('expired') remembers why", () => {
    adminSession.set("tok");
    const seen = vi.fn();
    const off = adminSession.subscribe(seen);
    adminSession.clear("expired");
    expect(adminSession.expired()).toBe(true);
    expect(seen).toHaveBeenCalled();
    off();
  });
});
```

In `remote-ui/src/admin/accounts/accounts.test.tsx`:
- replace line 3 `import { AccountsApp } from "./AccountsApp";` with

```tsx
import { AccountsSection } from "../AccountsSection";
import { adminSession } from "../session";
```

- make `adminSession.set("tok");` the first statement of the top-level `beforeEach` (the one that resets `calls`, `R` and `once`);
- replace every `render(<AccountsApp />);` with `render(<AccountsSection desktop />);` (`sed -i '' 's#render(<AccountsApp />);#render(<AccountsSection desktop />);#' remote-ui/src/admin/accounts/accounts.test.tsx`);
- append:

```tsx
describe("Admin gate", () => {
  it("sends the admin bearer token on every call", async () => {
    render(<AccountsSection desktop />);
    await screen.findByText("Music server");
    await waitFor(() => expect(calls.length).toBeGreaterThan(3));
    expect(calls.every((c) => c.headers?.Authorization === "Bearer tok")).toBe(true);
  });

  it("locked: shows the lock screen, unlocks with the web password", async () => {
    adminSession.clear("logout");
    once["POST /api/accounts/session"] = [{ status: 200,
      body: { ok: true, token: "fresh", expires_at: 1 } }];
    render(<AccountsSection desktop />);
    expect(screen.queryByText("Music server")).toBeNull();
    fireEvent.change(screen.getByLabelText("Web password"),
      { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
    expect(await screen.findByText("Music server")).toBeTruthy();
    expect(calls.find((c) => c.url === "/api/accounts/session")!.body)
      .toEqual({ password: "correct horse battery" });
    expect(adminSession.token()).toBe("fresh");
  });

  it("explains a lockout", async () => {
    adminSession.clear("logout");
    once["POST /api/accounts/session"] = [{ status: 429,
      body: { ok: false, error: "too many wrong passwords — try again later", retry_after: 240 } }];
    render(<AccountsSection desktop />);
    fireEvent.change(screen.getByLabelText("Web password"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
    expect(await screen.findByText(/try again in 4 minutes/i)).toBeTruthy();
  });

  it("an expired session drops back to the lock screen", async () => {
    once["GET /api/accounts/summary"] = [{ status: 401, body: { error: "admin session required" } }];
    render(<AccountsSection desktop />);
    expect(await screen.findByText(/session expired/i)).toBeTruthy();
    expect(adminSession.token()).toBeNull();
  });

  it("Lock logs out", async () => {
    render(<AccountsSection desktop />);
    await screen.findByText("Music server");
    fireEvent.click(screen.getByRole("button", { name: /lock admin/i }));
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/accounts/session"
      && c.headers?.Authorization === "Bearer tok")).toBe(true);
  });

  it("changing the web password keeps you unlocked", async () => {
    R["PUT /api/accounts/web-login"] = { ok: true, updated: ["web", "samba"] };
    render(<AccountsSection desktop />);
    await screen.findByText("Boombox web login");
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "old password 1" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "correct horse battery" } });
    fireEvent.change(screen.getByLabelText(/repeat new password/i), { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: /change password/i }));
    expect(await screen.findByText(/password changed/i)).toBeTruthy();
    expect(adminSession.token()).toBe("tok");
  });

  it("two columns on desktop, one on phones", async () => {
    const { unmount } = render(<AccountsSection desktop />);
    expect((await screen.findByTestId("accounts-grid")).dataset.columns).toBe("2");
    unmount();
    render(<AccountsSection desktop={false} />);
    expect((await screen.findByTestId("accounts-grid")).dataset.columns).toBe("1");
  });
});
```

Append to `remote-ui/src/components/AppShell.test.tsx` (add `act` to its `@testing-library/react` import and `import { adminSession } from "../admin/session";`):

```tsx
describe("AppShell admin", () => {
  it("Accounts is locked by default and the sidebar lock follows the session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    adminSession.clear("logout");
    setViewport(1440, 900);
    window.location.hash = "#/accounts";
    renderShell();
    expect(await screen.findByLabelText("Web password")).toBeTruthy();
    const sidebar = screen.getByRole("navigation", { name: "Sections" });
    const accounts = within(sidebar).getByRole("button", { name: "Accounts" });
    expect(accounts.textContent).toContain("🔒");
    act(() => adminSession.set("t"));
    expect(accounts.textContent).toContain("🔓");
    act(() => adminSession.clear("logout"));
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd remote-ui && npx vitest run src/admin src/components/AppShell.test.tsx`
Expected: FAIL — `Failed to resolve import "./session"` / `"../AccountsSection"`, `"./api"` (the moved cards import `./api`, which doesn't exist in remote-ui yet).

- [ ] **Step 4: Implement**

Create `remote-ui/src/admin/session.ts`:

```ts
import { useSyncExternalStore } from "react";

/** The admin session token for Admin sections (/api/accounts/*). Kept in
 *  sessionStorage — this tab only, gone when the browser closes — and
 *  mirrored in memory for the React store. */
export const SESSION_KEY = "boombox-admin-session";
const SESSION_URL = "/api/accounts/session";

type Listener = () => void;

function readStored(): string | null {
  try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; }
}

const state: { token: string | null; expired: boolean } = { token: readStored(), expired: false };
const listeners = new Set<Listener>();

function emit(): void {
  for (const l of listeners) l();
}

export const adminSession = {
  token: (): string | null => state.token,
  expired: (): boolean => state.expired,
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  set(token: string): void {
    state.token = token;
    state.expired = false;
    try { sessionStorage.setItem(SESSION_KEY, token); } catch { /* private mode: memory only */ }
    emit();
  },
  clear(reason: "logout" | "expired"): void {
    state.token = null;
    state.expired = reason === "expired";
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
    emit();
  },
};

function snapshot(): string {
  return `${state.token ?? ""}|${state.expired ? 1 : 0}`;
}

export function useAdminSession(): { unlocked: boolean; expired: boolean } {
  useSyncExternalStore(adminSession.subscribe, snapshot, snapshot);
  return { unlocked: state.token !== null, expired: state.expired };
}

export type UnlockResult = { ok: true } | { ok: false; error: string };

export async function unlock(password: string): Promise<UnlockResult> {
  let r: Response;
  try {
    r = await fetch(SESSION_URL, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
  } catch {
    return { ok: false, error: "Couldn't reach the Boombox." };
  }
  const body = await r.json().catch(() => ({})) as
    { token?: unknown; error?: unknown; retry_after?: unknown };
  if (r.ok && typeof body.token === "string") {
    adminSession.set(body.token);
    return { ok: true };
  }
  if (r.status === 429) {
    const secs = typeof body.retry_after === "number" ? body.retry_after : 300;
    const mins = Math.max(1, Math.ceil(secs / 60));
    return { ok: false,
      error: `Too many wrong passwords — try again in ${mins} minute${mins === 1 ? "" : "s"}.` };
  }
  if (r.status === 401) return { ok: false, error: "Wrong password." };
  if (r.status === 403) return { ok: false, error: "Admin can't be unlocked from the boombox's own screen." };
  return { ok: false,
    error: typeof body.error === "string" && body.error ? body.error : `Couldn't unlock (HTTP ${r.status}).` };
}

export async function lock(): Promise<void> {
  const token = state.token;
  adminSession.clear("logout");
  if (!token) return;
  try {
    await fetch(SESSION_URL, {
      method: "DELETE", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: "{}",
    });
  } catch { /* the token dies with its 12 h idle timeout anyway */ }
}
```

Create `remote-ui/src/admin/accounts/api.ts`:

```ts
import { adminSession } from "../session";

const BASE = "/api/accounts/";

/** Same-origin JSON call with the admin token. A 401 means the admin session
 *  expired (12 h idle, or boombox-setup restarted): drop it so the section
 *  shows the lock screen. A non-2xx response with a JSON body resolves to
 *  that body (cards show its `error`); network failure / non-JSON rejects. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = adminSession.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  const init: RequestInit = { method, credentials: "same-origin", headers };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body ?? {});
  }
  const r = await fetch(BASE + path, init);
  if (r.status === 401) adminSession.clear("expired");
  try {
    return (await r.json()) as T;
  } catch {
    throw new Error(`HTTP ${r.status}`);
  }
}

export const accountsApi = {
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body?: unknown) => call<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => call<T>("PUT", path, body),
};
```

Create `remote-ui/src/admin/LockScreen.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { ErrorText, Field, PrimaryButton, inputStyle } from "./ui";
import { unlock } from "./session";

/** Admin sections stay locked until the boombox web password is entered. */
export function LockScreen({ expired }: { expired: boolean }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await unlock(password);
    setBusy(false);
    if (r.ok) setPassword("");
    else setError(r.error);
  };

  return (
    <form onSubmit={submit} style={{
      padding: 24, maxWidth: 420, margin: "0 auto",
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <h1 style={{ fontSize: 22, margin: 0 }}>🔒 Admin</h1>
      <p style={{ margin: 0, color: "var(--ink2)", fontSize: 14 }}>
        {expired
          ? "Your admin session expired. Enter the boombox web password again."
          : "Enter the boombox web password to manage accounts."}
      </p>
      <Field label="Web password">
        <input type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} aria-label="Web password"
               style={inputStyle} />
      </Field>
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton type="submit" disabled={busy || password === ""}>
        {busy ? "Unlocking…" : "Unlock"}
      </PrimaryButton>
    </form>
  );
}
```

Create `remote-ui/src/admin/AccountsSection.tsx`:

```tsx
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ErrorText, SecondaryButton } from "./ui";
import { accountsApi } from "./accounts/api";
import type { Summary, CardStatus } from "./accounts/types";
import { StatusPill } from "./accounts/StatusPill";
import { MusicCard } from "./accounts/MusicCard";
import { VideoCard } from "./accounts/VideoCard";
import { StreamingCard } from "./accounts/StreamingCard";
import { WebLoginCard } from "./accounts/WebLoginCard";
import { LockScreen } from "./LockScreen";
import { lock, useAdminSession } from "./session";

export const UNREACHABLE = "Couldn't reach the Boombox.";

function Section({ title, status, children }: {
  title: string; status?: CardStatus; children: ReactNode;
}) {
  return (
    <section style={{ border: "1px solid var(--rule)", borderRadius: 14, padding: 16, minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>{title}</h2>
        {status && <StatusPill state={status.state} detail={status.detail} />}
      </div>
      {children}
    </section>
  );
}

function AccountsCards({ desktop }: { desktop: boolean }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    accountsApi.get<Summary & { error?: string }>("summary").then((s) => {
      if (s && s.music) { setSummary(s); setError(null); }
      else setError(s?.error ?? UNREACHABLE);
    }).catch(() => setError(UNREACHABLE));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return (
    <div style={{ padding: 16, paddingBottom: 96, display: "flex", flexDirection: "column", gap: 16 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h1 style={{ fontSize: 24, margin: 0 }}>Accounts</h1>
        <SecondaryButton aria-label="Lock admin" onClick={() => void lock()}
                         style={{ width: "auto", minHeight: 40, padding: "8px 14px" }}>
          🔒 Lock
        </SecondaryButton>
      </header>
      {error && <ErrorText>{error}</ErrorText>}
      <div data-testid="accounts-grid" data-columns={desktop ? 2 : 1} style={{
        display: "grid", gap: 16, alignItems: "start",
        gridTemplateColumns: desktop ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)",
      }}>
        <Section title="Music server" status={summary?.music}><MusicCard onChanged={refresh} /></Section>
        <Section title="Video server" status={summary?.video}><VideoCard onChanged={refresh} /></Section>
        <Section title="Streaming receivers" status={summary?.streaming}>
          <StreamingCard onChanged={refresh} /></Section>
        <Section title="Boombox web login" status={summary?.web}><WebLoginCard /></Section>
      </div>
    </div>
  );
}

/** Admin → Accounts: the four Accounts cards, behind the web password. */
export function AccountsSection({ desktop }: { desktop: boolean }) {
  const { unlocked, expired } = useAdminSession();
  if (!unlocked) return <LockScreen expired={expired} />;
  return <AccountsCards desktop={desktop} />;
}
```

`remote-ui/src/admin/accounts/WebLoginCard.tsx` (moved file):
- replace

```tsx
      if (r.ok) {
        setDone(true);
        setTimeout(() => window.location.reload(), 2000);
      } else {
```

with

```tsx
      if (r.ok) {
        // The admin session survives a password change; no reload needed.
        setDone(true);
      } else {
```

- replace the `if (done) return …` lines with

```tsx
  if (done) return <p style={{ margin: 0 }}>
    Password changed — use the new one next time you unlock Admin or open the music share.</p>;
```

- replace `The password for this web UI (user <code>boombox</code>) and the music file share.</p>` with

```tsx
        The boombox web password (user <code>boombox</code>): it unlocks Admin here and the music file share.</p>
```

`remote-ui/src/components/AppShell.tsx`:
- add imports `import { AccountsSection } from "../admin/AccountsSection";` and `import { useAdminSession } from "../admin/session";`, and delete `import { SectionMessage } from "./SectionMessage";` (no longer used once the accounts case below is replaced — `noUnusedLocals` would fail the build)
- replace `const adminLocked = true;` with

```tsx
  const { unlocked } = useAdminSession();
  const adminLocked = !unlocked;
```

- replace the `case "accounts":` (two lines returning the `SectionMessage`) with

```tsx
    case "accounts": return <AccountsSection desktop={p.desktop} />;
```

- [ ] **Step 5: Run the tests and builds**

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build`
Expected: tsc silent; all test files pass (including the moved `accounts.test.tsx` and copied `forms.test.tsx`); build succeeds.

Run: `cd setup-ui && npx tsc -b && npx vitest run && npm run build && ls dist`
Expected: tsc silent; wizard tests + `src/shared/forms.test.tsx` pass; `dist` has `index.html` and `assets/` but no `accounts.html`.

- [ ] **Step 6: Commit**

```bash
# the git mv / git rm from Step 1 are already staged
git add -A remote-ui/src/admin remote-ui/src/components/AppShell.tsx \
  remote-ui/src/components/AppShell.test.tsx setup-ui/vite.config.ts
git status --short   # expect: R setup-ui/src/accounts/* -> remote-ui/src/admin/accounts/*, D accounts.html/AccountsApp/api/main
git commit -m "feat(remote-ui): Admin lock (web password → session) and the Accounts cards, moved from setup-ui

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Old-PWA hand-off (kill-switch worker + "moved" hint) and docs

**Files:**
- Create: `remote-ui/public/legacy-remote-sw.js`, `remote-ui/src/components/MovedHint.tsx`, `remote-ui/src/components/MovedHint.test.tsx`
- Modify: `remote-ui/src/App.tsx` (wrap in `MovedHint`)
- Modify: `services/tests/test_remote_ui_config.py` (append)
- Modify: `docs/SERVICES.md` (boombox-remote intro ~lines 300–315 + endpoint table ~line 335; boombox-setup section lines 415–453), `docs/ACCESS.md` (lines 35–45), `docs/HOME-SERVERS.md` (lines 252, 284), `docs/HOME-LIBRARY.md` (lines 234–238), `docs/ARCHITECTURE.md` (lines 27, 29), `README.md` (lines 30, 60–62)

**Interfaces:**
- Consumes: Task 5 nginx (`/remote/sw.js` → `remote-ui/dist/legacy-remote-sw.js`; `/remote/*` → `301 /?from=remote`); Vite copies `public/*` to `dist/` verbatim.
- Produces: `MovedHint()` — a one-time dismissable banner shown when the page URL has `?from=remote`; it strips the marker from the URL (`history.replaceState`) and records `localStorage["boombox.moved_hint_seen"] = "1"` so it never shows again.

- [ ] **Step 1: Write the failing tests**

Append to `services/tests/test_remote_ui_config.py`:

```python
def test_legacy_remote_sw_unregisters_itself():
    sw = (ROOT / "remote-ui" / "public" / "legacy-remote-sw.js").read_text()
    assert "self.skipWaiting()" in sw
    assert "self.registration.unregister()" in sw
    assert 'client.navigate("/?from=remote")' in sw
    # Only the old app's caches go; the new root-scoped app's precache stays.
    assert 'key.includes("/remote/")' in sw
```

Create `remote-ui/src/components/MovedHint.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MovedHint } from "./MovedHint";

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("MovedHint", () => {
  it("shows once when opened from the old /remote/ address, and strips the marker", () => {
    window.history.replaceState(null, "", "/?from=remote#/now");
    render(<MovedHint />);
    const hint = screen.getByRole("region", { name: /app moved/i });
    expect(hint.textContent).toContain(window.location.host);
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#/now");
    cleanup();
    window.history.replaceState(null, "", "/?from=remote");
    render(<MovedHint />);
    expect(screen.queryByRole("region", { name: /app moved/i })).toBeNull();
  });

  it("is hidden without the marker", () => {
    render(<MovedHint />);
    expect(screen.queryByRole("region", { name: /app moved/i })).toBeNull();
  });

  it("can be dismissed", () => {
    window.history.replaceState(null, "", "/?from=remote");
    render(<MovedHint />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("region", { name: /app moved/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_ui_config.py && (cd remote-ui && npx vitest run src/components/MovedHint.test.tsx)`
Expected: FAIL — `FileNotFoundError: …/remote-ui/public/legacy-remote-sw.js`; vitest `Failed to resolve import "./MovedHint"`.

- [ ] **Step 3: Implement**

Create `remote-ui/public/legacy-remote-sw.js`:

```js
// Kill-switch for the old phone remote's service worker (scope /remote/).
// nginx serves this file at /remote/sw.js, so an installed old PWA's update
// check finds a "new" worker: it installs at once, drops the old app's
// caches, unregisters itself and sends any open old-app tab to the new app
// (/?from=remote shows the one-time "reinstall from this address" hint).
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((key) => key.includes("/remote/"))
      .map((key) => caches.delete(key)));
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: "window" });
    for (const client of clients) client.navigate("/?from=remote");
  })());
});
```

Create `remote-ui/src/components/MovedHint.tsx`:

```tsx
import { useEffect, useState } from "react";

const SEEN_KEY = "boombox.moved_hint_seen";

function fromOldApp(): boolean {
  return new URLSearchParams(window.location.search).get("from") === "remote";
}

function seen(): boolean {
  try { return localStorage.getItem(SEEN_KEY) === "1"; } catch { return false; }
}

/** One-time hint for people arriving from the old /remote/ address (nginx
 *  redirects it to /?from=remote): the app lives at / now, so an old
 *  home-screen icon should be replaced. */
export function MovedHint() {
  const [show] = useState(() => fromOldApp() && !seen());
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!fromOldApp()) return;
    // Drop the marker so a reload or bookmark doesn't re-trigger it, and
    // remember we've shown it.
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    try { localStorage.setItem(SEEN_KEY, "1"); } catch { /* private mode */ }
  }, []);

  if (!show || dismissed) return null;
  return (
    <div role="region" aria-label="The app moved" style={{
      margin: 12, padding: "10px 12px", borderRadius: 12, fontSize: 13,
      background: "var(--panel)", border: "1px solid var(--accent)",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <span style={{ flex: 1, minWidth: 0 }}>
        The Boombox app now lives at <strong>{window.location.host}/</strong>. If you added
        the old remote to your home screen, remove it and add this page instead.
      </span>
      <button type="button" aria-label="Dismiss" onClick={() => setDismissed(true)} style={{
        background: "transparent", border: 0, color: "var(--ink2)", fontSize: 18,
        cursor: "pointer", lineHeight: 1,
      }}>×</button>
    </div>
  );
}
```

In `remote-ui/src/App.tsx`: add `import { MovedHint } from "./components/MovedHint";`, rename `export default function App() {` to `function Main() {`, and add at the end of the file:

```tsx
export default function App() {
  return (
    <>
      <MovedHint />
      <Main />
    </>
  );
}
```

Docs:

- `docs/SERVICES.md`, boombox-remote intro: replace "the phone web app at `/remote/`" with "the LAN app at `/` on the LAN port (phone + desktop)"; replace the sentence "nginx serves it from `current/remote-ui/dist/` at the `/remote/` location, built in place by `install.sh` / `apply-release.sh` (same pattern as the kiosk SPA)." with "nginx's LAN server block serves it from `current/remote-ui/dist/` at `/` (bundles under `/app-assets/`; `/remote/*` redirects to `/?from=remote`, `/accounts/*` to `/#/accounts`); the kiosk's loopback server keeps the kiosk UI at `/`." Append to the endpoint table:

```
| `GET  /api/remote/home/browse?type=artists\|albums\|playlists` | Bearer: Home Library lists (boombox-library pass-through, ETag kept) |
| `GET  /api/remote/home/search?q=`, `GET /api/remote/home/{artist\|album\|playlist}/{id}` | Bearer: Home Library search / drill-down |
| `GET  /api/remote/home/art/{art_id}?size=` | Bearer: cover art via the library art proxy |
| `POST /api/remote/home/play` | Bearer: `{ids, mode: play\|queue}` → resolve, drop offline misses, first track now + rest in background chunks |
| `GET  /api/remote/video/views`, `/resume`, `/items?parent_id=&type=&search=&start=&limit=` | Bearer: Jellyfin browse as the kiosk's signed-in user (API key server-side only) |
| `GET  /api/remote/video/image/{id}?max_width=` | Bearer: poster, cached on disk |
| `POST /api/remote/video/play` | Bearer: `{item_id, start_ticks?}` → WATCH the kiosk if needed, wait ≤ 20 s for its session, PlayNow |
```

  and change the existing video row to "`GET /api/remote/video/state`, `POST /api/remote/video/command` | Bearer: Jellyfin transport — state has audio/subtitle streams + indexes; commands `play_pause`, `stop`, `seek`, `volume`, `mute`, `set_audio`, `set_subtitle` (-1 = off)".
- `docs/SERVICES.md`, boombox-setup section: change "`/api/accounts/` (keeps the LAN Basic auth)" to "`/api/accounts/` (`auth_basic off`; admin-session gated)"; change "the LAN **Accounts** page (`http://<boombox>:8090/accounts/`, served from the `setup-ui` build)" to "**Admin → Accounts** in the LAN app (`http://<boombox>:8090/#/accounts`)"; add table rows `| POST /api/accounts/session | {password} → {token, expires_at}; the web password from web-auth.env; 5 failures in 5 min lock logins for 5 min; refused from loopback |` and `| DELETE /api/accounts/session | Log out (forget the token) |`; replace the "Auth rules" bullets with:

```
- nginx forwards `X-Real-IP: $remote_addr` and `X-Boombox-Host: $http_host`
  and passes `Authorization` through (it carries the admin token).
- Every request must come from a non-loopback `X-Real-IP` (`127.0.0.1`,
  `::1`, `localhost`; missing counts as loopback) — the kiosk can never log
  in or use a token. All routes but `/session` also need
  `Authorization: Bearer <admin token>`: 32 random bytes, in memory only
  (a service restart logs everyone out), 12 h idle expiry refreshed on use.
- Mutations (POST/PUT/PATCH/DELETE) need `Content-Type: application/json`
  and, when `Origin` is present, its host:port must equal `X-Boombox-Host`.
- Every login attempt is logged with the client IP and outcome, never the
  password. Secrets are write-only: no response carries a password, API key
  or token (other than a fresh admin token), and none are logged. Upstream
  failures come back as an error message (400/502) or a card status, never a 500.
```

- `docs/ACCESS.md` lines 35–45: replace "the phone web app at `/remote/`" with "the LAN app at `/`", and "`http://<pi-ip>:8090/remote/` — the same URL the touchscreen's web-QR overlay encodes." with "`http://<pi-ip>:8090/` (the touchscreen's web-QR overlay still encodes the old `/remote/` address, which redirects there)."
- `docs/HOME-SERVERS.md` lines 252 and 284: replace `http://<boombox>:8090/accounts/` with `http://<boombox>:8090/#/accounts`; at line 284 replace "(the boombox web login)" with "(unlock Admin with the boombox web password)".
- `docs/HOME-LIBRARY.md` lines 234–238: replace the "No PWA browse parity yet" bullet with "- **Phone / desktop browse.** The LAN app at `http://<boombox>:8090/` → Music → Home Library browses artists, albums and playlists and plays or queues them on the boombox; pinning still happens on the touchscreen."
- `docs/ARCHITECTURE.md`: line 27 `│  │ /remote/   (PWA)    │  │` → `│  │ :8090 / (LAN app)   │  │`; line 29 `LAN :8090 → Basic auth` → `LAN :8090 → app + auth`.
- `README.md`: line 30 `├─ /remote/   (PWA — no auth)` → `├─ / on :8090 (LAN app — pairing)`; lines 60–62: replace "live on the LAN Accounts page: [`http://<boombox>:8090/accounts/`](docs/SERVICES.md#boombox-setup--first-run-wizard--lan-accounts-api)." with "live in the LAN app under Admin → Accounts: [`http://<boombox>:8090/#/accounts`](docs/SERVICES.md#boombox-setup--first-run-wizard--lan-accounts-api) (unlock with the boombox web password)."

- [ ] **Step 4: Run the tests and checks**

Run: `.venv/bin/python -m pytest -q services/tests/test_remote_ui_config.py`
Expected: PASS.

Run: `cd remote-ui && npx tsc -b && npx vitest run && npm run build && ls dist/legacy-remote-sw.js`
Expected: all pass; build succeeds; `dist/legacy-remote-sw.js` exists.

Run: `grep -rn "8090/accounts/\|8090/remote/" docs README.md`
Expected: only `docs/SKINS.md:213` (the kiosk QR overlay still encodes `/remote/`, which redirects — the kiosk UI is out of scope).

- [ ] **Step 5: Commit**

```bash
git add remote-ui/public/legacy-remote-sw.js remote-ui/src/components/MovedHint.tsx \
  remote-ui/src/components/MovedHint.test.tsx remote-ui/src/App.tsx \
  services/tests/test_remote_ui_config.py docs/SERVICES.md docs/ACCESS.md \
  docs/HOME-SERVERS.md docs/HOME-LIBRARY.md docs/ARCHITECTURE.md README.md
git commit -m "feat(remote-ui): hand old /remote/ PWAs over (kill-switch worker + one-time hint); docs for the LAN app

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Deploy to MarkII and verify on the device

**Device facts:** MarkII = `192.168.1.81` (`markii.local`), DietPi, service user `dietpi`; `ssh root@192.168.1.81` / `ssh dietpi@192.168.1.81`. Releases live in `/opt/boombox/releases/<ref>`, `current` → the active one. Jellyfin is remote (`video.coblr.io`) with the kiosk pinned as `BOOMBOX_JELLYFIN_DEVICE_ID=boombox-markii-kiosk`. **Never build on the Pi. Deploy only when the Pi is < 65 °C and the minute is not within 2 of `:38`** (hourly library sync; MarkII brown-outs under load). This deploy needs the root helper reinstalled **before** `swap` (swap now calls its `nginx-sync` action) and the sudoers file re-rendered (snippet rule removed).

**Files:** none (fixes found here go back to the owning task's files, with a test, as separate commits).

- [ ] **Step 1: Preconditions**

```bash
ssh root@192.168.1.81 'vcgencmd measure_temp; date +%M; uptime'
```
Expected: `temp=` below `65.0'C`; minute not in 36–40. If not, wait and re-check.

- [ ] **Step 2: Build every UI on the Mac and stage the release**

```bash
cd /Users/jwc/code/Boombox
(cd ui && npm ci && npm run build) && (cd remote-ui && npm ci && npm run build) && (cd setup-ui && npm ci && npm run build)
SHA=$(git rev-parse --short HEAD); echo "$SHA"
CUR=$(ssh dietpi@192.168.1.81 'basename "$(readlink -f /opt/boombox/current)"'); echo "$CUR"
ssh root@192.168.1.81 "cp -a /opt/boombox/releases/$CUR /opt/boombox/releases/$SHA"
git archive HEAD | ssh dietpi@192.168.1.81 "tar -x -C /opt/boombox/releases/$SHA"
for d in ui remote-ui setup-ui; do
  rsync -a --delete "$d/dist/" "dietpi@192.168.1.81:/opt/boombox/releases/$SHA/$d/dist/"
done
ssh dietpi@192.168.1.81 "printf '%s\n' $SHA > /opt/boombox/releases/$SHA/VERSION && chmod -R a+rX /opt/boombox/releases/$SHA/ui/dist /opt/boombox/releases/$SHA/remote-ui/dist /opt/boombox/releases/$SHA/setup-ui/dist"
```
Expected: `ls /opt/boombox/releases/$SHA/remote-ui/dist` on the Pi shows `index.html`, `app-assets/`, `legacy-remote-sw.js`, `sw.js`.

- [ ] **Step 3: Root: back up nginx, reinstall the helper, re-render sudoers**

```bash
ssh root@192.168.1.81 "set -e
  D=\$(date +%Y%m%d-%H%M)
  cp /etc/nginx/sites-available/boombox /root/nginx-site.bak-\$D
  cp /etc/nginx/snippets/boombox-common.conf /root/nginx-snippet.bak-\$D
  install -m 0755 -o root -g root /opt/boombox/releases/$SHA/install/bin/boombox-setup-apply /usr/local/sbin/boombox-setup-apply
  sed 's/%BOOMBOX_USER%/dietpi/g' /opt/boombox/releases/$SHA/install/sudoers/boombox > /tmp/boombox.sudoers
  visudo -cf /tmp/boombox.sudoers
  install -m 0440 -o root -g root /tmp/boombox.sudoers /etc/sudoers.d/boombox
  rm /tmp/boombox.sudoers
  echo '{\"action\":\"nonexistent\"}' | /usr/local/sbin/boombox-setup-apply || true"
```
Expected: `visudo` prints `/tmp/boombox.sudoers: parsed OK`; the last line prints `{"ok": false, "error": "unknown action: nonexistent"}` (helper is the new one and runs).

- [ ] **Step 4: Apply as `dietpi`**

```bash
ssh dietpi@192.168.1.81 "export XDG_RUNTIME_DIR=/run/user/\$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u)/bus
  R=/opt/boombox/releases/$SHA
  \$R/install/apply-release.sh preflight $SHA &&
  \$R/install/apply-release.sh swap $SHA &&
  \$R/install/apply-release.sh restart &&
  \$R/install/apply-release.sh verify; echo rc=\$?"
```
Expected: `swap` logs `nginx site + snippet in sync with releases/<SHA>`; `verify` passes both `nginx / (kiosk UI)` and `LAN app /`; `rc=0`. If verify fails: `$R/install/apply-release.sh revert` (restores the previous nginx pair through the helper) and investigate; restore by hand from `/root/nginx-*.bak-*` only if the helper itself fails.

- [ ] **Step 5: HTTP checks from the Mac**

```bash
B=http://192.168.1.81:8090
curl -s -o /dev/null -w "%{http_code}\n" $B/                       # 200 (no Basic auth)
curl -s $B/ | grep -o '/app-assets/[^"]*\.js' | head -1             # /app-assets/index-*.js
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" $B/remote/        # 301 http://192.168.1.81:8090/?from=remote
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" $B/accounts/      # 301 http://192.168.1.81:8090/#/accounts
curl -s $B/remote/sw.js | grep -c 'registration.unregister'         # 1
curl -s -o /dev/null -w "%{http_code}\n" $B/api/state               # 401 (Basic auth kept)
curl -s -o /dev/null -w "%{http_code}\n" $B/api/accounts/summary    # 401 (admin session required)
curl -s -o /dev/null -w "%{http_code}\n" $B/setup/                  # 200 (wizard still served)
ssh dietpi@192.168.1.81 "curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{\"password\":\"x\"}' http://127.0.0.1/api/accounts/session"   # 403: the kiosk can't log in
ssh dietpi@192.168.1.81 "curl -s http://127.0.0.1/ | grep -c '/assets/'"   # ≥ 1: kiosk UI still at / on :80
```

Admin login with the real password (read on the Pi into a Mac variable; never echo it):

```bash
PW=$(ssh root@192.168.1.81 "sed -n 's/^BOOMBOX_WEB_PASSWORD=//p' /etc/boombox/web-auth.env")
TOKEN=$(curl -s -X POST -H 'Content-Type: application/json' -H "Origin: $B" \
  --data "$(python3 -c 'import json,sys; print(json.dumps({"password": sys.argv[1]}))' "$PW")" \
  $B/api/accounts/session | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" $B/api/accounts/summary   # 200
ssh root@192.168.1.81 "journalctl _SYSTEMD_USER_UNIT=boombox-setup.service --since '-5 min' | grep 'admin login'"   # '… admin login from 192.168.1.x: ok' — no password in the line
```

Pair a temporary client for the `/api/remote/*` checks:

```bash
PIN=$(ssh dietpi@192.168.1.81 "curl -s -X POST http://127.0.0.1/api/remote/pair/start" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pin"])')
RT=$(curl -s -X POST -H 'Content-Type: application/json' -d "{\"pin\":\"$PIN\",\"label\":\"deploy-check\"}" $B/api/remote/pair | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth_token"])')
curl -s -H "Authorization: Bearer $RT" "$B/api/remote/home/browse?type=albums" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["items"]))'   # ≈ 8701
curl -s -H "Authorization: Bearer $RT" $B/api/remote/video/views | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ok"], [i["name"] for i in d["items"]])'
KEY=$(ssh root@192.168.1.81 'cat /etc/boombox/jellyfin-api-key')
curl -s -H "Authorization: Bearer $RT" $B/api/remote/video/views $B/api/remote/video/resume | grep -c "$KEY"   # 0
unset KEY
```

- [ ] **Step 6: Browser checks with agent-browser (phone 390×844, desktop 1440×900)**

```bash
agent-browser open http://192.168.1.81:8090/
agent-browser eval "localStorage.setItem('boombox-remote-pairing', JSON.stringify({base: 'http://192.168.1.81:8090', token: '$RT', name: 'MarkII'})); location.reload()"
for W in 320:640 390:844 1440:900; do
  agent-browser set viewport ${W%%:*} ${W##*:}
  agent-browser open "http://192.168.1.81:8090/#/music"
  agent-browser wait 1500
  agent-browser eval "document.documentElement.scrollWidth <= window.innerWidth"   # true — no horizontal scroll
done
agent-browser set viewport 390 844
agent-browser open "http://192.168.1.81:8090/#/now";   agent-browser wait 1500; agent-browser screenshot /tmp/lan-phone-now.png
agent-browser open "http://192.168.1.81:8090/#/music"; agent-browser wait 2500; agent-browser screenshot /tmp/lan-phone-music.png
agent-browser open "http://192.168.1.81:8090/#/video"; agent-browser wait 2500; agent-browser screenshot /tmp/lan-phone-video.png
agent-browser set viewport 1440 900
agent-browser open "http://192.168.1.81:8090/#/music"; agent-browser wait 2500; agent-browser screenshot /tmp/lan-desktop-music.png
agent-browser open "http://192.168.1.81:8090/#/accounts"; agent-browser wait 1500; agent-browser screenshot /tmp/lan-desktop-locked.png
```
Expected: phone shots show bottom tabs Now/Music/Video/Search/More with the mini-player above them (Music/Video); desktop shots show the sidebar, the centre section with a multi-column tile grid, and the right Now Playing + queue panel; `#/accounts` shows the lock screen with 🔒 in the sidebar. Read each PNG to confirm.

- [ ] **Step 7: Play a Home Library album from the phone layout**

At 390×844: `#/music/home/albums` → `agent-browser snapshot` → click an album tile → click **Play all** → toast "Playing … — N tracks." Then:

```bash
ssh dietpi@192.168.1.81 "curl -s -X POST -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"core.playback.get_state\"}' http://127.0.0.1:6680/mopidy/rpc"   # "result": "playing"
ssh dietpi@192.168.1.81 "curl -s -X POST -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"core.tracklist.get_length\"}' http://127.0.0.1:6680/mopidy/rpc"  # grows to the album length within seconds
```
Keep the volume low (≤ 20 %); stop playback afterwards (Now → pause).

- [ ] **Step 8: Play an episode on the kiosk and steer it**

With the kiosk showing the music UI (`#/now` pause first): `#/video` → a TV library → series → season → episode → **Play on the boombox**. Expected: the request returns within ~20 s; `curl -s -H "Authorization: Bearer $RT" $B/api/remote/video/state` shows `"active": true` with `audio_streams` / `subtitle_streams`. In the Video section's controls: pause (state `playing: false`), **+30 s** (position jumps ~30 s), pick a subtitle track then **Off**, **Stop** (state `active: false`). Check the kiosk screen via its CDP URL: `ssh dietpi@192.168.1.81 "curl -s http://127.0.0.1:9222/json | grep -o '\"url\": \"[^\"]*\"' | head -1"` shows the Jellyfin host while playing.

- [ ] **Step 9: Unlock Admin and use an Accounts card**

At 1440×900: `#/accounts` → fill **Web password** (use `agent-browser fill` with `$PW`) → **Unlock** → the four cards show in two columns (screenshot `/tmp/lan-desktop-accounts.png`); Music server → **Test** → "✓ Connected". Then **Lock** → back to the lock screen.

- [ ] **Step 10: Clean up and record**

```bash
ssh dietpi@192.168.1.81 "curl -s -X POST -H 'Content-Type: application/json' -d '{\"token\":\"$RT\"}' http://127.0.0.1/api/remote/admin/unpair"   # {"ok": true}
curl -s -X DELETE -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{}' $B/api/accounts/session   # {"ok": true}
unset PW TOKEN RT
```
Record the results (screenshots, curl outputs, any deviations) in the PR description. Any fix found here gets a failing test first, in the owning task's files, as its own commit.

---

## Spec coverage map

| Spec requirement | Task |
|---|---|
| LAN app at `/` on :8090, `base: "/"`, `assetsDir: "app-assets"`, no Basic auth; everything else keeps it | 5, 6 |
| `/remote*` → `/`, `/accounts*` → `/#/accounts`; old PWA hint | 5, 10 |
| `/api/accounts/` `auth_basic off`, forwards `X-Real-IP` | 5 |
| Site file synced by `apply-release.sh swap` (narrow privilege); first deploy by hand | 5, 11 |
| Admin session: login/logout, bytes constant-time, 32-byte token, in memory, 12 h idle refreshed, lockout 5/5 min/5 min global, logged without password, loopback refused, token on every accounts route, JSON + same-origin, no `X-Boombox-User` | 1 |
| Household tier unchanged (pair token on every `/api/remote/*`) | 2, 3, 4 (existing middleware) |
| Phone tabs Now/Music/Video/Search/More + mini-player; desktop sidebar + centre + Now/queue panel; 900 px; min tile 160 px; hash routes; no horizontal scroll ≥ 320 px | 6, 7, 8, 11 |
| Music: Mopidy library + Home Library (Artists/Albums/Playlists → drilldown → play / play-all / queue), cover art | 2, 7 |
| Home Library routes (browse/search/detail/play/art), resolve → drop `offline_miss` → first track then background chunks | 2 |
| Video: libraries, Continue watching, Movies grid, Series → Seasons → Episodes, search, posters (cached), Play on the boombox | 3, 4, 8 |
| Video play: WATCH navigation, 20 s wait, PlayNow, clear errors; state + audio/subtitle streams; seek/set_audio/set_subtitle; controls incl. ±30 s, scrubber, stop, volume | 4, 8 |
| Admin → Accounts: four cards, 2-column desktop grid, locked until the password, lock icon, never from the kiosk | 1, 9 |
| Errors: message + Retry; library down / Jellyfin not configured / kiosk not signed in / pairing revoked / admin expired; upstream → 502, never 500; 15 s / 30 s timeouts | 1–4, 6–9 |
| Testing: Python route tests, UI vitest with mocked viewport, nginx static tests, `nginx -t` + screenshots + flows on MarkII | 1–11 |
