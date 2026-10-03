"""What the download scheduler checks before each start (spec 2A): SoC
temperature, free space, and whether Mopidy is playing a boombox-library
stream-proxy URI. Every probe degrades to "no reason to wait" when its
source is absent — no thermal zone on a dev box, Mopidy down — per the
hardware-optional rule."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("boombox-library.gates")

THERMAL_PATH = Path("/sys/class/thermal/thermal_zone0/temp")
MOPIDY_RPC = os.environ.get("BOOMBOX_MOPIDY_RPC", "http://127.0.0.1:6680/mopidy/rpc")
STREAM_MARKER = "/api/library/stream/"
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=2)


def read_soc_temp_c(path: Path = THERMAL_PATH) -> Optional[float]:
    """SoC temperature in °C from a sysfs thermal zone (millidegrees), or
    None when the file is absent or unreadable."""
    try:
        return int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def free_bytes(path: Path) -> Optional[int]:
    """Bytes available to us on path's filesystem, or None if unknown."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return st.f_bavail * st.f_frsize


class MopidyStreamProbe:
    """is_streaming(): Mopidy is playing a stream-proxy URI right now."""

    def __init__(self, rpc_url: str = MOPIDY_RPC) -> None:
        self._rpc = rpc_url
        self._session: aiohttp.ClientSession | None = None

    async def _call(self, method: str) -> object:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_PROBE_TIMEOUT)
        async with self._session.post(
                self._rpc, json={"jsonrpc": "2.0", "id": 1, "method": method}) as r:
            body = await r.json(content_type=None)
        return body.get("result") if isinstance(body, dict) else None

    async def is_streaming(self) -> bool:
        try:
            if await self._call("core.playback.get_state") != "playing":
                return False
            track = await self._call("core.playback.get_current_track")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.debug("mopidy probe failed: %s", type(e).__name__)
            return False
        uri = track.get("uri") if isinstance(track, dict) else None
        return isinstance(uri, str) and STREAM_MARKER in uri

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
