# Wireless remote — Phase 2: CYD firmware + PIN pairing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working CYD wireless remote. User powers on the CYD, types their WiFi password on the touchscreen, enters a PIN displayed on the boombox kiosk, and lands on a NowPlaying screen that mirrors the boombox's everyday control surface. Tap transport buttons → music actually plays/pauses/skips. Drag the volume slider → volume actually changes. 30 s idle → ambient art-only mode. Touch wakes it back.

**Architecture:** Two halves. Pi-side: add a PIN-pairing endpoint + kiosk overlay to Phase 1's `boombox-remote` service. Firmware-side: PlatformIO project with `boombox-remote-core` shared library (transport, state, NVS, action dispatch) and a `cyd-2432s028r` device shell (display, touch, LDR, LVGL UI). BLE deferred to Phase 4; multi-pair switcher deferred (single paired boombox in MVP); USB installer deferred to Phase 3.

**Tech Stack:** PlatformIO + Arduino-ESP32, LVGL 9 for UI, TFT_eSPI for ILI9341 display, XPT2046_Touchscreen for resistive touch, ArduinoJson, ArduinoWebsockets. Python additions to `boombox-remote.py` (aiohttp endpoint + kiosk-overlay POST).

---

## Roadmap snapshot

This is Phase 2 of 7. Phase 1 (the Pi-side service) is shipped. Subsequent phases:

