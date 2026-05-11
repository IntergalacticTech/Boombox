#!/usr/bin/env python3
"""Boombox MPRIS aggregator.

Polls `playerctl` (with `playerctld` for active-player tracking) and exposes
the current MPRIS state at GET /state. The SPA combines this with Mopidy's
own HTTP/WS API to render unified now-playing across all four sources.

Why not include Mopidy here too? Mopidy's HTTP API gives us richer data
(library, queue, search, exact position, volume) than MPRIS — we keep that
direct path. This service surfaces the *non-Mopidy* sources only:
  - ShairportSync  (AirPlay)
  - librespot       (Spotify Connect, when its MPRIS feature is enabled)
  - BlueZ phone     (incoming Bluetooth A2DP)

When the SPA sees a non-Mopidy MPRIS player in 'Playing' state, it overrides
Mopidy's track display with that player's metadata.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-state")

POLL_INTERVAL_S = 0.5
EXCLUDED_PLAYERS = {"mopidy"}  # Mopidy's richer HTTP API is the source-of-truth.

# Friendly names for MPRIS player IDs we expect to see.
SOURCE_LABELS = {
    "shairportsync": "AirPlay",
    "shairport-sync": "AirPlay",
    "spotify": "Spotify",
    "spotifyd": "Spotify",
    "librespot": "Spotify",
    "raspotify": "Spotify",
    "vlc": "VLC",
    "chromium": "Browser",
}

EMPTY_STATE = {
    "source": None,
    "label": None,
    "status": "stopped",
    "player": None,
    "track": None,
    "volume": None,
    "position_ms": 0,
    "length_ms": 0,
    "ts": 0,
}


def label_for(player: str) -> str:
    p = player.lower()
    for key, lbl in SOURCE_LABELS.items():
        if key in p:
            return lbl
    if "bluez" in p or "bluetooth" in p:
        return "Bluetooth"
    return player


async def run(*args: str, timeout: float = 1.5) -> tuple[int, str]:
    """Run a subprocess and return (returncode, stdout-stripped)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, ""
    return proc.returncode or 0, out.decode().rstrip("\n")


async def list_players() -> list[str]:
    rc, out = await run("playerctl", "--list-all")
    if rc != 0 or not out:
        return []
    return [p for p in (line.strip() for line in out.splitlines()) if p]


async def status_of(player: str) -> str:
    rc, out = await run("playerctl", "-p", player, "status")
    if rc != 0:
        return "stopped"
    return out.lower() or "stopped"


async def metadata_of(player: str) -> dict:
    # Use a separator unlikely to appear in titles to keep parsing trivial.
    sep = "|::|"
    fmt = sep.join([
        "{{xesam:title}}",
        "{{xesam:artist}}",
        "{{xesam:album}}",
        "{{mpris:length}}",
        "{{position}}",
        "{{volume}}",
    ])
    rc, out = await run("playerctl", "-p", player, "metadata", "--format", fmt)
    if rc != 0:
        return {}
    parts = out.split(sep)
    if len(parts) < 6:
        return {}
    title, artist, album, length, position, volume = parts
    def _int(s: str) -> int:
        try:
            return int(s)
        except ValueError:
            return 0
    def _float(s: str) -> Optional[float]:
        try:
            return float(s)
        except ValueError:
            return None
    length_us = _int(length)
    position_us = _int(position)
    return {
        "title": title.strip() or None,
        "artist": artist.strip() or None,
        "album": album.strip() or None,
        "length_ms": length_us // 1000,
        "position_ms": position_us // 1000,
        "volume": _float(volume),
    }


async def aggregate() -> dict:
    players = await list_players()
    candidates = [p for p in players if p.split(".")[0].lower() not in EXCLUDED_PLAYERS]
    if not candidates:
        return dict(EMPTY_STATE, ts=time.time())

    # First Playing wins; else first Paused; else first listed.
    statuses = {p: await status_of(p) for p in candidates}
    active = (
        next((p for p, s in statuses.items() if s == "playing"), None)
        or next((p for p, s in statuses.items() if s == "paused"), None)
        or candidates[0]
    )
    meta = await metadata_of(active)
    return {
        "source": active,
        "label": label_for(active),
        "status": statuses.get(active, "stopped"),
        "player": active,
        "track": {
            "title": meta.get("title"),
            "artist": meta.get("artist"),
            "album": meta.get("album"),
        } if meta.get("title") or meta.get("artist") else None,
        "volume": meta.get("volume"),
        "position_ms": meta.get("position_ms", 0),
        "length_ms": meta.get("length_ms", 0),
        "ts": time.time(),
    }


