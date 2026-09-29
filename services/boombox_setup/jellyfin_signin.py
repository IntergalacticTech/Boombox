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
    parts = ['Client="Jellyfin Web"', f'Device="{device_name}"',
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