| Phase | Scope | Status |
|---|---|---|
| 1 | Pi `boombox-remote.py` HTTP/WS/mDNS + `actions.py` refactor | shipped (PR #1) |
| **2 (this plan)** | CYD firmware (HTTP-only) + PIN pairing + Pi-side pairing endpoint | this plan |
| 3 | USB firmware installer on the Pi (udev + esptool + kiosk picker) | next |
| 4 | BLE primary transport — phase-0 spike, GATT server on Pi, NimBLE on CYD | next |
| 5 | Headless DIY profile + kiosk pin-map config UI | depends on 3 |
| 6 | External profile pack infrastructure | depends on 5 |
| 7 | ELECROW round profile | deferred |

**Phase 2 deliverable:** A CYD on the user's desk, talking to the user's boombox over WiFi, controlling music. Filmable demo.

---

## Phase 2 scope decisions

**Included:**
- WiFi setup screen (on-screen keyboard, SSID picker)
- PIN pairing (boombox kiosk shows a 6-digit PIN; CYD prompts for it)
- NowPlaying view with album art, transport, volume slider, source badge
- Sources view (full-screen 2×3 grid)
- More view (sleep timer, mic, record, skin cycle)
- Ambient mode with LDR-driven backlight after 30 s idle
- WS-driven state sync (push-on-change from Phase 1's `/api/remote/ws`)
- Action dispatch via Phase 1's `POST /api/remote/command`
- Album art fetched from Phase 1's `/api/remote/art/{hash}.jpg`
- Single paired boombox stored in NVS

**Explicitly NOT in Phase 2 MVP:**
- BLE transport (Phase 4)
- Multi-pair BoomboxSwitcher view (defer until 2+ boomboxes exist)
- USB-fast-path pairing (Phase 3)
- Tap-to-seek scrub (position display only — drag-to-seek invites latency bugs)
- Touch calibration UI (use hardcoded calibration; revisit if drift bites)
- OTA firmware updates (USB-install flow in Phase 3 supersedes)
- Profile manifest / external pack infra (Phase 6)

---

## Architectural shape after Phase 2

```
firmware/
├── platformio.ini                       # cyd-2432s028r env + future-profile slots
├── VERSION                              # bumped per release
├── lib/
│   └── boombox-remote-core/             # shared library (Phase 2 = single profile,
│       ├── library.json                 #   structured for future profiles)
│       └── src/
│           ├── core/
│           │   ├── App.cpp              # lifecycle, mode loop
│           │   └── BoombInfo.cpp        # version + paired-status partition
│           ├── transport/
│           │   ├── WiFiManager.cpp      # join, retry, on-screen creds
│           │   ├── HttpClient.cpp       # REST against /api/remote
│           │   └── WsClient.cpp         # WebSocket subscriber
│           ├── state/
│           │   └── BoomboxState.cpp     # observable model
│           ├── storage/
│           │   ├── PairedBoombox.cpp    # NVS, single boombox in MVP
│           │   └── WifiCreds.cpp        # NVS, keyed by SSID
│           ├── action/
│           │   └── ActionDispatch.cpp   # send commands via WS or HTTP
│           └── device/
│               ├── IDevice.h            # interface
│               └── IUI.h                # interface
└── src/
    └── devices/cyd-2432s028r/
        ├── main.cpp                     # entry, registers device, boots core
        ├── Device.cpp                   # implements IDevice (display, touch, LDR)
        └── ui/
            ├── WifiSetup.cpp            # SSID picker + on-screen keyboard
            ├── PairScreen.cpp           # 6-digit PIN entry
            ├── NowPlaying.cpp           # main view
            ├── Sources.cpp              # 2×3 source grid
            ├── More.cpp                 # sleep/mic/record/skin
            └── Ambient.cpp              # idle full-art view

services/
├── boombox-remote.py                    # +/api/remote/pair endpoints
└── tests/
    └── test_remote_pair.py              # new

site/
├── components/
│   └── PairOverlay.{js,html,css}        # new kiosk overlay for PIN display

install/
└── install.sh                           # already enables boombox-remote.service
```

The CYD firmware is one PlatformIO env: `cyd-2432s028r`. The directory layout already anticipates a second env (`elecrow-round-128`, `headless-gpio`) per the design spec — they'll share `lib/boombox-remote-core/` and add their own `devices/<id>/` shell. Phase 2 builds only the CYD env; the structure is the value.

---

## Conventions used throughout this plan

- **Working directory**: the worktree root (`/Users/jwc/code/Boombox/.claude/worktrees/wireless-remote` during the session, or wherever you continue from).
- **Python**: `.venv/bin/python` and `.venv/bin/pytest` for Pi-side tasks (already set up).
- **PlatformIO**: installed as a local CLI (`pio`) in Stage 2. All firmware-side builds run via `pio run -e cyd-2432s028r`.
- **Flashing the CYD**: `pio run -e cyd-2432s028r -t upload`. Requires the CH340 serial driver on the Mac (one-time install — Stage 2 documents).
- **Commits**: one per task, conventional commit format.

---

## Stage 1 — Pi-side PIN-pairing endpoint + kiosk overlay

The CYD needs a way to obtain an auth token without the user editing `peers.json`. Phase 2 uses **PIN-based pairing**: the boombox kiosk shows a 6-digit PIN for 60 s; the CYD prompts for it; on match, the Pi issues a fresh auth token and saves it to `peers.json`.

The PIN-generation endpoint is gated to localhost so only the kiosk (running on the Pi itself) can mint PINs. The PIN-redeem endpoint is open on the LAN but accepts at most one attempt per PIN and rate-limits by IP.

### Task 1: PIN-pairing endpoints — `/api/remote/pair/start` and `/api/remote/pair`

**Files:**
- Modify: `services/boombox-remote.py`
- Create: `services/tests/test_remote_pair.py`

Endpoints:
- `POST /api/remote/pair/start` (localhost-only) — generates a fresh 6-digit PIN, returns `{pin, expires_at}`. Stores the PIN hash + expiry in process memory. Only one active PIN at a time.
- `POST /api/remote/pair {pin, label}` (LAN, no auth required) — if `pin` matches the active one and not expired, issues a 32-byte hex auth token, writes it to `peers.json` with the supplied `label` and `paired_at = now`, returns `{auth_token, boombox_id, boombox_name}`. Invalidates the PIN after one attempt.

- [ ] **Step 1: Write the failing test**

Create `services/tests/test_remote_pair.py`:

```python
"""Tests for PIN-based pairing endpoints."""
from __future__ import annotations

import json
import pytest
from pathlib import Path


@pytest.fixture
async def app_with_pairing(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text("{}")
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    monkeypatch.setenv("BOOMBOX_ID", "boombox-test")
    monkeypatch.setenv("BOOMBOX_NAME", "Test")

    import boombox_remote
    return boombox_remote.create_app(), peers


@pytest.mark.asyncio
async def test_pair_start_returns_pin(app_with_pairing, aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/pair/start")
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert len(body["pin"]) == 6
    assert body["pin"].isdigit()
    assert body["expires_at"] > 0


@pytest.mark.asyncio
async def test_pair_redeems_pin_and_writes_peer(app_with_pairing,
                                                  aiohttp_client):
    app, peers_path = app_with_pairing
    client = await aiohttp_client(app)
    pin = (await (await client.post("/api/remote/pair/start"))
            .json())["pin"]

    resp = await client.post("/api/remote/pair",
                              json={"pin": pin, "label": "my-cyd"})
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert len(body["auth_token"]) == 64
    assert body["boombox_id"] == "boombox-test"
    assert body["boombox_name"] == "Test"

    peers = json.loads(peers_path.read_text())
    assert body["auth_token"] in peers
    assert peers[body["auth_token"]]["label"] == "my-cyd"


@pytest.mark.asyncio
async def test_pair_rejects_bad_pin(app_with_pairing, aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    await client.post("/api/remote/pair/start")

    resp = await client.post("/api/remote/pair",
                              json={"pin": "000000", "label": "x"})
    assert resp.status == 403
    body = await resp.json()
    assert body["ok"] is False
    assert body["error"] == "bad_pin"


@pytest.mark.asyncio
async def test_pair_pin_single_use(app_with_pairing, aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    pin = (await (await client.post("/api/remote/pair/start"))
            .json())["pin"]
    # First redemption succeeds
    r1 = await client.post("/api/remote/pair",
                            json={"pin": pin, "label": "a"})
    assert r1.status == 200
    # Second with the same PIN fails (invalidated)
    r2 = await client.post("/api/remote/pair",
                            json={"pin": pin, "label": "b"})
    assert r2.status == 403


@pytest.mark.asyncio
async def test_pair_without_active_pin_rejects(app_with_pairing,
                                                 aiohttp_client):
    app, _ = app_with_pairing
    client = await aiohttp_client(app)
    # No /pair/start has been called
    resp = await client.post("/api/remote/pair",
                              json={"pin": "123456", "label": "x"})
    assert resp.status == 403
```

- [ ] **Step 2: Run the tests (will fail)**

Run: `.venv/bin/pytest services/tests/test_remote_pair.py -v`
Expected: 5 errors/failures (routes don't exist).

- [ ] **Step 3: Implement the endpoints**

In `services/boombox-remote.py`:

1. Add at the top of imports:

```python
import hmac
import secrets
import time
```

2. Add module-level state for the active PIN (process-memory only — restarts wipe pending pairings, which is fine):

```python
_PAIR_STATE: dict = {"pin_hash": None, "expires_at": 0}
PAIR_PIN_TTL_S = int(os.environ.get("BOOMBOX_REMOTE_PAIR_TTL_S", "120"))


def _make_pin() -> str:
    """Cryptographically random 6-digit numeric PIN."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_pin(pin: str) -> str:
    """Constant-time-comparable hex digest (process-local, not stored)."""
    import hashlib
    return hashlib.sha256(pin.encode()).hexdigest()
```

3. Add the two endpoints:

```python
async def _post_pair_start(request: web.Request) -> web.Response:
    # Localhost-only — the kiosk runs on the Pi and is the only caller.
    peer_ip = request.remote
    if peer_ip not in ("127.0.0.1", "::1", "localhost"):
        log.warning("/pair/start from non-localhost: %s", peer_ip)
        return web.json_response(
            {"ok": False, "error": "forbidden"}, status=403)

    pin = _make_pin()
    _PAIR_STATE["pin_hash"] = _hash_pin(pin)
    _PAIR_STATE["expires_at"] = time.time() + PAIR_PIN_TTL_S
    log.info("paring PIN issued, expires in %ds", PAIR_PIN_TTL_S)
    return web.json_response({
        "ok": True,
        "pin": pin,
        "expires_at": _PAIR_STATE["expires_at"],
    })


async def _post_pair(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response(
            {"ok": False, "error": "invalid_body"}, status=400)

    pin = body.get("pin", "")
    label = body.get("label", "remote")
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isdigit():
        return web.json_response(
            {"ok": False, "error": "bad_pin"}, status=403)

    if (_PAIR_STATE["pin_hash"] is None or
            time.time() > _PAIR_STATE["expires_at"]):
        return web.json_response(
            {"ok": False, "error": "no_active_pin"}, status=403)

    if not hmac.compare_digest(_hash_pin(pin), _PAIR_STATE["pin_hash"]):
        return web.json_response(
            {"ok": False, "error": "bad_pin"}, status=403)

    # PIN verified — invalidate it (single-use), mint a token, persist.
    _PAIR_STATE["pin_hash"] = None
    _PAIR_STATE["expires_at"] = 0

    token = secrets.token_hex(32)
    peers = _load_peers()
    peers[token] = {
        "label": str(label)[:40] or "remote",
        "paired_at": int(time.time()),
    }
    path = Path(os.environ.get("BOOMBOX_REMOTE_PEERS", str(DEFAULT_PEERS)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(peers, indent=2))
    log.info("paired remote label=%s", peers[token]["label"])

    return web.json_response({
        "ok": True,
        "auth_token": token,
        "boombox_id":   os.environ.get("BOOMBOX_ID", "boombox-default"),
        "boombox_name": os.environ.get("BOOMBOX_NAME", "Boombox"),
    })
```

4. Bypass the auth middleware for both endpoints (they predate any token):

In `require_auth`, extend the bypass list:

```python
if request.path in ("/api/remote/ws", "/api/remote/pair/start",
                     "/api/remote/pair"):
    return await handler(request)
```

5. Register both routes in `create_app`:

```python
app.router.add_post("/api/remote/pair/start", _post_pair_start)
app.router.add_post("/api/remote/pair", _post_pair)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest services/tests/test_remote_pair.py -v`
Expected: 5 passed.

Run full suite: `.venv/bin/pytest services/tests/ -q`
Expected: 50 passed (45 prior + 5 new).

- [ ] **Step 5: Commit**

```bash
git add services/boombox-remote.py services/tests/test_remote_pair.py
git commit -m "feat(remote): PIN-based pairing endpoints (/pair/start + /pair)"
```

---

### Task 2: Kiosk PairOverlay component

**Files:**
- Create: `site/components/PairOverlay.js`
- Modify: `site/index.html` (or wherever the SPA's component registry lives — check first)
- Add: a "Pair remote" button in `site/components/SettingsDrawer.{js,html}` (wherever the existing Settings drawer lives)

The kiosk shows a full-screen overlay with the PIN when the user taps "Pair remote" in Settings. The overlay:
- Calls `POST /api/remote/pair/start` on open
- Displays the 6-digit PIN in large monospaced text
- Shows a countdown timer (60 s default, or whatever the response says)
- Dismisses on user tap OR when a CYD successfully pairs (poll `/api/remote/state` periodically — wait, that doesn't work; we need a different signal)

Signaling that pairing happened: simplest is a small new endpoint `GET /api/remote/pair/status` that returns `{has_active_pin: bool, paired_count_delta: int}` since overlay-open. The overlay polls every 2 s and dismisses when `paired_count_delta > 0`.

Alternative simpler signal: just dismiss the overlay when the PIN expires or the user dismisses. The CYD sees its own success and shows its own confirmation. No round-trip needed. Going with this — keeps the kiosk overlay dumb.

- [ ] **Step 1: Read the existing SPA structure**

Run: `ls site/components/ && head -30 site/components/SettingsDrawer.js 2>/dev/null || head -30 site/index.html`

Understand the project's component conventions (vanilla JS, no framework — the SPA is hand-rolled).

- [ ] **Step 2: Create `site/components/PairOverlay.js`**

```javascript
// PairOverlay — full-screen modal showing a pairing PIN for new wireless
// remotes. Opens via Settings drawer's "Pair remote" row. Posts to
// /api/remote/pair/start to mint a PIN, displays it monospaced, and shows
// a countdown. Dismisses on tap or PIN expiry.
export class PairOverlay {
  constructor(host) {
    this.host = host;
    this.el = null;
    this.expiresAt = 0;
    this.timer = null;
  }

  async open() {
    const resp = await fetch("/api/remote/pair/start", {method: "POST"});
    if (!resp.ok) {
      console.warn("pair/start failed:", resp.status);
      return;
    }
    const data = await resp.json();
    this.expiresAt = data.expires_at;
    this._render(data.pin);
    this.timer = setInterval(() => this._tick(), 1000);
  }

  _render(pin) {
    this.el = document.createElement("div");
    this.el.className = "pair-overlay";
    this.el.innerHTML = `
      <div class="pair-card">
        <h2>Pair a remote</h2>
        <div class="pair-pin">${pin}</div>
        <p class="pair-hint">Enter this code on your remote.</p>
        <p class="pair-countdown"><span data-countdown>—</span> seconds</p>
        <button class="pair-dismiss">Done</button>
      </div>
    `;
    this.el.querySelector(".pair-dismiss").addEventListener("click",
      () => this.close());
    this.el.addEventListener("click", (e) => {
      if (e.target === this.el) this.close();
    });
    this.host.appendChild(this.el);
  }

  _tick() {
    const remaining = Math.max(0,
      Math.ceil(this.expiresAt - Date.now() / 1000));
    const cd = this.el?.querySelector("[data-countdown]");
    if (cd) cd.textContent = remaining;
    if (remaining === 0) this.close();
  }

  close() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.el?.remove();
    this.el = null;
  }
}
```

- [ ] **Step 3: Create CSS for the overlay**

Create or extend `site/components/PairOverlay.css`:

```css
.pair-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex; align-items: center; justify-content: center;
  z-index: 10000;
}
.pair-card {
  background: #1a1a1a; color: #fff;
  padding: 40px 60px; border-radius: 12px;
  text-align: center; min-width: 360px;
}
.pair-card h2 { margin: 0 0 16px 0; font-size: 20px; }
.pair-pin {
  font-family: ui-monospace, 'JetBrains Mono', monospace;
  font-size: 64px; letter-spacing: 12px;
  padding: 24px 0; color: #4fc3f7;
}
.pair-hint { margin: 0 0 16px 0; opacity: 0.8; }
.pair-countdown { font-size: 14px; opacity: 0.6; margin: 0 0 24px 0; }
.pair-dismiss {
  background: #4fc3f7; color: #000; border: 0;
  padding: 12px 32px; font-size: 16px; border-radius: 6px;
  cursor: pointer;
}
```

Link the CSS in `site/index.html` (or the project's bundle loader — match existing pattern).

- [ ] **Step 4: Add a "Pair remote" entry to the Settings drawer**

Find the Settings drawer file (likely `site/components/SettingsDrawer.{js,html}` — explore first). Add a row near the "Buttons" panel (from the GPIO spec) that says "Pair wireless remote" → opens the PairOverlay.

Wire-up sketch (adapt to actual conventions):

```javascript
import { PairOverlay } from "./PairOverlay.js";
// ... in the settings drawer's render:
//   <button class="settings-row" data-action="pair-remote">
//     Pair wireless remote…
//   </button>
// and a click handler:
this.addEventListener("click", (e) => {
  if (e.target.dataset.action === "pair-remote") {
    new PairOverlay(document.body).open();
  }
});
```

- [ ] **Step 5: Manual smoke check in browser**

Run the boombox-remote service locally:

```bash
mkdir -p /tmp/smoke && echo "{}" > /tmp/smoke/peers.json
BOOMBOX_REMOTE_PEERS=/tmp/smoke/peers.json \
  .venv/bin/python services/boombox-remote.py &
```

Open the SPA in the agent-browser:

```bash
agent-browser open http://127.0.0.1:8090/
```

(Or whatever port nginx is on locally — likely you can't run nginx; in that case skip this verification step and check it on the Pi after deploy.)

Click Settings → Pair remote → confirm an overlay appears with a 6-digit PIN. Tap Done. Confirm overlay dismisses.

If the Pi-side service ISN'T running locally (likely the case on a dev Mac), this step is best done after deploying to the Pi. Note as a deploy-time verification.

- [ ] **Step 6: Commit**

```bash
git add site/components/PairOverlay.js site/components/PairOverlay.css \
        site/components/SettingsDrawer.* site/index.html
git commit -m "feat(ui): PairOverlay for showing remote pairing PIN on kiosk"
```

---

## Stage 2 — Firmware tooling setup

These three tasks set up PlatformIO and prove the toolchain can flash the CYD.

### Task 3: Install PlatformIO

**Files:** none committed; documentation only.

- [ ] **Step 1: Install PlatformIO via the official CLI installer**

The cleanest install on macOS is via the `get-platformio.py` script (avoids polluting Homebrew). From the worktree root:

```bash
mkdir -p firmware
cd firmware
curl -L -o get-platformio.py https://docs.platformio.org/en/latest/_downloads/4c0c0e6f5b8e9b8ee9d4c46f55b6c87b/get-platformio.py
python3 get-platformio.py
```

This installs to `~/.platformio` and adds shims to `~/.local/bin`. On first run, the installer downloads ~200 MB of toolchains.

Alternative (simpler if Homebrew is acceptable): `brew install platformio`.

After install:

```bash
export PATH="$HOME/.platformio/penv/bin:$PATH"
pio --version
```

Expected: `PlatformIO Core, version 6.x.x`.

- [ ] **Step 2: Install the CH340 USB-serial driver on this Mac**

The CYD uses a CH340 chip. macOS doesn't ship the driver. Install from WCH:

```bash
# Option 1: install via Homebrew cask
brew install --cask wch-ch34x-usb-serial-driver

# Option 2: download manually from
#   https://www.wch.cn/downloads/CH34XSER_MAC_ZIP.html
# and run the .pkg
```

After install (Option 1 requires a system restart):

```bash
ls /dev/cu.usbserial* /dev/cu.wchusbserial*
```

Expected: a `/dev/cu.wchusbserial*` device path appears when the CYD is plugged in.

- [ ] **Step 3: Document the install steps**

Create `firmware/README.md`:

```markdown
# Boombox wireless remote firmware

Build with PlatformIO. Multi-environment for future device support; Phase 2
ships `cyd-2432s028r` only.

## One-time setup (macOS)

1. Install PlatformIO:
   - `brew install platformio` (or use the install script — see PlatformIO docs)
2. Install CH340 USB-serial driver:
   - `brew install --cask wch-ch34x-usb-serial-driver`
   - Restart if prompted.

## Build

    cd firmware
    pio run -e cyd-2432s028r

## Flash a CYD

Plug the CYD into USB. Verify `/dev/cu.wchusbserial*` exists.

    pio run -e cyd-2432s028r -t upload

The first build downloads the ESP32 toolchain (~300 MB) — subsequent builds
are seconds.

## Monitor serial output

    pio device monitor -e cyd-2432s028r -b 115200
```

- [ ] **Step 4: Commit the README**

```bash
git add firmware/README.md
git commit -m "docs(firmware): toolchain setup for CYD remote firmware"
```

---

### Task 4: PlatformIO project skeleton

**Files:**
- Create: `firmware/platformio.ini`
- Create: `firmware/src/devices/cyd-2432s028r/main.cpp` (just enough to compile)
- Create: `firmware/lib/boombox-remote-core/library.json` (empty PlatformIO library)
- Create: `firmware/lib/boombox-remote-core/src/.gitkeep`

- [ ] **Step 1: Write `firmware/platformio.ini`**

```ini
[platformio]
default_envs = cyd-2432s028r
src_dir = src
lib_dir = lib

[env]
platform = espressif32@^6.5.0
framework = arduino
monitor_speed = 115200
upload_speed = 921600
lib_deps =
    lvgl/lvgl@^9
    bblanchon/ArduinoJson@^7
    gilmaimon/ArduinoWebsockets@^0.5
    bodmer/TFT_eSPI@^2.5
    paulstoffregen/XPT2046_Touchscreen@^1.4
build_flags =
    -D BOOMBOX_FW_VERSION=\"0.1.0\"
    -D LV_CONF_INCLUDE_SIMPLE=1

; ----- cyd-2432s028r — CYD 2.8" 240x320 resistive touch ---------------
[env:cyd-2432s028r]
board = esp32dev
board_build.partitions = huge_app.csv
build_src_filter = +<devices/cyd-2432s028r/>
build_flags = ${env.build_flags}
    -D PROFILE_ID=\"cyd-2432s028r\"
    -D USER_SETUP_LOADED=1
    -D ILI9341_2_DRIVER=1
    -D TFT_WIDTH=240
    -D TFT_HEIGHT=320
    -D TFT_MISO=12
    -D TFT_MOSI=13
    -D TFT_SCLK=14
    -D TFT_CS=15
    -D TFT_DC=2
    -D TFT_RST=-1
    -D TFT_BL=21
    -D TOUCH_CS=33
    -D SPI_FREQUENCY=55000000
    -D SPI_READ_FREQUENCY=20000000
    -D SPI_TOUCH_FREQUENCY=2500000
```

Pin assignments are the standard CYD 2.8" wiring — verified against the
"random nerd tutorials" CYD references; if a different CYD batch lands
later, override in a board-specific config.

- [ ] **Step 2: Create a minimal main.cpp that compiles**

`firmware/src/devices/cyd-2432s028r/main.cpp`:

```cpp
#include <Arduino.h>

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("profile: %s\n", PROFILE_ID);
    Serial.printf("version: %s\n", BOOMBOX_FW_VERSION);
}

void loop() {
    delay(1000);
    Serial.println("alive");
}
```

- [ ] **Step 3: Scaffold the shared library**

`firmware/lib/boombox-remote-core/library.json`:

```json
{
  "name": "boombox-remote-core",
  "version": "0.1.0",
  "description": "Shared core for the Boombox wireless remote firmware. Transport, state, NVS, action dispatch. Phase 2 ships with one consumer (the CYD profile).",
  "platforms": ["espressif32"],
  "frameworks": ["arduino"]
}
```

Empty `firmware/lib/boombox-remote-core/src/.gitkeep`.

- [ ] **Step 4: Build and confirm**

```bash
cd firmware
pio run -e cyd-2432s028r
```

Expected: a successful compile producing `.pio/build/cyd-2432s028r/firmware.bin`.
The first build downloads the ESP32 platform toolchain (slow). Subsequent
builds are fast.

If the build fails with library errors, check that PlatformIO's library
manager can fetch the listed deps (network reachable). On flaky network,
re-run; PlatformIO caches downloads.

- [ ] **Step 5: Commit**

```bash
git add firmware/platformio.ini firmware/src firmware/lib
git commit -m "feat(firmware): PlatformIO scaffold + minimal main.cpp for CYD"
```

---

### Task 5: First flash + serial verify

**Files:** none committed; verification only.

- [ ] **Step 1: Plug in the CYD**

Confirm:
```bash
ls /dev/cu.wchusbserial* 2>/dev/null
```

If empty: the CYD isn't enumerating. Most common cause: a power-only USB cable. Use a data-capable USB-A → USB-micro cable.

- [ ] **Step 2: Flash**

```bash
cd firmware
pio run -e cyd-2432s028r -t upload
```

Expected: esptool writes the firmware in ~10-30s. The CYD's red LED may flicker during flash.

- [ ] **Step 3: Open serial monitor**

```bash
pio device monitor -e cyd-2432s028r -b 115200
```

Expected output (continuously):

```
=== boombox-remote firmware ===
profile: cyd-2432s028r
version: 0.1.0
alive
alive
alive
...
```

If "alive" prints, the CYD is running our firmware. The display is blank
(no display code yet — Task 7).

Ctrl-C to exit the monitor. No commit (verification only).

---

## Stage 3 — Shared core library

Build the shared library piece by piece. Each module gets a header + cpp + tested behavior. Where unit testing is impractical (e.g. WiFi connect requires a real radio), we use compile-only verification and document the runtime test.

### Task 6: `IDevice` and `IUI` interfaces

**Files:**
- Create: `firmware/lib/boombox-remote-core/src/device/IDevice.h`
- Create: `firmware/lib/boombox-remote-core/src/device/IUI.h`

These are pure interfaces. The CYD shell will implement them; future profiles will too.

- [ ] **Step 1: Write `IDevice.h`**

```cpp
#pragma once
#include <Arduino.h>

namespace boombox {

struct DeviceCapabilities {
    bool has_display;
    bool has_touch;
    bool has_ldr;        // light sensor for ambient brightness
    bool has_rgb_led;
};

// Implemented by each profile's device shell.
class IDevice {
public:
    virtual ~IDevice() = default;
    virtual void init() = 0;             // boot-time init (display, touch, etc.)
    virtual void pollInputs() = 0;       // called from main loop
    virtual void setBrightness(uint8_t pct) = 0;  // 0-100; no-op if no display
    virtual uint16_t readLdr() = 0;      // 0-4095; 0 if no LDR
    virtual DeviceCapabilities caps() const = 0;
};

} // namespace boombox
```

- [ ] **Step 2: Write `IUI.h`**

```cpp
#pragma once
#include <Arduino.h>

namespace boombox {

class BoomboxState;  // forward

// Implemented by each profile's UI layer (LVGL for CYD; no-op for headless).
class IUI {
public:
    virtual ~IUI() = default;
    virtual void init() = 0;                       // LVGL setup
    virtual void tick(uint32_t millis_now) = 0;    // LVGL handler tick
    virtual void onStateUpdate(const BoomboxState& s) = 0;
    virtual void enterAmbient() = 0;
    virtual void exitAmbient() = 0;
};

} // namespace boombox
```

- [ ] **Step 3: Verify it compiles**

Edit `main.cpp` to include them and trivially instantiate (force-compile):

```cpp
#include <Arduino.h>
#include "device/IDevice.h"
#include "device/IUI.h"

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("caps_size: %zu\n", sizeof(boombox::DeviceCapabilities));
}
void loop() { delay(1000); }
```

Run: `cd firmware && pio run -e cyd-2432s028r`
Expected: clean compile.

- [ ] **Step 4: Commit**

```bash
git add firmware/lib/boombox-remote-core/src/device firmware/src/devices/cyd-2432s028r/main.cpp
git commit -m "feat(firmware): IDevice and IUI interfaces"
```

---

### Task 6.5: NVS storage — `WifiCreds` and `PairedBoombox`

**Files:**
- Create: `firmware/lib/boombox-remote-core/src/storage/WifiCreds.h`
- Create: `firmware/lib/boombox-remote-core/src/storage/WifiCreds.cpp`
- Create: `firmware/lib/boombox-remote-core/src/storage/PairedBoombox.h`
- Create: `firmware/lib/boombox-remote-core/src/storage/PairedBoombox.cpp`

NVS = ESP32's non-volatile storage. Two persisted structs:
- WiFi creds (one SSID + PSK at a time in MVP — multi-SSID is Phase 4+)
- Paired boombox (one — multi-pair switcher is post-MVP)

- [ ] **Step 1: Write `WifiCreds.h`**

```cpp
#pragma once
#include <Arduino.h>

namespace boombox {

// One SSID + PSK pair in NVS namespace "wifi". MVP stores only the
// most-recent successful join. Phase 4+ may add a credential list keyed
// by SSID.
class WifiCreds {
public:
    static bool load(String& ssid_out, String& psk_out);
    static bool save(const String& ssid, const String& psk);
    static void clear();
};

} // namespace boombox
```

- [ ] **Step 2: Write `WifiCreds.cpp`**

```cpp
#include "WifiCreds.h"
#include <Preferences.h>

namespace boombox {

static constexpr const char* NS = "wifi";

bool WifiCreds::load(String& ssid_out, String& psk_out) {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/true)) return false;
    ssid_out = p.getString("ssid", "");
    psk_out  = p.getString("psk", "");
    p.end();
    return ssid_out.length() > 0;
}

bool WifiCreds::save(const String& ssid, const String& psk) {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/false)) return false;
    p.putString("ssid", ssid);
    p.putString("psk", psk);
    p.end();
    return true;
}

void WifiCreds::clear() {
    Preferences p;
    if (!p.begin(NS, /*readOnly=*/false)) return;
    p.clear();
    p.end();
}

} // namespace boombox
```

- [ ] **Step 3: Write `PairedBoombox.h`**

```cpp
#pragma once
#include <Arduino.h>

namespace boombox {

struct PairedBoombox {
    String id;
    String name;
    String auth_token;
    uint32_t paired_at;     // epoch
};

class PairedBoomboxStore {
public:
    static bool load(PairedBoombox& out);
    static bool save(const PairedBoombox& pb);
    static void clear();
    static bool isPaired();
};

} // namespace boombox
```

- [ ] **Step 4: Write `PairedBoombox.cpp`**

```cpp
#include "PairedBoombox.h"
#include <Preferences.h>

namespace boombox {

static constexpr const char* NS = "paired";

bool PairedBoomboxStore::load(PairedBoombox& out) {
    Preferences p;
    if (!p.begin(NS, true)) return false;
    out.id         = p.getString("id", "");
    out.name       = p.getString("name", "");
    out.auth_token = p.getString("token", "");
    out.paired_at  = p.getUInt("paired_at", 0);
    p.end();
    return out.auth_token.length() > 0;
}

bool PairedBoomboxStore::save(const PairedBoombox& pb) {
    Preferences p;
    if (!p.begin(NS, false)) return false;
    p.putString("id", pb.id);
    p.putString("name", pb.name);
    p.putString("token", pb.auth_token);
    p.putUInt("paired_at", pb.paired_at);
    p.end();
    return true;
}

void PairedBoomboxStore::clear() {
    Preferences p;
    if (!p.begin(NS, false)) return;
    p.clear();
    p.end();
}

bool PairedBoomboxStore::isPaired() {
    PairedBoombox tmp;
    return load(tmp);
}

} // namespace boombox
```

- [ ] **Step 5: Verify it compiles**

```bash
cd firmware && pio run -e cyd-2432s028r
```

Expected: clean compile. No new code references these yet — just verifying they parse.

- [ ] **Step 6: Commit**

```bash
git add firmware/lib/boombox-remote-core/src/storage
git commit -m "feat(firmware): NVS-backed WifiCreds and PairedBoomboxStore"
```

---

### Task 7: WiFi manager

**Files:**
- Create: `firmware/lib/boombox-remote-core/src/transport/WifiManager.h`
- Create: `firmware/lib/boombox-remote-core/src/transport/WifiManager.cpp`

Tries stored creds at boot. Exposes `scanSsids()` for the WiFi setup UI. Exposes `join(ssid, psk)` for fresh attempts. Exposes `isConnected()`, `localIp()`, `signalRssi()`.

- [ ] **Step 1: Write `WifiManager.h`**

```cpp
#pragma once
#include <Arduino.h>
#include <vector>

namespace boombox {

struct WifiScanResult {
    String ssid;
    int8_t rssi;
    bool secured;
};

class WifiManager {
public:
    bool tryStored();                                  // load from NVS, attempt join
    bool join(const String& ssid, const String& psk, uint32_t timeout_ms = 15000);
    void disconnect();
    bool isConnected() const;
    String localIp() const;
    int8_t signalRssi() const;
    std::vector<WifiScanResult> scan(uint32_t timeout_ms = 5000);
};

} // namespace boombox
```

- [ ] **Step 2: Write `WifiManager.cpp`**

```cpp
#include "WifiManager.h"
#include "../storage/WifiCreds.h"
#include <WiFi.h>

namespace boombox {

bool WifiManager::tryStored() {
    String ssid, psk;
    if (!WifiCreds::load(ssid, psk)) return false;
    return join(ssid, psk);
}

bool WifiManager::join(const String& ssid, const String& psk, uint32_t timeout_ms) {
    Serial.printf("[wifi] joining %s\n", ssid.c_str());
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), psk.c_str());
    uint32_t deadline = millis() + timeout_ms;
    while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
        delay(250);
    }
    bool ok = WiFi.status() == WL_CONNECTED;
    if (ok) {
        Serial.printf("[wifi] joined, ip=%s rssi=%d\n",
                       WiFi.localIP().toString().c_str(), WiFi.RSSI());
        WifiCreds::save(ssid, psk);
    } else {
        Serial.printf("[wifi] join failed (status=%d)\n", WiFi.status());
    }
    return ok;
}

void WifiManager::disconnect() { WiFi.disconnect(true); }

bool WifiManager::isConnected() const {
    return WiFi.status() == WL_CONNECTED;
}

String WifiManager::localIp() const {
    return WiFi.localIP().toString();
}

int8_t WifiManager::signalRssi() const { return WiFi.RSSI(); }

std::vector<WifiScanResult> WifiManager::scan(uint32_t /*timeout_ms*/) {
    std::vector<WifiScanResult> out;
    int n = WiFi.scanNetworks(/*async=*/false, /*show_hidden=*/false);
    for (int i = 0; i < n; i++) {
        WifiScanResult r;
        r.ssid = WiFi.SSID(i);
        r.rssi = WiFi.RSSI(i);
        r.secured = WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
        out.push_back(r);
    }
    WiFi.scanDelete();
    return out;
}

} // namespace boombox
```

- [ ] **Step 3: Verify compile**

```bash
cd firmware && pio run -e cyd-2432s028r
```

- [ ] **Step 4: Commit**

```bash
git add firmware/lib/boombox-remote-core/src/transport
git commit -m "feat(firmware): WifiManager — join, scan, persist creds"
```

---

### Task 8: HTTP client and state model

**Files:**
- Create: `firmware/lib/boombox-remote-core/src/transport/HttpClient.h`
- Create: `firmware/lib/boombox-remote-core/src/transport/HttpClient.cpp`
- Create: `firmware/lib/boombox-remote-core/src/state/BoomboxState.h`
- Create: `firmware/lib/boombox-remote-core/src/state/BoomboxState.cpp`

`HttpClient` is a thin wrapper over `HTTPClient` (ESP32 Arduino's bundled HTTP lib) plus ArduinoJson for parsing. Three calls:
- `getState(host, token, out_state)` → fills BoomboxState from `/api/remote/state`
- `postCommand(host, token, action, value)` → fires a command
- `getArt(host, token, hash, out_bytes)` → fetches JPEG bytes; returns count

`BoomboxState` is a plain struct that mirrors the JSON shape (`track`, `source`, `playing`, `volume`, `muted`, `art_hash`, `sources_available`, etc.).

- [ ] **Step 1: Write `BoomboxState.h`**

```cpp
#pragma once
#include <Arduino.h>
#include <vector>

namespace boombox {

struct TrackInfo {
    String title;
    String artist;
    String album;
    uint32_t duration_s;
    uint32_t position_s;
    bool valid() const { return title.length() > 0; }
};

struct BoomboxState {
    String boombox_id;
    String boombox_name;
    String source;          // mopidy | airplay | spotify | bluetooth | movies | ""
    bool playing;
    TrackInfo track;
    String art_hash;
    String art_url;
    int8_t volume;          // 0-100 or -1 if unknown
    bool muted;
    std::vector<String> sources_available;
    int32_t sleep_timer_s;  // -1 if unset
    bool recording;
    bool mic_on;

    BoomboxState() : playing(false), volume(-1), muted(false),
                      sleep_timer_s(-1), recording(false), mic_on(false) {}
};

} // namespace boombox
```

- [ ] **Step 2: Write `BoomboxState.cpp` parser**

```cpp
#include "BoomboxState.h"
#include <ArduinoJson.h>

namespace boombox {

// Parses {"ok": true, "data": {...}} from /api/remote/state into out.
// Returns true on success.
bool parseStateJson(const String& body, BoomboxState& out) {
    JsonDocument doc;
    if (deserializeJson(doc, body)) return false;
    if (!doc["ok"].as<bool>()) return false;
    JsonObject data = doc["data"].as<JsonObject>();
    out.boombox_id   = data["boombox"]["id"].as<String>();
    out.boombox_name = data["boombox"]["name"].as<String>();
    out.source       = data["source"].as<String>();
    out.playing      = data["playing"].as<bool>();
    if (data["track"].is<JsonObject>()) {
        auto t = data["track"];
        out.track.title      = t["title"].as<String>();
        out.track.artist     = t["artist"].as<String>();
        out.track.album      = t["album"].as<String>();
        out.track.duration_s = t["duration_s"].as<uint32_t>();
        out.track.position_s = t["position_s"].as<uint32_t>();
    } else {
        out.track = TrackInfo();
    }
    out.art_hash = data["art_hash"].as<String>();
    out.art_url  = data["art_url"].as<String>();
    if (data["volume"].is<int>()) out.volume = data["volume"].as<int>();
    out.muted = data["muted"].as<bool>();
    out.sources_available.clear();
    for (JsonVariant v : data["sources_available"].as<JsonArray>()) {
        out.sources_available.push_back(v.as<String>());
    }
    out.sleep_timer_s = data["sleep_timer_s"].is<int>()
                          ? data["sleep_timer_s"].as<int>() : -1;
    out.recording = data["recording"].as<bool>();
    out.mic_on    = data["mic_on"].as<bool>();
    return true;
}

} // namespace boombox
```

- [ ] **Step 3: Write `HttpClient.h`**

```cpp
#pragma once
#include <Arduino.h>
#include "../state/BoomboxState.h"

namespace boombox {

class HttpClient {
public:
    HttpClient(const String& host_with_port, const String& base_path,
                const String& token);

    bool getState(BoomboxState& out);
    bool postCommand(const String& action, const String* value_or_null);
    // Returns the number of bytes read into out_buf (max out_buf_max), or
    // 0 on failure. out_etag_hex is populated when known.
    size_t getArt(const String& hash, uint8_t* out_buf, size_t out_buf_max);

private:
    String _base;   // "http://host:port/api/remote/"
    String _token;
};

} // namespace boombox
```

- [ ] **Step 4: Write `HttpClient.cpp`**

```cpp
#include "HttpClient.h"
#include <HTTPClient.h>
#include <ArduinoJson.h>

namespace boombox {

extern bool parseStateJson(const String& body, BoomboxState& out);

HttpClient::HttpClient(const String& host_with_port, const String& base_path,
                        const String& token)
    : _token(token) {
    _base = "http://" + host_with_port + base_path;
    if (!_base.endsWith("/")) _base += "/";
}

bool HttpClient::getState(BoomboxState& out) {
    HTTPClient http;
    http.begin(_base + "state");
    http.addHeader("Authorization", "Bearer " + _token);
    http.setTimeout(3000);
    int code = http.GET();
    if (code != 200) { http.end(); return false; }
    String body = http.getString();
    http.end();
    return parseStateJson(body, out);
}

bool HttpClient::postCommand(const String& action, const String* value_or_null) {
    HTTPClient http;
    http.begin(_base + "command");
    http.addHeader("Authorization", "Bearer " + _token);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(3000);

    JsonDocument req;
    req["action"] = action;
    if (value_or_null) req["value"] = *value_or_null;
    String body;
    serializeJson(req, body);

    int code = http.POST(body);
    http.end();
    return code >= 200 && code < 300;
}

size_t HttpClient::getArt(const String& hash, uint8_t* out_buf, size_t out_buf_max) {
    HTTPClient http;
    http.begin(_base + "art/" + hash + ".jpg");
    http.addHeader("Authorization", "Bearer " + _token);
    http.setTimeout(5000);
    int code = http.GET();
    if (code != 200) { http.end(); return 0; }
    WiFiClient* stream = http.getStreamPtr();
    size_t total = 0;
    while (http.connected() && total < out_buf_max) {
        size_t avail = stream->available();
        if (avail == 0) { delay(5); continue; }
        size_t read = stream->readBytes(
            out_buf + total, min(avail, out_buf_max - total));
        if (read == 0) break;
        total += read;
    }
    http.end();
    return total;
}

} // namespace boombox
```

- [ ] **Step 5: Verify compile**

```bash
cd firmware && pio run -e cyd-2432s028r
```

- [ ] **Step 6: Commit**

```bash
git add firmware/lib/boombox-remote-core/src/state firmware/lib/boombox-remote-core/src/transport/HttpClient.*
git commit -m "feat(firmware): HttpClient + BoomboxState parser"
```

---

### Task 9: WebSocket subscriber

**Files:**
- Create: `firmware/lib/boombox-remote-core/src/transport/WsClient.h`
- Create: `firmware/lib/boombox-remote-core/src/transport/WsClient.cpp`

ArduinoWebsockets-based subscriber to `/api/remote/ws?token=...`. Calls a callback with parsed `BoomboxState` on each push. Handles reconnect.

- [ ] **Step 1: Write `WsClient.h`**

```cpp
#pragma once
#include <Arduino.h>
#include <functional>
#include "../state/BoomboxState.h"

namespace boombox {

class WsClient {
public:
    using StateCallback = std::function<void(const BoomboxState&)>;
    using StatusCallback = std::function<void(bool connected)>;

    WsClient(const String& host_with_port, const String& token);
    void onState(StateCallback cb)   { _on_state = cb; }
    void onStatus(StatusCallback cb) { _on_status = cb; }
    void connect();
    void poll();      // call from main loop
    void disconnect();
    bool isConnected() const;
private:
    String _url;
    String _token;
    void* _impl;      // typed-erased to keep header lean
    StateCallback _on_state;
    StatusCallback _on_status;
};

} // namespace boombox
```

- [ ] **Step 2: Write `WsClient.cpp`**

```cpp
#include "WsClient.h"
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

namespace boombox {

extern bool parseStateJson(const String& body, BoomboxState& out);

using websockets::WebsocketsClient;

WsClient::WsClient(const String& host_with_port, const String& token)
    : _token(token) {
    _url = "ws://" + host_with_port + "/api/remote/ws?token=" + token;
    _impl = new WebsocketsClient();
}

void WsClient::connect() {
    auto* c = static_cast<WebsocketsClient*>(_impl);
    c->onMessage([this](websockets::WebsocketsMessage msg) {
        BoomboxState s;
        if (parseStateJson(msg.data(), s) && _on_state) _on_state(s);
    });
    c->onEvent([this](websockets::WebsocketsEvent event, String /*data*/) {
        if (event == websockets::WebsocketsEvent::ConnectionOpened) {
            if (_on_status) _on_status(true);
        } else if (event == websockets::WebsocketsEvent::ConnectionClosed) {
            if (_on_status) _on_status(false);
        }
    });
    if (!c->connect(_url)) {
        Serial.println("[ws] connect failed");
    }
}

void WsClient::poll() {
    static_cast<WebsocketsClient*>(_impl)->poll();
}

void WsClient::disconnect() {
    static_cast<WebsocketsClient*>(_impl)->close();
}

bool WsClient::isConnected() const {
    return static_cast<WebsocketsClient*>(_impl)->available();
}

} // namespace boombox
```

- [ ] **Step 3: Verify compile and commit**

```bash
cd firmware && pio run -e cyd-2432s028r
git add firmware/lib/boombox-remote-core/src/transport/WsClient.*
git commit -m "feat(firmware): WsClient subscriber for /api/remote/ws"
```

---

### Task 10: Action dispatcher (client-side)

**Files:**
- Create: `firmware/lib/boombox-remote-core/src/action/ActionDispatch.h`
- Create: `firmware/lib/boombox-remote-core/src/action/ActionDispatch.cpp`

Thin wrapper over `HttpClient::postCommand` with convenience methods (`playPause()`, `next()`, `volume(int)`, `mute()`, `source(String)`, `sleepTimer(int)`, `mic()`, `record()`, `skinCycle()`).

- [ ] **Step 1: Write `ActionDispatch.h`**

```cpp
#pragma once
#include <Arduino.h>
#include "../transport/HttpClient.h"

namespace boombox {

class ActionDispatch {
public:
    explicit ActionDispatch(HttpClient* http) : _http(http) {}
    bool playPause()                   { return _http->postCommand("play_pause", nullptr); }
    bool next()                        { return _http->postCommand("next", nullptr); }
    bool previous()                    { return _http->postCommand("previous", nullptr); }
    bool stop()                        { return _http->postCommand("stop", nullptr); }
    bool shuffle()                     { return _http->postCommand("shuffle", nullptr); }
    bool mute()                        { return _http->postCommand("mute", nullptr); }
    bool volume(int v) {
        String s = String(v);
        return _http->postCommand("volume", &s);
    }
    bool source(const String& name)    { return _http->postCommand("source", &name); }
    bool sleepTimer(int minutes) {
        String s = String(minutes);
        return _http->postCommand("sleep_timer", &s);
    }
    bool micToggle()                   { return _http->postCommand("mic_karaoke", nullptr); }
    bool recordToggle()                { return _http->postCommand("record", nullptr); }
    bool skinCycle()                   { return _http->postCommand("skin_cycle", nullptr); }
private:
    HttpClient* _http;
};

} // namespace boombox
```

- [ ] **Step 2: Verify compile and commit**

```bash
cd firmware && pio run -e cyd-2432s028r
git add firmware/lib/boombox-remote-core/src/action
git commit -m "feat(firmware): ActionDispatch convenience wrapper"
```

---

## Stage 4 — CYD device shell

### Task 11: Device implementation — display, touch, LDR

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/Device.h`
- Create: `firmware/src/devices/cyd-2432s028r/Device.cpp`
- Modify: `firmware/src/devices/cyd-2432s028r/main.cpp` (wire it up)

Implement `IDevice`:
- Init TFT_eSPI + LVGL.
- Init XPT2046 touch.
- Read LDR on GPIO 34 (CYD wiring).
- Backlight via PWM on GPIO 21.

- [ ] **Step 1: Write `Device.h`**

```cpp
#pragma once
#include "device/IDevice.h"

namespace boombox {

class CydDevice : public IDevice {
public:
    void init() override;
    void pollInputs() override;
    void setBrightness(uint8_t pct) override;
    uint16_t readLdr() override;
    DeviceCapabilities caps() const override;
};

} // namespace boombox
```

- [ ] **Step 2: Write `Device.cpp`**

```cpp
#include "Device.h"
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <lvgl.h>

namespace boombox {

static TFT_eSPI _tft;
static XPT2046_Touchscreen _touch(33);   // touch CS pin
static lv_display_t* _disp;
static lv_color_t _draw_buf[240 * 40];

// CYD pins (cross-checked against random nerd tutorials reference):
//   TFT backlight: GPIO 21
//   LDR analog:   GPIO 34
static constexpr int PIN_BACKLIGHT = 21;
static constexpr int PIN_LDR       = 34;

static void _flush(lv_display_t* disp, const lv_area_t* area,
                    unsigned char* px) {
    uint32_t w = area->x2 - area->x1 + 1;
    uint32_t h = area->y2 - area->y1 + 1;
    _tft.startWrite();
    _tft.setAddrWindow(area->x1, area->y1, w, h);
    _tft.pushColors((uint16_t*)px, w * h, true);
    _tft.endWrite();
    lv_display_flush_ready(disp);
}

static void _read_touch(lv_indev_t* /*indev*/, lv_indev_data_t* data) {
    if (_touch.tirqTouched() && _touch.touched()) {
        TS_Point p = _touch.getPoint();
        // Map raw XPT2046 to 240x320 — these are typical CYD coefficients.
        data->point.x = map(p.x, 200, 3700, 0, 239);
        data->point.y = map(p.y, 240, 3800, 0, 319);
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

void CydDevice::init() {
    pinMode(PIN_BACKLIGHT, OUTPUT);
    analogWrite(PIN_BACKLIGHT, 200);   // ~80% initial brightness

    _tft.init();
    _tft.setRotation(0);
    _tft.fillScreen(TFT_BLACK);

    SPI.begin(25, 39, 32);  // CYD's touch SPI bus (HSPI)
    _touch.begin();

    lv_init();
    _disp = lv_display_create(240, 320);
    lv_display_set_flush_cb(_disp, _flush);
    lv_display_set_buffers(_disp, _draw_buf, nullptr,
                            sizeof(_draw_buf), LV_DISPLAY_RENDER_MODE_PARTIAL);

    lv_indev_t* indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, _read_touch);
}

void CydDevice::pollInputs() {
    // LVGL handles its own tick when we call lv_timer_handler().
}

void CydDevice::setBrightness(uint8_t pct) {
    if (pct > 100) pct = 100;
    analogWrite(PIN_BACKLIGHT, map(pct, 0, 100, 0, 255));
}

uint16_t CydDevice::readLdr() {
    return analogRead(PIN_LDR);
}

DeviceCapabilities CydDevice::caps() const {
    return DeviceCapabilities{true, true, true, false};
}

} // namespace boombox
```

- [ ] **Step 3: Wire up in main.cpp**

```cpp
#include <Arduino.h>
#include <lvgl.h>
#include "Device.h"

boombox::CydDevice gDevice;

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== boombox-remote firmware ===");
    Serial.printf("profile: %s\n", PROFILE_ID);

    gDevice.init();

    // Quick visible smoke: paint a centered green square so we know LVGL works.
    lv_obj_t* sq = lv_obj_create(lv_screen_active());
    lv_obj_set_size(sq, 100, 100);
    lv_obj_center(sq);
    lv_obj_set_style_bg_color(sq, lv_color_make(0, 255, 0), 0);
}

void loop() {
    lv_timer_handler();
    delay(5);
}
```

- [ ] **Step 4: Flash and visually verify**

```bash
cd firmware && pio run -e cyd-2432s028r -t upload
```

Expected: CYD displays a green square in the middle of the screen.

If the screen stays black or flickers: check the pin map in `platformio.ini`'s build flags against the actual CYD board variant (some batches have different pins; the random nerd tutorials site has a per-batch reference).

- [ ] **Step 5: Commit**

```bash
git add firmware/src/devices/cyd-2432s028r
git commit -m "feat(firmware/cyd): IDevice implementation — TFT + touch + LDR"
```

---

## Stage 5 — UI screens

### Task 12: LVGL theming setup

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/ui/Theme.h`
- Create: `firmware/src/devices/cyd-2432s028r/ui/Theme.cpp`

Centralized colors + fonts + button-style helpers so the per-view files stay short.

- [ ] **Step 1: Write `Theme.h`**

```cpp
#pragma once
#include <lvgl.h>

namespace boombox {

namespace theme {
    constexpr lv_color_t BG_DARK   = LV_COLOR_MAKE(20, 20, 26);
    constexpr lv_color_t FG_TEXT   = LV_COLOR_MAKE(240, 240, 245);
    constexpr lv_color_t ACCENT    = LV_COLOR_MAKE(79, 195, 247);
    constexpr lv_color_t BUTTON_BG = LV_COLOR_MAKE(40, 40, 50);
    constexpr lv_color_t MUTED     = LV_COLOR_MAKE(120, 120, 130);

    void apply();
    lv_obj_t* makeIconButton(lv_obj_t* parent, const char* symbol,
                              int w, int h);
}

} // namespace boombox
```

- [ ] **Step 2: Write `Theme.cpp`**

```cpp
#include "Theme.h"

namespace boombox::theme {

void apply() {
    lv_obj_set_style_bg_color(lv_screen_active(), BG_DARK, 0);
    lv_obj_set_style_text_color(lv_screen_active(), FG_TEXT, 0);
    lv_obj_set_style_text_font(lv_screen_active(), &lv_font_montserrat_16, 0);
}

lv_obj_t* makeIconButton(lv_obj_t* parent, const char* symbol, int w, int h) {
    lv_obj_t* btn = lv_button_create(parent);
    lv_obj_set_size(btn, w, h);
    lv_obj_set_style_bg_color(btn, BUTTON_BG, 0);
    lv_obj_set_style_radius(btn, 8, 0);
    lv_obj_t* lbl = lv_label_create(btn);
    lv_label_set_text(lbl, symbol);
    lv_obj_set_style_text_font(lbl, &lv_font_montserrat_28, 0);
    lv_obj_center(lbl);
    return btn;
}

} // namespace boombox::theme
```

- [ ] **Step 3: Verify compile and commit**

```bash
cd firmware && pio run -e cyd-2432s028r
git add firmware/src/devices/cyd-2432s028r/ui/Theme.*
git commit -m "feat(firmware/cyd): LVGL theme — colors, fonts, icon button helper"
```

---

### Task 13: WifiSetup screen

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/ui/WifiSetup.h`
- Create: `firmware/src/devices/cyd-2432s028r/ui/WifiSetup.cpp`

- Show "Scanning…" while WiFiManager.scan() runs.
- Display visible SSIDs in a list.
- Tap an SSID → on-screen keyboard for password.
- Tap Connect → WifiManager.join().
- On success → callback to caller (next screen).

- [ ] **Step 1: Write `WifiSetup.h`**

```cpp
#pragma once
#include <lvgl.h>
#include <functional>
#include "transport/WifiManager.h"

namespace boombox::ui {

class WifiSetup {
public:
    using DoneCallback = std::function<void()>;
    WifiSetup(WifiManager* wifi, DoneCallback on_done);
    void show();
private:
    WifiManager* _wifi;
    DoneCallback _on_done;
    lv_obj_t* _screen;
    String _selected_ssid;
    void _renderList();
    void _renderKeyboard(const String& ssid);
};

} // namespace boombox::ui
```

- [ ] **Step 2: Write `WifiSetup.cpp`** (sketch — the details are LVGL boilerplate)

The UI flow:

```cpp
#include "WifiSetup.h"
#include "Theme.h"

namespace boombox::ui {

WifiSetup::WifiSetup(WifiManager* wifi, DoneCallback on_done)
    : _wifi(wifi), _on_done(on_done) {}

void WifiSetup::show() {
    _screen = lv_obj_create(NULL);
    lv_screen_load(_screen);
    lv_obj_set_style_bg_color(_screen, theme::BG_DARK, 0);

    lv_obj_t* title = lv_label_create(_screen);
    lv_label_set_text(title, "Choose your WiFi");
    lv_obj_set_style_text_color(title, theme::FG_TEXT, 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 8);

    _renderList();
}

void WifiSetup::_renderList() {
    lv_obj_t* spinner = lv_spinner_create(_screen);
    lv_obj_set_size(spinner, 50, 50);
    lv_obj_center(spinner);

    // Run a synchronous scan (5s). Production would do async to keep LVGL
    // responsive; MVP synchronous is acceptable.
    auto results = _wifi->scan();
    lv_obj_del(spinner);

    lv_obj_t* list = lv_list_create(_screen);
    lv_obj_set_size(list, 220, 240);
    lv_obj_align(list, LV_ALIGN_CENTER, 0, 16);

    for (const auto& r : results) {
        lv_obj_t* btn = lv_list_add_button(list, LV_SYMBOL_WIFI, r.ssid.c_str());
        // Attach the SSID as user data and a callback that calls _renderKeyboard
        // ... LVGL boilerplate using lv_obj_add_event_cb
    }
}

void WifiSetup::_renderKeyboard(const String& ssid) {
    // Replace the screen with: label "Password for <ssid>", lv_textarea,
    // lv_keyboard. On keyboard "Ready" event:
    //   1. read textarea value as psk
    //   2. show spinner "Connecting…"
    //   3. call _wifi->join(ssid, psk)
    //   4. on success: _on_done()
    //   5. on failure: show "Wrong password" and re-render keyboard
}

} // namespace boombox::ui
```

Note: this task is intentionally larger and rougher than the others — LVGL list/keyboard boilerplate is real lines of code (~150). Build and iterate by flashing.

- [ ] **Step 3: Wire into main.cpp** (provisional)

```cpp
boombox::WifiManager gWifi;
boombox::ui::WifiSetup* gWifiSetup;

void setup() {
    // ... existing init ...
    boombox::theme::apply();
    if (!gWifi.tryStored()) {
        gWifiSetup = new boombox::ui::WifiSetup(&gWifi, [](){
            Serial.println("[wifi] connected — next: pair screen");
        });
        gWifiSetup->show();
    }
}
```

- [ ] **Step 4: Flash and verify**

```bash
cd firmware && pio run -e cyd-2432s028r -t upload && pio device monitor
```

- Plug in CYD with no saved WiFi (or call `WifiCreds::clear()` first).
- Confirm SSID list appears.
- Tap your SSID, enter password.
- Confirm serial shows "joined, ip=...".

- [ ] **Step 5: Commit**

```bash
git add firmware/src/devices/cyd-2432s028r/ui/WifiSetup.* firmware/src/devices/cyd-2432s028r/main.cpp
git commit -m "feat(firmware/cyd): WifiSetup screen with SSID list + keyboard"
```

---

### Task 14: PairScreen

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/ui/PairScreen.h`
- Create: `firmware/src/devices/cyd-2432s028r/ui/PairScreen.cpp`

- Numeric keypad (10 buttons + backspace + clear)
- 6-digit display area
- "Boombox host" auto-discovered via mDNS, falls back to a text input
- On 6 digits entered, POST to `/api/remote/pair`
- On success → save PairedBoombox to NVS, call `on_done` callback

For MVP: skip mDNS; use a hardcoded host or a text input above the keypad ("boombox.local" default).

- [ ] **Step 1: Write `PairScreen.h`**

```cpp
#pragma once
#include <lvgl.h>
#include <functional>
#include "storage/PairedBoombox.h"

namespace boombox::ui {

class PairScreen {
public:
    using DoneCallback = std::function<void(const PairedBoombox&)>;
    PairScreen(DoneCallback on_done);
    void show();
private:
    DoneCallback _on_done;
    lv_obj_t* _screen;
    String _host;       // default "boombox.local"
    String _pin;        // accumulates digits
    lv_obj_t* _pin_label;
    lv_obj_t* _status_label;
    void _renderKeypad();
    void _appendDigit(char d);
    void _attemptPair();
};

} // namespace boombox::ui
```

- [ ] **Step 2: Write `PairScreen.cpp`**

Sketch the UI: a textarea at the top for the host (default "boombox.local"), a big monospaced label for the PIN-being-typed below it, a 3x4 keypad (1-9, 0, backspace, clear). On 6 digits entered, set status to "Pairing…", POST to `http://<host>/api/remote/pair` with the PIN, on success: `PairedBoomboxStore::save(...)` and `_on_done()`. On failure: show "Wrong PIN, try again" and reset.

The host should be the LAN-reachable nginx port — by default `boombox.local:8090` (matches the mDNS advertisement from Phase 1). User can edit if their nginx port is different.

```cpp
#include "PairScreen.h"
#include "Theme.h"
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WiFi.h>

namespace boombox::ui {

PairScreen::PairScreen(DoneCallback on_done)
    : _on_done(on_done), _host("boombox.local:8090") {}

void PairScreen::show() {
    _screen = lv_obj_create(NULL);
    lv_screen_load(_screen);
    lv_obj_set_style_bg_color(_screen, theme::BG_DARK, 0);

    lv_obj_t* title = lv_label_create(_screen);
    lv_label_set_text(title, "Pair to a boombox");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 8);
    lv_obj_set_style_text_color(title, theme::FG_TEXT, 0);

    lv_obj_t* host_ta = lv_textarea_create(_screen);
    lv_textarea_set_one_line(host_ta, true);
    lv_textarea_set_text(host_ta, _host.c_str());
    lv_obj_set_width(host_ta, 200);
    lv_obj_align(host_ta, LV_ALIGN_TOP_MID, 0, 36);

    _pin_label = lv_label_create(_screen);
    lv_label_set_text(_pin_label, "______");
    lv_obj_set_style_text_font(_pin_label, &lv_font_montserrat_28, 0);
    lv_obj_align(_pin_label, LV_ALIGN_TOP_MID, 0, 80);

    _status_label = lv_label_create(_screen);
    lv_label_set_text(_status_label, "Enter the PIN from the boombox");
    lv_obj_align(_status_label, LV_ALIGN_BOTTOM_MID, 0, -8);
    lv_obj_set_style_text_color(_status_label, theme::MUTED, 0);

    _renderKeypad();
}

// _renderKeypad creates a 3x4 grid of buttons; each button's event handler
// calls _appendDigit. The keypad sits below the PIN label.
void PairScreen::_renderKeypad() {
    static const char* keys[] = {
        "1","2","3","4","5","6","7","8","9","C","0","<"};
    int x0 = 24, y0 = 120, w = 60, h = 40, gap = 6;
    for (int i = 0; i < 12; i++) {
        int row = i / 3, col = i % 3;
        lv_obj_t* btn = theme::makeIconButton(_screen, keys[i], w, h);
        lv_obj_set_pos(btn, x0 + col * (w + gap), y0 + row * (h + gap));
        char* key_copy = strdup(keys[i]);
        lv_obj_add_event_cb(btn, [](lv_event_t* e) {
            char* k = static_cast<char*>(lv_event_get_user_data(e));
            // Resolve `this` from event target's parent's user data
            // (set below). For brevity, route via a static pointer.
        }, LV_EVENT_CLICKED, key_copy);
    }
    // NOTE: real implementation will use lv_obj_set_user_data on the
    // screen with `this`, and look it up in the handler. Sketch only.
}

void PairScreen::_appendDigit(char d) {
    if (d == 'C') { _pin = ""; }
    else if (d == '<') { if (_pin.length()) _pin.remove(_pin.length() - 1); }
    else if (_pin.length() < 6) { _pin += d; }
    String shown = _pin + String("______").substring(_pin.length());
    lv_label_set_text(_pin_label, shown.c_str());
    if (_pin.length() == 6) _attemptPair();
}

void PairScreen::_attemptPair() {
    lv_label_set_text(_status_label, "Pairing…");
    HTTPClient http;
    http.begin(String("http://") + _host + "/api/remote/pair");
    http.addHeader("Content-Type", "application/json");

    JsonDocument req;
    req["pin"] = _pin;
    req["label"] = "cyd-" + WiFi.macAddress().substring(12);
    String body;
    serializeJson(req, body);

    int code = http.POST(body);
    if (code == 200) {
        JsonDocument resp;
        deserializeJson(resp, http.getString());
        PairedBoombox pb;
        pb.id         = resp["boombox_id"].as<String>();
        pb.name       = resp["boombox_name"].as<String>();
        pb.auth_token = resp["auth_token"].as<String>();
        pb.paired_at  = (uint32_t)time(nullptr);
        PairedBoomboxStore::save(pb);
        http.end();
        _on_done(pb);
    } else {
        http.end();
        lv_label_set_text(_status_label, "Wrong PIN — try again");
        _pin = "";
        lv_label_set_text(_pin_label, "______");
    }
}

} // namespace boombox::ui
```

- [ ] **Step 3: Flash and verify**

Manual: trigger pairing on the boombox kiosk to get a PIN, enter on the CYD, confirm "Pairing…" → succeeds; serial shows "[pair] saved boombox=…".

- [ ] **Step 4: Commit**

```bash
git add firmware/src/devices/cyd-2432s028r/ui/PairScreen.*
git commit -m "feat(firmware/cyd): PairScreen with PIN keypad + /api/remote/pair POST"
```

---

### Task 15: NowPlaying view

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/ui/NowPlaying.h`
- Create: `firmware/src/devices/cyd-2432s028r/ui/NowPlaying.cpp`

The main screen. Mirrors the sketch in the design spec:

```
┌────────────────────────────────┐
│ Living Room ▾  📶 WiFi         │
├────────────────────────────────┤
│        [album art 160x160]     │
│  Bohemian Rhapsody             │
│  Queen — A Night at the Opera  │
│  ▶━━━━━━━━━━━━━━━━○━━          │  (position only, no tap-to-seek)
│   ⏮      ⏯       ⏭   🅼  ⋯     │
├────────────────────────────────┤
│         🔊 ━━━━━━━━━━○━━       │
└────────────────────────────────┘
```

- Updates on every `onStateUpdate(state)` call (from WsClient).
- Transport buttons call ActionDispatch.
- Volume slider drag-to-set (debounced 200 ms during drag, fires on release).
- Source badge shows current source; tap → opens Sources view.
- "⋯" tap opens More view.
- Status bar tap on boombox name opens BoomboxSwitcher (skipped in MVP — show no-op tooltip or just don't wire).

- [ ] **Step 1: Write `NowPlaying.h`**

```cpp
#pragma once
#include <lvgl.h>
#include "action/ActionDispatch.h"
#include "state/BoomboxState.h"

namespace boombox::ui {

class NowPlaying {
public:
    NowPlaying(ActionDispatch* actions);
    void show();
    void onStateUpdate(const BoomboxState& s);
    void onConnectionChange(bool connected);
private:
    ActionDispatch* _actions;
    lv_obj_t* _screen;
    lv_obj_t* _lbl_boombox;
    lv_obj_t* _lbl_status;
    lv_obj_t* _art;        // image holder
    lv_obj_t* _lbl_title;
    lv_obj_t* _lbl_artist;
    lv_obj_t* _bar_pos;
    lv_obj_t* _btn_play;
    lv_obj_t* _btn_next;
    lv_obj_t* _btn_prev;
    lv_obj_t* _slider_vol;
    lv_obj_t* _lbl_pos;
    String _last_art_hash;
    void _build();
    void _onPlay();
    void _onNext();
    void _onPrev();
    void _onSourcesTap();
    void _onMoreTap();
    void _onVolumeChange(int v);
};

} // namespace boombox::ui
```

- [ ] **Step 2: Write `NowPlaying.cpp`**

The implementation is ~250 lines of LVGL widget setup + event handlers + state-to-UI mapping. Build, flash, iterate. Key behaviors:

- Title/artist labels use `lv_label_set_long_mode(LV_LABEL_LONG_DOT)` for ellipsis.
- Album art: fetch via `HttpClient::getArt(hash, ...)` when `art_hash` changes, decode JPEG with a small lib (`TJpg_Decoder` already pulled by TFT_eSPI), draw onto an lv_canvas at (40, 36) with size 160×160.
- Volume slider: lv_slider with range 0-100, fires `_actions->volume(v)` on `LV_EVENT_RELEASED`.
- Play/pause button label updates between `LV_SYMBOL_PLAY` and `LV_SYMBOL_PAUSE` based on state.

Sketch (the full file is too long to inline; the agent expands during impl):

```cpp
#include "NowPlaying.h"
#include "Theme.h"

namespace boombox::ui {

NowPlaying::NowPlaying(ActionDispatch* actions) : _actions(actions) {}

void NowPlaying::show() {
    _build();
    lv_screen_load(_screen);
}

void NowPlaying::_build() {
    _screen = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(_screen, theme::BG_DARK, 0);

    // Status bar
    _lbl_boombox = lv_label_create(_screen);
    lv_label_set_text(_lbl_boombox, "—");
    lv_obj_align(_lbl_boombox, LV_ALIGN_TOP_LEFT, 8, 8);

    _lbl_status = lv_label_create(_screen);
    lv_label_set_text(_lbl_status, LV_SYMBOL_WIFI);
    lv_obj_align(_lbl_status, LV_ALIGN_TOP_RIGHT, -8, 8);

    // Art placeholder
    _art = lv_obj_create(_screen);
    lv_obj_set_size(_art, 160, 160);
    lv_obj_align(_art, LV_ALIGN_TOP_MID, 0, 36);
    lv_obj_set_style_bg_color(_art, theme::BUTTON_BG, 0);

    // Title + artist
    _lbl_title = lv_label_create(_screen);
    lv_label_set_text(_lbl_title, "—");
    lv_obj_set_style_text_font(_lbl_title, &lv_font_montserrat_24, 0);
    lv_obj_align(_lbl_title, LV_ALIGN_TOP_MID, 0, 206);

    _lbl_artist = lv_label_create(_screen);
    lv_label_set_text(_lbl_artist, "—");
    lv_obj_set_style_text_color(_lbl_artist, theme::MUTED, 0);
    lv_obj_align(_lbl_artist, LV_ALIGN_TOP_MID, 0, 236);

    // Transport row
    _btn_prev = theme::makeIconButton(_screen, LV_SYMBOL_PREV, 56, 40);
    lv_obj_set_pos(_btn_prev, 12, 264);
    lv_obj_add_event_cb(_btn_prev, [](lv_event_t* e){
        static_cast<NowPlaying*>(lv_event_get_user_data(e))->_onPrev();
    }, LV_EVENT_CLICKED, this);

    _btn_play = theme::makeIconButton(_screen, LV_SYMBOL_PLAY, 56, 40);
    lv_obj_set_pos(_btn_play, 92, 264);
    lv_obj_add_event_cb(_btn_play, [](lv_event_t* e){
        static_cast<NowPlaying*>(lv_event_get_user_data(e))->_onPlay();
    }, LV_EVENT_CLICKED, this);

    _btn_next = theme::makeIconButton(_screen, LV_SYMBOL_NEXT, 56, 40);
    lv_obj_set_pos(_btn_next, 172, 264);
    lv_obj_add_event_cb(_btn_next, [](lv_event_t* e){
        static_cast<NowPlaying*>(lv_event_get_user_data(e))->_onNext();
    }, LV_EVENT_CLICKED, this);

    // Volume slider
    _slider_vol = lv_slider_create(_screen);
    lv_obj_set_size(_slider_vol, 200, 12);
    lv_obj_align(_slider_vol, LV_ALIGN_BOTTOM_MID, 0, -16);
    lv_slider_set_range(_slider_vol, 0, 100);
    lv_obj_add_event_cb(_slider_vol, [](lv_event_t* e){
        auto* np = static_cast<NowPlaying*>(lv_event_get_user_data(e));
        np->_onVolumeChange(lv_slider_get_value(np->_slider_vol));
    }, LV_EVENT_RELEASED, this);
}

void NowPlaying::onStateUpdate(const BoomboxState& s) {
    lv_label_set_text(_lbl_boombox, s.boombox_name.c_str());
    lv_label_set_text(_lbl_title, s.track.valid() ? s.track.title.c_str() : "—");
    String aa = s.track.artist;
    if (s.track.album.length()) aa += " — " + s.track.album;
    lv_label_set_text(_lbl_artist, aa.length() ? aa.c_str() : "");
    if (s.volume >= 0) lv_slider_set_value(_slider_vol, s.volume, LV_ANIM_OFF);
    const char* sym = s.playing ? LV_SYMBOL_PAUSE : LV_SYMBOL_PLAY;
    lv_label_set_text(lv_obj_get_child(_btn_play, 0), sym);
    // Art: deferred — fetch only if hash changed; decoded later
    if (s.art_hash != _last_art_hash && s.art_hash.length()) {
        _last_art_hash = s.art_hash;
        // ... fetch + decode + draw ...
    }
}

void NowPlaying::onConnectionChange(bool connected) {
    lv_label_set_text(_lbl_status, connected ? LV_SYMBOL_WIFI : LV_SYMBOL_WARNING);
}

void NowPlaying::_onPlay()  { _actions->playPause(); }
void NowPlaying::_onNext()  { _actions->next(); }
void NowPlaying::_onPrev()  { _actions->previous(); }
void NowPlaying::_onVolumeChange(int v) { _actions->volume(v); }

} // namespace boombox::ui
```

(Art fetch + JPEG decode is deferred — too much for a single task. Task 16 handles it.)

- [ ] **Step 3: Wire main.cpp into the full boot flow**

```cpp
boombox::WifiManager     gWifi;
boombox::HttpClient*     gHttp = nullptr;
boombox::WsClient*       gWs = nullptr;
boombox::ActionDispatch* gActions = nullptr;
boombox::ui::NowPlaying* gNowPlaying = nullptr;

void bootRemote(const boombox::PairedBoombox& pb) {
    // For Phase 2 MVP: use mDNS-discovered host. If discovery fails,
    // fall back to "boombox.local:8090" (the LAN port nginx advertises).
    String host = "boombox.local:8090";
    gHttp = new boombox::HttpClient(host, "/api/remote/", pb.auth_token);
    gWs = new boombox::WsClient(host, pb.auth_token);
    gActions = new boombox::ActionDispatch(gHttp);
    gNowPlaying = new boombox::ui::NowPlaying(gActions);

    gWs->onState([](const boombox::BoomboxState& s){
        gNowPlaying->onStateUpdate(s);
    });
    gWs->onStatus([](bool ok){ gNowPlaying->onConnectionChange(ok); });

    gNowPlaying->show();
    gWs->connect();
}

void setup() {
    Serial.begin(115200);
    delay(500);
    boombox::CydDevice device;
    device.init();
    boombox::theme::apply();

    if (!gWifi.tryStored()) {
        auto* setup = new boombox::ui::WifiSetup(&gWifi, [](){
            // After WiFi joins, check for pairing
            boombox::PairedBoombox pb;
            if (boombox::PairedBoomboxStore::load(pb)) {
                bootRemote(pb);
            } else {
                auto* pair = new boombox::ui::PairScreen([](const auto& pb){
                    bootRemote(pb);
                });
                pair->show();
            }
        });
        setup->show();
    } else {
        boombox::PairedBoombox pb;
        if (boombox::PairedBoomboxStore::load(pb)) {
            bootRemote(pb);
        } else {
            auto* pair = new boombox::ui::PairScreen([](const auto& pb){
                bootRemote(pb);
            });
            pair->show();
        }
    }
}

void loop() {
    lv_timer_handler();
    if (gWs) gWs->poll();
    delay(5);
}
```

- [ ] **Step 4: Flash + smoke test**

```bash
cd firmware && pio run -e cyd-2432s028r -t upload && pio device monitor
```

Steps:
1. Power up the CYD with no NVS.
2. Goes through WifiSetup → PairScreen → NowPlaying.
3. Trigger pairing PIN from the boombox kiosk (or curl `/pair/start` manually).
4. Enter PIN on CYD.
5. NowPlaying appears with current track.
6. Tap play/pause → music actually pauses.
7. Tap next → track advances.
8. Drag volume slider → volume changes.

This is the demo moment.

- [ ] **Step 5: Commit**

```bash
git add firmware/src/devices/cyd-2432s028r/ui/NowPlaying.* firmware/src/devices/cyd-2432s028r/main.cpp
git commit -m "feat(firmware/cyd): NowPlaying view + end-to-end boot flow"
```

---

### Task 16: Album art fetch + decode

**Files:**
- Modify: `firmware/src/devices/cyd-2432s028r/ui/NowPlaying.cpp`

`TJpg_Decoder` is bundled with `TFT_eSPI`. Decode the JPEG bytes from `HttpClient::getArt` into a 160×160 area on the screen.

- [ ] **Step 1: Add the JPEG decode path**

```cpp
#include <TJpg_Decoder.h>

// Tile-callback that draws decoded blocks onto the CYD directly.
static bool _tjpg_output(int16_t x, int16_t y, uint16_t w, uint16_t h,
                          uint16_t* bitmap) {
    if (y >= 160) return false;
    extern TFT_eSPI _tft;  // from Device.cpp
    _tft.pushImage(40 + x, 36 + y, w, h, bitmap);  // 40,36 = art origin
    return true;
}

void NowPlaying::_fetchAndDrawArt(const String& hash) {
    static uint8_t buf[32 * 1024];  // 32 KB scratch
    size_t n = gHttp->getArt(hash, buf, sizeof(buf));
    if (n == 0) return;
    TJpgDec.setCallback(_tjpg_output);
    TJpgDec.setJpgScale(1);  // server already returns 240x240
    TJpgDec.drawJpg(0, 0, buf, n);
}
```

Call `_fetchAndDrawArt(s.art_hash)` from `onStateUpdate` when the hash changes.

- [ ] **Step 2: Flash and verify**

Trigger a track change on the boombox. Confirm the CYD shows the new album art.

- [ ] **Step 3: Commit**

```bash
git add firmware/src/devices/cyd-2432s028r/ui/NowPlaying.cpp
git commit -m "feat(firmware/cyd): fetch and decode album art via TJpg_Decoder"
```

---

### Task 17: Sources view

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/ui/Sources.h`
- Create: `firmware/src/devices/cyd-2432s028r/ui/Sources.cpp`

Full-screen 2×3 grid: Mopidy, AirPlay, Spotify, Bluetooth, Movies, (one blank). Tap fires `_actions->source(name)`. Auto-returns to NowPlaying after 3 s or on any tap.

- [ ] **Step 1: Write the screen** (~100 lines LVGL)

```cpp
#pragma once
#include <lvgl.h>
#include "action/ActionDispatch.h"

namespace boombox::ui {

class Sources {
public:
    Sources(ActionDispatch* actions, std::function<void()> on_close);
    void show();
private:
    ActionDispatch* _actions;
    std::function<void()> _on_close;
    lv_obj_t* _screen;
    lv_timer_t* _auto_close;
};

} // namespace boombox::ui
```

`.cpp` builds a 2×3 grid of large buttons with the source name + icon, attaches click handlers that fire `_actions->source(name)` and then `_on_close()`. A 3-second `lv_timer` auto-closes if no tap.

- [ ] **Step 2: Wire from NowPlaying**

Add a source badge in NowPlaying's transport row (the "🅼" tile in the sketch). Tap → show Sources screen with `on_close` callback that re-loads NowPlaying.

- [ ] **Step 3: Flash, verify, commit**

Tap source button on CYD, confirm Sources view appears, tap "Spotify" → confirm boombox switches to Spotify mode (or shows the "pick Boombox under Spotify Devices" overlay).

```bash
git add firmware/src/devices/cyd-2432s028r/ui/Sources.* firmware/src/devices/cyd-2432s028r/ui/NowPlaying.*
git commit -m "feat(firmware/cyd): Sources screen with 2x3 grid"
```

---

### Task 18: More view (sleep / mic / record / skin)

**Files:**
- Create: `firmware/src/devices/cyd-2432s028r/ui/More.h`
- Create: `firmware/src/devices/cyd-2432s028r/ui/More.cpp`

Full-screen list. Four rows:
- Sleep timer (tap cycles 15 → 30 → 60 → off, displayed on the row)
- Mic (toggle, shows on/off state from BoomboxState)
- Record (toggle, pulses red dot when active)
- Cycle skin

Each row fires the matching action via ActionDispatch.

- [ ] **Step 1: Write the screen**

`MoreView` follows the same pattern as Sources: full-screen list, fires action on row tap, returns to NowPlaying. Each row's display updates from the next BoomboxState push (since the boombox is the source of truth for sleep_timer_s, recording, mic_on).

- [ ] **Step 2: Wire from NowPlaying's "⋯" button, flash, commit**

```bash
git add firmware/src/devices/cyd-2432s028r/ui/More.* firmware/src/devices/cyd-2432s028r/ui/NowPlaying.*
git commit -m "feat(firmware/cyd): More view for sleep/mic/record/skin"
```

---

### Task 19: Ambient mode

**Files:**
- Modify: `firmware/src/devices/cyd-2432s028r/main.cpp`
- Modify: `firmware/src/devices/cyd-2432s028r/ui/NowPlaying.cpp`

After 30 s of no touch (LVGL has a "screen inactivity" timer): swap the screen contents to a 240×240 album-art-only layout. LDR drives backlight: scale `analogRead(LDR)` to a 10–100 % brightness range. Touch wakes back to NowPlaying.

- [ ] **Step 1: Add ambient detection in the main loop**

```cpp
void loop() {
    lv_timer_handler();
    if (gWs) gWs->poll();

    static uint32_t last_brightness_update = 0;
    if (millis() - last_brightness_update > 1000) {
        last_brightness_update = millis();
        uint16_t ldr = gDevice.readLdr();
        uint8_t pct = map(ldr, 0, 4095, 10, 100);
        gDevice.setBrightness(pct);
    }

    static bool in_ambient = false;
    uint32_t idle_ms = lv_display_get_inactive_time(NULL);
    if (idle_ms > 30000 && !in_ambient && gNowPlaying) {
        gNowPlaying->enterAmbient();
        in_ambient = true;
    } else if (idle_ms < 1000 && in_ambient && gNowPlaying) {
        gNowPlaying->exitAmbient();
        in_ambient = false;
    }
    delay(5);
}
```

- [ ] **Step 2: Add `enterAmbient` / `exitAmbient` to NowPlaying**

Ambient mode: hide transport/volume/status-bar widgets, scale art to 240×240 centered. ExitAmbient restores the original layout.

- [ ] **Step 3: Flash, verify, commit**

Touch CYD, wait 30 s, confirm screen dims and art fills. Touch again, confirm full UI returns.

```bash
git add firmware/src/devices/cyd-2432s028r
git commit -m "feat(firmware/cyd): ambient mode after 30s idle + LDR backlight"
```

---

## Stage 6 — Integration + polish + demo

### Task 20: Update install.sh + docs

**Files:**
- Modify: `install/install.sh` (no new units, but the kiosk now has the PairOverlay component)
- Modify: `docs/SERVICES.md` (mention `/api/remote/pair/*` in the boombox-remote section)

- [ ] **Step 1: Verify install.sh deploys the new SPA files**

Check that whatever rsync/cp logic the installer uses for `site/` already includes the new `PairOverlay.js` and `PairOverlay.css`. If not, add them.

- [ ] **Step 2: Add the pairing endpoints to docs/SERVICES.md**

Inside the boombox-remote section, expand the endpoints list to include:
- `POST /api/remote/pair/start` — localhost-only; mints a PIN
- `POST /api/remote/pair {pin, label}` — redeems PIN, returns auth_token

- [ ] **Step 3: Commit**

```bash
git add install/install.sh docs/SERVICES.md
git commit -m "docs(remote): document PIN-pairing endpoints; install.sh ships PairOverlay"
```

---

### Task 21: End-to-end smoke demo

**Files:** none committed; this is the demo flow.

- [ ] **Step 1: Deploy Phase 2 to the Pi**

```bash
./install/install.sh        # or whatever the user's deploy command is
```

- [ ] **Step 2: Flash the CYD from this Mac**

```bash
cd firmware && pio run -e cyd-2432s028r -t upload
```

- [ ] **Step 3: Walk the pairing flow**

1. Power up the CYD (USB).
2. CYD scans WiFi → user taps SSID → types password → joins.
3. CYD shows PairScreen.
4. On the boombox kiosk, open Settings → Pair wireless remote.
5. Kiosk displays a 6-digit PIN.
6. User enters PIN on CYD.
7. CYD transitions to NowPlaying.

- [ ] **Step 4: Walk the control flow**

1. Tap play/pause → music actually toggles.
2. Tap next → track advances.
3. Drag volume → boombox volume changes.
4. Tap source badge → Sources view opens.
5. Tap "More" (⋯) → sleep timer / mic / record buttons.
6. Wait 30 s → ambient mode engages.
7. Touch → wakes back.

- [ ] **Step 5: Capture video / screenshots for posterity**

Optional: record a 30-second clip of the demo for the PR / README.

---

## Risks and unknowns

1. **CYD pin map variation.** Different CYD batches have different LDR / backlight / touch pins. If the screen stays black or touch is dead, the first place to look is the random nerd tutorials reference for your specific board variant. **Mitigation:** the `platformio.ini` flags are commented at the source so they're easy to swap.

2. **LVGL learning curve.** LVGL 9 is the latest version; some online tutorials reference v8 with different APIs (`lv_scr_act()` vs `lv_screen_active()`, etc.). **Mitigation:** the plan uses v9 syntax throughout; if compile errors arise from API mismatch, check the LVGL v9 docs.

3. **mDNS resolution from ESP32.** The CYD's `boombox.local` resolution requires the network to forward mDNS queries. Most home routers do; corporate/guest networks often don't. **Mitigation:** the PairScreen's host field is editable; user can type an IP directly.

4. **WiFi password entry on resistive touch.** A 240×320 on-screen keyboard is fiddly. **Mitigation:** large buttons (40 px); after the first successful join, the password is cached in NVS and never asked again.

5. **JPEG memory.** A 240×240 JPEG is ~15-25 KB; we allocate a 32 KB scratch buffer. Larger art (Phase 2 server returns 240×240) will fit; safety net is in HttpClient::getArt with `out_buf_max`. **Mitigation:** server is already configured to return 240×240.

6. **Single-paired-boombox MVP.** Multi-pair switcher (per the design spec's BoomboxSwitcher view) is deferred. If the user adds a second boombox they'll need to factory-reset the CYD. **Mitigation:** explicit Phase 2 scope decision; Phase 3 or 4 adds the switcher.

7. **No tap-to-seek.** Position bar is display-only. Drag-to-seek introduces latency vs the streaming player's actual position; we punt to a future phase when we have a real UX answer. **Mitigation:** position display alone is still useful.

8. **Pairing race.** If two CYDs try to redeem the same PIN simultaneously, only the first succeeds; the second gets "bad_pin" since the PIN is invalidated on first use. That's actually the desired behavior — the alternative (multiple uses per PIN) would be a real security regression. Phase 2 doesn't paper over this.

## Out of scope (explicit)

- BLE transport (Phase 4)
- USB firmware installer on the Pi (Phase 3)
- BoomboxSwitcher / multi-pair (deferred)
- ELECROW round profile (Phase 7)
- Headless profile (Phase 5)
- Profile-pack infrastructure (Phase 6)
- Touch calibration UI (revisit if drift)
- OTA updates (Phase 3 USB-install covers this)
- Drag-to-seek
- Custom enclosure / battery / 3D printing