_state: dict = dict(EMPTY_STATE)


async def poll_loop():
    global _state
    while True:
        try:
            _state = await aggregate()
        except Exception as e:  # pragma: no cover
            log.warning("aggregate failed: %s", e)
        await asyncio.sleep(POLL_INTERVAL_S)


async def state_handler(_request: web.Request) -> web.Response:
    return web.json_response(_state)


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "version": "0.1.0"})


# Whitelist of playerctl actions we forward. Note: 'play-pause' is the
# canonical MPRIS toggle; we map our /toggle alias to it.
_ALLOWED_ACTIONS = {"play", "pause", "play-pause", "next", "previous", "stop"}


async def control_handler(request: web.Request) -> web.Response:
    """POST /control/<action> routes a transport command to the active MPRIS
    player. The SPA calls this only when the external source is the live
    player (its `useMopidy()` covers the Mopidy case directly)."""
    action = request.match_info.get("action", "").lower()
    if action == "toggle":
        action = "play-pause"
    if action not in _ALLOWED_ACTIONS:
        return web.json_response({"ok": False, "error": "unknown action"}, status=400)

    player = _state.get("player")
    if not player:
        return web.json_response({"ok": False, "error": "no active player"}, status=409)

    rc, _ = await run("playerctl", "-p", player, action)
    return web.json_response({"ok": rc == 0, "player": player, "action": action})


async def volume_get(_request: web.Request) -> web.Response:
    """Return PipeWire's default-sink volume as 0..1."""
    rc, out = await run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    if rc != 0 or "Volume:" not in out:
        return web.json_response({"ok": False, "volume": None}, status=502)
    # Output looks like "Volume: 0.50" or "Volume: 0.50 [MUTED]".
    try:
        token = out.split("Volume:", 1)[1].split()[0]
        vol = float(token)
        muted = "MUTED" in out
    except (IndexError, ValueError):
        return web.json_response({"ok": False, "volume": None}, status=502)
    return web.json_response({"ok": True, "volume": vol, "muted": muted})


async def volume_set(request: web.Request) -> web.Response:
    """POST {volume: 0..1} sets the default sink volume."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    raw = body.get("volume")
    try:
        vol = float(raw)
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "volume must be a number"}, status=400)
    vol = max(0.0, min(1.5, vol))   # wpctl caps internally; allow up to 150% boost
    rc, _ = await run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol:.3f}")
    return web.json_response({"ok": rc == 0, "volume": vol})


async def bluetooth_pair(_request: web.Request) -> web.Response:
    """Put the BT controller into discoverable+pairable mode for 60 s.

    The boombox runs as the user `jwc` who is in the `bluetooth` group, so
    bluetoothctl can flip these flags without sudo. The 60-second TTL is
    bluetoothctl's default; we just trigger it.
    """
    cmd_input = (
        "power on\n"
        "agent on\n"
        "default-agent\n"
        "discoverable on\n"
        "pairable on\n"
        "discoverable-timeout 60\n"
        "quit\n"
    )
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(cmd_input.encode()), timeout=4.0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return web.json_response({"ok": False, "message": "bluetoothctl timed out"}, status=504)
    if proc.returncode and proc.returncode != 0:
        return web.json_response({
            "ok": False,
            "message": (err.decode(errors="replace").splitlines() or ["bluetoothctl failed"])[-1],
        }, status=502)
    return web.json_response({
        "ok": True,
        "message": "discoverable for 60 s — pair from your phone now",
    })


async def karaoke_state(_request: web.Request) -> web.Response:
    """Return current karaoke state: which mics are available, whether the
    loopback module is loaded right now, and which source it's bridging."""
    rc, sources = await run("pactl", "list", "short", "sources")
    mics: list[dict] = []
    if rc == 0:
        for line in sources.splitlines():
            cols = line.split("\t")
            # cols: id, name, driver, format, state
            if len(cols) < 2:
                continue
            name = cols[1]
            # Skip monitor sources — those are output taps, not real mics.
            if name.endswith(".monitor"):
                continue
            mics.append({"name": name, "label": _short_mic_name(name)})

    # Look for an active module-loopback that we previously created.
    rc, modules = await run("pactl", "list", "short", "modules")
    on = False
    mic = None
    if rc == 0:
        for line in modules.splitlines():
            if "module-loopback" in line and "boombox-karaoke" in line:
                on = True
                m = _extract_arg(line, "source=")
                if m:
                    mic = m
                break

    return web.json_response({
        "ok": True,
        "available": len(mics) > 0,
        "on": on,
        "mic": mic,
        "mics": mics,
    })


