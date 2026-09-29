# Accounts Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A persistent LAN web page at `http://<boombox>:8090/accounts/` where the owner manages the music server, video server + kiosk Jellyfin sign-in, AirPlay/Spotify receivers, and the boombox web login.

**Architecture:** Extend the existing first-run pieces. `boombox-setup` (aiohttp, 127.0.0.1:6689) gains an `/api/accounts/*` route group with its own auth (nginx Basic-auth user + non-loopback + JSON/Origin checks). Root-only changes go through new narrow actions in the stdlib root helper `install/bin/boombox-setup-apply`. The UI is a second entry point (`accounts.html`) in the `setup-ui` Vite app; the wizard's Music form and Video server form become shared components.

**Tech Stack:** Python 3.11+ (aiohttp, websockets, pytest + pytest-aiohttp), stdlib-only root helper, React 19 + TypeScript + Vite 8 + Vitest 4 (setup-ui), nginx.

**Spec:** `docs/superpowers/specs/2026-09-29-accounts-page-design.md`

## Global Constraints

- Page URL `http://<boombox>:8090/accounts/`; API prefix `/api/accounts/`; service `boombox-setup` on `127.0.0.1:6689`.
- Auth: request accepted only if `X-Boombox-User` is non-empty **and** `X-Real-IP` is not loopback (`127.0.0.1`, `::1`, `localhost`). Missing `X-Real-IP` counts as loopback (direct on-box call) → refused.
- Mutating requests (POST/PUT/PATCH/DELETE) require `Content-Type: application/json`; if an `Origin` header is present its host:port must equal `X-Boombox-Host`.
- Secrets are write-only: no GET ever returns a password, API key, or token; logs never contain them. Blank secret field on save = keep current.
- Web password policy: 10–128 characters, printable, no newline/control characters.
- Kiosk Jellyfin DeviceId = `<BOOMBOX_ID>-kiosk` (e.g. `boombox-markii-kiosk`).
- Every hardware/service-coupled card must degrade to a status ("Not installed", "Not set up", "Problem: …") — never a 500 (hardware-optional rule).
- Outbound HTTP timeouts: 15 s total (Quick Connect flow 30 s). No 500s for upstream failures.
- Python: `.venv/bin/python -m pytest -q services/tests`, `~/.local/bin/ruff check services`, `~/.local/bin/mypy`. UI: `cd setup-ui && npx tsc -b && npx vitest run && npm run build`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Kiosk-origin requests** (`X-Real-IP: 127.0.0.1`, even with `X-Boombox-User` set) must be refused — a Jellyfin page in the kiosk must never change accounts. (Task 3 test `test_accounts_refuses_loopback_even_with_user`.)
2. **Blank password/API-key on save keeps the stored secret** instead of blanking it. (Task 4 `test_source_put_blank_password_keeps_current`, Task 5 `test_video_save_blank_key_keeps_current`.)
3. **Web password change where Samba fails mid-way** must roll back htpasswd and web-auth.env so the old password still works everywhere. (Task 2 `test_web_password_rolls_back_on_smb_failure`.)
4. **Kiosk sign-in when the kiosk/CDP is unreachable** must revoke the Jellyfin device it just created and return a clear error, not leave a dangling token. (Task 6 `test_signin_revokes_device_when_kiosk_unreachable`.)
5. **Names/passwords containing quotes, backslashes, newlines or `$`** for AirPlay/Spotify must be rejected or safely escaped, never break the config file. (Task 1 `test_validate_receiver_name_rejects_hazards`, `test_airplay_password_escaped`.)

---

## File Structure

| File | Responsibility |
|---|---|
| `install/bin/boombox-setup-apply` (modify) | New actions `streaming-status`, `streaming`, `web-password`; `jellyfin` accepts `device_id`; shairport config path detection shared with `identity`. |
| `services/boombox_library/api.py` (modify) | `/api/library/source` PUT/test: empty password = keep current. |
| `services/boombox_setup/accounts.py` (create) | Auth check + all `/api/accounts/*` handlers. |
| `services/boombox_setup/jellyfin_signin.py` (create) | Pure async Jellyfin HTTP helpers (users, system info, Quick Connect token, device revoke, kiosk device user) + CDP kiosk injection. |
| `services/boombox_setup/api.py` (modify) | Middleware delegates `/api/accounts/*` to `accounts.check_auth`; `build_app` registers accounts routes. |
| `services/boombox-setup.py` (modify) | Context gains `jellyfin_env()`, `library_health()`, `http()`. |
| `install/config/nginx-boombox-common.conf` (modify) | `/api/accounts/` and `/accounts/` locations. |
| `setup-ui/vite.config.ts` (modify), `setup-ui/accounts.html` (create) | Multi-page build. |
| `setup-ui/src/accounts/*` (create) | `api.ts`, `types.ts`, `AccountsApp.tsx`, `main.tsx`, cards `MusicCard.tsx`, `VideoCard.tsx`, `StreamingCard.tsx`, `WebLoginCard.tsx`, `StatusPill.tsx`, tests. |
| `setup-ui/src/shared/MusicForm.tsx`, `VideoServerForm.tsx` (create) | Presentational forms shared by wizard + Accounts. |
| `setup-ui/src/steps/Music.tsx`, `Video.tsx` (modify) | Use shared forms. |
| `ui/src/lib/SettingsDrawer.tsx` (modify), `docs/HOME-SERVERS.md`, `README.md` | Link/docs. |

---

### Task 1: Root helper — streaming receivers (AirPlay + Spotify)

**Files:**
- Modify: `install/bin/boombox-setup-apply` (constants near line 36; `_set_shairport_name` ~263; `ACTIONS` ~612)
- Test: `services/tests/test_setup_helper_streaming.py` (create)

**Interfaces:**
- Produces (helper JSON actions):
  - `{"action":"streaming-status"}` → `{"ok":true,"airplay":{"installed":bool,"active":bool,"name":str,"password_set":bool},"spotify":{"installed":bool,"active":bool,"name":str}}`
  - `{"action":"streaming","airplay_name"?:str,"airplay_password"?:str,"airplay_password_clear"?:bool,"spotify_name"?:str}` → `{"ok":true,"changed":[...]}` or `{"ok":false,"error":str}`
- Pure functions (tested): `shairport_conf_path() -> str | None`, `validate_receiver_name(raw) -> str`, `validate_receiver_password(raw) -> str`, `shairport_set(conf: str, key: str, value: str | None) -> str`, `shairport_get(conf: str, key: str) -> str | None`, `raspotify_set_name(conf: str, name: str) -> str`, `raspotify_get_name(conf: str) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_setup_helper_streaming.py
"""boombox-setup-apply streaming actions (AirPlay / Spotify Connect)."""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    loader = SourceFileLoader("boombox_setup_apply_streaming", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()

DIETPI_CONF = """// Sample Configuration File for Shairport Sync
general =
{
//\tname = "%H"; // comment
//\tpassword = "secret";
\toutput_backend = "alsa";
};

alsa =
{
};
"""


def test_conf_path_prefers_existing(tmp_path, monkeypatch):
    usr = tmp_path / "usr-local-etc.conf"
    etc = tmp_path / "etc.conf"
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [str(etc), str(usr)])
    assert helper.shairport_conf_path() is None
    usr.write_text(DIETPI_CONF)
    assert helper.shairport_conf_path() == str(usr)
    etc.write_text(DIETPI_CONF)
    assert helper.shairport_conf_path() == str(etc)


@pytest.mark.parametrize("bad", ["", " lead", "a\nb", 'say "hi"', "back\\slash",
                                 "$HOME", "x" * 33, None, 7])
def test_validate_receiver_name_rejects_hazards(bad):
    with pytest.raises(ValueError):
        helper.validate_receiver_name(bad)


def test_validate_receiver_name_accepts_room_names():
    assert helper.validate_receiver_name("Kids' Room 2") == "Kids' Room 2"


def test_shairport_set_uncomments_and_sets_name():
    out = helper.shairport_set(DIETPI_CONF, "name", "Kitchen")
    assert '\tname = "Kitchen";' in out
    assert helper.shairport_get(out, "name") == "Kitchen"
    # only one active name line
    assert sum(1 for ln in out.splitlines()
               if ln.strip().startswith("name =")) == 1


def test_airplay_password_escaped_and_cleared():
    out = helper.shairport_set(DIETPI_CONF, "password", 'p"a\\ss')
    assert helper.shairport_get(out, "password") == 'p"a\\ss'
    cleared = helper.shairport_set(out, "password", None)
    assert helper.shairport_get(cleared, "password") is None


@pytest.mark.parametrize("bad", ["short", "a\nb", "x" * 65, None])
def test_validate_receiver_password(bad):
    with pytest.raises(ValueError):
        helper.validate_receiver_password(bad)


def test_raspotify_name_roundtrip():
    conf = '#LIBRESPOT_NAME="Librespot"\nLIBRESPOT_BITRATE=320\n'
    out = helper.raspotify_set_name(conf, "Living Room")
    assert 'LIBRESPOT_NAME="Living Room"' in out
    assert helper.raspotify_get_name(out) == "Living Room"
    assert "LIBRESPOT_BITRATE=320" in out


def test_streaming_action_airplay(tmp_path, monkeypatch):
    conf = tmp_path / "shairport-sync.conf"
    conf.write_text(DIETPI_CONF)
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(helper, "RASPOTIFY_CONF", str(tmp_path / "missing"))
    restarted = []
    monkeypatch.setattr(helper, "_restart_system_units", restarted.extend)
    r = helper.action_streaming({"airplay_name": "Den", "airplay_password": "hunter22"})
    assert r["ok"] and r["changed"] == ["airplay"]
    assert helper.shairport_get(conf.read_text(), "name") == "Den"
    assert helper.shairport_get(conf.read_text(), "password") == "hunter22"
    assert restarted == ["shairport-sync"]


def test_streaming_action_spotify_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [])
    monkeypatch.setattr(helper, "RASPOTIFY_CONF", str(tmp_path / "missing"))
    r = helper.action_streaming({"spotify_name": "Den"})
    assert r == {"ok": False, "error": "Spotify Connect is not installed"}


def test_streaming_status_reports_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [])
    monkeypatch.setattr(helper, "RASPOTIFY_CONF", str(tmp_path / "missing"))
    monkeypatch.setattr(helper, "_unit_active", lambda u: False)
    r = helper.action_streaming_status({})
    assert r["airplay"]["installed"] is False
    assert r["spotify"]["installed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_setup_helper_streaming.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'SHAIRPORT_CONF_CANDIDATES'`

- [ ] **Step 3: Implement in the helper**

Replace the constant `SHAIRPORT_CONF = "/etc/shairport-sync.conf"` with:

```python
# Debian packages read /etc; DietPi's source build reads /usr/local/etc
# (sysconfdir), which the old single path silently missed.
SHAIRPORT_CONF_CANDIDATES = ["/etc/shairport-sync.conf",
                             "/usr/local/etc/shairport-sync.conf"]
RASPOTIFY_CONF = "/etc/raspotify/conf"
```

Add after `_restart_system_units`:

```python
# Receiver names: same shape as device names (no quotes/backslash/$/control).
def validate_receiver_name(raw: object) -> str:
    if not isinstance(raw, str) or not _NAME_RE.match(raw):
        raise ValueError("name must be 1-32 letters, digits, spaces or . ' _ -")
    return raw


def validate_receiver_password(raw: object) -> str:
    if (not isinstance(raw, str) or not 8 <= len(raw) <= 64
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)):
        raise ValueError("AirPlay password must be 8-64 printable characters")
    return raw


def shairport_conf_path() -> str | None:
    for p in SHAIRPORT_CONF_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _c_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _c_unescape(s: str) -> str:
    return re.sub(r'\\(.)', r'\1', s)


_ACTIVE_KEY = r'(?m)^(\s*){key}\s*=\s*"((?:[^"\\]|\\.)*)"\s*;[^\n]*$'
_COMMENTED_KEY = r'(?m)^\s*//\s*{key}\s*=[^\n]*$'


def shairport_get(conf: str, key: str) -> str | None:
    m = re.search(_ACTIVE_KEY.format(key=re.escape(key)), conf)
    return _c_unescape(m.group(2)) if m else None


def shairport_set(conf: str, key: str, value: str | None) -> str:
    """Set (value) or remove (None) `key = "value";` in the general block."""
    active = re.compile(_ACTIVE_KEY.format(key=re.escape(key)))
    if value is None:
        return active.sub("", conf)
    line = f'\t{key} = "{_c_escape(value)}";'
    if active.search(conf):
        return active.sub(lambda _m: line, conf, count=1)
    commented = re.compile(_COMMENTED_KEY.format(key=re.escape(key)))
    if commented.search(conf):
        return commented.sub(lambda _m: line, conf, count=1)
    m = re.search(r"(?m)^\s*general\s*=\s*\{", conf)
    if not m:
        raise ValueError("shairport-sync.conf has no general block")
    return conf[:m.end()] + "\n" + line + conf[m.end():]


def raspotify_get_name(conf: str) -> str | None:
    m = re.search(r'(?m)^\s*LIBRESPOT_NAME\s*=\s*"?([^"\n]*)"?\s*$', conf)
    return m.group(1) if m else None


def raspotify_set_name(conf: str, name: str) -> str:
    line = f'LIBRESPOT_NAME="{name}"'
    pat = re.compile(r'(?m)^\s*#?\s*LIBRESPOT_NAME\s*=.*$')
    if pat.search(conf):
        return pat.sub(lambda _m: line, conf, count=1)
    return conf.rstrip("\n") + "\n" + line + "\n"


def _unit_active(unit: str) -> bool:
    try:
        return _run(["systemctl", "is-active", unit], timeout=8).stdout.strip() == "active"
    except Exception:
        return False


def action_streaming_status(_body: dict) -> dict:
    sp = shairport_conf_path()
    airplay = {"installed": sp is not None, "active": False, "name": "",
               "password_set": False}
    if sp:
        with open(sp) as f:
            conf = f.read()
        airplay.update(active=_unit_active("shairport-sync"),
                       name=shairport_get(conf, "name") or "",
                       password_set=shairport_get(conf, "password") is not None)
    spotify = {"installed": os.path.exists(RASPOTIFY_CONF), "active": False, "name": ""}
    if spotify["installed"]:
        with open(RASPOTIFY_CONF) as f:
            spotify.update(active=_unit_active("raspotify"),
                           name=raspotify_get_name(f.read()) or "")
    return {"ok": True, "airplay": airplay, "spotify": spotify}


def action_streaming(body: dict) -> dict:
    changed: list[str] = []
    wants_airplay = any(k in body for k in
                        ("airplay_name", "airplay_password", "airplay_password_clear"))
    if wants_airplay:
        sp = shairport_conf_path()
        if sp is None:
            return {"ok": False, "error": "AirPlay (shairport-sync) is not installed"}
        with open(sp) as f:
            conf = f.read()
        new = conf
        if "airplay_name" in body:
            new = shairport_set(new, "name", validate_receiver_name(body["airplay_name"]))
        if body.get("airplay_password_clear"):
            new = shairport_set(new, "password", None)
        elif "airplay_password" in body:
            new = shairport_set(new, "password",
                                validate_receiver_password(body["airplay_password"]))
        if new != conf:
            _atomic_write(sp, new, 0o644)
            _restart_system_units(["shairport-sync"])
        changed.append("airplay")
    if "spotify_name" in body:
        if not os.path.exists(RASPOTIFY_CONF):
            return {"ok": False, "error": "Spotify Connect is not installed"}
        name = validate_receiver_name(body["spotify_name"])
        with open(RASPOTIFY_CONF) as f:
            conf = f.read()
        _atomic_write(RASPOTIFY_CONF, raspotify_set_name(conf, name), 0o644)
        _restart_system_units(["raspotify"])
        changed.append("spotify")
    return {"ok": True, "changed": changed}
```

Rewrite `_set_shairport_name` to reuse the new helpers:

```python
def _set_shairport_name(name: str) -> bool:
    """Set the AirPlay advertised name (general block)."""
    sp = shairport_conf_path()
    if sp is None:
        return False
    try:
        with open(sp) as f:
            conf = f.read()
        new = shairport_set(conf, "name", name)
        if new != conf:
            _atomic_write(sp, new, 0o644)
            _restart_system_units(["shairport-sync"])
        return True
    except (OSError, ValueError):
        return False
```

Register actions and update the header docstring's action list:

```python
ACTIONS = {
    "identity": action_identity,
    "wifi-scan": action_wifi_scan,
    "wifi-join": action_wifi_join,
    "jellyfin": action_jellyfin,
    "streaming-status": action_streaming_status,
    "streaming": action_streaming,
}
```

```
#   streaming-status {}                 → AirPlay/Spotify installed/active/name
#   streaming  {airplay_name?, airplay_password?, airplay_password_clear?,
#               spotify_name?}          → rename receivers / set AirPlay password
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_setup_helper_streaming.py services/tests/test_setup_helper.py`
Expected: PASS (existing helper tests still pass).

- [ ] **Step 5: Commit**

