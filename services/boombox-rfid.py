#!/usr/bin/env python3
# services/boombox-rfid.py
"""boombox-rfid service entry point.

Wires together: evdev RFID reader → SQLite bindings lookup → Mopidy
playback. HTTP API on :6688 for bindings CRUD + recent-tap polling.

Resilient to: reader being unplugged (auto-reopens), Mopidy being down
(plays best-effort, logs and moves on), library DB being absent (won't
start — bindings live in library.db).
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time

from aiohttp import web
from boombox_library.config import load_config as load_library_config
from boombox_rfid import __version__
from boombox_rfid.api import build_app
from boombox_rfid.bindings import get_binding, record_tap
from boombox_rfid.config import LIBRARY_DB_PATH, load_config
from boombox_rfid.db import connect, migrate
from boombox_rfid.mopidy_client import MopidyClient
from boombox_rfid.playback import expand_to_track_ids, resolve_uris
from boombox_rfid.reader import auto_detect_device, read_uids

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-rfid")

PORT = 6688


class ServiceContext:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.conn = connect(LIBRARY_DB_PATH)
        migrate(self.conn)
        self._device_path: str = self.cfg.device_path or (auto_detect_device() or "")
        # Last *bound* tap (for /status); last *unbound* uid (for /recent).
        self.last_tap_uid: str = ""
        self.last_tap_ts: float = 0.0
        self.last_unbound_uid: str = ""
        self.last_unbound_ts: float = 0.0
        self._last_uid_seen: str = ""
        self._last_uid_at: float = 0.0

    def device_path(self) -> str:
        return self._device_path

    async def reader_loop(self) -> None:
        if not self.cfg.enabled:
            log.info("RFID disabled in config; reader loop skipped")
            return
        if not self._device_path:
            log.warning("no RFID reader device detected; reader loop disabled")
            return
        async for uid in read_uids(self._device_path):
            now = time.time()
            # Debounce: skip the same UID inside debounce window.
            if uid == self._last_uid_seen and (now - self._last_uid_at) * 1000 < self.cfg.debounce_ms:
                continue
            self._last_uid_seen = uid
            self._last_uid_at = now
            # Never let a tap handler crash kill the reader loop.
            try:
                await self._handle_tap(uid)
            except Exception:
                log.exception("_handle_tap raised for uid %s; continuing", uid)

    async def _handle_tap(self, uid: str) -> None:
        log.info("RFID tap: uid=%s", uid)
        try:
            binding = get_binding(self.conn, uid)
        except Exception:
            log.exception("get_binding failed for uid %s", uid)
            return
        log.info("binding lookup uid=%s → %s", uid, binding)
        if binding is None:
            # Unbound — remember for the UI to prompt the user.
            self.last_unbound_uid = uid
            self.last_unbound_ts = time.time()
            log.info("uid %s is unbound; surfacing via /api/rfid/recent", uid)
            return

        self.last_tap_uid = uid
        self.last_tap_ts = time.time()
        try:
            record_tap(self.conn, uid)
        except Exception:
            log.exception("record_tap failed for uid %s", uid)

        try:
            track_ids = expand_to_track_ids(self.conn, binding.kind, binding.target_id)
        except Exception:
            log.exception("expand_to_track_ids failed for uid %s", uid)
            return
        log.info("uid %s expanded to %d track ids", uid, len(track_ids))
        if not track_ids:
            log.warning("binding %s → %s/%s expanded to zero tracks",
                        uid, binding.kind.value, binding.target_id)
            return
        # Re-read library config every tap so freshly-saved creds take
        # effect without restarting boombox-rfid.
        lib_cfg = load_library_config()
        try:
            uris = resolve_uris(
                self.conn, track_ids, online=True,
                source_url=lib_cfg.source.url,
                source_username=lib_cfg.source.username,
                source_password=lib_cfg.source.password,
            )
        except Exception:
            log.exception("resolve_uris failed for uid %s", uid)
            return
        log.info("uid %s resolved %d/%d playable URIs", uid, len(uris), len(track_ids))
        if not uris:
            log.warning("no playable URIs for binding %s (offline?)", uid)
            return
        try:
            async with MopidyClient(self.cfg.mopidy_rpc) as m:
                await m.play_uris(uris)
            log.info("playing %d tracks for %s (binding %s/%s)",
                     len(uris), uid, binding.kind.value, binding.target_id)
        except Exception as e:
            log.exception("playback failed for uid %s: %s", uid, e)

    async def expire_recent(self) -> None:
        """Drop last_unbound_uid once its TTL is up so the UI overlay
        doesn't pop forever after the user walked away."""
        ttl_s = self.cfg.recent_ttl_ms / 1000.0
        while True:
            await asyncio.sleep(2)
            if self.last_unbound_uid and (time.time() - self.last_unbound_ts) > ttl_s:
                self.last_unbound_uid = ""


async def amain() -> None:
    ctx = ServiceContext()
    app = build_app(ctx)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    log.info("boombox-rfid %s listening on :%d (device=%s)",
             __version__, PORT, ctx.device_path() or "<none>")

    reader_task = asyncio.create_task(ctx.reader_loop())
    expire_task = asyncio.create_task(ctx.expire_recent())

    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    reader_task.cancel()
    expire_task.cancel()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
