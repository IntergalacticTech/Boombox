"""Jellyfin REST proxy for boombox-remote — video transport control.

boombox-remote calls Jellyfin server-side with the stored API key so the
PWA never sees Jellyfin credentials or hits CORS. Targets the Jellyfin
"session" running on the boombox's own kiosk Chromium.

Jellyfin API reference used here:
  GET  /Sessions                          → active sessions
  POST /Sessions/{id}/Playing/PlayPause   → toggle
  POST /Sessions/{id}/Playing/Stop
  POST /Sessions/{id}/Playing/NextTrack
  POST /Sessions/{id}/Playing/PreviousTrack
  POST /Sessions/{id}/Playing/Seek?seekPositionTicks=<100ns ticks>
  POST /Sessions/{id}/Command  body {"Name": "SetVolume", "Arguments": {...}}
  POST /Sessions/{id}/Command  body {"Name": "ToggleMute"}
"""
from __future__ import annotations

import logging

import aiohttp
from aiohttp import web
from jellyfin_env import jellyfin_base, jellyfin_token

log = logging.getLogger("boombox-remote")

_TICKS_PER_SECOND = 10_000_000

# action → (HTTP path suffix under /Sessions/{id}/Playing, or "Command")
_PLAYING_ACTIONS = {
    "play_pause": "PlayPause",
    "stop": "Stop",
    "next": "NextTrack",
    "previous": "PreviousTrack",
}
_VALID_ACTIONS = set(_PLAYING_ACTIONS) | {"seek", "volume", "mute"}


class JellyfinClient:
    """Talks to the local Jellyfin server with the boombox-managed API key."""

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    def _token(self) -> str | None:
        return jellyfin_token()

    def _headers(self) -> dict | None:
        tok = self._token()
        return {"X-MediaBrowser-Token": tok} if tok else None

    async def _local_session(self) -> dict | None:
        """Return the Jellyfin session running on this device, or None.

        Heuristic: prefer a session whose RemoteEndPoint is loopback (the
        kiosk Chromium); fall back to the most recently active session.
        """
        headers = self._headers()
        if headers is None:
            return None
        try:
            async with self._sess.get(
                    f"{jellyfin_base()}/Sessions", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=2)) as r:
                if r.status != 200:
                    return None
                sessions = await r.json()
        except Exception as e:
            log.debug("jellyfin /Sessions failed: %s", e)
            return None
        playing = [s for s in sessions if s.get("NowPlayingItem")]
        if not playing:
            return None
        local = [s for s in playing
                 if str(s.get("RemoteEndPoint", "")).startswith("127.")
                 or str(s.get("RemoteEndPoint", "")) in ("::1", "localhost")]
        pool = local or playing
        pool.sort(key=lambda s: s.get("LastActivityDate", ""), reverse=True)
        return pool[0]

    async def local_session_state(self) -> dict:
        """Consolidated state for the local Jellyfin session."""
        s = await self._local_session()
        if s is None:
            return {"active": False}
        item = s.get("NowPlayingItem") or {}
        play = s.get("PlayState") or {}
        runtime_ticks = item.get("RunTimeTicks") or 0
        position_ticks = play.get("PositionTicks") or 0
        return {
            "active": True,
            "playing": not play.get("IsPaused", False),
            "title": item.get("Name"),
            "position_s": position_ticks // _TICKS_PER_SECOND,
            "duration_s": runtime_ticks // _TICKS_PER_SECOND,
            "volume": play.get("VolumeLevel"),
            "muted": bool(play.get("IsMuted", False)),
        }

    async def command(self, action: str, value=None) -> dict:
        """Map a remote command onto the Jellyfin session API."""
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
                url = f"{base}/Playing/{_PLAYING_ACTIONS[action]}"
                await self._sess.post(url, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=2))
            elif action == "seek":
                ticks = int(float(value or 0) * _TICKS_PER_SECOND)
                url = (f"{base}/Playing/Seek"
                       f"?seekPositionTicks={ticks}")
                await self._sess.post(url, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=2))
            elif action == "volume":
                await self._sess.post(
                    f"{base}/Command", headers=headers,
                    json={"Name": "SetVolume",
                          "Arguments": {"Volume": str(int(value or 0))}},
                    timeout=aiohttp.ClientTimeout(total=2))
            elif action == "mute":
                await self._sess.post(
                    f"{base}/Command", headers=headers,
                    json={"Name": "ToggleMute"},
                    timeout=aiohttp.ClientTimeout(total=2))
            else:
                return {"ok": False, "error": f"unknown_action:{action}"}
        except Exception as e:
            log.warning("jellyfin command %s failed: %s", action, e)
            return {"ok": False, "error": "jellyfin_unreachable"}
        return {"ok": True}


def _make_handlers(client):
    async def state(request: web.Request) -> web.Response:
        return web.json_response(await client.local_session_state())

    async def command(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"},
                                     status=400)
        action = (body or {}).get("action") if isinstance(body, dict) else None
        if action not in _VALID_ACTIONS:
            return web.json_response(
                {"ok": False, "error": "bad_action"}, status=400)
        result = await client.command(action, (body or {}).get("value"))
        status = 200 if result.get("ok") else 502
        return web.json_response(result, status=status)

    return state, command


def add_routes(app: web.Application, client) -> None:
    """Register /api/remote/video/* . `client` is a JellyfinClient (or any
    object with async local_session_state() and command(action, value))."""
    state, command = _make_handlers(client)
    app.router.add_get("/api/remote/video/state", state)
    app.router.add_post("/api/remote/video/command", command)