```bash
git add install/bin/boombox-setup-apply services/tests/test_setup_helper_streaming.py
git commit -m "feat(setup-apply): streaming receiver actions; find DietPi shairport config

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Root helper — web password and Jellyfin device id

**Files:**
- Modify: `install/bin/boombox-setup-apply`
- Test: `services/tests/test_setup_helper_webpw.py` (create)

**Interfaces:**
- Produces:
  - `{"action":"web-password","current_password":str,"new_password":str}` → `{"ok":true,"updated":["web","samba",("jellyfin")]}` / `{"ok":false,"error":str}`
  - `jellyfin` action accepts optional `"device_id": str` (`^[A-Za-z0-9._-]{1,64}$`) → writes `BOOMBOX_JELLYFIN_DEVICE_ID`; `"device_id": ""` removes it.
- Pure: `validate_web_password(raw) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_setup_helper_webpw.py
"""boombox-setup-apply: web-password rotation + jellyfin device_id."""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    loader = SourceFileLoader("boombox_setup_apply_webpw", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()


@pytest.mark.parametrize("bad", ["short", "x" * 129, "has\nnewline", "tab\there", None])
def test_validate_web_password_rejects(bad):
    with pytest.raises(ValueError):
        helper.validate_web_password(bad)


def test_validate_web_password_accepts_passphrase():
    assert helper.validate_web_password("correct horse battery") == "correct horse battery"


@pytest.fixture
def env(tmp_path, monkeypatch):
    webenv = tmp_path / "web-auth.env"
    webenv.write_text("BOOMBOX_WEB_PORT=8090\nBOOMBOX_WEB_USER=boombox\n"
                      "BOOMBOX_WEB_PASSWORD=123456\nBOOMBOX_SMB_USER=dietpi\n")
    htp = tmp_path / "boombox.htpasswd"
    htp.write_text("boombox:$2y$old\n")
    monkeypatch.setattr(helper, "WEB_AUTH_ENV", str(webenv))
    monkeypatch.setattr(helper, "HTPASSWD", str(htp))
    monkeypatch.setattr(helper, "JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    calls: list[list[str]] = []

    class R:
        def __init__(self, rc=0):
            self.returncode, self.stdout, self.stderr = rc, "", ""

    def fake_run(cmd, timeout=25, check=False, inp=None):
        calls.append(cmd)
        if cmd[0] == "htpasswd":
            Path(cmd[-2]).write_text(f"{cmd[-1]}:$2y$new\n")
        return R(0)

    monkeypatch.setattr(helper, "_run", fake_run)
    monkeypatch.setattr(helper, "_chown", lambda *a, **k: None)
    return {"webenv": webenv, "htp": htp, "calls": calls, "R": R}


def test_web_password_requires_current(env):
    r = helper.action_web_password({"current_password": "nope",
                                    "new_password": "correct horse battery"})
    assert r == {"ok": False, "error": "current password is incorrect"}
    assert env["calls"] == []


def test_web_password_updates_web_and_samba(env):
    r = helper.action_web_password({"current_password": "123456",
                                    "new_password": "correct horse battery"})
    assert r["ok"] and r["updated"] == ["web", "samba"]
    assert "BOOMBOX_WEB_PASSWORD=correct horse battery" in env["webenv"].read_text()
    assert [c[0] for c in env["calls"]] == ["htpasswd", "smbpasswd"]


def test_web_password_rolls_back_on_smb_failure(env, monkeypatch):
    R = env["R"]
    old_htp = env["htp"].read_text()

    def run(cmd, timeout=25, check=False, inp=None):
        env["calls"].append(cmd)
        if cmd[0] == "htpasswd":
            Path(cmd[-2]).write_text(f"{cmd[-1]}:$2y$new\n")
            return R(0)
        if cmd[0] == "smbpasswd" and inp and "correct horse" in inp:
            return R(1)
        return R(0)

    monkeypatch.setattr(helper, "_run", run)
    r = helper.action_web_password({"current_password": "123456",
                                    "new_password": "correct horse battery"})
    assert r["ok"] is False and "samba" in r["error"]
    assert env["htp"].read_text() == old_htp
    assert "BOOMBOX_WEB_PASSWORD=123456" in env["webenv"].read_text()


def test_jellyfin_device_id_written_and_removed(tmp_path, monkeypatch):
    jenv = tmp_path / "jellyfin.env"
    jenv.write_text("BOOMBOX_JELLYFIN_BASE=https://video.example\nJELLYFIN_API_KEY=abc\n")
    monkeypatch.setattr(helper, "JELLYFIN_ENV", str(jenv))
    monkeypatch.setattr(helper, "_chown_boombox_group", lambda p: None)
    r = helper.action_jellyfin({"mode": "remote", "base": "https://video.example",
                                "device_id": "boombox-markii-kiosk"})
    assert r["ok"]
    assert "BOOMBOX_JELLYFIN_DEVICE_ID=boombox-markii-kiosk" in jenv.read_text()
    assert "JELLYFIN_API_KEY=abc" in jenv.read_text()
    helper.action_jellyfin({"mode": "remote", "base": "https://video.example",
                            "device_id": ""})
    assert "DEVICE_ID" not in jenv.read_text()


@pytest.mark.parametrize("bad", ["has space", "a;b", "x" * 65, "$(id)"])
def test_jellyfin_device_id_rejected(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(helper, "JELLYFIN_ENV", str(tmp_path / "j.env"))
    monkeypatch.setattr(helper, "_chown_boombox_group", lambda p: None)
    r = helper.action_jellyfin({"mode": "remote", "base": "https://v.example",
                                "device_id": bad})
    assert r["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q services/tests/test_setup_helper_webpw.py`
Expected: FAIL — `AttributeError: ... 'validate_web_password'`

- [ ] **Step 3: Implement**

Add constants beside the others:

```python
WEB_AUTH_ENV = "/etc/boombox/web-auth.env"
HTPASSWD = "/etc/nginx/boombox.htpasswd"
```

Add functions (before `ACTIONS`):

```python
def validate_web_password(raw: object) -> str:
    if (not isinstance(raw, str) or not 10 <= len(raw) <= 128
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)):
        raise ValueError("password must be 10-128 printable characters")
    return raw


def _chown(path: str, user: str, group: str) -> None:
    import grp
    import pwd
    try:
        os.chown(path, pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid)
    except (KeyError, OSError):
        pass


def _smb_set(user: str, password: str) -> bool:
    r = _run(["smbpasswd", "-s", user], inp=f"{password}\n{password}\n")
    return r.returncode == 0


def action_web_password(body: dict) -> dict:
    env = _read_env_file(WEB_AUTH_ENV)
    current = env.get("BOOMBOX_WEB_PASSWORD", "")
    supplied = body.get("current_password")
    import hmac
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, current):
        return {"ok": False, "error": "current password is incorrect"}
    new = validate_web_password(body.get("new_password"))
    web_user = env.get("BOOMBOX_WEB_USER", "boombox")
    smb_user = env.get("BOOMBOX_SMB_USER") or os.environ.get("SUDO_USER") or "dietpi"

    with open(HTPASSWD) as f:
        old_htpasswd = f.read()
    with open(WEB_AUTH_ENV) as f:
        old_env_text = f.read()
    updated: list[str] = []

    def rollback(step: str) -> dict:
        _atomic_write(HTPASSWD, old_htpasswd, 0o640)
        _chown(HTPASSWD, "root", "www-data")
        _atomic_write(WEB_AUTH_ENV, old_env_text, 0o640)
        if "samba" in updated:
            _smb_set(smb_user, current)
        return {"ok": False, "error": f"could not update {step}; nothing was changed"}

    r = _run(["htpasswd", "-iB", HTPASSWD, web_user], inp=new + "\n")
    if r.returncode != 0:
        return rollback("web login")
    _chown(HTPASSWD, "root", "www-data")
    updated.append("web")
    if shutil.which("smbpasswd"):  # Samba is optional on some installs
        if not _smb_set(smb_user, new):
            return rollback("samba")
        updated.append("samba")
    env["BOOMBOX_WEB_PASSWORD"] = new
    _write_env_file(WEB_AUTH_ENV, env, mode=0o640)
    _chown_boombox_group(WEB_AUTH_ENV)
    if _builtin_jellyfin_password(current, new):
        updated.append("jellyfin")
    return {"ok": True, "updated": updated}


def _builtin_jellyfin_password(old: str, new: str) -> bool:
    """Best-effort: the built-in Jellyfin's bootstrapped admin shares the web
    password. Skipped for a remote server (BOOMBOX_JELLYFIN_BASE set)."""
    jenv = _read_env_file(JELLYFIN_ENV)
    uid, key = jenv.get("JELLYFIN_USER_ID"), jenv.get("JELLYFIN_API_KEY")
    if jenv.get("BOOMBOX_JELLYFIN_BASE") or not uid or not key:
        return False
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:8096/Users/{uid}/Password",
        data=json.dumps({"CurrentPw": old, "NewPw": new}).encode(),
        headers={"Content-Type": "application/json", "X-Emby-Token": key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
```

In the `env` test fixture add `monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/bin/" + n)` so Samba counts as installed without touching the real binary.

In `action_jellyfin`, after the `api_key` block (both modes), add:

```python
    if "device_id" in body:
        dev = body.get("device_id")
        if dev == "":
            env.pop("BOOMBOX_JELLYFIN_DEVICE_ID", None)
        elif isinstance(dev, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", dev):
            env["BOOMBOX_JELLYFIN_DEVICE_ID"] = dev
        else:
            return {"ok": False, "error": "device_id must be 1-64 of A-Z a-z 0-9 . _ -"}
```

Register `"web-password": action_web_password` in `ACTIONS` and document it in the header.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_setup_helper_webpw.py services/tests/test_setup_helper.py services/tests/test_setup_helper_streaming.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add install/bin/boombox-setup-apply services/tests/test_setup_helper_webpw.py
git commit -m "feat(setup-apply): web-password rotation with rollback; jellyfin device_id

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Accounts API skeleton + auth

**Files:**
- Create: `services/boombox_setup/accounts.py`
- Modify: `services/boombox_setup/api.py` (`_auth_mw` top; `build_app`)
- Test: `services/tests/test_accounts_api.py` (create)

**Interfaces:**
- Produces: `accounts.check_auth(req: web.Request) -> web.Response | None`; `accounts.add_routes(app: web.Application) -> None`; `GET /api/accounts/summary` → `{"music": CardStatus, "video": CardStatus, "streaming": CardStatus, "web": CardStatus}` where `CardStatus = {"state": "ok"|"problem"|"unset"|"absent", "detail": str}`.
- Consumes: Context (Task 4/5 add methods); test `FakeAccountsContext` defined here is extended by later tasks.

- [ ] **Step 1: Write the failing tests**

```python
# services/tests/test_accounts_api.py
"""/api/accounts/* — auth gate and card endpoints."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer
from boombox_setup.api import build_app

LAN = {"X-Real-IP": "192.168.1.50", "X-Boombox-User": "boombox",
       "X-Boombox-Host": "192.168.1.81:8090"}


class FakeAccountsContext:
    lan_port = 8090

    def __init__(self):
        self.applied: list[dict] = []
        self.apply_results: dict[str, dict] = {}
        self.music = {"url": "https://m.example", "username": "bb",
                      "configured": True, "reachable": True}
        self.health = {"navidrome_reachable": True, "last_sync_ts": 1.0,
                       "syncing": False, "prune_deferred": None}
        self.jf_env = {"BOOMBOX_JELLYFIN_BASE": "https://v.example",
                       "JELLYFIN_API_KEY": "k"}
        self.music_calls: list[tuple] = []
        self.restarted: list[list[str]] = []

    # setup Context surface used by build_app / status
    def read_identity(self):
        return {"name": "MarkII", "id": "boombox-markii", "hostname": "markii"}
    def wifi_status(self): return {"present": False, "connected": False, "ssid": "", "ip": ""}
    def video_status(self): return {"mode": "remote", "base": "https://v.example", "has_key": True}
    def is_complete(self): return True
    def mark_complete(self): pass
    def lan_host(self): return "192.168.1.81"
    def get_skin(self): return None
    def set_skin(self, s): return True
    async def remote_status(self): return {"enabled": False, "peers": []}
    async def remote_enable(self): return {"ok": True}
    async def remote_pair_start(self): return {"ok": True}

    async def apply(self, payload):
        self.applied.append(payload)
        return self.apply_results.get(payload["action"], {"ok": True})
    async def restart_units(self, units): self.restarted.append(units)
    async def music_get(self): return dict(self.music)
    async def music_test(self, url, username, password):
        self.music_calls.append(("test", url, username, password))
        return True, ""
    async def music_save(self, url, username, password):
        self.music_calls.append(("save", url, username, password))
        return True, ""
    async def library_health(self): return dict(self.health)
    def jellyfin_env(self): return dict(self.jf_env)


@pytest.fixture
async def ctx():
    return FakeAccountsContext()


@pytest.fixture
async def client(ctx):
    app = build_app(ctx)
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c
    await c.close()


async def test_accounts_requires_basic_auth_user(client):
    r = await client.get("/api/accounts/summary", headers={"X-Real-IP": "192.168.1.50"})
    assert r.status == 401


async def test_accounts_refuses_loopback_even_with_user(client):
    r = await client.get("/api/accounts/summary",
                         headers={"X-Real-IP": "127.0.0.1", "X-Boombox-User": "boombox"})
    assert r.status == 403
    r = await client.get("/api/accounts/summary", headers={"X-Boombox-User": "boombox"})
    assert r.status == 403  # no X-Real-IP = direct on-box call


async def test_accounts_mutation_needs_json_and_same_origin(client):
    r = await client.post("/api/accounts/music/test", data="x", headers=LAN)
    assert r.status == 415
    r = await client.post("/api/accounts/music/test", json={},
                          headers={**LAN, "Origin": "http://evil.example"})
    assert r.status == 403
    r = await client.post("/api/accounts/music/test", json={"url": "u", "username": "n"},
                          headers={**LAN, "Origin": "http://192.168.1.81:8090"})
    assert r.status == 200


async def test_setup_token_does_not_open_accounts(client):
    r = await client.get("/api/accounts/summary",
                         headers={"X-Real-IP": "192.168.1.50",
                                  "Authorization": "Bearer whatever"})
    assert r.status == 401


async def test_summary_shape(client):
    r = await client.get("/api/accounts/summary", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert set(body) == {"music", "video", "streaming", "web"}
    assert body["music"]["state"] == "ok"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest -q services/tests/test_accounts_api.py`
Expected: FAIL (404s / missing module).

- [ ] **Step 3: Implement `accounts.py` (auth + summary) and wire into `api.py`**

```python
# services/boombox_setup/accounts.py
"""/api/accounts/* — the LAN Accounts page backend.

Auth is NOT the wizard's token/code: nginx Basic auth on the LAN port is the
admin gate. nginx forwards `X-Boombox-User: $remote_user` (empty on the
loopback kiosk server, which has no auth) and `X-Real-IP`; we require a user
AND a non-loopback client, so a page open in the kiosk can never change
accounts. Mutations also need JSON and, when the browser sends Origin, a
same-origin match against `X-Boombox-Host` ($http_host). Secrets are
write-only: no response ever carries a password, API key or token.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

log = logging.getLogger("boombox-setup.accounts")

PREFIX = "/api/accounts/"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def check_auth(req: web.Request) -> web.Response | None:
    """None when the request may proceed, else the refusal response."""
    if not req.headers.get("X-Boombox-User", "").strip():
        return web.json_response({"error": "sign in to the boombox web UI"}, status=401)
    if req.headers.get("X-Real-IP", "127.0.0.1") in _LOOPBACK:
        return web.json_response(
            {"error": "accounts can only be changed from another device"}, status=403)
    if req.method in _MUTATING:
        if req.content_type != "application/json":
            return web.json_response(
                {"error": "Content-Type must be application/json"}, status=415)
        origin = req.headers.get("Origin")
        if origin and urlsplit(origin).netloc != req.headers.get("X-Boombox-Host", ""):
            return web.json_response({"error": "cross-origin request refused"}, status=403)
    return None


def _state(state: str, detail: str = "") -> dict[str, str]:
    return {"state": state, "detail": detail}


async def _summary(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    out: dict[str, dict[str, str]] = {}
    try:
        m = await ctx.music_get()
        out["music"] = (_state("unset") if not m.get("configured") else
                        _state("ok") if m.get("reachable") else
                        _state("problem", "music server not reachable"))
    except Exception:
        out["music"] = _state("problem", "library service not answering")
    out["video"] = await _video_state(ctx)
    out["streaming"] = await _streaming_state(ctx)
    out["web"] = _state("ok")
    return web.json_response(out)


async def _video_state(ctx: Any) -> dict[str, str]:
    env = ctx.jellyfin_env()
    if env.get("BOOMBOX_JELLYFIN_BASE") and not env.get("JELLYFIN_API_KEY"):
        return _state("problem", "API key missing")
    return _state("ok")


async def _streaming_state(ctx: Any) -> dict[str, str]:
    r = await ctx.apply({"action": "streaming-status"})
    if not r.get("ok"):
        return _state("problem", r.get("error", "status unavailable"))
    installed = [k for k in ("airplay", "spotify") if r.get(k, {}).get("installed")]
    return _state("ok" if installed else "absent", ", ".join(installed))


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/accounts/summary", _summary)
```

In `services/boombox_setup/api.py`, add `from . import accounts` to the imports, and make the first lines of `_auth_mw`:

```python
@web.middleware
async def _auth_mw(req: web.Request, handler):
    if req.path.startswith(accounts.PREFIX):
        deny = accounts.check_auth(req)
        return deny if deny is not None else await handler(req)
    if req.method in _MUTATING and req.content_type != "application/json":
```

and at the end of `build_app`, before `return app`: `accounts.add_routes(app)`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_accounts_api.py services/tests/test_setup_api.py`
Expected: `test_accounts_mutation_needs_json_and_same_origin` still FAILS on the last assertion (route added in Task 4) — mark it `@pytest.mark.skip("route in Task 4")` now and un-skip in Task 4. All others PASS.

- [ ] **Step 5: Commit**

```bash
git add services/boombox_setup/accounts.py services/boombox_setup/api.py services/tests/test_accounts_api.py
git commit -m "feat(accounts): /api/accounts auth gate (LAN basic-auth user, never kiosk) + summary

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Music card API (+ library keeps password when blank)

**Files:**
- Modify: `services/boombox_library/api.py` (`_source_put` ~108, `_source_test` ~141)
- Modify: `services/boombox_setup/accounts.py`, `services/boombox-setup.py`
- Test: `services/tests/test_library_api.py` (append), `services/tests/test_accounts_api.py` (append)

**Interfaces:**
- Produces: `GET /api/accounts/music` → `{"url","username","configured","reachable","last_sync_ts","syncing","prune_deferred"}`; `POST /api/accounts/music/test {url,username,password?}` → `{"ok","error"}`; `PUT /api/accounts/music {url,username,password?}` → `{"ok"}` / 400 `{"ok":false,"error"}`.
- Context gains `async library_health() -> dict` (GET `{LIBRARY_BASE}/api/library/health`, `{}` on failure).

- [ ] **Step 1: Failing tests**

Append to `services/tests/test_library_api.py` (use that file's existing app/client fixture and fake ctx; the fake ctx has `cfg.source.password`):

```python
async def test_source_put_blank_password_keeps_current(client, ctx):
    ctx.cfg = replace(ctx.cfg, source=replace(ctx.cfg.source, password="s3cret"))
    r = await client.put("/api/library/source",
                         json={"url": "https://m.example", "username": "bb", "password": ""})
    assert r.status == 200
    assert ctx.tested[-1][2] == "s3cret"          # tested with the stored password
    assert ctx.saved[-1].source.password == "s3cret"


async def test_source_test_blank_password_uses_current(client, ctx):
    ctx.cfg = replace(ctx.cfg, source=replace(ctx.cfg.source, password="s3cret"))
    await client.post("/api/library/source/test",
                      json={"url": "https://m.example", "username": "bb"})
    assert ctx.tested[-1][2] == "s3cret"
```

(If that test file's fake ctx does not record `tested`/`saved`, extend the fake: `self.tested.append((url, user, pw))` in `test_source`, `self.saved.append(cfg)` in `save_config`.)

Append to `services/tests/test_accounts_api.py` and remove the skip from `test_accounts_mutation_needs_json_and_same_origin`:

```python
async def test_music_get_merges_health_and_never_returns_password(client):
    r = await client.get("/api/accounts/music", headers=LAN)
    body = await r.json()
    assert body["url"] == "https://m.example" and body["reachable"] is True
    assert "password" not in body and body["last_sync_ts"] == 1.0


async def test_music_put_passes_blank_password_through(client, ctx):
    r = await client.put("/api/accounts/music", headers=LAN,
                         json={"url": "https://m2.example", "username": "bb"})
    assert r.status == 200
    assert ctx.music_calls[-1] == ("save", "https://m2.example", "bb", "")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_api.py services/tests/test_accounts_api.py`
Expected: FAIL (password blanked; 404 on /api/accounts/music).

- [ ] **Step 3: Implement**

`services/boombox_library/api.py` `_source_put`: replace `password=body.get("password", ""),` with
`password=body.get("password") or ctx.cfg.source.password,` and add a comment: `# Blank = keep: the Accounts page never receives the stored password, so an unchanged field arrives empty.`

`_source_test`: replace the password arg with `body.get("password") or ctx.cfg.source.password,`.

`services/boombox-setup.py` in `ServiceContext`, after `music_get`:

```python
    async def library_health(self) -> dict:
        try:
            s = await self._http()
            async with s.get(f"{LIBRARY_BASE}/api/library/health") as r:
                return await self._json_or_none(r) or {}
        except Exception:
            return {}
```

`services/boombox_setup/accounts.py` handlers + routes:

```python
async def _music_get(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    m = await ctx.music_get()
    h = await ctx.library_health()
    return web.json_response({
        "url": m.get("url", ""), "username": m.get("username", ""),
        "configured": bool(m.get("configured")), "reachable": bool(m.get("reachable")),
        "last_sync_ts": h.get("last_sync_ts"), "syncing": bool(h.get("syncing")),
        "prune_deferred": h.get("prune_deferred"),
    })


def _music_fields(b: dict) -> tuple[str, str, str]:
    return (str(b.get("url", "")).strip(), str(b.get("username", "")).strip(),
            str(b.get("password") or ""))


async def _music_test(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    ok, err = await ctx.music_test(*_music_fields(await req.json()))
    return web.json_response({"ok": ok, "error": "" if ok else err})


async def _music_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    url, user, pw = _music_fields(await req.json())
    if not url.startswith(("http://", "https://")) or not user:
        return web.json_response({"ok": False, "error": "URL and username are required"},
                                 status=400)
    ok, err = await ctx.music_save(url, user, pw)
    if not ok:
        return web.json_response(
            {"ok": False, "error": err.replace(pw, "***") if pw else err}, status=400)
    return web.json_response({"ok": True})
```

In `add_routes`: `r.add_get("/api/accounts/music", _music_get)`, `r.add_post("/api/accounts/music/test", _music_test)`, `r.add_put("/api/accounts/music", _music_put)`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_library_api.py services/tests/test_accounts_api.py services/tests/test_setup_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/boombox_library/api.py services/boombox_setup/accounts.py services/boombox-setup.py services/tests/test_library_api.py services/tests/test_accounts_api.py
git commit -m "feat(accounts): music card API; blank library password means keep

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Jellyfin HTTP helpers + video server card API

**Files:**
- Create: `services/boombox_setup/jellyfin_signin.py` (HTTP part)
- Modify: `services/boombox_setup/accounts.py`, `services/boombox-setup.py`
- Test: `services/tests/test_jellyfin_signin.py` (create), `services/tests/test_accounts_api.py` (append)

**Interfaces:**
- Produces in `jellyfin_signin.py`:
  - `class JellyfinError(Exception)`
  - `async def system_info(s: aiohttp.ClientSession, base: str, key: str) -> dict` (GET `/System/Info`, raises `JellyfinError(reason)`)
  - `async def public_info(s, base) -> dict` (GET `/System/Info/Public`: `Id`, `ServerName`)
  - `async def list_users(s, base, key) -> list[dict]` → `[{"id","name","admin"}]`
  - `async def quick_connect_token(s, base, key, user_id, device_id, device_name, version) -> str` (AccessToken)
  - `async def revoke_device(s, base, key, device_id) -> None`
  - `async def device_user(s, base, key, device_id) -> str | None` (LastUserName for device)
  - `def mb_auth(device_id, device_name, version, token="") -> str` (the `Authorization: MediaBrowser ...` header)
- Context gains `jellyfin_env() -> dict[str,str]` (reads `/etc/boombox/jellyfin.env`) and `async http() -> aiohttp.ClientSession`.
- API: `GET /api/accounts/video` → `{"mode","base","key_set","kiosk_device_id","kiosk_user"}`; `POST /api/accounts/video/test {base,api_key?}` → `{"ok","error","server_name"}`; `PUT /api/accounts/video {mode,base?,api_key?}` → `{"ok"}`; `GET /api/accounts/video/users` → `{"users":[...]}`.

- [ ] **Step 1: Failing tests**

```python
# services/tests/test_jellyfin_signin.py
"""jellyfin_signin HTTP helpers against a fake Jellyfin."""
from __future__ import annotations

import pytest
from aiohttp import ClientSession, web
from boombox_setup import jellyfin_signin as jf

KEY = "apikey"


def fake_jellyfin(qc_enabled=True):
    state = {"authorized": set(), "devices": {}, "revoked": []}

    def keyed(req):
        return req.headers.get("X-Emby-Token") == KEY

    async def info(req):
        if not keyed(req):
            return web.Response(status=401)
        return web.json_response({"ServerName": "5CVideo", "Version": "10.10.7"})

    async def pub(req):
        return web.json_response({"Id": "srv1", "ServerName": "5CVideo"})

    async def users(req):
        return web.json_response([{"Id": "u1", "Name": "jwc",
                                   "Policy": {"IsAdministrator": True}}])

    async def initiate(req):
        if not qc_enabled:
            return web.Response(status=401, text="Quick connect is disabled")
        assert 'DeviceId="dev-kiosk"' in req.headers["Authorization"]
        return web.json_response({"Secret": "sec", "Code": "123456"})

    async def authorize(req):
        assert keyed(req) and req.query["code"] == "123456"
        state["authorized"].add(req.query["userId"])
        return web.json_response(True)

    async def auth_qc(req):
        body = await req.json()
        assert body == {"Secret": "sec"} and state["authorized"]
        state["devices"]["dev-kiosk"] = "jwc"
        return web.json_response({"AccessToken": "tok", "User": {"Id": "u1"}})

    async def devices_delete(req):
        state["revoked"].append(req.query["id"])
        return web.Response(status=204)

    async def device_info(req):
        name = state["devices"].get(req.query["id"])
        if not name:
            return web.Response(status=404)
        return web.json_response({"LastUserName": name})

    app = web.Application()
    app.router.add_get("/System/Info", info)
    app.router.add_get("/System/Info/Public", pub)
    app.router.add_get("/Users", users)
    app.router.add_post("/QuickConnect/Initiate", initiate)
    app.router.add_post("/QuickConnect/Authorize", authorize)
    app.router.add_post("/Users/AuthenticateWithQuickConnect", auth_qc)
    app.router.add_delete("/Devices", devices_delete)
    app.router.add_get("/Devices/Info", device_info)
    return app, state


@pytest.fixture
async def server(aiohttp_server):
    app, state = fake_jellyfin()
    srv = await aiohttp_server(app)
    return str(srv.make_url("")).rstrip("/"), state


async def test_system_info_bad_key(server):
    base, _ = server
    async with ClientSession() as s:
        with pytest.raises(jf.JellyfinError, match="API key"):
            await jf.system_info(s, base, "wrong")


async def test_list_users(server):
    base, _ = server
    async with ClientSession() as s:
        assert await jf.list_users(s, base, KEY) == [{"id": "u1", "name": "jwc", "admin": True}]


async def test_quick_connect_token_flow(server):
    base, state = server
    async with ClientSession() as s:
        tok = await jf.quick_connect_token(s, base, KEY, "u1", "dev-kiosk", "MarkII kiosk", "1.0")
        assert tok == "tok"
        assert await jf.device_user(s, base, KEY, "dev-kiosk") == "jwc"
        await jf.revoke_device(s, base, KEY, "dev-kiosk")
    assert state["revoked"] == ["dev-kiosk"]


async def test_quick_connect_disabled_message(aiohttp_server):
    app, _ = fake_jellyfin(qc_enabled=False)
    srv = await aiohttp_server(app)
    async with ClientSession() as s:
        with pytest.raises(jf.JellyfinError, match="Quick Connect"):
            await jf.quick_connect_token(s, str(srv.make_url("")).rstrip("/"), KEY,
                                         "u1", "dev-kiosk", "k", "1")


async def test_unreachable_server_is_jellyfin_error():
    async with ClientSession() as s:
        with pytest.raises(jf.JellyfinError, match="reach"):
            await jf.system_info(s, "http://127.0.0.1:9", KEY)
```

Append to `services/tests/test_accounts_api.py`:

```python
async def test_video_get_redacts_key(client):
    body = await (await client.get("/api/accounts/video", headers=LAN)).json()
    assert body["key_set"] is True and "k" not in str(body.get("api_key", ""))
    assert body["kiosk_device_id"] == "boombox-markii-kiosk"


async def test_video_save_blank_key_keeps_current(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def ok(*a, **k): return {"ServerName": "5CVideo"}
    monkeypatch.setattr(jf, "system_info", ok)
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://v2.example"})
    assert r.status == 200
    sent = ctx.applied[-1]
    assert sent["action"] == "jellyfin" and "api_key" not in sent
    assert ctx.restarted  # consumers restarted


async def test_video_save_refuses_failing_server_unless_forced(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def boom(*a, **k): raise jf.JellyfinError("Couldn't reach the Jellyfin server")
    monkeypatch.setattr(jf, "system_info", boom)
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://down.example"})
    assert r.status == 400 and (await r.json())["can_force"] is True
    assert not ctx.applied
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://down.example", "force": True})
    assert r.status == 200


async def test_video_save_rejects_bad_base(client):
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "ftp://x"})
    assert r.status == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest -q services/tests/test_jellyfin_signin.py services/tests/test_accounts_api.py`
Expected: FAIL (module missing / 404).

- [ ] **Step 3: Implement**

```python
# services/boombox_setup/jellyfin_signin.py
"""Jellyfin helpers for the Accounts page: server checks, user list, and a
server-side Quick Connect sign-in whose token is injected into the kiosk.

The boombox (not the kiosk browser) initiates Quick Connect with a DeviceId
it chooses (<BOOMBOX_ID>-kiosk), approves the code with the API key for the
picked user, and exchanges the secret for that user's AccessToken — no
Jellyfin password is ever typed or stored.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=15)
QC_TIMEOUT = aiohttp.ClientTimeout(total=30)


class JellyfinError(Exception):
    """A user-presentable reason a Jellyfin call failed."""


def mb_auth(device_id: str, device_name: str, version: str, token: str = "") -> str:
    parts = [f'Client="Jellyfin Web"', f'Device="{device_name}"',
             f'DeviceId="{device_id}"', f'Version="{version}"']
    if token:
        parts.append(f'Token="{token}"')
    return "MediaBrowser " + ", ".join(parts)


async def _req(s: aiohttp.ClientSession, method: str, url: str, *,
               timeout: aiohttp.ClientTimeout = TIMEOUT, **kw: Any) -> Any:
    try:
        async with s.request(method, url, timeout=timeout, **kw) as r:
            if r.status == 401:
                raise JellyfinError("Jellyfin rejected the API key")
            if r.status >= 400:
                text = (await r.text())[:200]
                raise JellyfinError(f"Jellyfin answered {r.status}: {text}".strip())
            if r.status == 204 or r.content_length == 0:
                return None
            try:
                return await r.json(content_type=None)
            except Exception as e:
                raise JellyfinError("Jellyfin returned an unexpected page "
                                    "(proxy or login screen?)") from e
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise JellyfinError("Couldn't reach the Jellyfin server") from e


def _key(key: str) -> dict[str, str]:
    return {"X-Emby-Token": key}


async def system_info(s: aiohttp.ClientSession, base: str, key: str) -> dict:
    return await _req(s, "GET", f"{base}/System/Info", headers=_key(key)) or {}


async def public_info(s: aiohttp.ClientSession, base: str) -> dict:
    return await _req(s, "GET", f"{base}/System/Info/Public") or {}


async def list_users(s: aiohttp.ClientSession, base: str, key: str) -> list[dict]:
    raw = await _req(s, "GET", f"{base}/Users", headers=_key(key)) or []
    return [{"id": u["Id"], "name": u["Name"],
             "admin": bool((u.get("Policy") or {}).get("IsAdministrator"))}
            for u in raw if isinstance(u, dict) and u.get("Id")]


async def quick_connect_token(s: aiohttp.ClientSession, base: str, key: str,
                              user_id: str, device_id: str, device_name: str,
                              version: str) -> str:
    dev = {"Authorization": mb_auth(device_id, device_name, version)}
    try:
        init = await _req(s, "POST", f"{base}/QuickConnect/Initiate",
                          headers=dev, timeout=QC_TIMEOUT)
    except JellyfinError as e:
        if "401" in str(e) or "rejected" in str(e):
            raise JellyfinError("Quick Connect is disabled on the Jellyfin server — "
                                "enable it in Dashboard → General") from e
        raise
    await _req(s, "POST", f"{base}/QuickConnect/Authorize",
               params={"code": init["Code"], "userId": user_id},
               headers=_key(key), timeout=QC_TIMEOUT)
    auth = await _req(s, "POST", f"{base}/Users/AuthenticateWithQuickConnect",
                      json={"Secret": init["Secret"]}, headers=dev, timeout=QC_TIMEOUT)
    token = (auth or {}).get("AccessToken")
    if not token:
        raise JellyfinError("Jellyfin did not return a session token")
    return str(token)


async def revoke_device(s: aiohttp.ClientSession, base: str, key: str,
                        device_id: str) -> None:
    await _req(s, "DELETE", f"{base}/Devices", params={"id": device_id},
               headers=_key(key))


async def device_user(s: aiohttp.ClientSession, base: str, key: str,
                      device_id: str) -> str | None:
    try:
        d = await _req(s, "GET", f"{base}/Devices/Info", params={"id": device_id},
                       headers=_key(key))
    except JellyfinError:
        return None
    return (d or {}).get("LastUserName") or None
```

`services/boombox-setup.py` `ServiceContext`:

```python
    def jellyfin_env(self) -> dict[str, str]:
        return _read_env_file(JELLYFIN_ENV)

    async def http(self) -> aiohttp.ClientSession:
        return await self._http()
```

Add to `FakeAccountsContext` (test file) for later tasks: `async def http(self): return self._http_session` with `self._http_session = None` set per-test when a fake Jellyfin is used.

`accounts.py`:

```python
import re

from . import jellyfin_signin as jf

_BASE_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(/[A-Za-z0-9._~%/+-]*)?$")
_VIDEO_UNITS = ["boombox-remote.service", "boombox-kiosk-guard.service",
                "boombox-buttons.service"]


def kiosk_device_id(ctx: Any) -> str:
    return f"{ctx.read_identity()['id']}-kiosk"


def _jf(ctx: Any) -> tuple[str, str]:
    env = ctx.jellyfin_env()
    return (env.get("BOOMBOX_JELLYFIN_BASE") or "http://127.0.0.1:8096",
            env.get("JELLYFIN_API_KEY", ""))


async def _video_get(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    env = ctx.jellyfin_env()
    base, key = _jf(ctx)
    dev = kiosk_device_id(ctx)
    user = None
    if key:
        try:
            user = await jf.device_user(await ctx.http(), base, key, dev)
        except Exception:
            user = None
    return web.json_response({
        "mode": "remote" if env.get("BOOMBOX_JELLYFIN_BASE") else "builtin",
        "base": base, "key_set": bool(key),
        "kiosk_device_id": dev, "kiosk_user": user,
    })


async def _video_test(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await req.json()
    base = str(b.get("base", "")).rstrip("/")
    key = str(b.get("api_key") or "") or _jf(ctx)[1]
    if not _BASE_RE.match(base):
        return web.json_response({"ok": False, "error": "Enter an http(s):// address"})
    try:
        info = await jf.system_info(await ctx.http(), base, key)
    except jf.JellyfinError as e:
        return web.json_response({"ok": False, "error": str(e)})
    return web.json_response({"ok": True, "error": "",
                              "server_name": info.get("ServerName", "")})


async def _video_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await req.json()
    mode = b.get("mode")
    payload: dict[str, Any] = {"action": "jellyfin", "mode": mode}
    if mode == "remote":
        base = str(b.get("base", "")).rstrip("/")
        if not _BASE_RE.match(base):
            return web.json_response({"ok": False, "error": "Enter an http(s):// address"},
                                     status=400)
        payload["base"] = base
        if b.get("api_key"):
            payload["api_key"] = str(b["api_key"])
        # Spec: validate → test → write; never overwrite a working config
        # with one that fails, unless the owner explicitly chose "Save anyway".
        if not b.get("force"):
            try:
                await jf.system_info(await ctx.http(), base,
                                     str(b.get("api_key") or "") or _jf(ctx)[1])
            except jf.JellyfinError as e:
                return web.json_response({"ok": False, "error": str(e),
                                          "can_force": True}, status=400)
    elif mode != "builtin":
        return web.json_response({"ok": False, "error": "unknown mode"}, status=400)
    r = await ctx.apply(payload)
    if not r.get("ok"):
        return web.json_response({"ok": False, "error": r.get("error", "save failed")},
                                 status=400)
    await ctx.restart_units(_VIDEO_UNITS)
    return web.json_response({"ok": True})


async def _video_users(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    base, key = _jf(ctx)
    if not key:
        return web.json_response({"users": [], "error": "Save an API key first"})
    try:
        users = await jf.list_users(await ctx.http(), base, key)
    except jf.JellyfinError as e:
        return web.json_response({"users": [], "error": str(e)})
    return web.json_response({"users": users})
```

Routes: `r.add_get("/api/accounts/video", _video_get)`, `r.add_post("/api/accounts/video/test", _video_test)`, `r.add_put("/api/accounts/video", _video_put)`, `r.add_get("/api/accounts/video/users", _video_users)`.

In the test fixture, `ctx.http()` must return a real session for `_video_get` (device_user swallows errors); set `self._http_session = aiohttp.ClientSession()` lazily in `FakeAccountsContext.http` and close it in the `client` fixture teardown.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q services/tests/test_jellyfin_signin.py services/tests/test_accounts_api.py && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: PASS / clean

- [ ] **Step 5: Commit**

```bash
git add services/boombox_setup/jellyfin_signin.py services/boombox_setup/accounts.py services/boombox-setup.py services/tests/test_jellyfin_signin.py services/tests/test_accounts_api.py
git commit -m "feat(accounts): video server card API + Jellyfin helpers (users, Quick Connect token)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Kiosk Jellyfin sign-in (CDP injection) + sign-out

**Files:**
- Modify: `services/boombox_setup/jellyfin_signin.py` (add CDP part), `services/boombox_setup/accounts.py`
- Test: `services/tests/test_jellyfin_signin.py`, `services/tests/test_accounts_api.py` (append)

**Interfaces:**
- Produces:
  - `def credentials_blob(base: str, server_id: str, server_name: str, user_id: str, token: str, now_ms: int) -> str` (JSON for `localStorage.jellyfin_credentials`)
  - `async def inject_kiosk(cdp_base: str, jf_base: str, device_id: str, creds_json: str | None, return_url: str = "http://localhost/") -> None` — `creds_json=None` clears (sign-out). Raises `JellyfinError("kiosk not reachable ...")`.
  - `POST /api/accounts/video/kiosk-signin {user_id}` → `{"ok":true,"user":name}`; `POST /api/accounts/video/kiosk-signout {}` → `{"ok":true}`.
- Consumes: Task 5 functions; helper `jellyfin` action `device_id` (Task 2).

- [ ] **Step 1: Verify the live jellyfin-web storage format first**

Run on the Mac with the kiosk CDP tunnel (`ssh -f -N -L 9333:127.0.0.1:9222 root@192.168.1.81`) while the kiosk is on `https://video.coblr.io/web/`:

```bash
agent-browser connect 9333 && agent-browser eval 'JSON.stringify({d: localStorage.getItem("_deviceId2"), c: JSON.parse(localStorage.getItem("jellyfin_credentials")||"{}").Servers?.map(s=>Object.keys(s))})'
```

Expected: `_deviceId2` present and `Servers[0]` keys include `ManualAddress`, `Id`, `UserId`, `AccessToken`. If the key names differ, use the observed names in `credentials_blob` below and note it in the commit message.

- [ ] **Step 2: Failing tests**

```python
# append to services/tests/test_jellyfin_signin.py
import json


def test_credentials_blob_shape():
    blob = json.loads(jf.credentials_blob("https://v.example", "srv1", "5CVideo",
                                          "u1", "tok", 1700000000000))
    s = blob["Servers"][0]
    assert s["ManualAddress"] == "https://v.example" and s["Id"] == "srv1"
    assert s["UserId"] == "u1" and s["AccessToken"] == "tok"


async def test_inject_kiosk_drives_cdp(aiohttp_server):
    sent: list[dict] = []

    async def json_list(req):
        port = req.url.port
        return web.json_response([{"type": "page", "url": "http://localhost/",
                                   "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/1"}])

    async def ws(req):
        w = web.WebSocketResponse()
        await w.prepare(req)
        async for msg in w:
            m = json.loads(msg.data)
            sent.append(m)
            result = {"result": {"value": "complete"}} if m["method"] == "Runtime.evaluate" else {}
            await w.send_str(json.dumps({"id": m["id"], "result": result.get("result", {})}))
        return w

    app = web.Application()
    app.router.add_get("/json", json_list)
    app.router.add_get("/devtools/page/1", ws)
    srv = await aiohttp_server(app)
    await jf.inject_kiosk(str(srv.make_url("")).rstrip("/"), "https://v.example",
                          "dev-kiosk", '{"Servers":[]}')
    methods = [m["method"] for m in sent]
    assert methods[0] == "Page.navigate" and sent[0]["params"]["url"] == "https://v.example/web/"
    js = " ".join(m["params"].get("expression", "") for m in sent if m["method"] == "Runtime.evaluate")
    assert "_deviceId2" in js and "jellyfin_credentials" in js and "dev-kiosk" in js
    assert sent[-1]["method"] == "Page.navigate" and sent[-1]["params"]["url"] == "http://localhost/"


async def test_inject_kiosk_unreachable():
    with pytest.raises(jf.JellyfinError, match="kiosk"):
        await jf.inject_kiosk("http://127.0.0.1:9", "https://v.example", "d", "{}")
```

```python
# append to services/tests/test_accounts_api.py
async def test_signin_revokes_device_when_kiosk_unreachable(client, ctx, monkeypatch):
    from boombox_setup import accounts, jellyfin_signin as jf
    revoked = []

    async def fake_token(*a, **k): return "tok"
    async def fake_pub(*a, **k): return {"Id": "srv1", "ServerName": "5CVideo"}
    async def fake_users(*a, **k): return [{"id": "u1", "name": "jwc", "admin": True}]
    async def fake_inject(*a, **k): raise jf.JellyfinError("kiosk not reachable — is the screen on?")
    async def fake_revoke(s, base, key, dev): revoked.append(dev)

    monkeypatch.setattr(jf, "quick_connect_token", fake_token)
    monkeypatch.setattr(jf, "public_info", fake_pub)
    monkeypatch.setattr(jf, "list_users", fake_users)
    monkeypatch.setattr(jf, "inject_kiosk", fake_inject)
    monkeypatch.setattr(jf, "revoke_device", fake_revoke)
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "u1"})
    body = await r.json()
    assert r.status == 502 and "kiosk" in body["error"]
    assert revoked == ["boombox-markii-kiosk"]
    assert not any(p.get("device_id") for p in ctx.applied)


async def test_signin_success_pins_device(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def fake_token(*a, **k): return "tok"
    async def fake_pub(*a, **k): return {"Id": "srv1", "ServerName": "5CVideo"}
    async def fake_users(*a, **k): return [{"id": "u1", "name": "jwc", "admin": True}]
    async def fake_inject(*a, **k): return None
    monkeypatch.setattr(jf, "quick_connect_token", fake_token)
    monkeypatch.setattr(jf, "public_info", fake_pub)
    monkeypatch.setattr(jf, "list_users", fake_users)
    monkeypatch.setattr(jf, "inject_kiosk", fake_inject)
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "u1"})
    assert r.status == 200 and (await r.json())["user"] == "jwc"
    pin = [p for p in ctx.applied if p["action"] == "jellyfin"][-1]
    assert pin["device_id"] == "boombox-markii-kiosk" and pin["mode"] == "remote"


async def test_signin_unknown_user_400(client, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def fake_users(*a, **k): return []
    monkeypatch.setattr(jf, "list_users", fake_users)
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "zz"})
    assert r.status == 400
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest -q services/tests/test_jellyfin_signin.py services/tests/test_accounts_api.py`
Expected: FAIL (missing functions / 404).

- [ ] **Step 4: Implement**

Append to `jellyfin_signin.py`:

```python
import json

import websockets


def credentials_blob(base: str, server_id: str, server_name: str, user_id: str,
                     token: str, now_ms: int) -> str:
    return json.dumps({"Servers": [{
        "ManualAddress": base, "manualAddressOnly": True, "Id": server_id,
        "Name": server_name, "UserId": user_id, "AccessToken": token,
        "DateLastAccessed": now_ms, "LastConnectionMode": 2,
    }]})


async def inject_kiosk(cdp_base: str, jf_base: str, device_id: str,
                       creds_json: str | None,
                       return_url: str = "http://localhost/") -> None:
    """Point the kiosk tab at Jellyfin, write (or clear) its stored session and
    device id, then send it home. Needs the kiosk's CDP port (127.0.0.1:9222)."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.get(f"{cdp_base}/json") as r:
                pages = await r.json(content_type=None)
        page = next(p for p in pages if p.get("type") == "page"
                    and p.get("webSocketDebuggerUrl"))
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, StopIteration,
            ValueError) as e:
        raise JellyfinError("kiosk not reachable — is the screen on?") from e

    if creds_json is None:
        js = ("localStorage.removeItem('jellyfin_credentials');"
              "localStorage.removeItem('_deviceId2');'ok'")
    else:
        js = (f"localStorage.setItem('_deviceId2', {json.dumps(device_id)});"
              f"localStorage.setItem('jellyfin_credentials', {json.dumps(creds_json)});'ok'")
    msg_id = 0

    async def call(ws: Any, method: str, params: dict) -> dict:
        nonlocal msg_id
        msg_id += 1
        await ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == msg_id:
                return m.get("result") or {}

    try:
        async with websockets.connect(page["webSocketDebuggerUrl"],
                                      max_size=2**22, open_timeout=5) as ws:
            await call(ws, "Page.navigate", {"url": f"{jf_base}/web/"})
            for _ in range(30):  # wait for the Jellyfin origin to load
                r = await call(ws, "Runtime.evaluate",
                               {"expression": "document.readyState", "returnByValue": True})
                if (r.get("result") or {}).get("value") == "complete":
                    break
                await asyncio.sleep(0.5)
            await call(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True})
            await call(ws, "Page.navigate", {"url": return_url})
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
        raise JellyfinError("kiosk not reachable — is the screen on?") from e
```

Note: the fake CDP server in the test replies `{"id", "result": {"value": "complete"}}` for `Runtime.evaluate`; production CDP nests the value as `result.result.value` — handle both by checking `r.get("value") or (r.get("result") or {}).get("value")`.

In `accounts.py`:

```python
import os
import time

CDP_BASE = os.environ.get("BOOMBOX_KIOSK_CDP", "http://127.0.0.1:9222")


async def _kiosk_signin(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    user_id = str((await req.json()).get("user_id", ""))
    base, key = _jf(ctx)
    if not key:
        return web.json_response({"ok": False, "error": "Save an API key first"}, status=400)
    s = await ctx.http()
    try:
        users = {u["id"]: u for u in await jf.list_users(s, base, key)}
    except jf.JellyfinError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    if user_id not in users:
        return web.json_response({"ok": False, "error": "unknown Jellyfin user"}, status=400)
    ident = ctx.read_identity()
    dev = kiosk_device_id(ctx)
    try:
        pub = await jf.public_info(s, base)
        token = await jf.quick_connect_token(
            s, base, key, user_id, dev, f"{ident['name']} kiosk", "boombox")
    except jf.JellyfinError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    creds = jf.credentials_blob(base, pub.get("Id", ""), pub.get("ServerName", ""),
                                user_id, token, int(time.time() * 1000))
    try:
        await jf.inject_kiosk(CDP_BASE, base, dev, creds)
    except jf.JellyfinError as e:
        try:
            await jf.revoke_device(s, base, key, dev)
        except jf.JellyfinError:
            log.warning("could not revoke kiosk device after failed injection")
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    env = ctx.jellyfin_env()
    mode = "remote" if env.get("BOOMBOX_JELLYFIN_BASE") else "builtin"
    pin: dict[str, Any] = {"action": "jellyfin", "mode": mode, "device_id": dev}
    if mode == "remote":
        pin["base"] = base
    r = await ctx.apply(pin)
    if not r.get("ok"):
        return web.json_response({"ok": False, "error": r.get("error", "")}, status=400)
    await ctx.restart_units(["boombox-remote.service"])
    return web.json_response({"ok": True, "user": users[user_id]["name"]})


async def _kiosk_signout(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    base, key = _jf(ctx)
    dev = kiosk_device_id(ctx)
    errors = []
    if key:
        try:
            await jf.revoke_device(await ctx.http(), base, key, dev)
        except jf.JellyfinError as e:
            errors.append(str(e))
    try:
        await jf.inject_kiosk(CDP_BASE, base, dev, None)
    except jf.JellyfinError as e:
        errors.append(str(e))
    return web.json_response({"ok": not errors, "error": "; ".join(errors)})
```

Routes: `r.add_post("/api/accounts/video/kiosk-signin", _kiosk_signin)`, `r.add_post("/api/accounts/video/kiosk-signout", _kiosk_signout)`.

- [ ] **Step 5: Run tests + lint**

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: PASS / clean

- [ ] **Step 6: Commit**

```bash
git add services/boombox_setup/ services/tests/test_jellyfin_signin.py services/tests/test_accounts_api.py
git commit -m "feat(accounts): sign the kiosk into Jellyfin via server-side Quick Connect

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Streaming + web-login card APIs

**Files:**
- Modify: `services/boombox_setup/accounts.py`
- Test: `services/tests/test_accounts_api.py` (append)

**Interfaces:**
- Produces: `GET /api/accounts/streaming` → helper `streaming-status` result minus `ok`; `PUT /api/accounts/streaming {airplay_name?, airplay_password?, airplay_password_clear?, spotify_name?}` → `{"ok","changed"}` / 400; `PUT /api/accounts/web-login {current_password, new_password}` → `{"ok","updated"}` / 400.

- [ ] **Step 1: Failing tests**

```python
async def test_streaming_get_passthrough(client, ctx):
    ctx.apply_results["streaming-status"] = {
        "ok": True, "airplay": {"installed": True, "active": True, "name": "MarkII",
                                "password_set": False},
        "spotify": {"installed": False, "active": False, "name": ""}}
    body = await (await client.get("/api/accounts/streaming", headers=LAN)).json()
    assert body["airplay"]["name"] == "MarkII" and "ok" not in body


async def test_streaming_put_only_forwards_known_fields(client, ctx):
    r = await client.put("/api/accounts/streaming", headers=LAN,
                         json={"airplay_name": "Den", "evil": "x"})
    assert r.status == 200
    assert ctx.applied[-1] == {"action": "streaming", "airplay_name": "Den"}


async def test_streaming_put_helper_error_is_400(client, ctx):
    ctx.apply_results["streaming"] = {"ok": False, "error": "Spotify Connect is not installed"}
    r = await client.put("/api/accounts/streaming", headers=LAN, json={"spotify_name": "Den"})
    assert r.status == 400 and "not installed" in (await r.json())["error"]


async def test_web_login_forwards_and_never_echoes(client, ctx):
    ctx.apply_results["web-password"] = {"ok": False, "error": "current password is incorrect"}
    r = await client.put("/api/accounts/web-login", headers=LAN,
                         json={"current_password": "old", "new_password": "correct horse battery"})
    body = await r.json()
    assert r.status == 400 and "correct horse" not in str(body)
    assert ctx.applied[-1]["action"] == "web-password"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest -q services/tests/test_accounts_api.py`
Expected: FAIL (404).

- [ ] **Step 3: Implement**

```python
_STREAMING_FIELDS = ("airplay_name", "airplay_password", "airplay_password_clear",
                     "spotify_name")


async def _streaming_get(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    r = await ctx.apply({"action": "streaming-status"})
    if not r.get("ok"):
        return web.json_response({"error": r.get("error", "status unavailable")}, status=502)
    return web.json_response({k: v for k, v in r.items() if k != "ok"})


async def _streaming_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await req.json()
    payload = {"action": "streaming", **{k: b[k] for k in _STREAMING_FIELDS if k in b}}
    r = await ctx.apply(payload)
    if not r.get("ok"):
        return web.json_response({"ok": False, "error": r.get("error", "save failed")},
                                 status=400)
    return web.json_response({"ok": True, "changed": r.get("changed", [])})


async def _web_login_put(req: web.Request) -> web.Response:
    ctx: Any = req.app["ctx"]
    b = await req.json()
    r = await ctx.apply({"action": "web-password",
                         "current_password": str(b.get("current_password", "")),
                         "new_password": str(b.get("new_password", ""))})
    if not r.get("ok"):
        return web.json_response({"ok": False, "error": r.get("error", "not changed")},
                                 status=400)
    return web.json_response({"ok": True, "updated": r.get("updated", [])})
```

Routes: `r.add_get("/api/accounts/streaming", _streaming_get)`, `r.add_put("/api/accounts/streaming", _streaming_put)`, `r.add_put("/api/accounts/web-login", _web_login_put)`.

- [ ] **Step 4: Run tests + lint**

Run: `.venv/bin/python -m pytest -q services/tests && ~/.local/bin/ruff check services && ~/.local/bin/mypy`
Expected: PASS / clean

- [ ] **Step 5: Commit**

```bash
git add services/boombox_setup/accounts.py services/tests/test_accounts_api.py
git commit -m "feat(accounts): streaming receivers and web-login card APIs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: nginx wiring

**Files:**
- Modify: `install/config/nginx-boombox-common.conf` (after the `/setup/` block ~line 122)
- Test: `services/tests/test_nginx_accounts.py` (create — static checks on the snippet)

- [ ] **Step 1: Failing test**

```python
# services/tests/test_nginx_accounts.py
from pathlib import Path

CONF = (Path(__file__).resolve().parents[2] / "install" / "config"
        / "nginx-boombox-common.conf").read_text()


def _block(prefix: str) -> str:
    start = CONF.index(prefix)
    return CONF[start:CONF.index("}", start)]


def test_api_accounts_keeps_basic_auth_and_forwards_identity():
    b = _block("location /api/accounts/")
    assert "auth_basic off" not in b
    assert "proxy_set_header X-Boombox-User $remote_user;" in b
    assert "proxy_set_header X-Real-IP $remote_addr;" in b
    assert "proxy_set_header X-Boombox-Host $http_host;" in b
    assert "127.0.0.1:6689/api/accounts/" in b


def test_accounts_page_served_from_setup_build():
    b = _block("location ^~ /accounts/")
    assert "auth_basic off" not in b
    assert "setup-ui/dist/accounts.html" in b
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest -q services/tests/test_nginx_accounts.py`
Expected: FAIL (`ValueError: substring not found`)

- [ ] **Step 3: Add the blocks**

```nginx
# LAN Accounts page API (boombox-setup). Unlike /api/setup/ this KEEPS the
# LAN Basic auth: the authenticated user is forwarded so the service can
# require it — the loopback kiosk server has no auth, so $remote_user is
# empty there and the service refuses (a page in the kiosk can never change
# accounts). $http_host (with port) lets the service same-origin-check writes.
location /api/accounts/ {
    proxy_pass http://127.0.0.1:6689/api/accounts/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Boombox-User $remote_user;
    proxy_set_header X-Boombox-Host $http_host;
    proxy_read_timeout 60s;
}

# The Accounts page: accounts.html from the setup-ui build (its assets load
# from /setup/assets/, served by the block above). Basic auth stays on.
location = /accounts {
    return 301 /accounts/;
}

location ^~ /accounts/ {
    alias /opt/boombox/current/setup-ui/dist/accounts.html;
    default_type text/html;
    add_header Cache-Control "no-cache" always;
}
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest -q services/tests/test_nginx_accounts.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add install/config/nginx-boombox-common.conf services/tests/test_nginx_accounts.py
git commit -m "feat(nginx): /accounts/ page and /api/accounts/ behind LAN basic auth

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Shared forms + wizard refactor

**Files:**
- Create: `setup-ui/src/shared/MusicForm.tsx`, `setup-ui/src/shared/VideoServerForm.tsx`, `setup-ui/src/shared/forms.test.tsx`
- Modify: `setup-ui/src/steps/Music.tsx`, `setup-ui/src/steps/Video.tsx`

**Interfaces:**
- Produces:
  - `MusicForm(props: { initial: {url: string; username: string}; passwordSet: boolean; onTest(v: MusicValues): Promise<{ok: boolean; error?: string}>; onSave(v: MusicValues): Promise<{ok: boolean; error?: string}>; saveLabel?: string; secondary?: ReactNode })` with `type MusicValues = {url: string; username: string; password: string}` (password `""` = keep).
  - `VideoServerForm(props: { initial: {mode: "builtin"|"remote"; base: string}; keySet: boolean; onTest?(v: VideoValues): Promise<{ok: boolean; error?: string; server_name?: string}>; onSave(v: VideoValues): Promise<{ok: boolean; error?: string}>; saveLabel?: string; secondary?: ReactNode })` with `type VideoValues = {mode: "builtin"|"remote"; base: string; api_key: string}` (`""` = keep).

- [ ] **Step 1: Failing test**

```tsx
// setup-ui/src/shared/forms.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MusicForm } from "./MusicForm";
import { VideoServerForm } from "./VideoServerForm";

describe("MusicForm", () => {
  it("shows 'saved' placeholder and sends blank password to keep it", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    render(<MusicForm initial={{ url: "https://m", username: "bb" }} passwordSet
      onTest={vi.fn()} onSave={onSave} />);
    expect(screen.getByPlaceholderText(/saved — leave blank to keep/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(
      { url: "https://m", username: "bb", password: "" }));
  });

  it("renders a test failure", async () => {
    const onTest = vi.fn().mockResolvedValue({ ok: false, error: "401 bad creds" });
    render(<MusicForm initial={{ url: "https://m", username: "bb" }} passwordSet={false}
      onTest={onTest} onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /test/i }));
    expect(await screen.findByText(/401 bad creds/)).toBeTruthy();
  });
});

describe("VideoServerForm", () => {
  it("requires an http(s) base for remote mode", () => {
    render(<VideoServerForm initial={{ mode: "remote", base: "ftp://x" }} keySet
      onSave={vi.fn()} />);
    expect((screen.getByRole("button", { name: /save/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("sends blank api_key to keep the stored key", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    render(<VideoServerForm initial={{ mode: "remote", base: "https://v" }} keySet
      onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(
      { mode: "remote", base: "https://v", api_key: "" }));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd setup-ui && npx vitest run src/shared`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement the forms**

Move the field/test/save state and JSX from `steps/Music.tsx` into `shared/MusicForm.tsx`, parameterised by the props above:

```tsx
// setup-ui/src/shared/MusicForm.tsx
import { useState, type ReactNode } from "react";
import { PrimaryButton, SecondaryButton, Field, ErrorText, inputStyle } from "../components/ui";

export type MusicValues = { url: string; username: string; password: string };
type Result = { ok: boolean; error?: string };
type TestState = { kind: "idle" } | { kind: "testing" } | { kind: "ok" } | { kind: "error"; message: string };

export function MusicForm({ initial, passwordSet, onTest, onSave, saveLabel = "Save", secondary }: {
  initial: { url: string; username: string };
  passwordSet: boolean;
  onTest: (v: MusicValues) => Promise<Result>;
  onSave: (v: MusicValues) => Promise<Result>;
  saveLabel?: string;
  secondary?: ReactNode;
}) {
  const [url, setUrl] = useState(initial.url);
  const [username, setUsername] = useState(initial.username);
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const values = (): MusicValues => ({ url: url.trim(), username: username.trim(), password });
  const canSubmit = /^https?:\/\//.test(url.trim()) && username.trim() !== ""
    && (passwordSet || password !== "");

  const runTest = async () => {
    setTest({ kind: "testing" });
    try {
      const r = await onTest(values());
      setTest(r.ok ? { kind: "ok" } : { kind: "error", message: r.error || "Connection failed." });
    } catch { setTest({ kind: "error", message: "Couldn't reach the Boombox." }); }
  };
  const save = async () => {
    setError(null); setBusy(true);
    try {
      const r = await onSave(values());
      if (!r.ok) setError(r.error || "Couldn't save.");
    } catch { setError("Couldn't reach the Boombox."); }
    setBusy(false);
  };

  return (
    <div>
      <Field label="Server address">
        <input style={inputStyle} value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://music.example.com" autoCapitalize="off" autoCorrect="off" />
      </Field>
      <Field label="Username">
        <input style={inputStyle} value={username} onChange={(e) => setUsername(e.target.value)}
          autoCapitalize="off" autoCorrect="off" />
      </Field>
      <Field label="Password">
        <input style={inputStyle} type="password" value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={passwordSet ? "saved — leave blank to keep" : ""} />
      </Field>
      {test.kind === "ok" && <div style={{ color: "var(--ok, #4ade80)" }}>Connected ✓</div>}
      {test.kind === "error" && <ErrorText>{test.message}</ErrorText>}
      {error && <ErrorText>{error}</ErrorText>}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <SecondaryButton onClick={runTest} disabled={!canSubmit || test.kind === "testing"}>
          {test.kind === "testing" ? "Testing…" : "Test"}
        </SecondaryButton>
        <PrimaryButton onClick={save} disabled={!canSubmit || busy}>
          {busy ? "Saving…" : saveLabel}
        </PrimaryButton>
        {secondary}
      </div>
    </div>
  );
}
```

`shared/VideoServerForm.tsx` follows the same pattern: two `Card`s (built-in / remote, copied from `steps/Video.tsx`), base + API-key inputs when remote (API key placeholder `saved — leave blank to keep` when `keySet`), optional Test button (only when `onTest` given, showing `Connected to <server_name> ✓`), Save disabled when `mode === "remote" && !/^https?:\/\//.test(base.trim())`, and `onSave({mode, base: base.trim(), api_key: apiKey.trim()})`.

Check `components/ui.tsx` for the exact `PrimaryButton`/`SecondaryButton` prop names (`onClick`, `disabled`, `children`) and adapt if they differ.

Refactor `steps/Music.tsx` to render `<MusicForm initial={status.music} passwordSet={status.music.configured} onTest={(v) => api.post("music/test", v)} onSave={async (v) => { const r = await api.put<OkResult>("music", v); if (r.ok) { update({...}); next(); } return r; }} saveLabel="Save & continue" secondary={<SecondaryButton onClick={back}>Back</SecondaryButton>} />` inside its existing `StepBody`, keeping whatever `update(...)` summary call and skip behaviour the step has today. Do the same for `steps/Video.tsx` with `VideoServerForm` (`onSave` → `api.put("video", mode === "remote" ? {mode, base, api_key: api_key || undefined} : {mode})`).

- [ ] **Step 4: Run all setup-ui checks**

Run: `cd setup-ui && npx tsc -b && npx vitest run && npm run build`
Expected: all pass (existing wizard tests unchanged and green).

- [ ] **Step 5: Commit**

```bash
git add setup-ui/src/shared setup-ui/src/steps/Music.tsx setup-ui/src/steps/Video.tsx
git commit -m "refactor(setup-ui): shared Music/Video server forms for wizard and Accounts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Accounts page UI

**Files:**
- Create: `setup-ui/accounts.html`, `setup-ui/src/accounts/main.tsx`, `api.ts`, `types.ts`, `AccountsApp.tsx`, `StatusPill.tsx`, `MusicCard.tsx`, `VideoCard.tsx`, `StreamingCard.tsx`, `WebLoginCard.tsx`, `accounts.test.tsx`
- Modify: `setup-ui/vite.config.ts`

**Interfaces:**
- Consumes: API from Tasks 3–7; `MusicForm`, `VideoServerForm` (Task 9).
- Produces: `accountsApi = { get<T>(path), post<T>(path, body), put<T>(path, body) }` — same-origin `/api/accounts/<path>`, `Content-Type: application/json` on writes, `credentials: "same-origin"`; non-2xx with JSON body resolves to that body (so cards can show `error`), network failure rejects.

- [ ] **Step 1: Failing tests**

```tsx
// setup-ui/src/accounts/accounts.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AccountsApp } from "./AccountsApp";

const R: Record<string, unknown> = {
  "GET /api/accounts/summary": {
    music: { state: "ok", detail: "" }, video: { state: "ok", detail: "" },
    streaming: { state: "ok", detail: "airplay" }, web: { state: "ok", detail: "" } },
  "GET /api/accounts/music": { url: "https://m", username: "bb", configured: true,
    reachable: true, last_sync_ts: 1790000000, syncing: false, prune_deferred: null },
  "GET /api/accounts/video": { mode: "remote", base: "https://v", key_set: true,
    kiosk_device_id: "boombox-markii-kiosk", kiosk_user: null },
  "GET /api/accounts/video/users": { users: [{ id: "u1", name: "jwc", admin: true }] },
  "GET /api/accounts/streaming": {
    airplay: { installed: true, active: true, name: "MarkII", password_set: false },
    spotify: { installed: false, active: false, name: "" } },
  "POST /api/accounts/video/kiosk-signin": { ok: true, user: "jwc" },
  "PUT /api/accounts/web-login": { ok: false, error: "current password is incorrect" },
};

let calls: { method: string; url: string; body?: unknown; headers?: Record<string, string> }[];

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined,
                 headers: init?.headers as Record<string, string> });
    const body = R[`${method} ${url}`] ?? { ok: true };
    const ok = method === "GET" || (body as { ok?: boolean }).ok !== false;
    return Promise.resolve({ ok, status: ok ? 200 : 400,
      json: async () => body, text: async () => JSON.stringify(body) });
  }));
});

describe("AccountsApp", () => {
  it("renders the four cards with status", async () => {
    render(<AccountsApp />);
    expect(await screen.findByText("Music server")).toBeTruthy();
    expect(screen.getByText("Video server")).toBeTruthy();
    expect(screen.getByText("Streaming receivers")).toBeTruthy();
    expect(screen.getByText("Boombox web login")).toBeTruthy();
  });

  it("never renders stored secrets", async () => {
    render(<AccountsApp />);
    await screen.findByText("Music server");
    expect(document.body.innerHTML).not.toMatch(/apikey|s3cret/);
  });

  it("signs the kiosk in as the picked Jellyfin user", async () => {
    render(<AccountsApp />);
    fireEvent.click(await screen.findByRole("button", { name: /sign kiosk in as jwc/i }));
    await waitFor(() => expect(calls.some(c => c.url === "/api/accounts/video/kiosk-signin"
      && (c.body as { user_id: string }).user_id === "u1")).toBe(true));
    expect(await screen.findByText(/signed in as jwc/i)).toBeTruthy();
  });

  it("shows Spotify as not installed", async () => {
    render(<AccountsApp />);
    expect(await screen.findByText(/spotify connect.*not installed/i)).toBeTruthy();
  });

  it("sends JSON content type on writes and shows web-login errors", async () => {
    render(<AccountsApp />);
    await screen.findByText("Boombox web login");
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "correct horse battery" } });
    fireEvent.change(screen.getByLabelText(/repeat new password/i), { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: /change password/i }));
    expect(await screen.findByText(/current password is incorrect/)).toBeTruthy();
    const put = calls.find(c => c.method === "PUT")!;
    expect(put.headers?.["Content-Type"]).toBe("application/json");
  });

  it("blocks mismatched or short new passwords client-side", async () => {
    render(<AccountsApp />);
    await screen.findByText("Boombox web login");
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "short" } });
    expect((screen.getByRole("button", { name: /change password/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd setup-ui && npx vitest run src/accounts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

`setup-ui/vite.config.ts` — add multi-page input (keep `base: "/setup/"` so assets live under `/setup/assets/`):

```ts
import { resolve } from "node:path";
// ...
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      input: {
        setup: resolve(__dirname, "index.html"),
        accounts: resolve(__dirname, "accounts.html"),
      },
    },
  },
```

`setup-ui/accounts.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#07060c" />
    <title>Boombox Accounts</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/accounts/main.tsx"></script>
  </body>
</html>
```

`src/accounts/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import { AccountsApp } from "./AccountsApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode><AccountsApp /></StrictMode>,
);
```

`src/accounts/api.ts`:

```ts
const BASE = "/api/accounts/";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  if (method !== "GET") {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body ?? {});
  }
  const r = await fetch(BASE + path, init);
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

`src/accounts/types.ts`:

```ts
export type CardState = "ok" | "problem" | "unset" | "absent";
export interface CardStatus { state: CardState; detail: string }
export interface Summary { music: CardStatus; video: CardStatus; streaming: CardStatus; web: CardStatus }
export interface MusicInfo { url: string; username: string; configured: boolean; reachable: boolean;
  last_sync_ts: number | null; syncing: boolean; prune_deferred: unknown }
export interface VideoInfo { mode: "builtin" | "remote"; base: string; key_set: boolean;
  kiosk_device_id: string; kiosk_user: string | null }
export interface JfUser { id: string; name: string; admin: boolean }
export interface Receiver { installed: boolean; active: boolean; name: string; password_set?: boolean }
export interface StreamingInfo { airplay: Receiver; spotify: Receiver }
export interface OkResult { ok: boolean; error?: string }
```

`src/accounts/StatusPill.tsx`:

```tsx
import type { CardState } from "./types";

const LABEL: Record<CardState, string> = { ok: "Connected", problem: "Problem",
  unset: "Not set up", absent: "Not installed" };
const COLOR: Record<CardState, string> = { ok: "#4ade80", problem: "#f87171",
  unset: "#fbbf24", absent: "#94a3b8" };

export function StatusPill({ state, detail }: { state: CardState; detail?: string }) {
  return (
    <span style={{ fontSize: 12, fontWeight: 700, color: COLOR[state],
      border: `1px solid ${COLOR[state]}`, borderRadius: 999, padding: "2px 10px" }}>
      {LABEL[state]}{state === "problem" && detail ? `: ${detail}` : ""}
    </span>
  );
}
```

`src/accounts/AccountsApp.tsx` — loads `summary` once, renders a `Section` per card (title `h2`, `StatusPill`, children) inside the existing `Shell`; exports `AccountsApp`:

```tsx
import { useEffect, useState, type ReactNode } from "react";
import { Shell } from "../components/ui";
import { accountsApi } from "./api";
import type { Summary, CardStatus } from "./types";
import { StatusPill } from "./StatusPill";
import { MusicCard } from "./MusicCard";
import { VideoCard } from "./VideoCard";
import { StreamingCard } from "./StreamingCard";
import { WebLoginCard } from "./WebLoginCard";

function Section({ title, status, children }: { title: string; status?: CardStatus; children: ReactNode }) {
  return (
    <section style={{ border: "1px solid var(--line, #2a2a33)", borderRadius: 14,
      padding: 16, margin: "12px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>{title}</h2>
        {status && <StatusPill state={status.state} detail={status.detail} />}
      </div>
      {children}
    </section>
  );
}

export function AccountsApp() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => accountsApi.get<Summary>("summary").then(setSummary)
    .catch(() => setError("Couldn't reach the Boombox."));
  useEffect(() => { void refresh(); }, []);
  return (
    <Shell>
      <h1 style={{ fontSize: 24 }}>Accounts</h1>
      {error && <p role="alert">{error}</p>}
      <Section title="Music server" status={summary?.music}><MusicCard onChanged={refresh} /></Section>
      <Section title="Video server" status={summary?.video}><VideoCard onChanged={refresh} /></Section>
      <Section title="Streaming receivers" status={summary?.streaming}><StreamingCard onChanged={refresh} /></Section>
      <Section title="Boombox web login" status={summary?.web}><WebLoginCard /></Section>
    </Shell>
  );
}
```

`MusicCard.tsx`:

```tsx
import { useEffect, useState } from "react";
import { accountsApi } from "./api";
import type { MusicInfo, OkResult } from "./types";
import { MusicForm, type MusicValues } from "../shared/MusicForm";

export function MusicCard({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<MusicInfo | null>(null);
  useEffect(() => { accountsApi.get<MusicInfo>("music").then(setInfo).catch(() => {}); }, []);
  if (!info) return <p>Loading…</p>;
  return (
    <>
      {info.last_sync_ts && <p style={{ fontSize: 13 }}>
        Last sync {new Date(info.last_sync_ts * 1000).toLocaleString()}{info.syncing ? " (syncing…)" : ""}</p>}
      {info.prune_deferred != null && <p style={{ fontSize: 13, color: "#fbbf24" }}>
        The server listed far fewer albums than before — removal is on hold until it's confirmed.</p>}
      <MusicForm initial={info} passwordSet={info.configured}
        onTest={(v: MusicValues) => accountsApi.post<OkResult>("music/test", v)}
        onSave={async (v: MusicValues) => { const r = await accountsApi.put<OkResult>("music", v);
          if (r.ok) onChanged(); return r; }} />
      <p style={{ fontSize: 12, opacity: 0.7 }}>Tip: use a dedicated, non-admin Navidrome user for this boombox.</p>
    </>
  );
}
```

`VideoCard.tsx` — `VideoServerForm` (onTest → `video/test`, onSave → `video` then reload info + `onChanged`; when the save response has `can_force: true`, show its error plus a **Save anyway** button that re-sends with `force: true`); below it, when `info.key_set`, a "Kiosk sign-in" block: shows `Kiosk signed in as <kiosk_user>` + **Sign out** (`POST video/kiosk-signout`) when signed in; otherwise loads `video/users` and renders one button per user labelled `Sign kiosk in as <name>` calling `POST video/kiosk-signin {user_id}`; on success sets `kiosk_user` to the returned `user` (text `Kiosk signed in as <user>`); on failure shows the `error` string; shows `users` endpoint `error` if present.

```tsx
import { useEffect, useState } from "react";
import { accountsApi } from "./api";
import type { VideoInfo, JfUser, OkResult } from "./types";
import { VideoServerForm, type VideoValues } from "../shared/VideoServerForm";
import { ErrorText, SecondaryButton } from "../components/ui";

export function VideoCard({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [users, setUsers] = useState<JfUser[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => accountsApi.get<VideoInfo>("video").then((v) => {
    setInfo(v);
    if (v.key_set) accountsApi.get<{ users: JfUser[]; error?: string }>("video/users")
      .then((u) => { setUsers(u.users); if (u.error) setMsg(u.error); }).catch(() => {});
  }).catch(() => setMsg("Couldn't reach the Boombox."));
  useEffect(() => { void load(); }, []);
  if (!info) return <p>Loading…</p>;

  const signIn = async (u: JfUser) => {
    setBusy(true); setMsg(null);
    const r = await accountsApi.post<OkResult & { user?: string }>("video/kiosk-signin", { user_id: u.id });
    setBusy(false);
    if (r.ok) { setInfo({ ...info, kiosk_user: r.user ?? u.name }); onChanged(); }
    else setMsg(r.error ?? "Sign-in failed.");
  };
  const signOut = async () => {
    setBusy(true);
    const r = await accountsApi.post<OkResult>("video/kiosk-signout", {});
    setBusy(false);
    if (r.ok) setInfo({ ...info, kiosk_user: null }); else setMsg(r.error ?? "Sign-out failed.");
  };

  return (
    <>
      <VideoServerForm initial={info} keySet={info.key_set}
        onTest={(v: VideoValues) => accountsApi.post("video/test", v)}
        onSave={async (v: VideoValues) => { const r = await accountsApi.put<OkResult>("video", v);
          if (r.ok) { onChanged(); void load(); } return r; }} />
      {info.key_set && (
        <div style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 15 }}>Kiosk sign-in</h3>
          {info.kiosk_user ? (
            <p>Kiosk signed in as {info.kiosk_user}{" "}
              <SecondaryButton onClick={signOut} disabled={busy}>Sign out</SecondaryButton></p>
          ) : users.map((u) => (
            <SecondaryButton key={u.id} onClick={() => signIn(u)} disabled={busy}>
              Sign kiosk in as {u.name}
            </SecondaryButton>
          ))}
          {msg && <ErrorText>{msg}</ErrorText>}
        </div>
      )}
    </>
  );
}
```

`StreamingCard.tsx` — loads `streaming`; AirPlay row: name input (initial `airplay.name`), password input (placeholder `saved — leave blank to keep` when `password_set`), "Remove password" checkbox when set, Save → `PUT streaming` with only changed fields; when `!airplay.installed` render `AirPlay — not installed`. Spotify row: name input + Save when installed, else text `Spotify Connect — not installed`. Errors from the response render with `ErrorText`.

`WebLoginCard.tsx` — three labelled password inputs (`Current password`, `New password`, `Repeat new password`), button `Change password` disabled unless new ≥ 10 chars and both match; on `ok` shows "Password changed — your browser will ask you to sign in again." and reloads the page after 2 s; on error shows `error`.

- [ ] **Step 4: Run all setup-ui checks**

Run: `cd setup-ui && npx tsc -b && npx vitest run && npm run build && ls dist/accounts.html dist/index.html`
Expected: all pass; both HTML files exist.

- [ ] **Step 5: Commit**

```bash
git add setup-ui/accounts.html setup-ui/vite.config.ts setup-ui/src/accounts
git commit -m "feat(setup-ui): Accounts page (music, video + kiosk sign-in, streaming, web login)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Entry points + docs

**Files:**
- Modify: `ui/src/lib/SettingsDrawer.tsx` (near the existing "Setup wizard" entry), `docs/HOME-SERVERS.md`, `README.md`, `docs/SERVICES.md` (boombox-setup section)

- [ ] **Step 1:** In `SettingsDrawer.tsx`, next to the Setup wizard row, add an info row: **Accounts** — "Manage music, video and streaming accounts from a phone or computer at `http://<host>:8090/accounts/`" (use the same LAN host string the drawer already shows for remote access, or `window.location.hostname` fallback). No button (the kiosk can't use it).
- [ ] **Step 2:** Docs: `HOME-SERVERS.md` — replace the manual "set BOOMBOX_JELLYFIN_DEVICE_ID" instructions with "open /accounts/ → Video server → Sign kiosk in as …"; `SERVICES.md` — list `/api/accounts/*` routes and auth rules; `README.md` — one line linking `/accounts/`.
- [ ] **Step 3:** Run `cd ui && npx tsc -b && npx vitest run` → PASS.
- [ ] **Step 4:** Commit `docs+ui: point to the LAN Accounts page`.

---

### Task 12: Deploy to MarkII and verify on device

**Precondition:** MarkII temperature < 65 °C and not within 2 minutes of `:38` (hourly library sync). Build all UIs on the Mac; never on the Pi.

- [ ] **Step 1:** Stage release as done for `690e20a`: `git archive HEAD` + Mac-built `ui/dist`, `remote-ui/dist`, `setup-ui/dist` → `rsync` into a `cp -a` copy of the current release on the Pi; name `/opt/boombox/releases/<shortsha>`; write `VERSION`.
- [ ] **Step 2:** As `dietpi`: `$R/install/apply-release.sh preflight|swap|restart|verify <shortsha>` (with `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`). Expect all rc=0; swap syncs the nginx snippet.
- [ ] **Step 3:** As root: `install -m 0755 -o root -g root /opt/boombox/current/install/bin/boombox-setup-apply /usr/local/sbin/boombox-setup-apply`.
- [ ] **Step 4:** API checks from the Mac:
  - `curl -s -o /dev/null -w "%{http_code}" http://192.168.1.81:8090/api/accounts/summary` → `401`
  - with `-u boombox:<password>` → `200` JSON with 4 cards
  - on the Pi: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/api/accounts/summary` → `401`/`403`
- [ ] **Step 5:** Page walk-through with `agent-browser` against `http://boombox:<pw>@192.168.1.81:8090/accounts/`; screenshots of each card; Music Test shows Connected; Video shows server + user list.
- [ ] **Step 6:** Kiosk sign-in: Sign out (kiosk localStorage cleared, `/Devices` no longer lists the old id), then **Sign kiosk in as jwc**; confirm `jellyfin.env` has `BOOMBOX_JELLYFIN_DEVICE_ID=boombox-markii-kiosk`; tap Video on the kiosk (CDP) → lands on Jellyfin home signed in (screenshot); start an episode via `/Sessions/{id}/Playing` and confirm `jellyfin_client` selects the session (as in the earlier session test).
- [ ] **Step 7:** AirPlay: set name to "MarkII Test" → `grep name /usr/local/etc/shairport-sync.conf`, `avahi-browse -rt _raop._tcp | grep "MarkII Test"`; restore "MarkII".
- [ ] **Step 8:** Web password: change to a temporary passphrase, verify `curl -u boombox:<new>` → 200 and old → 401, `smbclient -L //127.0.0.1 -U dietpi%<new>` works; change back to the original and re-verify.
- [ ] **Step 9:** Record results in the PR description; commit any fixes found with tests.
