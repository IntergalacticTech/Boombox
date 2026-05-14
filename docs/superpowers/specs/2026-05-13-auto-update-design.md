# Auto-update for Boombox

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-05-13
**Owner:** jwc

## Goal

Boombox is OSS and ships to non-technical end-users on a Pi. Today the only
update path is `boombox-update`, a CLI wrapper around an in-place `git pull
main` that runs only when a human SSHes in. We want devices to:

1. Discover new releases on their own.
2. Show the user that an update is available, in the touchscreen Settings panel
   and on the LAN web page.
3. Optionally install updates unattended inside a user-chosen daily window.
4. Survive a bad release by rolling back automatically.

## Non-goals (v1)

- Cryptographic signing of releases (Sigstore / signed tags). Trust is GitHub
  + HTTPS for now; signing is a future channel hardening pass.
- Per-day-of-week schedules. One daily window covers the use case.
- Push/email notifications when an update is available. Quiet UI surfaces only.
- Pre-built `ui/dist` release assets (Pi builds the SPA itself, same as today).
  Listed as a future optimization.
- A/B "two full installs hot" model with shared services. We swap one symlink;
  services restart during the swap. The swap itself is atomic, services are
  not.

## Decisions (from brainstorming)

| Topic              | Decision |
|--------------------|----------|
| Release model      | Two channels: `stable` (GitHub Releases, tagged) and `edge` (`main` HEAD). Default `stable`. |
| Notification UI    | Touchscreen Settings panel + LAN web page. No badge, no overlay. |
| Window shape       | Daily: start time + duration. Default 03:00, 60min. |
| Playback rule      | If music is playing when the window opens, skip — try again tomorrow. |
| Default state      | Auto-update on, channel stable, window 03:00–04:00. |
| Trust model        | GitHub Releases API + git clone over HTTPS. No signature verification in v1. |
| Failure mode       | Snapshot-based atomic install (symlink swap). Smoke-test post-install; revert on failure. |
| Process model      | New `boombox-updater` user systemd service exposing an HTTP API on port 6685. |
| CLI                | `bin/boombox-update` rewritten as thin client of the updater API; falls back to direct script if the service is disabled/unreachable. |

## Filesystem layout

Refactor `/opt/boombox/` from today's flat git checkout to a release-pointer
layout:

```
/opt/boombox/
├── releases/
│   ├── v0.4.0/                 ← clean shallow clone @ tag (full repo + built ui/dist)
│   ├── v0.4.1/
│   └── edge-<sha>/             ← edge-channel checkouts (newest 2 retained)
├── current   → releases/v0.4.1  (symlink — active release)
├── previous  → releases/v0.4.0  (symlink — last-known-good)
├── .venv/                       ← shared Python venv across releases
└── state/
    ├── updater.json             ← persisted updater state
    └── logs/                    ← per-attempt install logs
```

Rules:

- Systemd user units, the system unit `boombox-usb-mount@.service`, the nginx
  config, and `bin/boombox-update` all reference `/opt/boombox/current/...`.
- nginx serves the SPA directly out of `/opt/boombox/current/ui/dist/`,
  replacing today's rsync to `/var/www/boombox/`. This is what makes the UI
  flip atomically with the rest of the install.
- User-modifiable state stays outside the swap and survives upgrades:
  `/etc/boombox/*` (web auth, `buttons.json`, `updater.json`, music dir),
  `~/Music`, and the user's `~/.config/systemd/user/` enable-state.
- `git clone --depth=1 --branch <ref>` for each release tree. Edge-channel
  clones don't drag history along.
- Disk hygiene: keep `current`, `previous`, plus at most one extra. Prune
  others after a successful install.
- `previous` only advances after `verifying` succeeds. Two bad releases in a
  row still roll back to the last good one.

### Migration

The first `install/install.sh` run after this lands detects the legacy flat
layout (a `.git` directory directly inside `/opt/boombox`) and migrates:

1. `mkdir -p /opt/boombox/releases /opt/boombox/state`
2. Move the existing checkout into `releases/legacy-<short-sha>/`.
3. If `/opt/boombox/.venv` was inside the old checkout, move it up to
   `/opt/boombox/.venv` (still shared).
4. Create `current → releases/legacy-<short-sha>`. No `previous` yet.
5. Reinstall systemd unit files and nginx config so they reference
   `/opt/boombox/current/...` and serve the SPA from
   `current/ui/dist/`.
6. Optional: remove `/var/www/boombox/` once nginx is happy.

Migration is idempotent — re-running on an already-migrated tree is a no-op.

## `boombox-updater` service

`services/boombox-updater.py` plus
`install/systemd/user/boombox-updater.service`. Long-lived asyncio process,
single instance. Three concurrent loops.

### Poll loop

- Runs once 30 seconds after start, then every hour.
- Stable channel: `GET https://api.github.com/repos/IntergalacticTech/Boombox/releases/latest` → `tag_name`.
- Edge channel: `GET https://api.github.com/repos/IntergalacticTech/Boombox/commits/main` → short sha.
- Compares against installed version:
  - Stable: read `current/VERSION` (a single-line file the updater writes
    after each successful install with the resolved tag, e.g. `v0.4.1`. For
    legacy migration, set to `legacy` so the first poll sees any tagged
    release as newer).
  - Edge: `git -C current rev-parse HEAD`.
- When the user switches channels via `PUT /api/update/config`, the poll
  loop re-resolves `available_version` immediately against the new channel
  before the next status read — so the UI updates without waiting for the
  hourly tick.
- Persists `last_check`, `available_version`, `available_published_at` to
  `state/updater.json` atomically (`.tmp` → rename).
- Network failures and non-200s are logged and counted but never raise — the
  next hour will retry.

### Window scheduler

- Wakes at the configured `window_start` each local day (and recomputes if
  the user changes the window via the API).
- If `auto == false` → no-op.
- If no new version available → log + done.
- If `GET http://localhost/api/state` reports playback `Playing` → log
  `skipped: playback active`, do not start the install. The window only gates
  *starting*; an install that runs past `window_duration` finishes normally.
- Otherwise → kick off the install state machine.

### HTTP API (port 6685)

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/api/update/status` | channel, installed version, available version, last_check, last_attempt {timestamp, ref, result, error}, current state-machine state, auto on/off, window |
| GET    | `/api/update/config` | current effective config |
| PUT    | `/api/update/config` | update auto / channel / window_start / window_duration_min; validated, persisted to `/etc/boombox/updater.json` |
| POST   | `/api/update/check` | force a poll now; returns the new status |
| POST   | `/api/update/install` | install latest available immediately. Body: `{ref?: string, force?: bool}`. `force` overrides the music-playing guard. Streams the install log via SSE; also written to `state/logs/`. *(implemented as status-polling on GET /api/update/status rather than SSE — simpler, same UX)* |
| POST   | `/api/update/rollback` | flip `current` ↔ `previous`, restart services, smoke-test |
| GET    | `/api/update/log?n=200` | tail last N lines of the most recent install log |

nginx adds `/api/update/` → `:6685` to its existing reverse-proxy snippet so
the touchscreen UI and the authenticated `:8090` LAN page share the surface.

### Config persistence

`/etc/boombox/updater.json`:

```json
{
  "auto": true,
  "channel": "stable",
  "window_start": "03:00",
  "window_duration_min": 60
}
```

Same model as `buttons.json`: lives outside the repo, persists across
reinstalls, user-writable. Defaults compiled into the service if the file is
absent.

### Opt-out

Per the project's "every feature optional" rule:

- `systemctl --user disable --now boombox-updater.service` → no polling, no
  auto-install, no API. The CLI's fallback path keeps manual updates working
  (see CLI section).
- Setting `"auto": false` in `updater.json` keeps polling and the API on (so
  the UI can still show "update available") but disables scheduled installs.

## Install state machine

Logic lives in `services/boombox_updater/installer.py` (importable, testable).
A thin shell wrapper at `install/apply-release.sh` covers the parts that
genuinely need root (nginx reload, mopidy restart) via the existing
`/etc/sudoers.d/boombox` fragment.

```
idle → fetching → building → preflight → swapping → restarting → verifying
                                                                    ├── ok → idle (success persisted, prune old releases, advance `previous`)
                                                                    └── fail → reverting → idle (rolled_back persisted, `previous` untouched)
