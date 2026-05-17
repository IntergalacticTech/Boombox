#!/usr/bin/env python3
# services/boombox-library.py
"""boombox-library service entry point.

Wires together: Subsonic client, SQLite catalog, pin manager + sidecar,
cache drive detection (poll loop), downloader queue, eviction, HTTP API
on port 6687.

The service is resilient to Navidrome being unreachable and to the
cache drive being absent or yanked. Both states surface via /api/library/health.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import replace
from pathlib import Path

from aiohttp import web

from boombox_library import __version__
from boombox_library.api import build_app
from boombox_library.cache_drive import (
    CacheDriveState, detect_cache_drive,
    update_symlink, remove_symlink,
    DEFAULT_SYMLINK,
)
from boombox_library.catalog import sync_full
from boombox_library.config import (
    CONFIG_PATH, LibraryConfig, load_config, save_config,
)
from boombox_library.db import connect, migrate
from boombox_library.downloader import DownloadQueue
from boombox_library.mopidy_config import write_subsonic_block, reload_mopidy
from boombox_library.pins import (
    all_pinned_track_ids, load_sidecar, reconcile_starred, write_sidecar,
)
from boombox_library.subsonic import (
    SubsonicAuthError, SubsonicClient, SubsonicUnreachable,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-library")

DB_PATH = Path("/opt/boombox/state/library.db")
MOPIDY_CONF = Path("/etc/mopidy/mopidy.conf")
CACHE_POLL_SECONDS = 5
PORT = 6687


class ServiceContext:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.conn = connect(DB_PATH)
        migrate(self.conn)
        self.cache_state: CacheDriveState = CacheDriveState(
            present=False, mount_path=None,
            free_bytes=None, total_bytes=None,
        )
        self._online = False
        self._sync_task: asyncio.Task | None = None
        self._download_queue: DownloadQueue | None = None
        # Phase 2: surfaced through /api/library/health for the UI's SyncIndicator
        self.last_sync_ts: float = 0.0
        self.syncing: bool = False
        self._load_sidecar_if_present()

    # ----- helpers exposed to api.py -----
    async def is_online(self) -> bool:
        return self._online

    def cache_drive_state(self) -> CacheDriveState:
        return self.cache_state

    def save_config(self, cfg: LibraryConfig) -> None:
        self.cfg = cfg
        save_config(cfg)
        write_subsonic_block(MOPIDY_CONF, cfg.source.url,
                             cfg.source.username, cfg.source.password)
        reload_mopidy()

    async def test_source(self, url: str, username: str, password: str) -> tuple[bool, str]:
        async with SubsonicClient(url, username, password) as c:
            try:
                await c.ping()
                return (True, "")
            except SubsonicAuthError as e:
                return (False, f"auth: {e}")
            except SubsonicUnreachable as e:
                return (False, f"unreachable: {e}")

    async def trigger_sync(self) -> None:
        if self._sync_task and not self._sync_task.done():
            return  # one at a time
        self._sync_task = asyncio.create_task(self._sync_once())

    # ----- background loops -----
    async def _sync_once(self) -> None:
        if not self.cfg.source.url:
            log.info("no source configured; skipping sync")
            return
        self.syncing = True
        try:
            async with SubsonicClient(self.cfg.source.url,
                                      self.cfg.source.username,
                                      self.cfg.source.password) as client:
                try:
                    await client.ping()
                    self._online = True
                except (SubsonicAuthError, SubsonicUnreachable) as e:
                    log.warning("ping failed: %s", e)
                    self._online = False
                    return
                try:
                    await sync_full(client, self.conn)
                    if self.cfg.sync.starred_auto_pin:
                        reconcile_starred(self.conn)
                    self._enqueue_pinned_downloads()
                    self._persist_pins_sidecar()
                    self.last_sync_ts = time.time()
                except Exception as e:
                    log.exception("sync failed: %s", e)
        finally:
            self.syncing = False

    async def sync_timer(self) -> None:
        # First-boot immediate sync
        try:
            await self.trigger_sync()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("initial sync trigger failed")
        while True:
            await asyncio.sleep(self.cfg.sync.interval_seconds)
            try:
                await self.trigger_sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("periodic sync trigger failed; will retry")

    async def cache_poll(self) -> None:
        while True:
            try:
                new_state = detect_cache_drive(
                    search_paths=[Path(p) for p in self.cfg.cache.search_paths],
                    marker=self.cfg.cache.marker_filename,
                )
                if new_state.mount_path != self.cache_state.mount_path:
                    # Adopted or detached
                    if new_state.present and new_state.mount_path:
                        log.info("cache drive present at %s", new_state.mount_path)
                        update_symlink(DEFAULT_SYMLINK, new_state.mount_path)
                        self._init_download_queue(new_state.mount_path)
                        self._load_sidecar_if_present()
                    else:
                        log.warning("cache drive lost")
                        remove_symlink(DEFAULT_SYMLINK)
                        self._download_queue = None
                self.cache_state = new_state
            except asyncio.CancelledError:
                raise  # Always re-raise CancelledError so shutdown works
            except Exception:
                log.exception("cache_poll iteration failed; will retry")
            await asyncio.sleep(CACHE_POLL_SECONDS)

    # ----- internals -----
    def _init_download_queue(self, mount: Path) -> None:
        if not self.cfg.source.url:
            return
        # Note: client lifetime is per-download in default_fetch — this
        # client is only used for download_url() construction.
        client = SubsonicClient(self.cfg.source.url,
                                self.cfg.source.username,
                                self.cfg.source.password)
        self._download_queue = DownloadQueue(
            conn=self.conn, client=client, cache_root=mount,
            max_concurrent=self.cfg.sync.max_concurrent_downloads,
        )

    def _enqueue_pinned_downloads(self) -> None:
        if self._download_queue is None:
            log.info("cache drive absent; pinned downloads deferred")
            return
        pinned = all_pinned_track_ids(self.conn)
        if not pinned:
            return
        # Only enqueue tracks not already present
        rows = self.conn.execute(
            "SELECT track_id FROM cache_state WHERE status='present'"
        )
        present = {r[0] for r in rows}
        for tid in pinned - present:
            self._download_queue.enqueue(tid)

    def _persist_pins_sidecar(self) -> None:
        if not self.cache_state.present or not self.cache_state.mount_path:
            return
        sidecar = self.cache_state.mount_path / "meta" / "pins.json"
        write_sidecar(self.conn, sidecar)

    def _load_sidecar_if_present(self) -> None:
        if not self.cache_state.present or not self.cache_state.mount_path:
            return
        sidecar = self.cache_state.mount_path / "meta" / "pins.json"
        n = load_sidecar(self.conn, sidecar)
        if n:
            log.info("loaded %d pins from sidecar", n)


async def amain() -> None:
    ctx = ServiceContext()
    app = build_app(ctx)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    log.info("boombox-library %s listening on :%d", __version__, PORT)

    # Background loops
    sync_task = asyncio.create_task(ctx.sync_timer())
    cache_task = asyncio.create_task(ctx.cache_poll())

    # Wait forever (until SIGTERM)
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    sync_task.cancel()
    cache_task.cancel()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
