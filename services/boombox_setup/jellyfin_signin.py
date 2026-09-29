"""Jellyfin helpers for the Accounts page: server checks, user list, and a
server-side Quick Connect sign-in whose token is injected into the kiosk.

The boombox (not the kiosk browser) initiates Quick Connect with a DeviceId
it chooses (<BOOMBOX_ID>-kiosk), approves the code with the API key for the
picked user, and exchanges the secret for that user's AccessToken — no
Jellyfin password is ever typed or stored.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import aiohttp
import websockets

TIMEOUT = aiohttp.ClientTimeout(total=15)
QC_TIMEOUT = aiohttp.ClientTimeout(total=30)


class JellyfinError(Exception):
    """A user-presentable reason a Jellyfin call failed."""


_HDR_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _hdr(v: str) -> str:
    """Make a value safe inside a quoted MediaBrowser header field: a quote would
    break the field, and CR/LF (e.g. from the user-editable boombox name) would
    make aiohttp refuse the header outright."""
    return _HDR_CTRL.sub(" ", v).replace('"', "'")


def mb_auth(device_id: str, device_name: str, version: str, token: str = "") -> str:
    parts = ['Client="Jellyfin Web"', f'Device="{_hdr(device_name)}"',
             f'DeviceId="{_hdr(device_id)}"', f'Version="{_hdr(version)}"']
    if token:
        parts.append(f'Token="{_hdr(token)}"')
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


def _obj(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


async def system_info(s: aiohttp.ClientSession, base: str, key: str) -> dict:
    return _obj(await _req(s, "GET", f"{base}/System/Info", headers=_key(key)))


async def public_info(s: aiohttp.ClientSession, base: str) -> dict:
    return _obj(await _req(s, "GET", f"{base}/System/Info/Public"))


async def list_users(s: aiohttp.ClientSession, base: str, key: str) -> list[dict]:
    raw = await _req(s, "GET", f"{base}/Users", headers=_key(key))
    if not isinstance(raw, list):
        return []
    return [{"id": u["Id"], "name": str(u.get("Name", "")),
             "admin": bool(_obj(u.get("Policy")).get("IsAdministrator"))}
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
    init = _obj(init)
    if not init.get("Code") or not init.get("Secret"):
        raise JellyfinError("Jellyfin did not start a Quick Connect request")
    await _req(s, "POST", f"{base}/QuickConnect/Authorize",
               params={"code": init["Code"], "userId": user_id},
               headers=_key(key), timeout=QC_TIMEOUT)
    auth = await _req(s, "POST", f"{base}/Users/AuthenticateWithQuickConnect",
                      json={"Secret": init["Secret"]}, headers=dev, timeout=QC_TIMEOUT)
    token = _obj(auth).get("AccessToken")
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
    return _obj(d).get("LastUserName") or None


# ---------------------------------------------------------------------------
# Kiosk session injection over the Chrome DevTools Protocol

_KIOSK_DOWN = "kiosk not reachable — is the screen on?"
INJECT_CAP = 40.0  # seconds for the whole websocket phase of an injection


def credentials_blob(base: str, server_id: str, server_name: str, user_id: str,
                     token: str, now_ms: int) -> str:
    """jellyfin-web's `localStorage.jellyfin_credentials` for one signed-in server."""
    return json.dumps({"Servers": [{
        "ManualAddress": base, "manualAddressOnly": True, "Id": server_id,
        "Name": server_name, "UserId": user_id, "AccessToken": token,
        "DateLastAccessed": now_ms, "LastConnectionMode": 2,
    }]})


def _eval_value(r: dict) -> Any:
    # Real Chrome nests Runtime.evaluate's value as result.result.value; accept
    # a flat {"value": ...} too.
    if "value" in r:
        return r.get("value")
    return _obj(r.get("result")).get("value")


async def inject_kiosk(cdp_base: str, jf_base: str, device_id: str,
                       creds_json: str | None,
                       return_url: str = "http://localhost/") -> None:
    """Point the kiosk tab at Jellyfin, write (or, with creds_json=None, clear)
    its stored session and device id, then send it home. Needs the kiosk's CDP
    port (127.0.0.1:9222)."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.get(f"{cdp_base}/json") as r:
                pages = await r.json(content_type=None)
        if not isinstance(pages, list):
            raise ValueError("unexpected /json answer")
        page = next(p for p in pages if isinstance(p, dict)
                    and p.get("type") == "page" and p.get("webSocketDebuggerUrl"))
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, StopIteration,
            ValueError) as e:
        raise JellyfinError(_KIOSK_DOWN) from e

    if creds_json is None:
        js = ("localStorage.removeItem('jellyfin_credentials');"
              "localStorage.removeItem('_deviceId2');'ok'")
    else:
        js = (f"localStorage.setItem('_deviceId2', {json.dumps(device_id)});"
              f"localStorage.setItem('jellyfin_credentials', {json.dumps(creds_json)});'ok'")
    # Only report "complete" once the tab is on the Jellyfin page, so the
    # storage write can't land in the previous page's origin.
    ready = (f"location.href.startsWith({json.dumps(jf_base + '/')}) "
             "? document.readyState : 'loading'")
    msg_id = 0

    async def call(ws: Any, method: str, params: dict) -> dict:
        nonlocal msg_id
        msg_id += 1
        await ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if isinstance(m, dict) and m.get("id") == msg_id:
                return _obj(m.get("result"))

    async def session() -> None:
        # No Origin header: Chromium's --remote-allow-origins only lists the
        # CDP address itself, and websockets sends none by default.
        async with websockets.connect(page["webSocketDebuggerUrl"],
                                      max_size=2**22, open_timeout=5) as ws:
            await call(ws, "Page.navigate", {"url": f"{jf_base}/web/"})
            for _ in range(30):  # wait for the Jellyfin origin to load
                r = await call(ws, "Runtime.evaluate",
                               {"expression": ready, "returnByValue": True})
                if _eval_value(r) == "complete":
                    break
                await asyncio.sleep(0.5)
            else:
                await call(ws, "Page.navigate", {"url": return_url})
                raise JellyfinError("the kiosk couldn't open the Jellyfin page")
            r = await call(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True})
            await call(ws, "Page.navigate", {"url": return_url})
            # A thrown setItem/removeItem is reported in exceptionDetails, not
            # as a failed call — check the script really finished.
            if r.get("exceptionDetails") or _eval_value(r) != "ok":
                raise JellyfinError("the kiosk couldn't save the Jellyfin session")

    try:
        await asyncio.wait_for(session(), INJECT_CAP)
    except (OSError, asyncio.TimeoutError, ValueError,
            websockets.WebSocketException) as e:
        raise JellyfinError(_KIOSK_DOWN) from e