```

Each transition appends to `state/logs/<timestamp>-<ref>.log` and updates
`state/updater.json` atomically.

| State | Action | Failure handling |
|-------|--------|------------------|
| fetching | `git clone --depth=1 --branch <ref> <repo> releases/<ref>`. If `releases/<ref>` exists from a prior failed attempt, remove first. | Clone failure → cleanup `releases/<ref>/`, return to `idle`, no symlinks touched. |
| building | `pip install -r install/config/requirements.txt` into shared `.venv`; `npm install --no-audit --no-fund && npm run build` in `releases/<ref>/ui/`. | Non-zero exit → cleanup `releases/<ref>/`, return to `idle`. Nothing has changed yet. |
| preflight | `systemd-analyze verify` on every `.service` in the new release; `nginx -t` against the new fragment; `releases/<ref>/ui/dist/index.html` exists; new venv can `python -c 'import services.boombox_state'` (and the other entry points). | Fail → cleanup, `idle`. |
| swapping | `ln -sfn releases/<ref> /opt/boombox/current.new && mv -Tf /opt/boombox/current.new /opt/boombox/current`. If new systemd unit files differ from installed ones, copy them into `~/.config/systemd/user/` and `daemon-reload`. | Fail → straight to `reverting` (symlink may be in inconsistent state). |
| restarting | `systemctl --user restart` all `boombox-*.service` **except** `boombox-updater` itself. nginx reload via the sudoers fragment. The updater self-restarts as the very last step (`reload-or-restart boombox-updater.service`) so a crashing new updater can't kill the rollback path. | Fail → `reverting`. |
| verifying | Wait up to 30s for liveness: all `boombox-*` user units `is-active`; `GET http://localhost/` 200; `GET http://localhost/api/state` 200 within 5s; `GET http://localhost/api/buttons/` 200. | Fail → `reverting`. |
| reverting | `ln -sfn $(readlink previous) current`, restart services, run a minimal verify (state + nginx). | Revert verify also fails → persist `state: broken`, stop touching anything, log loudly. Don't loop. |

## Smoke-test details

Verification is intentionally narrow — enough to catch a missing dist, a
broken systemd unit, or a service that crashes on boot, without coupling the
updater to deep app-level behavior.

| Check | Pass criterion | Timeout |
|-------|----------------|---------|
| Each `boombox-*` user unit | `systemctl --user is-active <unit> == "active"` | 30s polled at 1s |
| nginx + SPA | `curl -fsS http://localhost/` returns 200 with non-empty body | 5s |
| State API | `curl -fsS http://localhost/api/state` returns 200 | 5s |
| Buttons API | `curl -fsS http://localhost/api/buttons/` returns 200 | 5s |

The verifier itself runs inside the updater process — but since the updater
self-restarts last, the verifier completes before the self-restart kicks in.

## CLI — `bin/boombox-update`

Rewritten as a thin client of the local API:

```
boombox-update                # default: check + (if available) install latest, follow log
boombox-update status         # JSON dump of /api/update/status
boombox-update check          # poll only
boombox-update install [REF]  # install latest, or a specific tag/sha
boombox-update rollback       # flip to previous
boombox-update config         # show effective config (read-only)
```

Config edits (auto on/off, channel, window) go through `PUT
/api/update/config` — i.e. the touchscreen Settings panel or the LAN page.
The CLI is intentionally read-only for config to keep one source of truth
for "what does the user want?"

