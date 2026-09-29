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
from pathlib import Path

import aiohttp
from aiohttp import web
from boombox_library import __version__
from boombox_library.api import build_app
from boombox_library.art import close_shared_session
from boombox_library.cache_drive import (
    DEFAULT_SYMLINK,
    CacheDriveState,
    adopt_drive,
    detect_cache_drive,
    list_candidate_drives,
    mark_rows_missing,
    remove_symlink,
    restore_missing_rows,
    update_symlink,
)
from boombox_library.catalog import sync_full
from boombox_library.config import (
    LibraryConfig,
    load_config,
    save_config,
)
from boombox_library.db import connect, migrate
from boombox_library.downloader import DownloadQueue
from boombox_library.mopidy_config import reload_mopidy, write_subsonic_block
from boombox_library.pins import (
    all_pinned_track_ids,
    load_sidecar,
    reconcile_starred,
    write_sidecar,
)
from boombox_library.snapshots import write_snapshots
from boombox_library.subsonic import (
    SubsonicAuthError,
    SubsonicClient,
    SubsonicUnreachable,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-library")

DB_PATH = Path("/opt/boombox/state/library.db")
ART_CACHE_DIR = Path("/opt/boombox/state/art-cache")
SNAPSHOT_DIR = Path("/opt/boombox/state/snapshots")
MOPIDY_CONF = Path("/etc/mopidy/mopidy.conf")
CACHE_POLL_SECONDS = 5
# After a TRANSIENT ping/sync failure (unreachable, timeout, Cloudflare
# page), retry after 60 s, 120 s, 240 s, … capped at the configured sync
# interval; the first success resets to the normal cadence. A remote
# homelab behind Cloudflare blips far more often than a LAN NAS, and
# waiting a full hour to notice it's back leaves the kiosk "offline".
# Permanent failures (bad password, a local bug) wait the full interval:
# hammering them only adds sync load and failed-auth hits at the edge.
SYNC_RETRY_BASE_SECONDS = 60
PORT = 6687


def is_transient(exc: BaseException) -> bool:
    """A failure worth a quick retry: the link, not the config or our code."""
    if isinstance(exc, SubsonicAuthError):
        return False
    return isinstance(exc, (SubsonicUnreachable, asyncio.TimeoutError,
                            aiohttp.ClientError, ConnectionError))


def retry_delay(failures: int, interval: float,
                base: float = SYNC_RETRY_BASE_SECONDS) -> float:
    """Seconds until the next sync attempt after `failures` consecutive
    failures (0 = last attempt succeeded → the regular interval)."""
    if failures <= 0:
        return interval
    return min(base * 2 ** min(failures - 1, 16), interval)


class ServiceContext:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.conn = connect(DB_PATH)
        migrate(self.conn)
        self.art_cache_dir = ART_CACHE_DIR
        self.snapshot_dir = SNAPSHOT_DIR
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
        # Consecutive transient sync failures (drives sync_timer's backoff)
        # and a wake-up for it when a sync it didn't start finishes.
        self._transient_failures = 0
        self._sync_done = asyncio.Event()
        # cache_poll's one-time startup check of cache_state vs. the drive
        self._cache_rows_checked = False
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
        try:
            async with SubsonicClient(url, username, password) as c:
                try:
                    await c.ping()
                    return (True, "")
                except SubsonicAuthError as e:
                    return (False, f"auth: {e}")
                except SubsonicUnreachable as e:
                    return (False, f"unreachable: {e}")
        except Exception as e:  # noqa: BLE001
            # A timeout (or any transport surprise) must come back as a
            # clean not-ok, never escape as an unhandled exception — that
            # surfaced to callers as a text/plain 504 and broke the setup
            # wizard's save with a 500.
            log.warning("source test failed: %s: %s", type(e).__name__, e)
            return (False, f"unreachable: {type(e).__name__}")

    async def trigger_sync(self) -> None:
        if self._sync_task and not self._sync_task.done():
            return  # one at a time
        self._sync_task = asyncio.create_task(self._sync_once())

    # ----- Phase 2 hooks consumed by api.py routes -----
    async def adopt_cache(self, mount_path: str) -> None:
        """Bless a USB drive as the boombox cache. Writes the marker file and
        creates required subdirs; cache_poll picks it up on the next tick."""
        p = Path(mount_path)
        adopt_drive(p, marker=self.cfg.cache.marker_filename)
        log.info("adopted cache drive at %s (marker written)", p)

    def enqueue_streamed_download(self, track_id: str) -> None:
        """Queue an opportunistic streamed-cache download for a track the user
        is currently streaming. No-op if no cache drive is adopted."""
        if self._download_queue is None:
            log.info("no cache drive; skipping streamed-cache enqueue of %s",
                     track_id)
            return
        self._download_queue.enqueue(track_id)

    async def clear_streamed_cache(self) -> int:
        """Delete every cache_state row whose track is NOT pin-protected, and
        remove the corresponding files. Returns the number of entries cleared.
        No-op if no cache drive is adopted.
        """
        if not self.cache_state.present or not self.cache_state.mount_path:
            return 0
        pinned = all_pinned_track_ids(self.conn)
        rows = list(self.conn.execute(
            "SELECT track_id, local_path FROM cache_state WHERE status='present'"
        ))
        cleared = 0
        for r in rows:
            if r["track_id"] in pinned:
                continue
            path = r["local_path"]
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError as e:
                    log.warning("could not delete %s: %s", path, e)
            self.conn.execute(
                "UPDATE cache_state SET status='absent', local_path=NULL, "
                "size_bytes=NULL WHERE track_id=?", (r["track_id"],),
            )
            cleared += 1
        return cleared

    def cache_candidates(self) -> list[dict]:
        """List drives that could be adopted as the cache (marker absent)."""
        return list_candidate_drives(
            [Path(p) for p in self.cfg.cache.search_paths],
            marker=self.cfg.cache.marker_filename,
        )

    # ----- background loops -----
    async def _sync_once(self) -> bool:
        """One ping + full sync. Returns True on success (or nothing to do).

        Never raises (other than cancellation): it runs as a bare task, so an
        escaping exception would vanish as "Task exception was never
        retrieved" — and, worse, leave _online stuck at its previous value.
        Any ping failure, of any type, reports the source offline.

        Every run, whoever started it (sync_timer, Settings' "Sync now",
        a source save), updates _transient_failures and wakes sync_timer
        so it schedules the next attempt from this outcome.
        """
        failure: BaseException | None = None
        try:
            failure = await self._sync_attempt()
        finally:
            if failure is not None and is_transient(failure):
                self._transient_failures += 1
            else:
                self._transient_failures = 0
            self._sync_done.set()
        return failure is None

    async def _sync_attempt(self) -> BaseException | None:
        """_sync_once's body; returns the failure (None on success)."""
        if not self.cfg.source.url:
            log.info("no source configured; skipping sync")
            return None
        self.syncing = True
        try:
            async with SubsonicClient(self.cfg.source.url,
                                      self.cfg.source.username,
                                      self.cfg.source.password) as client:
                try:
                    await client.ping()
                except Exception as e:
                    log.warning("ping failed: %s: %s", type(e).__name__, e)
                    self._online = False
                    return e
                self._online = True
                try:
                    t0 = time.monotonic()
                    counts = await sync_full(client, self.conn)
                    log.info("sync_full done in %.1fs: %s",
                             time.monotonic() - t0, counts)
                    if self.cfg.sync.starred_auto_pin:
                        reconcile_starred(self.conn)
                    self._enqueue_pinned_downloads()
                    self._persist_pins_sidecar()
                    # Materialise the browse snapshots while the sync is
                    # fresh — the API serves these instead of querying
                    # SQLite on every browse.
                    try:
                        write_snapshots(self.conn, self.snapshot_dir)
                    except Exception:
                        log.exception("snapshot write failed; "
                                      "browse will fall back to SQLite")
                    self.last_sync_ts = time.time()
                    return None
                except SubsonicUnreachable as e:
                    # The link dropped mid-sync (timeout, Cloudflare page).
                    log.warning("sync aborted, source unreachable: %s", e)
                    self._online = False
                    return e
                except Exception as e:
                    log.exception("sync failed: %s", e)
                    return e
        except Exception as e:
            # Client setup/teardown itself failed — treat as unreachable.
            log.exception("sync client failed")
            self._online = False
            return e
        finally:
            self.syncing = False

    async def _sync_cycle(self) -> bool:
        """Start a sync (or join the one already running) and wait for it."""
        await self.trigger_sync()
        task = self._sync_task
        if task is None:
            return True
        return await task

    async def _wait_or_woken(self, delay: float) -> bool:
        """Sleep `delay` s; True if a sync finished first (cut short)."""
        try:
            await asyncio.wait_for(self._sync_done.wait(), delay)
            return True
        except asyncio.TimeoutError:
            return False

    async def sync_timer(self) -> None:
        """First-boot immediate sync, then every interval_seconds — or
        sooner, with exponential backoff, while the source is unreachable.

        A sync started elsewhere (a source save from the setup wizard,
        "Sync now") wakes the timer, which re-arms from that sync's outcome:
        a failed first-run sync after the wizard is retried in 60 s, not
        after whatever full interval the timer was already sleeping.
        """
        while True:
            try:
                await self._sync_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sync cycle failed; will retry")
                self._transient_failures += 1
            while True:
                failures = self._transient_failures
                delay = retry_delay(failures, self.cfg.sync.interval_seconds)
                if failures:
                    log.info("sync unreachable %d time(s) in a row; "
                             "retrying in %ds", failures, delay)
                self._sync_done.clear()
                if not await self._wait_or_woken(delay):
                    break

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
                        self._reconcile_cache_rows(new_state.mount_path)
                        self._init_download_queue(new_state.mount_path)
                        self._load_sidecar_if_present()
                    else:
                        lost = self.cache_state.mount_path
                        log.warning("cache drive lost")
                        remove_symlink(DEFAULT_SYMLINK)
                        self._download_queue = None
                        if lost is not None:
                            n = mark_rows_missing(self.conn, lost)
                            if n:
                                log.info("marked %d cached tracks missing "
                                         "(drive gone; kept for re-adopt)", n)
                elif not new_state.present and not self._cache_rows_checked:
                    # Started without a drive: rows from the last run may
                    # still say 'present' with paths on the absent drive.
                    self._reconcile_cache_rows(None)
                self._cache_rows_checked = True
                self.cache_state = new_state
            except asyncio.CancelledError:
                raise  # Always re-raise CancelledError so shutdown works
            except Exception:
                log.exception("cache_poll iteration failed; will retry")
            await asyncio.sleep(CACHE_POLL_SECONDS)

    # ----- internals -----
    def _reconcile_cache_rows(self, mount: Path | None) -> None:
        """Bring cache_state in line with the drive actually mounted (see
        cache_drive's module docstring): 'present' rows whose file is gone
        become 'missing'; with a drive, 'missing' rows found on it return."""
        gone = mark_rows_missing(self.conn, None)
        back = restore_missing_rows(self.conn, mount) if mount else 0
        if gone or back:
            log.info("cache_state reconciled: %d missing, %d restored",
                     gone, back)

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
    await close_shared_session()


if __name__ == "__main__":
    asyncio.run(amain())
