#!/usr/bin/env python3
"""Boombox Jellyfin one-shot bootstrapper.

Drives Jellyfin's first-run wizard (POST /Startup/*), creates an admin
user with the boombox-managed LAN credentials, adds the `~/Videos`
library, and persists an API key for the USB-mount script + future
features.

Runs from install.sh; safe to re-run. Skips work if Jellyfin is already
configured AND we can hit /System/Info with our stored token.

Inputs:
  /etc/boombox/web-auth.env   — BOOMBOX_WEB_USER, BOOMBOX_WEB_PASSWORD
  ~/Videos                    — the library path

Outputs:
  /etc/boombox/jellyfin.env       — JELLYFIN_API_KEY, JELLYFIN_USER_ID, etc.
  /etc/boombox/jellyfin-api-key   — just the token, mode 0640 (consumed by
                                    boombox-usb-mount.sh)
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

JELLYFIN_BASE = os.environ.get("JELLYFIN_BASE", "http://127.0.0.1:8096")
WEB_AUTH_ENV = Path(os.environ.get("BOOMBOX_WEB_AUTH_ENV", "/etc/boombox/web-auth.env"))
JF_ENV_FILE = Path(os.environ.get("BOOMBOX_JELLYFIN_ENV", "/etc/boombox/jellyfin.env"))
JF_KEY_FILE = Path(os.environ.get("BOOMBOX_JELLYFIN_KEY", "/etc/boombox/jellyfin-api-key"))

# The boombox is a single-user appliance — one shared library is the goal.
LIBRARY_NAME = os.environ.get("BOOMBOX_VIDEO_LIBRARY_NAME", "Library")
LIBRARY_COLLECTION_TYPE = os.environ.get("BOOMBOX_VIDEO_COLLECTION_TYPE", "homevideos")
LIBRARY_PATH = Path(os.environ.get("BOOMBOX_VIDEO_DIR", f"/home/{os.environ.get('USER', 'jwc')}/Videos"))


CLIENT = "boombox-installer"
DEVICE_ID = secrets.token_hex(16)


def log(msg: str) -> None:
    print(f"[jellyfin-setup] {msg}", file=sys.stderr)


def auth_header(token: str | None = None) -> str:
    """The X-Emby-Authorization header Jellyfin expects on every call."""
    parts = [
        f'Client="{CLIENT}"',
        f'Device="installer"',
        f'DeviceId="{DEVICE_ID}"',
        'Version="0.1"',
    ]
    if token:
        parts.append(f'Token="{token}"')
    return "MediaBrowser " + ", ".join(parts)


def request(
    method: str,
    path: str,
    *,
    body: Any | None = None,
    token: str | None = None,
    query: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes]:
    url = JELLYFIN_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {
        "X-Emby-Authorization": auth_header(token),
        "Accept": "application/json",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        log(f"network error on {method} {path}: {e}")
        return 0, b""


def wait_for_jellyfin(deadline_s: float = 90.0) -> bool:
    """Block until Jellyfin's HTTP listener answers /System/Info/Public.

    First-time installs need this — systemd reports the unit "active" the
    moment the process is up, but Jellyfin spends ~10–20 s building its
    SQLite schema before it serves anything.
    """
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        code, _ = request("GET", "/System/Info/Public", timeout=3.0)
        if code == 200:
            return True
        time.sleep(1.5)
    return False


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except (FileNotFoundError, PermissionError):
        pass
    return out


def write_env_file(path: Path, env: dict[str, str], mode: int = 0o640) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    tmp.chmod(mode)
    tmp.replace(path)


def get_public_info() -> dict | None:
    code, raw = request("GET", "/System/Info/Public")
    if code != 200:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def token_works(token: str) -> bool:
    code, _ = request("GET", "/System/Info", token=token, timeout=4.0)
    return code == 200


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------

def run_wizard(username: str, password: str) -> None:
    log("driving Jellyfin first-run wizard")

    code, raw = request("POST", "/Startup/Configuration", body={
        "UICulture": "en-US",
        "MetadataCountryCode": "US",
        "PreferredMetadataLanguage": "en",
    })
    if code not in (200, 204):
        raise RuntimeError(f"Startup/Configuration failed: {code} {raw!r}")

    # Jellyfin 10.10+ doesn't seed a default user on startup — it does so
    # lazily when GET /Startup/FirstUser is called. The web wizard hits
    # this between the locale step and the name/password step; without it
    # /Startup/User throws 'Sequence contains no elements'.
    code, raw = request("GET", "/Startup/FirstUser")
    if code not in (200, 204):
        log(f"Startup/FirstUser returned {code} {raw!r} (continuing)")

    # /Startup/User modifies _userManager.Users.First(). If the lazy seed
    # above hasn't landed yet (race), retry through 500s.
    code = 0
    raw = b""
    for attempt in range(20):
        code, raw = request("POST", "/Startup/User", body={
            "Name": username,
            "Password": password,
        })
        if code in (200, 204):
            break
        if code == 500:
            # Body is opaque ("Error processing request"); retry through any
            # 500 while Jellyfin's InitializeAsync seeds the default user.
            log(f"Startup/User HTTP 500 (attempt {attempt + 1}); retrying in 2 s")
            time.sleep(2.0)
            continue
        break
    if code not in (200, 204):
        raise RuntimeError(f"Startup/User failed: {code} {raw!r}")

    code, raw = request("POST", "/Startup/RemoteAccess", body={
        "EnableRemoteAccess": False,
        "EnableAutomaticPortMapping": False,
    })
    # Some Jellyfin builds skip this step entirely if remote access UI was
    # never reached. 404 here is tolerable.
    if code not in (200, 204, 404):
        raise RuntimeError(f"Startup/RemoteAccess failed: {code} {raw!r}")

    code, raw = request("POST", "/Startup/Complete")
    if code not in (200, 204):
        raise RuntimeError(f"Startup/Complete failed: {code} {raw!r}")

    log("wizard complete")


def authenticate(username: str, password: str) -> dict:
    """Get an access token. Returns {AccessToken, User: {Id, Name}, ServerId}."""
    code, raw = request(
        "POST", "/Users/AuthenticateByName",
        body={"Username": username, "Pw": password},
    )
    if code != 200:
        raise RuntimeError(f"AuthenticateByName failed: {code} {raw!r}")
    return json.loads(raw)


def library_exists(token: str) -> bool:
    code, raw = request("GET", "/Library/VirtualFolders", token=token)
    if code != 200:
        log(f"could not list libraries (HTTP {code}); assuming none")
        return False
    try:
        folders = json.loads(raw) or []
    except json.JSONDecodeError:
        return False
    for f in folders:
        paths = f.get("Locations") or []
        if str(LIBRARY_PATH) in paths:
            return True
    return False


def add_library(token: str) -> None:
    log(f"adding {LIBRARY_NAME!r} ({LIBRARY_COLLECTION_TYPE}) → {LIBRARY_PATH}")
    LIBRARY_PATH.mkdir(parents=True, exist_ok=True)

    # Two-call dance: POST /Library/VirtualFolders creates the empty
    # virtual folder, then POST /Library/VirtualFolders/Paths attaches
    # the filesystem path. Doing both in one call (paths= query param
    # plus PathInfos body) leaves Jellyfin's scanner with a registered
    # library that has no scan path — silent dead-end.
    query = {
        "name": LIBRARY_NAME,
        "collectionType": LIBRARY_COLLECTION_TYPE,
        "refreshLibrary": "false",
    }
    body = {
        "LibraryOptions": {
            "EnableRealtimeMonitoring": True,
            "EnablePhotos": False,
        }
    }
    code, raw = request("POST", "/Library/VirtualFolders", body=body, token=token, query=query)
    if code not in (200, 204):
        raise RuntimeError(f"VirtualFolders create failed: {code} {raw!r}")

    code, raw = request(
        "POST", "/Library/VirtualFolders/Paths",
        body={
            "Name": LIBRARY_NAME,
            "Path": str(LIBRARY_PATH),
            "PathInfo": {"Path": str(LIBRARY_PATH)},
            "RefreshLibrary": True,
        },
        token=token,
    )
    if code not in (200, 204):
        raise RuntimeError(f"VirtualFolders/Paths failed: {code} {raw!r}")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    creds = read_env_file(WEB_AUTH_ENV)
    username = os.environ.get("JELLYFIN_USER") or creds.get("BOOMBOX_WEB_USER") or "boombox"
    password = os.environ.get("JELLYFIN_PASSWORD") or creds.get("BOOMBOX_WEB_PASSWORD")
    if not password:
        log(f"no password available — set BOOMBOX_WEB_PASSWORD in {WEB_AUTH_ENV}")
        return 2

    if not wait_for_jellyfin():
        log("Jellyfin didn't answer in 90 s; bailing")
        return 3

    info = get_public_info()
    if info is None:
        log("can't read /System/Info/Public")
        return 3

    wizard_done = bool(info.get("StartupWizardCompleted"))
    log(f"Jellyfin reports StartupWizardCompleted={wizard_done}")

    # Fast path: wizard already done AND our stored token still works.
    if wizard_done:
        stored = read_env_file(JF_ENV_FILE)
        existing = stored.get("JELLYFIN_API_KEY", "")
        if existing and token_works(existing):
            if library_exists(existing):
                log("already configured — nothing to do")
                return 0
            log("token works but library missing — re-adding")
            add_library(existing)
            return 0
        # Otherwise: re-auth (we changed the password, or never stored a token).
        log("wizard done but stored token isn't usable — re-authenticating")

    if not wizard_done:
        run_wizard(username, password)

    auth = authenticate(username, password)
    token = auth["AccessToken"]
    user_id = auth["User"]["Id"]
    server_id = auth.get("ServerId", "")

    JF_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_env_file(JF_ENV_FILE, {
        "JELLYFIN_USER": username,
        "JELLYFIN_USER_ID": user_id,
        "JELLYFIN_SERVER_ID": server_id,
        "JELLYFIN_API_KEY": token,
    })
    # Separate single-line file the USB-mount shell script reads.
    JF_KEY_FILE.write_text(token + "\n")
    JF_KEY_FILE.chmod(0o640)

    if not library_exists(token):
        add_library(token)

    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
