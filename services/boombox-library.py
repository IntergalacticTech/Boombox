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
from typing import Awaitable, Callable

import aiohttp
from aiohttp import web
from boombox_library import __version__
from boombox_library.api import build_app
from boombox_library.art import close_shared_session
from boombox_library.cache_drive import (
    DEFAULT_SYMLINK,
    CacheDriveState,
    adopt_drive,
    apply_rows_missing,
    apply_rows_restored,
    find_gone_rows,
    find_restorable_rows,
    list_candidate_drives,
    mark_rows_missing,
    mark_rows_outside_missing,
    missing_rows,
    present_rows,
    remove_symlink,
    select_cache_drive,
    update_symlink,
)
from boombox_library.catalog import sync_full
from boombox_library.config import (
    LibraryConfig,
    load_config,
    save_config,
)
from boombox_library.db import connect, migrate
from boombox_library.download_gates import MopidyStreamProbe, free_bytes, read_soc_temp_c
from boombox_library.downloader import DownloadQueue, Gates
from boombox_library.mopidy_config import reload_mopidy, remove_subsonic_block
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
# Reachability probe (a Subsonic ping, independent of the hourly sync):
# every PROBE_INTERVAL_S, or every PROBE_RETRY_S while it fails during the
# first PROBE_BOOT_WINDOW_S after start (Wi-Fi often comes up after us).
PROBE_INTERVAL_S = 30.0
PROBE_RETRY_S = 10.0
PROBE_BOOT_WINDOW_S = 120.0
PROBE_TIMEOUT_S = 5.0
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
        # Last known reachability of the music server. Until the first probe
        # or sync answers it is unknown (_reachability_known False) and
        # is_online() reports True, so a tap right after boot still streams;
        # the download gate reads _online itself and idles until known.
        self._online = False
        self._reachability_known = False
        self._probe_task: asyncio.Task | None = None
        self._sync_task: asyncio.Task | None = None
        self._download_queue: DownloadQueue | None = None
        # (drive, source) the current queue was built for; see _ensure_download_queue
        self._queue_key: tuple[str, str, str, str] | None = None
        # Teardowns (DownloadQueue.aclose) of dropped queues still unwinding:
        # no queue is built until they are done (see _drop_download_queue).
        self._retiring: set[asyncio.Future] = set()
        # cache_poll is moving to another drive (or losing it): between
        # retiring the old queue and setting cache_state, cache_state still
        # names the old mount — no request may build a queue on it.
        self._switching = False
        self._closed = False
        # Mopidy "is a stream-proxy URI playing?" — a download gate.
        self._stream_probe = MopidyStreamProbe()
        # Last time pinned tracks in 'error' / 'no_space' were re-enqueued:
        # failed downloads are retried on the hourly cadence only. Monotonic
        # (wall-clock jumps from NTP at boot must not skip or force a retry);
        # -inf so the first sync always retries.
        self._last_failed_retry = float("-inf")
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
        if not self.cfg.source.url:
            return False                 # no music server: nothing to stream
        return self._online if self._reachability_known else True

    def reachability_known(self) -> bool:
        return self._reachability_known or not self.cfg.source.url

    def _set_reachable(self, ok: bool) -> bool:
        """Record a reachability answer. True on an offline → online edge
        (a known offline before; unknown → online is not an edge)."""
        edge = ok and self._reachability_known and not self._online
        self._online = ok
        self._reachability_known = True
        return edge

    def mark_offline(self) -> None:
        """A stream relay or a download just lost the link: offline now,
        not at the next probe. The probe flips it back (and syncs)."""
        if self._online or not self._reachability_known:
            log.info("music server link failed; marking offline")
        self._set_reachable(False)

    def cache_drive_state(self) -> CacheDriveState:
        return self.cache_state

    def save_config(self, cfg: LibraryConfig) -> None:
        self.cfg = cfg
        save_config(cfg)
        # Mopidy no longer carries the Subsonic credentials; only a
        # leftover [subsonic] section from an old install is stripped.
        # Restart Mopidy just when that actually changed mopidy.conf —
        # restarting on every source save would cut playback for nothing.
        if remove_subsonic_block(MOPIDY_CONF):
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
        queue = self._ensure_download_queue()
        if queue is None:
            log.info("no cache drive; skipping streamed-cache enqueue of %s",
                     track_id)
            return
        queue.enqueue(track_id)

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
        """List drives that could be adopted as the cache (marker absent).
        Empty while the internal storage is the cache: a USB stick plugged
        in then must not raise the kiosk's adopt prompt."""
        if self.cache_state.internal:
            return []
        return list_candidate_drives(
            [Path(p) for p in self.cfg.cache.search_paths],
            marker=self.cfg.cache.marker_filename,
        )

    def download_queue(self) -> DownloadQueue | None:
        """The live download queue (api.py keep / storage routes), or None
        when there is no drive or no music server configured."""
        return self._ensure_download_queue()

    async def close(self) -> None:
        self._closed = True
        task, self._probe_task = self._probe_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._retire_download_queue()
        await self._stream_probe.close()

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
                    self._set_reachable(False)
                    return e
                self._set_reachable(True)
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
                    self._set_reachable(False)
                    return e
                except Exception as e:
                    log.exception("sync failed: %s", e)
                    return e
        except Exception as e:
            # Client setup/teardown itself failed — treat as unreachable.
            log.exception("sync client failed")
            self._set_reachable(False)
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

    def start_reachability_probe(self) -> None:
        """Start reachability_probe as a task owned here; close() stops it."""
        if self._probe_task is None or self._probe_task.done():
            self._probe_task = asyncio.create_task(self.reachability_probe())

    async def _probe_once(self) -> bool | None:
        """One short Subsonic ping. Sets reachability and returns it; None
        (nothing done) when no music server is configured. Any failure —
        unreachable, timeout, bad credentials — counts as offline, as it
        does for the sync's own ping. An offline → online edge kicks a sync
        (trigger_sync skips it when one is already running)."""
        src = self.cfg.source
        if not src.url:
            return None
        try:
            async with SubsonicClient(src.url, src.username, src.password,
                                      timeout_seconds=PROBE_TIMEOUT_S) as client:
                await client.ping()
            ok = True
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — any failure = unreachable
            log.debug("reachability ping failed: %s: %s", type(e).__name__, e)
            ok = False
        was = self._online if self._reachability_known else None
        if self._set_reachable(ok):
            log.info("music server reachable again; syncing")
            await self.trigger_sync()
        elif was is not ok:
            log.info("music server %s", "reachable" if ok else "unreachable")
        return ok

    async def reachability_probe(
        self, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Ping now, then every PROBE_INTERVAL_S — every PROBE_RETRY_S while
        failing in the first PROBE_BOOT_WINDOW_S. Never raises (other than
        cancellation)."""
        started = clock()
        while True:
            ok: bool | None = None
            try:
                ok = await self._probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reachability probe failed; will retry")
            booting = clock() - started < PROBE_BOOT_WINDOW_S
            await sleep(PROBE_RETRY_S if ok is False and booting else PROBE_INTERVAL_S)

    async def cache_poll(self) -> None:
        while True:
            try:
                new_state = select_cache_drive(
                    self.cfg.cache.internal_path,
                    [Path(p) for p in self.cfg.cache.search_paths],
                    marker=self.cfg.cache.marker_filename,
                )
                if new_state.mount_path != self.cache_state.mount_path:
                    self._switching = True
                    try:
                        await self._switch_cache_drive(new_state)
                    finally:
                        self._switching = False
                elif not new_state.present and not self._cache_rows_checked:
                    # Started without a drive: rows from the last run may
                    # still say 'present' with paths on the absent drive.
                    await self._reconcile_cache_rows(None)
                self._cache_rows_checked = True
                self.cache_state = new_state
            except asyncio.CancelledError:
                raise  # Always re-raise CancelledError so shutdown works
            except Exception:
                log.exception("cache_poll iteration failed; will retry")
            await asyncio.sleep(CACHE_POLL_SECONDS)

    async def _switch_cache_drive(self, new_state: CacheDriveState) -> None:
        """cache_poll's drive change (adopted, swapped or lost); runs with
        _switching set."""
        if new_state.present and new_state.mount_path:
            log.info("cache drive present at %s", new_state.mount_path)
            update_symlink(DEFAULT_SYMLINK, new_state.mount_path)
            if new_state.internal:
                # Rows on an old (maybe still mounted) USB cache are not
                # watched any more: 'missing', so pinned ones download again.
                n = mark_rows_outside_missing(self.conn, new_state.mount_path)
                if n:
                    log.info("marked %d cached tracks outside %s missing",
                             n, new_state.mount_path)
            await self._reconcile_cache_rows(new_state.mount_path)
            # Drive swap: the old queue's downloads must have finished their
            # cancel cleanup before a new queue (whose constructor sweeps
            # tmp/ and resets rows) exists.
            await self._retire_download_queue()
            self.cache_state = new_state
            self._switching = False
            self._init_download_queue(new_state.mount_path)
            self._load_sidecar_if_present()
        else:
            lost = self.cache_state.mount_path
            log.warning("cache drive lost")
            remove_symlink(DEFAULT_SYMLINK)
            await self._retire_download_queue()
            self.cache_state = new_state
            if lost is not None:
                n = mark_rows_missing(self.conn, lost)
                if n:
                    log.info("marked %d cached tracks missing "
                             "(drive gone; kept for re-adopt)", n)

    # ----- internals -----
    async def _reconcile_cache_rows(self, mount: Path | None) -> None:
        """Bring cache_state in line with the drive actually mounted (see
        cache_drive's module docstring): 'present' rows whose file is gone
        become 'missing'; with a drive, 'missing' rows found on it return.

        Every row costs a stat, so the file checks run in a worker thread
        — this loop also relays live audio (stream_proxy) and must not
        stall on a big or slow USB drive. SQLite reads/writes stay on the
        loop thread; the apply step's status guards skip any row that
        changed while the checks ran."""
        gone_rows = await asyncio.to_thread(
            find_gone_rows, present_rows(self.conn))
        gone = apply_rows_missing(self.conn, gone_rows)
        back = 0
        if mount:
            found = await asyncio.to_thread(
                find_restorable_rows, missing_rows(self.conn), mount)
            back = apply_rows_restored(self.conn, found)
        if gone or back:
            log.info("cache_state reconciled: %d missing, %d restored",
                     gone, back)

    def _init_download_queue(self, mount: Path) -> None:
        """Build the queue for mount. Callers drop the previous queue first
        and, on async paths, await its teardown (_retire_download_queue);
        while any teardown is still unwinding nothing is built — the next
        sync or request builds it lazily (_ensure_download_queue)."""
        if self._closed or self._download_queue is not None:
            return
        if self._switching:
            log.info("music storage changing; queue build deferred")
            return
        if self._teardown_pending():
            log.info("previous download queue still stopping; rebuild deferred")
            return
        src = self.cfg.source
        if not src.url:
            return
        # Note: client lifetime is per-download in the fetch — this client
        # is only used for download_url() construction.
        client = SubsonicClient(src.url, src.username, src.password)
        self._download_queue = DownloadQueue(
            conn=self.conn, client=client, cache_root=mount,
            max_concurrent=self.cfg.sync.max_concurrent_downloads,
            reserve_bytes=self.cfg.cache.reserve_bytes,
            gates=Gates(
                is_online=lambda: self._online,
                report_offline=self.mark_offline,
                is_streaming=self._stream_probe.is_streaming,
                soc_temp_c=read_soc_temp_c,
                free_bytes=lambda: free_bytes(mount),
            ),
        )
        self._queue_key = (str(mount), src.url, src.username, src.password)

    def _teardown_pending(self) -> bool:
        return any(not f.done() for f in self._retiring)

    def _drop_download_queue(self) -> None:
        """Detach the current queue and start its teardown (aclose) in the
        background; _retiring tracks it so no new queue is built on top of
        downloads still unwinding. For sync callers; async paths await
        _retire_download_queue instead."""
        queue = self._download_queue
        self._download_queue = None
        self._queue_key = None
        if queue is None:
            return
        # Its pending (not yet started) tracks are dropped here; their rows
        # go back to 'absent' and the next sync re-enqueues them.
        try:
            fut = asyncio.ensure_future(queue.aclose())
        except RuntimeError:          # no running loop: nothing to wait for
            queue.stop()
            return
        self._retiring.add(fut)
        fut.add_done_callback(self._retiring.discard)

    async def _retire_download_queue(self) -> None:
        """Drop the current queue and wait until it (and any earlier queue
        still stopping) has fully torn down."""
        self._drop_download_queue()
        if self._retiring:
            # Shielded: cancelling the waiter (cache_poll at shutdown) must
            # not cancel the teardowns themselves mid-cleanup.
            await asyncio.shield(
                asyncio.gather(*list(self._retiring), return_exceptions=True))

    def _ensure_download_queue(self) -> DownloadQueue | None:
        """The queue for the current drive + source: built on first need
        (a source saved after the drive was adopted — the internal drive
        never "changes"). A credentials-only change updates the live
        queue's client in place (no rebuild, in-flight downloads keep
        going); a drive change is cache_poll's job, which awaits the old
        queue's teardown before building the new one."""
        if self._closed:
            return None
        mount = self.cache_state.mount_path if self.cache_state.present else None
        src = self.cfg.source
        if mount is None or not src.url:
            self._drop_download_queue()
            return None
        key = (str(mount), src.url, src.username, src.password)
        queue = self._download_queue
        if queue is not None and self._queue_key != key:
            if self._queue_key is not None and self._queue_key[0] == str(mount):
                queue.set_client(SubsonicClient(src.url, src.username, src.password))
                self._queue_key = key
            else:
                # Drive changed under a sync caller (cache_poll normally gets
                # there first): tear down in the background; built once done.
                self._drop_download_queue()
        if self._download_queue is None:
            self._init_download_queue(mount)
        return self._download_queue

    def reset_failed_retry(self) -> None:
        """Let the next _enqueue_pinned_downloads re-enqueue 'error' /
        'no_space' tracks regardless of the hourly gate (admin "Retry
        failed")."""
        self._last_failed_retry = float("-inf")

    def _enqueue_pinned_downloads(self, now: float | None = None, *,
                                  force_failed: bool = False) -> None:
        """Enqueue every pinned track not yet on disk. Tracks that failed
        ('error' / 'no_space') are included only once per sync interval
        (hourly), or when force_failed (admin "Retry failed")."""
        if force_failed:
            self.reset_failed_retry()
        queue = self._ensure_download_queue()
        if queue is None:
            log.info("no music storage or no source; pinned downloads deferred")
            return
        pinned = all_pinned_track_ids(self.conn)
        if not pinned:
            return
        now = time.monotonic() if now is None else now
        retry_failed = now - self._last_failed_retry >= self.cfg.sync.interval_seconds
        skip = ("present",) if retry_failed else ("present", "error", "no_space")
        marks = ",".join("?" * len(skip))
        have = {r[0] for r in self.conn.execute(
            f"SELECT track_id FROM cache_state WHERE status IN ({marks})", skip)}
        if retry_failed:
            self._last_failed_retry = now
        for tid in pinned - have:
            queue.enqueue(tid)

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
    ctx.start_reachability_probe()

    # Wait forever (until SIGTERM)
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    sync_task.cancel()
    cache_task.cancel()
    # Stop serving first so no request can rebuild the queue mid-close.
    await runner.cleanup()
    await ctx.close()
    await close_shared_session()


if __name__ == "__main__":
    asyncio.run(amain())
