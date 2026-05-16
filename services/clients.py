"""Backend clients used by the boombox action dispatcher.

Each class is a thin async wrapper over an upstream service:
- MopidyRpc:    Mopidy's JSON-RPC at :6680
- StateApi:     boombox-state aggregator at :6681
- KioskClient:  Chromium DevTools WS at :9222
- Display:      wlr-randr backlight on/off
- SleepTimer:   in-process sleep-timer state machine
- Recorder:     parec -> flac subprocess manager
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger("boombox-buttons")

MOPIDY_RPC = "http://127.0.0.1:6680/mopidy/rpc"
STATE_BASE = "http://127.0.0.1:6681"
KIOSK_DEBUG = "http://127.0.0.1:9222"


class MopidyRpc:
    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session
        self._id = 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        try:
            async with self._sess.post(MOPIDY_RPC, json=body,
                                       timeout=aiohttp.ClientTimeout(total=2)) as r:
                if r.status != 200:
                    return {}
                return await r.json(content_type=None)
        except Exception as e:
            log.warning("mopidy.%s failed: %s", method, e)
            return {}


class StateApi:
    """Thin client for the boombox-state aggregator at :6681.

    `current_source()` returns the lowercase friendly source name
    ('mopidy', 'airplay', 'spotify', 'bluetooth') or None when nothing is
    playing.
    """

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    async def current_source(self) -> str | None:
        try:
            async with self._sess.get(f"{STATE_BASE}/state",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                if r.status != 200:
                    return None
                body = await r.json()
        except Exception:
            return None
        label = (body.get("label") or "").lower()
        return label or None

    async def active_external(self) -> str | None:
        """Returns the active non-Mopidy source label only when it's actually
        playing or paused. Mirrors the SPA's isExternalActive() — a stopped
        external (e.g. AirPlay after the iPhone disconnects) returns None so
        callers can fall back to Mopidy instead of routing dead commands to
        an MPRIS player that won't react."""
        try:
            async with self._sess.get(f"{STATE_BASE}/state",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                if r.status != 200:
                    return None
                body = await r.json()
        except Exception:
            return None
        label = (body.get("label") or "").lower()
        status = (body.get("status") or "").lower()
        if not label or status not in ("playing", "paused"):
            return None
        return label

    async def control(self, action: str) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/control/{action}",
                                   timeout=aiohttp.ClientTimeout(total=2))
        except Exception as e:
            log.warning("state.control(%s) failed: %s", action, e)

    async def volume_get(self) -> tuple[float, bool] | None:
        try:
            async with self._sess.get(f"{STATE_BASE}/volume",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                body = await r.json()
                if not body.get("ok"):
                    return None
                return float(body["volume"]), bool(body.get("muted"))
        except Exception:
            return None

    async def volume_set(self, volume: float) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/volume", json={"volume": volume},
                                  timeout=aiohttp.ClientTimeout(total=1))
        except Exception as e:
            log.warning("state.volume_set failed: %s", e)

    async def mute_toggle(self) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/volume/mute",
                                  timeout=aiohttp.ClientTimeout(total=1))
        except Exception as e:
            log.warning("state.mute_toggle failed: %s", e)

    async def karaoke_state(self) -> bool:
        try:
            async with self._sess.get(f"{STATE_BASE}/karaoke",
                                      timeout=aiohttp.ClientTimeout(total=1)) as r:
                body = await r.json()
                return bool(body.get("on"))
        except Exception:
            return False

    async def karaoke_toggle(self) -> None:
        on = await self.karaoke_state()
        path = "/karaoke/off" if on else "/karaoke/on"
        try:
            await self._sess.post(f"{STATE_BASE}{path}",
                                  timeout=aiohttp.ClientTimeout(total=2))
        except Exception as e:
            log.warning("state.karaoke_toggle failed: %s", e)

    async def bluetooth_pair(self) -> None:
        try:
            await self._sess.post(f"{STATE_BASE}/bluetooth/pair",
                                  timeout=aiohttp.ClientTimeout(total=5))
        except Exception as e:
            log.warning("state.bluetooth_pair failed: %s", e)

    async def album_art_url(
        self, artist: str | None, album: str | None, track: str | None,
    ) -> str | None:
        """Resolve album art via boombox-state's iTunes lookup. Returns a
        public https URL or None. boombox-state caches lookups in-process
        for 24 h.

        Lookup order:
          1. (artist, album) — shares the kiosk's cache key
          2. (artist, album-stripped) — drops a trailing parenthesised
             qualifier so "AC/DC Live (Disk One)" matches the canonical
             "AC/DC Live" iTunes entry
          3. (artist, track) — song-entity search; catches reissues that
             have unique track names but messy album metadata
          4. fallback to track-only or artist-only as last resort
        iTunes failures (timeout, 404, no match) become None and the
        caller renders the no-art placeholder."""
        if not (artist or album or track):
            return None

        async def _lookup(params: dict[str, str]) -> str | None:
            try:
                async with self._sess.get(
                        f"{STATE_BASE}/art", params=params,
                        timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status != 200:
                        return None
                    body = await r.json()
            except Exception:
                return None
            url = body.get("url")
            return url if isinstance(url, str) else None

        if artist and album:
            url = await _lookup({"artist": artist, "album": album})
            if url:
                return url
            stripped = _strip_album_qualifier(album)
            if stripped and stripped != album:
                url = await _lookup({"artist": artist, "album": stripped})
                if url:
                    return url
        if artist and track:
            return await _lookup({"artist": artist, "track": track})
        if track:
            return await _lookup({"track": track})
        if artist:
            return await _lookup({"artist": artist})
        return None


_ALBUM_QUALIFIER_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*$")


def _strip_album_qualifier(name: str) -> str:
    """Remove a trailing parenthesised qualifier from an album name so
    "AC/DC Live (Disk One)" or "Houses of the Holy [Remastered]" match
    the canonical iTunes catalog entry. Only strips from the END to
    avoid breaking albums that legitimately open with parens, like
    "(What's the Story) Morning Glory?"."""
    return _ALBUM_QUALIFIER_RE.sub("", name).strip()


class KioskClient:
    """DevTools client for the Chromium kiosk on :9222. Drives navigation
    and runs JS in the kiosk tab. Used for source overlays, swap-to-Jellyfin,
    QR code, sleep OSD, etc."""

    def __init__(self, session: aiohttp.ClientSession):
        self._sess = session

    async def _tab(self) -> dict | None:
        try:
            async with self._sess.get(f"{KIOSK_DEBUG}/json",
                                       timeout=aiohttp.ClientTimeout(total=1)) as r:
                tabs = await r.json()
                for t in tabs:
                    if t.get("type") == "page":
                        return t
        except Exception:
            return None
        return None

    async def navigate(self, url: str) -> None:
        tab = await self._tab()
        if not tab:
            return
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        try:
            import websockets
            async with websockets.connect(ws_url, open_timeout=2, max_size=2**24) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Page.navigate",
                                           "params": {"url": url}}))
        except Exception as e:
            log.warning("kiosk.navigate(%s) failed: %s", url, e)

    async def emit(self, event: str, detail: dict | None = None) -> None:
        """Dispatch a custom DOM event on the kiosk page so the SPA can
        react (overlay mount/unmount). The SPA listens on
        window.addEventListener('boombox:<event>')."""
        tab = await self._tab()
        if not tab:
            return
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return
        script = (
            f"window.dispatchEvent(new CustomEvent('boombox:{event}', "
            f"{{detail: {json.dumps(detail or {})}}}))"
        )
        try:
            import websockets
            async with websockets.connect(ws_url, open_timeout=2, max_size=2**24) as ws:
                await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                          "params": {"expression": script}}))
        except Exception as e:
            log.warning("kiosk.emit(%s) failed: %s", event, e)