def _short_mic_name(name: str) -> str:
    # Pretty-print a Pulse source name for a UI label.
    n = name.replace("alsa_input.", "").replace("usb-", "")
    n = n.split("__")[0]
    return n[:48]


def _extract_arg(haystack: str, key: str) -> str | None:
    idx = haystack.find(key)
    if idx < 0:
        return None
    rest = haystack[idx + len(key):]
    return rest.split()[0] if rest else None


async def karaoke_on(request: web.Request) -> web.Response:
    """POST {mic: "<source-name>"} (mic optional → default source).
    Loads a module-loopback bridging that source into the default sink with
    ~10 ms latency, tagged so we can find/unload it later."""
    try:
        body = await request.json() if request.body_exists else {}
    except Exception:
        body = {}
    mic = body.get("mic") if isinstance(body, dict) else None

    # Refuse if loopback already up — keeps the module list tidy.
    rc, modules = await run("pactl", "list", "short", "modules")
    if rc == 0 and "boombox-karaoke" in modules:
        return web.json_response({"ok": True, "on": True, "message": "already on"})

    args = [
        "pactl", "load-module", "module-loopback",
        "latency_msec=10",
        "sink=@DEFAULT_SINK@",
        "source_dont_move=true",
        "sink_dont_move=true",
        "sink_input_properties=media.name=boombox-karaoke",
    ]
    if mic:
        args.append(f"source={mic}")
    rc, out = await run(*args)
    if rc != 0:
        return web.json_response({"ok": False, "error": out or "load-module failed"}, status=502)
    return web.json_response({"ok": True, "on": True, "module_id": out.strip(), "mic": mic})


async def karaoke_off(_request: web.Request) -> web.Response:
    """Unload our karaoke loopback module(s). Tagged via media.name."""
    rc, modules = await run("pactl", "list", "short", "modules")
    if rc != 0:
        return web.json_response({"ok": False}, status=502)
    unloaded = 0
    for line in modules.splitlines():
        if "module-loopback" in line and "boombox-karaoke" in line:
            mid = line.split("\t", 1)[0]
            r2, _ = await run("pactl", "unload-module", mid)
            if r2 == 0:
                unloaded += 1
    return web.json_response({"ok": True, "on": False, "unloaded": unloaded})


async def sinks_list(_request: web.Request) -> web.Response:
    """List all PipeWire/Pulse sinks the user can route audio to."""
    rc, sinks = await run("pactl", "list", "short", "sinks")
    rc2, default = await run("pactl", "get-default-sink")
    items: list[dict] = []
    if rc == 0:
        for line in sinks.splitlines():
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            name = cols[1]
            items.append({
                "name": name,
                "label": _short_sink_name(name),
                "default": name == default,
                "state": cols[4] if len(cols) >= 5 else "",
            })
    return web.json_response({"ok": True, "default": default if rc2 == 0 else None, "sinks": items})


def _short_sink_name(name: str) -> str:
    n = name
    if n.startswith("alsa_output."):
        n = n[len("alsa_output."):]
    if n.startswith("bluez_output."):
        n = "BT · " + n[len("bluez_output."):]
    # Common Pi DAC name → friendly
    if "platform-soc" in n and "stereo-fallback" in n:
        return "Built-in DAC"
    if "platform-107c706400.hdmi" in n or "hdmi" in n:
        return "HDMI"
    return n[:36]


