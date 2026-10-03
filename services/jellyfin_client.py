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
  POST /Sessions/{id}/Command  body {"Name": "SetAudioStreamIndex"|
                                     "SetSubtitleStreamIndex", "Arguments": {"Index": "<n>"}}

Which session is "ours"? A Jellyfin server lists every client in the
household, so picking the wrong one means the phone remote pauses somebody
else's TV. Selection (first hit wins, among sessions that are playing):

  1. BOOMBOX_JELLYFIN_DEVICE_ID   — exact DeviceId (precise; see HOME-SERVERS.md)
  2. BOOMBOX_JELLYFIN_DEVICE_NAME — exact DeviceName (most recent if several)
     If either is set and nothing matched, stop here: no session.
  3. a loopback RemoteEndPoint    — ONLY when the server itself is on
     loopback (the kiosk against an on-device server). A remote server
     behind a same-host proxy/tunnel sees every client as 127.0.0.1.
  4. the most recently active session — ONLY when the server itself is on
     loopback/LAN and neither env var is set (the legacy single-device case).

Against a remote server with no match we control nothing rather than guess.
Both env vars arrive via EnvironmentFile=/etc/boombox/jellyfin.env.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import urllib.parse

import aiohttp
from aiohttp import web
from jellyfin_env import jellyfin_base, jellyfin_token

log = logging.getLogger("boombox-remote")

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


DEVICE_ID_ENV = "BOOMBOX_JELLYFIN_DEVICE_ID"
DEVICE_NAME_ENV = "BOOMBOX_JELLYFIN_DEVICE_NAME"
_LAN_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal")


def _is_loopback_endpoint(endpoint: object) -> bool:
    ep = str(endpoint or "")
    return ep.startswith("127.") or ep in ("::1", "localhost")


def _base_host(base: str) -> str:
    try:
        return (urllib.parse.urlparse(base).hostname or "").rstrip(".")
    except ValueError:
        return ""


def server_is_loopback(base: str) -> bool:
    """True when the Jellyfin base URL points at this device itself."""
    host = _base_host(base)
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def server_is_local(base: str) -> bool:
    """True when the Jellyfin base URL points at loopback or the home LAN.

    Only then is "the most recently active session" a reasonable guess for
    the kiosk — on an internet-facing server it is just as likely to be a TV
    in another room (or another house).
    """
    host = _base_host(base)
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # IP literals (v4 and v6) are decided by address class alone —
        # a v6 literal never contains a '.', so it must not reach the
        # single-label rule below.
        return ip.is_loopback or ip.is_private or ip.is_link_local
    # Single-label names ("nas", "jellyfin") only resolve on the LAN.
    return host == "localhost" or host.endswith(_LAN_SUFFIXES) or "." not in host


class JellyfinClient:
    """Talks to the configured Jellyfin server with the boombox API key."""

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session
        self._logged_unpinned = False

    def _token(self) -> str | None:
        return jellyfin_token()

    def _headers(self) -> dict | None:
        tok = self._token()
        return {"X-MediaBrowser-Token": tok} if tok else None

    async def _local_session(self) -> dict | None:
        """Return the Jellyfin session running on this device, or None.

        See the module docstring for the selection order.
        """
        headers = self._headers()
        if headers is None:
            return None
        try:
            async with self._sess.get(
                    f"{jellyfin_base()}/Sessions", headers=headers,
                    timeout=_TIMEOUT) as r:
                if r.status != 200:
                    return None
                sessions = await r.json()
        except Exception as e:
            log.debug("jellyfin /Sessions failed: %s", e)
            return None
        if not isinstance(sessions, list):
            return None
        return self._select_session(sessions)

    def _select_session(self, sessions: list) -> dict | None:
        playing = [s for s in sessions
                   if isinstance(s, dict) and s.get("NowPlayingItem")]
        if not playing:
            return None

        def newest(pool: list[dict]) -> dict:
            return max(pool, key=lambda s: str(s.get("LastActivityDate") or ""))

        device_id = os.environ.get(DEVICE_ID_ENV, "").strip()
        device_name = os.environ.get(DEVICE_NAME_ENV, "").strip()
        if device_id:
            hits = [s for s in playing if s.get("DeviceId") == device_id]
            if hits:
                return newest(hits)
        if device_name:
            hits = [s for s in playing if s.get("DeviceName") == device_name]
            if hits:
                return newest(hits)
        if device_id or device_name:
            # Explicitly pinned but our device isn't playing — never fall
            # through to somebody else's session.
            return None
        base = jellyfin_base()
        if server_is_loopback(base):
            # Only an on-device server makes a loopback client "us"; a
            # remote one behind a same-host proxy reports 127.0.0.1 for all.
            local = [s for s in playing
                     if _is_loopback_endpoint(s.get("RemoteEndPoint"))]
            if local:
                return newest(local)
        if server_is_local(base):
            return newest(playing)
        if not self._logged_unpinned:
            self._logged_unpinned = True
            log.info(
                "jellyfin at %s is off the LAN and no session is pinned; "
                "refusing to control an arbitrary household session. Set %s "
                "(or %s) in /etc/boombox/jellyfin.env to the kiosk's Jellyfin "
                "DeviceId (Dashboard -> Devices) and restart boombox-remote.",
                base, DEVICE_ID_ENV, DEVICE_NAME_ENV)
        return None

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

    async def _post(self, url: str, headers: dict,
                    body: dict | None = None) -> int:
        """POST and release the response; returns the HTTP status."""
        async with self._sess.post(url, headers=headers, json=body,
                                   timeout=_TIMEOUT) as r:
            return r.status

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
        value = (body or {}).get("value")
        if not value_ok(action, value):
            return web.json_response({"ok": False, "error": "bad_value"}, status=400)
        result = await client.command(action, value)
        status = 200 if result.get("ok") else 502
        return web.json_response(result, status=status)

    return state, command


def add_routes(app: web.Application, client) -> None:
    """Register /api/remote/video/* . `client` is a JellyfinClient (or any
    object with async local_session_state() and command(action, value))."""
    state, command = _make_handlers(client)
    app.router.add_get("/api/remote/video/state", state)
    app.router.add_post("/api/remote/video/command", command)
