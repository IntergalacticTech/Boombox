#!/usr/bin/env python3
# services/boombox-updater.py
"""boombox-updater service entry point.

Wires together: GitHub poller, scheduler decision, install state machine
backed by install/apply-release.sh, and the HTTP API on port 6686.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiohttp import ClientSession, web
from boombox_updater import __version__
from boombox_updater.api import build_app
from boombox_updater.config import CONFIG_PATH, load_config
from boombox_updater.installer import Installer, StepResult
from boombox_updater.poller import GitHubPoller
from boombox_updater.scheduler import should_attempt_install
from boombox_updater.state import (
    AttemptResult,
    LastAttempt,
    State,
    StateStore,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-updater")

REPO_ROOT = Path(os.environ.get("BOOMBOX_ROOT", "/opt/boombox"))
APPLY = REPO_ROOT / "current" / "install" / "apply-release.sh"
GITHUB_REPO = os.environ.get("BOOMBOX_REPO", "IntergalacticTech/Boombox")
PORT = int(os.environ.get("BOOMBOX_UPDATER_PORT", "6686"))
POLL_INTERVAL_S = int(os.environ.get("BOOMBOX_UPDATER_POLL_S", str(60 * 60)))
PLAYBACK_URL = "http://127.0.0.1/api/state"


class ShellSteps:
    """Real Steps implementation — shells out to apply-release.sh."""

    def __init__(self, log_path: Path) -> None:
        self._log = log_path
        self._log.parent.mkdir(parents=True, exist_ok=True)

    def _run(self, *args: str) -> StepResult:
        with self._log.open("a") as fh:
            fh.write(f"\n$ {APPLY} {' '.join(args)}\n")
            fh.flush()
            proc = subprocess.run(
                [str(APPLY), *args],
                stdout=fh, stderr=subprocess.STDOUT,
                env={**os.environ, "BOOMBOX_ROOT": str(REPO_ROOT)},
            )
        return StepResult.OK if proc.returncode == 0 else StepResult.FAIL

    def do_fetch(self, ref: str) -> StepResult:    return self._run("fetch", ref)
    def do_build(self, ref: str) -> StepResult:    return self._run("build", ref)
    def do_preflight(self, ref: str) -> StepResult: return self._run("preflight", ref)
    def do_swap(self, ref: str) -> StepResult:     return self._run("swap", ref)
    def do_restart(self) -> StepResult:            return self._run("restart")
    def do_verify(self) -> StepResult:             return self._run("verify")
    def do_revert(self) -> StepResult:             return self._run("revert")
    def do_revert_verify(self) -> StepResult:      return self._run("verify")
    def do_cleanup_failed_release(self, ref: str) -> None: self._run("cleanup", ref)


class UpdaterRunner:
    """Implements the api.Runner protocol."""

    def __init__(self, *, store: StateStore, poller: GitHubPoller,
                 lock: asyncio.Lock) -> None:
        self._store = store
        self._poller = poller
        self._lock = lock

    def _read_installed_version(self) -> str:
        try:
            return (REPO_ROOT / "current" / "VERSION").read_text().strip()
        except OSError:
            return "unknown"

    def _read_previous_ref(self) -> Optional[str]:
        prev = REPO_ROOT / "previous"
        if not prev.is_symlink():
            return None
        target = os.readlink(prev)
        # readlink returns "releases/<ref>" — strip prefix.
        return Path(target).name

    def _read_current_ref(self) -> str:
        cur = REPO_ROOT / "current"
        if not cur.is_symlink():
            return "unknown"
        return Path(os.readlink(cur)).name

    async def force_check(self) -> State:
        cfg = load_config()
        if cfg.channel == "stable":
            result = await self._poller.poll_stable()
        else:
            result = await self._poller.poll_edge()
        installed = self._read_installed_version()
        avail = result.version if result else ""
        published = result.published_at if result else ""
        return self._store.update(
            installed_version=installed,
            available_version=avail,
            available_published_at=published,
            last_check_ts=time.time(),
        )

    async def install_now(self, ref: Optional[str] = None,
                          force: bool = False) -> AttemptResult:
        if not force and await _playback_active():
            return AttemptResult.SKIPPED_PLAYBACK
        async with self._lock:
            return await self._do_install(ref)

    async def rollback(self) -> AttemptResult:
        async with self._lock:
            log_path = self._store.new_log_path("rollback")
            steps = ShellSteps(log_path=log_path)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._run_revert, steps)
            if result == AttemptResult.OK:
                self._store.update(
                    installed_version=self._read_installed_version(),
                    last_attempt=LastAttempt(
                        ts=time.time(),
                        ref=self._read_current_ref(),
                        result=AttemptResult.OK,
                        error=None,
                        log_path=str(log_path.relative_to(self._store._dir)),
                    ),
                    state_machine="idle",
                )
            return result

    @staticmethod
    def _run_revert(steps: "ShellSteps") -> AttemptResult:
        """Blocking — runs in an executor thread."""
        if steps.do_revert() != StepResult.OK:
            return AttemptResult.BROKEN
        if steps.do_revert_verify() != StepResult.OK:
            return AttemptResult.BROKEN
        return AttemptResult.OK

    async def _do_install(self, ref: Optional[str]) -> AttemptResult:
        state = await self.force_check()
        target = ref or state.available_version
        if not target:
            return AttemptResult.OK  # nothing to do
        log_path = self._store.new_log_path(target)
        steps = ShellSteps(log_path=log_path)
        installer = Installer(
            steps=steps,
            current_ref=self._read_current_ref(),
            previous_ref=self._read_previous_ref(),
            on_step=lambda step: self._store.update(state_machine=step.value),
        )
        loop = asyncio.get_running_loop()
        outcome = await loop.run_in_executor(None, installer.install, target)
        self._store.update(
            installed_version=self._read_installed_version(),
            last_attempt=LastAttempt(
                ts=time.time(), ref=target,
                result=outcome.result, error=outcome.error,
                log_path=str(log_path.relative_to(self._store._dir)),
            ),
            state_machine="idle",
        )
        # On a successful install, prune old releases and self-restart —
        # both blocking, so run them off the event loop.
        if outcome.result == AttemptResult.OK:
            await loop.run_in_executor(None, _prune_and_self_restart)
        return outcome.result


def _prune_and_self_restart() -> None:
    """Blocking — runs in an executor thread. Prunes old release dirs, then
    asks systemd to restart this very service (picks up a new updater.py)."""
    subprocess.run([str(APPLY), "prune"], check=False)
    subprocess.run(
        ["systemctl", "--user", "reload-or-restart", "boombox-updater.service"],
        check=False,
    )


async def _playback_active() -> bool:
    try:
        async with ClientSession() as session:
            async with session.get(PLAYBACK_URL,
                                   timeout=2.0) as resp:  # type: ignore[arg-type]
                if resp.status >= 400:
                    return False
                data = await resp.json()
                return data.get("status") == "playing"
    except Exception:
        return False


async def _scheduler_loop(runner: UpdaterRunner) -> None:
    """Wake every minute; if the configured window is open and a new
    version is available and nothing's playing, run an install."""
    while True:
        try:
            cfg = load_config()
            state = runner._store.load()
            decision = should_attempt_install(
                now=datetime.now(),
                config=cfg,
                installed_version=state.installed_version,
                available_version=state.available_version,
                playback_status="playing" if await _playback_active() else "paused",
            )
            if decision.install:
                log.info("scheduler: window open, installing %s",
                         state.available_version)
                await runner.install_now()
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        await asyncio.sleep(60)


async def _poll_loop(runner: UpdaterRunner) -> None:
    """Initial check 30s after start, then hourly."""
    await asyncio.sleep(30)
    while True:
        try:
            await runner.force_check()
        except Exception:  # noqa: BLE001
            log.exception("poll failed")
        await asyncio.sleep(POLL_INTERVAL_S)


async def main() -> None:
    log.info("boombox-updater %s starting on :%d", __version__, PORT)
    state_dir = REPO_ROOT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = StateStore(state_dir=state_dir)
    poller = GitHubPoller(repo=GITHUB_REPO)
    lock = asyncio.Lock()
    runner = UpdaterRunner(store=store, poller=poller, lock=lock)

    app = build_app(config_path=CONFIG_PATH, state_store=store, runner=runner)
    runner_task = asyncio.create_task(_scheduler_loop(runner))
    poll_task = asyncio.create_task(_poll_loop(runner))

    web_runner = web.AppRunner(app)
    await web_runner.setup()
    site = web.TCPSite(web_runner, "127.0.0.1", PORT)
    await site.start()

    try:
        await asyncio.Event().wait()
    finally:
        runner_task.cancel()
        poll_task.cancel()
        await web_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