- Implementation: shell wrapper around `curl` to `localhost:6685`.
- `--force` overrides the "music playing" guard (only applies to interactive
  `install` calls; never to scheduled runs).
- **Fallback path:** if the updater service is disabled or unreachable, the
  CLI invokes `install/apply-release.sh main` directly so manual updates keep
  working on a Pi where the user turned the updater off. A clear notice is
  printed on stderr when this happens.

## UI surface

Touchscreen Settings drawer gains an "Updates" section. The same SPA is
served over `:8090` LAN, so the phone surface comes for free.

```
┌─ Updates ──────────────────────────────────┐
│ Status: Up to date — v0.4.1 (stable)       │
│   Last checked: 12 min ago                 │
│                                            │
│ Auto-update    [ on ] [ off ]              │
│ Channel        [ stable ▼ ]                │
│ Window         Start 03:00  Duration 60m   │
│                                            │
│ [ Check now ]  [ Install now ]             │
│ [ Rollback to v0.4.0 ]                     │
│                                            │
│ Last attempt: 2026-05-12 03:14             │
│   Result: rolled back — see log            │
│   [ View log ]                             │
└────────────────────────────────────────────┘
```

- Reads `GET /api/update/status` on open and after every action.
- When an update is available: status line becomes `Update available: v0.4.2`
  and `Install now` takes the primary affordance.
- No badge on the Settings icon, no overlay — only visible when the user
  enters Settings, by your earlier choice.
- `View log` opens the response of `GET /api/update/log?n=500` in a scroll
  panel.
- "Rollback" button is hidden when `previous` is empty (e.g. immediately
  after migration).

## Release process (separate from this spec but called out)

This spec assumes a release exists. To produce one:

1. Bump `VERSION` in repo root (single line, e.g. `0.4.2`).
2. Commit + tag `v0.4.2` on `main`.
3. Push the tag. A GitHub Releases entry is created (manually or via a
   future workflow). The `tag_name` is what the updater polls for.

Edge devices don't need anything beyond a `main` push.

## Testing

Extends `services/tests/` (pytest + asyncio mode is already wired in
`pyproject.toml`).

### Unit

- Version comparison (`v0.4.10` > `v0.4.2`; sha equality on edge).
- Window scheduler: given `(config, now, available_version, playback_state)`,
  asserts whether install fires.
- State-machine transitions: feed canned step results, assert correct next
  state, log entries, and `state/updater.json` writes.
- Config validation: `PUT /api/update/config` with bad `window_start`, bad
  channel, out-of-range duration → 400 with a useful error.
- CLI argument parsing + fallback path selection.

### Integration

A throwaway tempdir stands in for `/opt/boombox/`. GitHub API is mocked with
fixtures.

- Happy-path: clone of fake-release-v0.0.2 over fake-release-v0.0.1 → swap →
  verify → `current` and `previous` correct, old release pruned.
- Smoke-test failure on the new release → revert → `current` back to v0.0.1,
  `previous` untouched, last-attempt result `rolled_back`.
- Two bad releases in a row → second one rolls back to v0.0.1 (the still-good
  `previous`), not to v0.0.2 (the bad one).
- Music-playing skip: mocked `/api/state` returns `Playing` → scheduler logs
  `skipped: playback active`, no clone happens.
- Updater service disabled: CLI `boombox-update` falls back to direct script
  invocation.

### Manual smoke (Pi, called out in the plan as a checklist, not automated)

- Cut a `v0.0.1-test` release containing the new install layout, install
  fresh, watch the boot.
- Cut `v0.0.2-test` that intentionally breaks a unit file, watch the nightly
  auto-install roll back.

## Open items deferred to v2

- Pre-built `ui/dist/` as a release asset (skips ~2 min of node build per
  update).
- Tag signing / Sigstore.
- Bandwidth-aware update windows (skip if on hotspot, etc.).
- Surfacing release notes in the UI (the GitHub release `body`).