async def sinks_set_default(request: web.Request) -> web.Response:
    """POST {name: "<sink>"} sets the default sink and moves existing inputs."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    name = (body or {}).get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name:
        return web.json_response({"ok": False, "error": "name required"}, status=400)
    rc, out = await run("pactl", "set-default-sink", name)
    if rc != 0:
        return web.json_response({"ok": False, "error": out or "set-default-sink failed"}, status=502)
    # Move existing streams to the new sink so what's playing keeps playing.
    rc2, inputs = await run("pactl", "list", "short", "sink-inputs")
    if rc2 == 0:
        for line in inputs.splitlines():
            cols = line.split("\t")
            if not cols:
                continue
            sid = cols[0]
            await run("pactl", "move-sink-input", sid, name)
    return web.json_response({"ok": True, "default": name})


_ART_CACHE: dict[str, dict] = {}
_ART_TTL_S = 60 * 60 * 24  # one day


async def album_art(request: web.Request) -> web.Response:
    """Look up album artwork via iTunes Search.

    Query params: ?artist=X&album=Y or ?artist=X&track=Z. Returns a JSON
    {url: <https-url-or-null>, source: "itunes"|"cache"|"none"}. Cached in
    memory keyed by (artist|album) for 24 h. The boombox is online via WiFi
    in the user's home, but failures (no network, rate limit, no match) are
    silently null so callers can render a fallback gradient.
    """
    artist = (request.query.get("artist") or "").strip()
    album = (request.query.get("album") or "").strip()
    track = (request.query.get("track") or "").strip()
    if not artist and not album and not track:
        return web.json_response({"url": None, "source": "none"})

    key = f"{artist.lower()}|{album.lower()}|{track.lower()}"
    now = time.time()
    cached = _ART_CACHE.get(key)
    if cached and now - cached.get("at", 0) < _ART_TTL_S:
        return web.json_response({"url": cached["url"], "source": "cache"})

    # iTunes resolves `term=` against multiple fields, so just hand it the
    # artist + album/track concatenated.
    parts = [p for p in (artist, album or track) if p]
    if not parts:
        return web.json_response({"url": None, "source": "none"})
    from urllib.parse import quote
    term = " ".join(parts)
    entity = "album" if album else "song"
    url = f"https://itunes.apple.com/search?term={quote(term)}&entity={entity}&limit=1"

    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.get(url) as r:
                if r.status != 200:
                    raise RuntimeError(f"itunes status {r.status}")
                data = await r.json(content_type=None)
        first = (data.get("results") or [None])[0]
        if not first:
            _ART_CACHE[key] = {"url": None, "at": now}
            return web.json_response({"url": None, "source": "itunes"})
        # iTunes returns 100x100 by default; swap for a higher-resolution.
        thumb = first.get("artworkUrl100") or first.get("artworkUrl60")
        big = thumb.replace("100x100bb.jpg", "300x300bb.jpg") if thumb else None
        _ART_CACHE[key] = {"url": big, "at": now}
        return web.json_response({"url": big, "source": "itunes"})
    except Exception as e:
        log.info("art lookup failed for %s: %s", term, e)
        _ART_CACHE[key] = {"url": None, "at": now}
        return web.json_response({"url": None, "source": "none"})


_LYRICS_CACHE: dict[str, dict] = {}
_LYRICS_TTL_S = 60 * 60 * 24 * 7  # week


async def lyrics(request: web.Request) -> web.Response:
    """Look up plain-text lyrics for an artist+title via Lyrics.ovh.

    Free, no key, ~300-1000 ms typical response. Cached server-side for a
    week; the UI tolerates a `null` response cleanly when no match exists.
    """
    artist = (request.query.get("artist") or "").strip()
    title  = (request.query.get("title")  or "").strip()
    if not artist or not title:
        return web.json_response({"lyrics": None, "source": "none"})

    key = f"{artist.lower()}|{title.lower()}"
    now = time.time()
    cached = _LYRICS_CACHE.get(key)
    if cached and now - cached.get("at", 0) < _LYRICS_TTL_S:
        return web.json_response({"lyrics": cached["lyrics"], "source": "cache"})

    # Try a few normalisations of the artist string. Lyrics.ovh 404s on names
    # with slashes (`AC/DC`) but accepts dashes (`AC-DC`); also strip
    # parenthetical "(feat. X)" / "(2003 Remaster)" from titles for better
    # match rates.
    from urllib.parse import quote
    import re
    artist_variants: list[str] = [artist]
    if "/" in artist:
        artist_variants.append(artist.replace("/", "-"))
        artist_variants.append(artist.replace("/", " "))
    title_clean = re.sub(r"\s*\((feat\.|featuring|with) [^)]*\)", "", title, flags=re.I).strip()
    title_clean = re.sub(r"\s*\(\d{4}.*\)", "", title_clean).strip()
    title_variants: list[str] = [title]
    if title_clean and title_clean != title:
        title_variants.append(title_clean)

    text: str | None = None
    last_err: str | None = None
    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            for a in artist_variants:
                for t in title_variants:
                    url = f"https://api.lyrics.ovh/v1/{quote(a)}/{quote(t)}"
                    try:
                        async with sess.get(url) as r:
                            if r.status != 200:
                                last_err = f"status {r.status}"
                                continue
                            data = await r.json(content_type=None)
                    except Exception as e:
                        last_err = str(e); continue
                    text = (data.get("lyrics") or "").strip() or None
                    if text:
                        break
                if text:
                    break
    except Exception as e:
        last_err = str(e)

    _LYRICS_CACHE[key] = {"lyrics": text, "at": now}
    if text:
        return web.json_response({"lyrics": text, "source": "lyrics.ovh"})
    log.info("lyrics lookup empty for %s — %s (%s)", artist, title, last_err or "no match")
    return web.json_response({"lyrics": None, "source": "none"})


async def info(_request: web.Request) -> web.Response:
    """Return device-identity + network strings the UI surfaces."""
    rc, hostname = await run("hostname")
    rc2, ips = await run("hostname", "-I")
    rc3, uptime = await run("uptime", "-p")
    # Read CPU temp if available (Pi exposes it via thermal_zone0).
    temp_c: float | None = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp_c = int(f.read().strip()) / 1000.0
    except Exception:
        pass
    return web.json_response({
        "hostname": hostname or "boombox",
        "ips": (ips or "").split(),
        "uptime": uptime or "",
        "temp_c": temp_c,
        "airplay_name": "Boombox",
        "spotify_name": "Boombox",
        "bluetooth_name": hostname or "boombox",
    })


async def mopidy_restart(_request: web.Request) -> web.Response:
    """Restart the Mopidy systemd service. Useful when playback wedges and
    a click is faster than SSH-and-systemctl. Also kicks the resume service
    so its snapshot-based restore re-runs against the freshly-booted Mopidy."""
    rc, _ = await run("sudo", "-n", "systemctl", "restart", "mopidy", timeout=10)
    if rc != 0:
        # Fallback: try systemctl --user (some setups host Mopidy as user unit)
        rc2, _ = await run("systemctl", "--user", "restart", "mopidy", timeout=10)
        if rc2 != 0:
            return web.json_response({"ok": False, "error": "restart failed (sudo and --user both rejected)"}, status=502)
    # Best-effort: bounce the resume service so its startup-restore logic runs
    # against the freshly-booted Mopidy. We don't fail the request if it isn't
    # installed.
    await run("systemctl", "--user", "restart", "boombox-resume.service", timeout=4)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Access (/upload, /usb, /library) — toggle the upload service, list mounted
# USB drives, copy files to/from them, and trigger a Mopidy library rescan.
# ---------------------------------------------------------------------------

UPLOADER_UNIT = "boombox-uploader.service"
HOME = Path(os.path.expanduser("~"))
MUSIC_ROOT = Path(os.environ.get("BOOMBOX_MUSIC_DIR", HOME / "Music"))
USB_LINKS_DIR = MUSIC_ROOT / ".usb"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
UPLOADER_PIN_FILE = RUNTIME_DIR / "boombox-uploader.pin"
WEB_AUTH_ENV = Path(os.environ.get("BOOMBOX_WEB_AUTH_ENV", "/etc/boombox/web-auth.env"))


def _read_web_auth() -> dict[str, str]:
    """Read the LAN web/SMB credential generated by install.sh.

    Missing file is tolerated so dev installs and older Pi images still work.
    """
    data = {
        "port": os.environ.get("BOOMBOX_WEB_PORT", "8090"),
        "user": os.environ.get("BOOMBOX_WEB_USER", "boombox"),
        "password": os.environ.get("BOOMBOX_WEB_PASSWORD", ""),
        "smb_user": os.environ.get("BOOMBOX_SMB_USER", os.environ.get("USER", "jwc")),
    }
    try:
        for raw in WEB_AUTH_ENV.read_text().splitlines():
            if not raw or raw.strip().startswith("#") or "=" not in raw:
                continue
            key, val = raw.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key == "BOOMBOX_WEB_PORT" and not os.environ.get("BOOMBOX_WEB_PORT"):
                data["port"] = val
            elif key == "BOOMBOX_WEB_USER" and not os.environ.get("BOOMBOX_WEB_USER"):
                data["user"] = val
            elif key == "BOOMBOX_WEB_PASSWORD" and not os.environ.get("BOOMBOX_WEB_PASSWORD"):
                data["password"] = val
            elif key == "BOOMBOX_SMB_USER" and not os.environ.get("BOOMBOX_SMB_USER"):
                data["smb_user"] = val
    except OSError:
        pass
    return data


def _web_url(ip: str, path: str = "/") -> str:
    auth = _read_web_auth()
    port = auth.get("port") or "8090"
    suffix = "" if port == "80" else f":{port}"
    return f"http://{ip}{suffix}{path}"


async def _systemctl_user(*args: str, timeout: float = 5.0) -> tuple[int, str]:
    return await run("systemctl", "--user", *args, timeout=timeout)


async def _read_pin() -> str:
    """Return the live uploader PIN, or '' if the service isn't running."""
    try:
        return UPLOADER_PIN_FILE.read_text().strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


