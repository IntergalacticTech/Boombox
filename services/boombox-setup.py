#!/usr/bin/env python3
# services/boombox-setup.py
"""boombox-setup service entry point (port 6689, nginx /api/setup/).

Front-door for the first-run setup wizard. Owns the runtime wiring the API's
Context protocol needs:
  * apply()          — run the privileged helper via `sudo -n`
  * restart_units()  — bounce user units after an identity/video change
  * music_*/remote_* — proxy to boombox-library (6687) / boombox-remote (6685)
                       over loopback, so a phone never has to clear LAN Basic auth
  * read_identity/wifi_status/video_status/is_complete — cheap local reads

The service is resilient to the library/remote services being down (status
degrades to booleans) and to the helper being absent (apply returns an error
dict the wizard surfaces).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import socket
import subprocess
from pathlib import Path

import aiohttp
from aiohttp import web
from boombox_setup import __version__
from boombox_setup.api import build_app

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-setup")

PORT = 6689
LIBRARY_BASE = os.environ.get("BOOMBOX_LIBRARY_BASE", "http://127.0.0.1:6687")
REMOTE_BASE = os.environ.get("BOOMBOX_REMOTE_BASE", "http://127.0.0.1:6685")
SETUP_APPLY = os.environ.get("BOOMBOX_SETUP_APPLY", "/usr/local/sbin/boombox-setup-apply")
BOOMBOX_ENV = Path(os.environ.get("BOOMBOX_ENV_FILE", "/etc/boombox/boombox.env"))
JELLYFIN_ENV = Path(os.environ.get("BOOMBOX_JELLYFIN_ENV", "/etc/boombox/jellyfin.env"))
COMPLETE_MARKER = Path(os.environ.get("BOOMBOX_SETUP_MARKER",
                                      "/opt/boombox/state/setup-complete"))
SKIN_FILE = Path(os.environ.get("BOOMBOX_SETUP_SKIN",
                                "/opt/boombox/state/setup-skin"))
# Kiosk skins live in the ui app's registry; the wizard offers the same set.
# Kept as a permissive pattern rather than a hard list so a new skin doesn't
# need a boombox-setup change to be selectable.
_SKIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# The LAN-facing web port (for the QR URL). web-auth.env sets BOOMBOX_WEB_PORT;
# accept BOOMBOX_LAN_PORT too for parity with boombox-remote's mDNS port.
LAN_PORT = int(os.environ.get("BOOMBOX_WEB_PORT")
               or os.environ.get("BOOMBOX_LAN_PORT") or "8090")


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return out


class ServiceContext:
    def __init__(self) -> None:
        self.lan_port = LAN_PORT
        self._session: aiohttp.ClientSession | None = None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    # ---- cheap local reads ------------------------------------------------
    def read_identity(self) -> dict:
        env = _read_env_file(BOOMBOX_ENV)
        try:
            hostname = socket.gethostname()
        except OSError:
            hostname = "boombox"
        return {
            "name": env.get("BOOMBOX_NAME", hostname),
            "id": env.get("BOOMBOX_ID", f"boombox-{hostname}"),
            "hostname": hostname,
        }

    def wifi_status(self) -> dict:
        if not Path("/sys/class/net/wlan0").is_dir():
            return {"present": False, "connected": False, "ssid": "", "ip": ""}
        ssid = ""
        try:
            r = subprocess.run(["iwgetid", "-r"], capture_output=True,
                               text=True, timeout=5)
            ssid = r.stdout.strip()
        except Exception:
            pass
        ip = ""
        try:
            r = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", "wlan0"],
                               capture_output=True, text=True, timeout=5)
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r.stdout)
            ip = m.group(1) if m else ""
        except Exception:
            pass
        return {"present": True, "connected": bool(ssid and ip),
                "ssid": ssid, "ip": ip}

    def video_status(self) -> dict:
        env = _read_env_file(JELLYFIN_ENV)
        base = env.get("BOOMBOX_JELLYFIN_BASE", "")
        return {
            "mode": "remote" if base else "builtin",
            "base": base or "http://127.0.0.1:8096",
            "has_key": bool(env.get("JELLYFIN_API_KEY")),
        }

    def lan_host(self) -> str:
        """Best LAN address for the QR URL: the primary global IPv4, else
        the mDNS hostname."""
        try:
            out = subprocess.run(["hostname", "-I"], capture_output=True,
                                 text=True, timeout=5).stdout.split()
            for tok in out:
                if re.match(r"\d+\.\d+\.\d+\.\d+$", tok) and not tok.startswith("127."):
                    return tok
        except Exception:
            pass
        return f"{socket.gethostname()}.local"

    def is_complete(self) -> bool:
        # A single explicit marker. install.sh writes it on upgrade when a
        # device already has a configured library (so existing boomboxes are
        # never forced back through setup); a fresh device has no marker and
        # the kiosk redirects into the wizard until POST /complete writes it.
        return COMPLETE_MARKER.exists()

    def mark_complete(self) -> None:
        try:
            COMPLETE_MARKER.parent.mkdir(parents=True, exist_ok=True)
            COMPLETE_MARKER.write_text("1\n")
        except OSError as e:
            log.warning("could not write completion marker: %s", e)

    def get_skin(self) -> str | None:
        """The skin chosen in the wizard, if any. The kiosk player itself
        reads localStorage / ?skin= — this file exists so a phone-side choice
        can reach the kiosk (the kiosk wizard polls status and redirects to
        /?skin=<id> on completion)."""
        try:
            v = SKIN_FILE.read_text().strip()
            return v or None
        except OSError:
            return None

    def set_skin(self, skin_id: str) -> bool:
        if not _SKIN_ID_RE.match(skin_id):
            return False
        try:
            SKIN_FILE.parent.mkdir(parents=True, exist_ok=True)
            SKIN_FILE.write_text(skin_id + "\n")
            return True
        except OSError as e:
            log.warning("could not persist skin choice: %s", e)
            return False

    # ---- privileged helper ------------------------------------------------
    async def apply(self, payload: dict) -> dict:
        """Run the root helper via `sudo -n`, feeding JSON on stdin."""
        def _invoke() -> dict:
            try:
                proc = subprocess.run(
                    ["sudo", "-n", SETUP_APPLY],
                    input=json.dumps(payload), capture_output=True,
                    text=True, timeout=60,
                )
            except FileNotFoundError:
                return {"ok": False, "error": "setup helper not installed"}
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "setup helper timed out"}
            out = (proc.stdout or "").strip()
            if not out:
                err = (proc.stderr or "").strip() or f"helper exit {proc.returncode}"
                return {"ok": False, "error": err}
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                return {"ok": False, "error": f"helper returned non-json: {out[:200]}"}
        return await asyncio.to_thread(_invoke)

    async def restart_units(self, units: list[str]) -> None:
        def _restart() -> None:
            for u in units:
                try:
                    subprocess.run(["systemctl", "--user", "restart", u],
                                   capture_output=True, text=True, timeout=20)
                except Exception:
                    log.warning("could not restart %s", u)
        await asyncio.to_thread(_restart)

    # ---- proxy: boombox-library ------------------------------------------
    async def music_get(self) -> dict:
        s = await self._http()
        async with s.get(f"{LIBRARY_BASE}/api/library/source") as r:
            src = await r.json()
        reachable = False
        try:
            async with s.get(f"{LIBRARY_BASE}/api/library/health") as r:
                h = await r.json()
                reachable = bool(h.get("navidrome_reachable"))
        except Exception:
            pass
        return {
            "url": src.get("url", ""),
            "username": src.get("username", ""),
            "configured": bool(src.get("url")),
            "reachable": reachable,
        }

    async def music_test(self, url, username, password) -> tuple[bool, str]:
        s = await self._http()
        async with s.post(f"{LIBRARY_BASE}/api/library/source/test",
                          json={"url": url, "username": username,
                                "password": password}) as r:
            d = await r.json()
        return bool(d.get("ok")), d.get("error", "")

    async def music_save(self, url, username, password) -> tuple[bool, str]:
        s = await self._http()
        async with s.put(f"{LIBRARY_BASE}/api/library/source",
                        json={"url": url, "username": username,
                              "password": password}) as r:
            d = await r.json()
            if r.status == 200 and d.get("ok"):
                return True, ""
            return False, d.get("error", "save failed")

    # ---- proxy: boombox-remote -------------------------------------------
    async def remote_status(self) -> dict:
        s = await self._http()
        async with s.get(f"{REMOTE_BASE}/api/remote/admin/status") as r:
            d = await r.json()
        return {"enabled": bool(d.get("enabled")), "peers": d.get("peers", [])}

    async def remote_enable(self) -> dict:
        s = await self._http()
        async with s.post(f"{REMOTE_BASE}/api/remote/admin/enable") as r:
            return await r.json()

    async def remote_pair_start(self) -> dict:
        s = await self._http()
        async with s.post(f"{REMOTE_BASE}/api/remote/pair/start") as r:
            return await r.json()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


async def amain() -> None:
    ctx = ServiceContext()
    app = build_app(ctx)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    log.info("boombox-setup %s listening on :%d", __version__, PORT)

    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    await ctx.close()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
