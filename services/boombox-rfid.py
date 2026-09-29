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
from boombox_rfid.mopidy_client import MopidyClient, PendingTail
from boombox_rfid.playback import (
    expand_to_track_ids,
    resolve_uris,
    wait_for_stream_proxy,
)
from boombox_rfid.reader import auto_detect_device, read_uids
from queue_intent import clear_intent, write_intent

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
        # Background append of a long list's tail (see mopidy_client). One
        # at a time: a new tap cancels the previous card's tail.
        self._tail_task: asyncio.Task | None = None
        # A queue intent left by a previous run is no longer being built.
        clear_intent()

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
        # Whatever the previous card was still queueing no longer applies.
        self._cancel_tail()
        clear_intent()
        if not await wait_for_stream_proxy(uris):
            log.error("boombox-library stream proxy (127.0.0.1:6687) is down; "
                      "streamed tracks for %s will fail until it is back", uid)
        try:
            async with MopidyClient(self.cfg.mopidy_rpc) as m:
                tail = await m.play_uris(uris)
            log.info("playing %d tracks for %s (binding %s/%s)%s",
                     len(uris), uid, binding.kind.value, binding.target_id,
                     f"; queueing {len(tail.uris)} more in background" if tail else "")
        except Exception as e:
            log.exception("playback failed for uid %s: %s", uid, e)
            return
        if tail:
            # Let boombox-resume snapshot the whole card, not the partial
            # queue, while the tail is still streaming in (queue_intent.py).
            token: str | None = None
            try:
                token = write_intent(uris)
            except OSError as e:
                log.warning("could not record queue intent: %s", e)
            self._tail_task = asyncio.create_task(self._append_tail(uid, tail, token))

    def _cancel_tail(self) -> None:
        if self._tail_task and not self._tail_task.done():
            self._tail_task.cancel()
        self._tail_task = None

    async def _append_tail(self, uid: str, tail: PendingTail,
                           token: str | None = None) -> None:
        """Queue the rest of a long card without blocking the tap handler.

        The queue intent is dropped once the tail is done (or gave up). It is
        kept on cancellation: a new tap clears it itself, and on shutdown it
        should outlive us so resume's snapshot keeps the full card.
        """
        try:
            async with MopidyClient(self.cfg.mopidy_rpc) as m:
                n = await m.append_tail(tail)
            log.info("uid %s: queued %d/%d remaining tracks", uid, n, len(tail.uris))
        except asyncio.CancelledError:
            log.info("uid %s: background queueing superseded", uid)
            raise
        except Exception as e:
            log.warning("uid %s: background queueing failed: %s", uid, e)
        if token is not None:
            clear_intent(token)

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
    ctx._cancel_tail()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