async def _primary_lan_ip() -> str:
    rc, out = await run("hostname", "-I")
    if rc != 0:
        return ""
    parts = (out or "").split()
    # Prefer the first non-loopback IPv4.
    for p in parts:
        if "." in p and not p.startswith("127."):
            return p
    return parts[0] if parts else ""


async def upload_status(_request: web.Request) -> web.Response:
    rc, _ = await _systemctl_user("is-active", "--quiet", UPLOADER_UNIT)
    enabled = rc == 0
    pin = await _read_pin() if enabled else ""
    ip = await _primary_lan_ip()
    auth = _read_web_auth()
    return web.json_response({
        "enabled": enabled,
        "pin": pin,
        "url": _web_url(ip, "/upload/") if ip else "",
        "ip": ip,
        "web_port": auth.get("port") or "8090",
        "web_user": auth.get("user") or "boombox",
        "web_password": auth.get("password") or "",
        "smb_user": auth.get("smb_user") or "",
        "smb_url": f"smb://{ip}/boombox-music" if ip else "",
    })


async def upload_enable(_request: web.Request) -> web.Response:
    rc, out = await _systemctl_user("start", UPLOADER_UNIT, timeout=10)
    if rc != 0:
        return web.json_response({"ok": False, "error": out or "systemctl failed"}, status=502)
    # Wait briefly for the service to lay down its PIN file.
    for _ in range(20):
        if UPLOADER_PIN_FILE.exists():
            break
        await asyncio.sleep(0.1)
    return await upload_status(_request)