class Display:
    """Wayland backlight control via wlr-randr. Async subprocess calls.

    On the kiosk, `wlr-randr` returns the active output's name on its first
    line. We cache it after the first call."""

    def __init__(self):
        self._output: str | None = None
        self._on: bool = True

    async def _detect_output(self) -> str | None:
        """Return the cached Wayland output name; query wlr-randr on first call.

        We pick the first non-indented line of wlr-randr's output, which is the
        connected output's name. Assumes one panel (the kiosk's DSI-1 in this
        build). If multiple outputs are connected, the kiosk should still be on
        the first; multi-output is out of scope.
        """
        if self._output:
            return self._output
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("wlr-randr failed (%s): %s",
                        proc.returncode, err.decode(errors="replace").strip())
            return None
        for line in out.decode().splitlines():
            if line and not line.startswith(" "):
                self._output = line.split()[0]
                return self._output
        return None

    async def toggle(self) -> None:
        out = await self._detect_output()
        if not out:
            return
        new = "off" if self._on else "on"
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr", "--output", out, "--" + new,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("wlr-randr --%s failed (%s): %s", new, proc.returncode,
                        err.decode(errors="replace").strip())
            return
        self._on = not self._on

    async def wake(self) -> None:
        out = await self._detect_output()
        if not out:
            return
        # Always send --on. If the display is already on, wlr-randr is a no-op;
        # if our cached _on state is stale (external tooling toggled the panel),
        # this still does the right thing.
        proc = await asyncio.create_subprocess_exec(
            "wlr-randr", "--output", out, "--on",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("wlr-randr --on failed (%s): %s", proc.returncode,
                        err.decode(errors="replace").strip())
            return
        self._on = True

    @property
    def is_on(self) -> bool:
        """Public read-only view of the cached backlight state. Used by the
        sleep-timer expire path so we only invoke toggle() when the screen is
        currently on (avoids waking an already-asleep panel)."""
        return self._on


class SleepTimer:
    """Cycles 15 -> 30 -> 60 -> off -> 15 (subsequent presses within 3s
    cycle the duration; otherwise the first press sets the next value).
    Long-press cancels.

    Fires by calling on_expire() (set externally). The dispatcher hooks
    in pause + display sleep + kiosk OSD events at startup."""

    _CYCLE = [15, 30, 60, None]

    def __init__(self, on_expire: Callable[[], Awaitable[None]]):
        self._on_expire = on_expire
        self._idx: int = -1            # -1 = inactive
        self._task: asyncio.Task | None = None
        self._last_press_ms: int | None = None

    @property
    def active_minutes(self) -> int | None:
        if self._idx < 0:
            return None
        return self._CYCLE[self._idx]

    async def press(self, t_ms: int) -> int | None:
        """Returns the new value in minutes, or None when cycled to off."""
        if self._last_press_ms is not None and (t_ms - self._last_press_ms) <= 3000:
            self._idx = (self._idx + 1) % len(self._CYCLE)
        else:
            self._idx = 0
        self._last_press_ms = t_ms
        await self._reschedule()
        return self.active_minutes

    async def cancel(self) -> None:
        self._idx = -1
        await self._reschedule()

    async def _reschedule(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        mins = self.active_minutes
        if mins is None:
            return
        async def _runner():
            try:
                await asyncio.sleep(mins * 60)
                await self._on_expire()
            except asyncio.CancelledError:
                return
        self._task = asyncio.create_task(_runner())


class Recorder:
    """Captures the current default PipeWire sink's monitor to FLAC.
    Start = spawn `parec | flac -`. Stop = SIGTERM the pipeline.

    Output: ~/Music/Recordings/YYYY-MM-DD-HHMMSS.flac
    """

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._flac: asyncio.subprocess.Process | None = None
        self._path: str | None = None

    @property
    def recording(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> str | None:
        if self.recording:
            return self._path
        from datetime import datetime
        rec_dir = Path.home() / "Music" / "Recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = rec_dir / f"{ts}.flac"
        self._path = str(out)
        # parec → flac via a real OS pipe. We can't use asyncio's PIPE here
        # because asyncio gives back a StreamReader for parec.stdout and
        # asyncio.create_subprocess_exec rejects non-fileno stdin.
        # --monitor-stream takes an INDEX (not a sink name); use --device
        # with @DEFAULT_MONITOR@ to read the default sink's monitor source.
        # flac reading raw PCM from stdin needs explicit format flags.
        read_fd, write_fd = os.pipe()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "parec", "--device=@DEFAULT_MONITOR@",
                "--format=s16le", "--rate=44100", "--channels=2",
                stdout=write_fd, stderr=asyncio.subprocess.DEVNULL,
            )
            self._flac = await asyncio.create_subprocess_exec(
                "flac", "--silent",
                "--endian=little", "--sign=signed",
                "--channels=2", "--bps=16", "--sample-rate=44100",
                "-", "-o", str(out),
                stdin=read_fd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        finally:
            # Each subprocess inherits its end; close our parent-side copies
            # so EOF propagates correctly when parec exits.
            os.close(write_fd)
            os.close(read_fd)
        return self._path

    async def stop(self) -> str | None:
        path = self._path
        for p in (self._proc, self._flac):
            if p is not None and p.returncode is None:
                p.terminate()
                try:
                    await asyncio.wait_for(p.wait(), timeout=3)
                except asyncio.TimeoutError:
                    p.kill()
        self._proc = None
        self._flac = None
        self._path = None
        return path