async def upload_disable(_request: web.Request) -> web.Response:
    rc, out = await _systemctl_user("stop", UPLOADER_UNIT, timeout=10)
    if rc != 0:
        return web.json_response({"ok": False, "error": out or "systemctl failed"}, status=502)
    # Belt-and-braces: the unit's ExecStopPost should remove the PIN file too.
    UPLOADER_PIN_FILE.unlink(missing_ok=True)
    return web.json_response({"enabled": False, "pin": "", "url": "", "ip": ""})


async def usb_devices(_request: web.Request) -> web.Response:
    """List mounted USB drives via the symlinks in MUSIC_ROOT/.usb/.

    Each entry: {id, label, mountpoint, total_bytes, used_bytes, free_bytes}.
    """
    devs: list[dict] = []
    if USB_LINKS_DIR.is_dir():
        for link in sorted(USB_LINKS_DIR.iterdir()):
            try:
                if not link.is_symlink():
                    continue
                target = link.resolve()
                if not target.is_dir():
                    continue
                usage = shutil.disk_usage(target)
                devs.append({
                    "id": link.name,
                    "label": link.name,
                    "mountpoint": str(target),
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                })
            except (OSError, ValueError) as e:
                log.debug("skipping usb entry %s: %s", link, e)
    return web.json_response({"devices": devs})


AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wav", ".aiff", ".alac", ".wma",
}


def _enumerate_audio(root: Path, skip_dirs: tuple[str, ...] = (".usb",)) -> list[Path]:
    """Return every audio file under root, skipping nested USB symlinks."""
    out: list[Path] = []
    for p in root.rglob("*"):
        try:
            # Don't recurse back into linked drives if root is the music dir.
            if any(part in skip_dirs for part in p.relative_to(root).parts):
                continue
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                out.append(p)
        except (OSError, ValueError):
            continue
    return out


async def usb_copy(request: web.Request) -> web.Response:
    """Copy files between a USB drive and the local library.

    JSON body: {
        direction: "to-library" | "to-drive",
        device_id: "<id from /usb/devices>",
        items?: ["relative/path", ...]   # paths relative to the source root.
                                         # If omitted/empty, copies every audio
                                         # file under the source root.
    }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    direction = body.get("direction")
    device_id = body.get("device_id")
    items = body.get("items")
    if direction not in ("to-library", "to-drive") or not device_id:
        return web.json_response({"error": "missing direction/device_id"}, status=400)

    link = USB_LINKS_DIR / device_id
    if not link.is_symlink():
        return web.json_response({"error": "unknown device"}, status=404)
    drive_root = link.resolve()
    if not drive_root.is_dir():
        return web.json_response({"error": "device not mounted"}, status=410)

    if direction == "to-library":
        src_root, dst_root = drive_root, MUSIC_ROOT / "from-usb" / device_id
        dst_anchor = MUSIC_ROOT
    else:
        src_root, dst_root = MUSIC_ROOT, drive_root / "from-boombox"
        dst_anchor = drive_root

    dst_root.mkdir(parents=True, exist_ok=True)

    # Build the work list.
    if items and isinstance(items, list):
        sources: list[Path] = []
        for rel in items:
            if not isinstance(rel, str) or not rel:
                continue
            sources.append(src_root / rel)
    else:
        sources = await asyncio.to_thread(_enumerate_audio, src_root)

    copied: list[str] = []
    errors: list[dict] = []
    for src in sources:
        try:
            real_src = src.resolve()
            real_src.relative_to(src_root.resolve())
        except ValueError:
            errors.append({"item": str(src), "error": "outside source root"})
            continue
        except OSError as e:
            errors.append({"item": str(src), "error": str(e)})
            continue
        if not real_src.is_file():
            errors.append({"item": str(src), "error": "not a file"})
            continue
        dst = dst_root / real_src.name
        n = 1
        while dst.exists():
            dst = dst_root / f"{real_src.stem}-{n}{real_src.suffix}"
            n += 1
        try:
            await asyncio.to_thread(shutil.copy2, real_src, dst)
            copied.append(str(dst.relative_to(dst_anchor)))
        except OSError as e:
            errors.append({"item": str(src), "error": str(e)})

    if direction == "to-library" and copied:
        asyncio.create_task(_scan_library())

    return web.json_response({"copied": copied, "errors": errors})


async def _scan_library() -> bool:
    """Run mopidyctl local scan if available. Sudoers must allow NOPASSWD.

    Returns True iff a scan was successfully started/completed.
    """
    rc, _ = await run("sudo", "-n", "/usr/sbin/mopidyctl", "local", "scan", timeout=300)
    if rc == 0:
        return True
    rc2, _ = await run("sudo", "-n", "/usr/bin/mopidyctl", "local", "scan", timeout=300)
    return rc2 == 0


async def library_scan(_request: web.Request) -> web.Response:
    ok = await _scan_library()
    return web.json_response({"ok": ok})


# ---------------------------------------------------------------------------
# Theme — the kiosk SPA POSTs the active skin's palette here so external
# surfaces (the LAN remote/upload page) can render in matching colors.
# ---------------------------------------------------------------------------

THEME_FILE = Path(os.environ.get(
    "BOOMBOX_THEME_FILE",
    str(HOME / ".local/state/boombox/active-theme.json"),
))

DEFAULT_THEME = {
    "skinId": "simple",
    "name": "Simple",
    "theme": {
        "bg": "#07060c", "panel": "#100d1c", "ink": "#f3f1ff", "ink2": "#9892b8",
        "accent": "#8b5cf6", "accent2": "#5be7ff", "rule": "rgba(255,255,255,0.08)",
        "font": "'Inter', system-ui, -apple-system, sans-serif",
        "mono": "'JetBrains Mono', ui-monospace, monospace",
    },
}


async def theme_get(_request: web.Request) -> web.Response:
    try:
        import json
        return web.json_response(json.loads(THEME_FILE.read_text()))
    except (FileNotFoundError, OSError, ValueError):
        return web.json_response(DEFAULT_THEME)


async def theme_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict) or "theme" not in body:
        return web.json_response({"error": "missing theme"}, status=400)
    THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    THEME_FILE.write_text(json.dumps(body))
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# OSK (on-screen keyboard) — toggles the hidden wvkbd instance via signals.
# SIGUSR1 hides, SIGUSR2 shows. The kiosk extension posts here on text-input
# focus / blur so any page (Jellyfin's login, the boombox remote, etc.) gets
# a keyboard automatically on the touchscreen.
# ---------------------------------------------------------------------------

import signal


async def _signal_wvkbd(sig: int) -> bool:
    """Send `sig` to every running wvkbd-mobintl process. Returns True iff at
    least one process was signaled."""
    rc, out = await run("pgrep", "-x", "wvkbd-mobintl")
    if rc != 0 or not out:
        return False
    sent = False
    for pid_s in out.splitlines():
        try:
            os.kill(int(pid_s.strip()), sig)
            sent = True
        except (ProcessLookupError, ValueError, PermissionError) as e:
            log.debug("osk: kill(%s, %d) failed: %s", pid_s, sig, e)
    return sent


async def osk_show(_request: web.Request) -> web.Response:
    ok = await _signal_wvkbd(signal.SIGUSR2)
    return web.json_response({"ok": ok})


async def osk_hide(_request: web.Request) -> web.Response:
    ok = await _signal_wvkbd(signal.SIGUSR1)
    return web.json_response({"ok": ok})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/state", state_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/control/{action}", control_handler)
    app.router.add_get("/volume", volume_get)
    app.router.add_post("/volume", volume_set)
    app.router.add_post("/bluetooth/pair", bluetooth_pair)
    app.router.add_get("/karaoke", karaoke_state)
    app.router.add_post("/karaoke/on", karaoke_on)
    app.router.add_post("/karaoke/off", karaoke_off)
    app.router.add_get("/sinks", sinks_list)
    app.router.add_post("/sinks/default", sinks_set_default)
    app.router.add_get("/info", info)
    app.router.add_get("/art", album_art)
    app.router.add_get("/lyrics", lyrics)
    app.router.add_post("/mopidy/restart", mopidy_restart)
    # Access (upload + USB)
    app.router.add_get("/upload/status", upload_status)
    app.router.add_post("/upload/enable", upload_enable)
    app.router.add_post("/upload/disable", upload_disable)
    app.router.add_get("/usb/devices", usb_devices)
    app.router.add_post("/usb/copy", usb_copy)
    app.router.add_post("/library/scan", library_scan)
    app.router.add_get("/theme", theme_get)
    app.router.add_post("/theme", theme_post)
    app.router.add_post("/osk/show", osk_show)
    app.router.add_post("/osk/hide", osk_hide)
    return app


async def main():
    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 6681)
    await site.start()
    log.info("boombox-state listening on http://127.0.0.1:6681/state")
    await poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
