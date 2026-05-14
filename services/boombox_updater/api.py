# services/boombox_updater/api.py
"""HTTP surface for boombox-updater (mounted at :6685, proxied via nginx)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional, Protocol

from aiohttp import web

from . import __version__
from .config import (
    UpdaterConfig,
    load_config,
    save_config,
    validate,
)
from .state import AttemptResult, State, StateStore


class Runner(Protocol):
    async def force_check(self) -> State: ...
    async def install_now(self, ref: Optional[str] = None,
                          force: bool = False) -> AttemptResult: ...
    async def rollback(self) -> AttemptResult: ...


def _state_to_status(state: State, config: UpdaterConfig) -> dict:
    payload = {
        "installed_version": state.installed_version,
        "available_version": state.available_version,
        "available_published_at": state.available_published_at,
        "last_check_ts": state.last_check_ts,
        "state_machine": state.state_machine,
        "auto": config.auto,
        "channel": config.channel,
        "window_start": config.window_start,
        "window_duration_min": config.window_duration_min,
        "service_version": __version__,
    }
    if state.last_attempt is not None:
        payload["last_attempt"] = {
            "ts": state.last_attempt.ts,
            "ref": state.last_attempt.ref,
            "result": state.last_attempt.result.value,
            "error": state.last_attempt.error,
            "log_path": state.last_attempt.log_path,
        }
    else:
        payload["last_attempt"] = None
    return payload


def build_app(*, config_path: Path, state_store: StateStore,
              runner: Runner) -> web.Application:
    app = web.Application()

    async def get_status(_request: web.Request) -> web.Response:
        return web.json_response(
            _state_to_status(state_store.load(), load_config(config_path))
        )

    async def get_config(_request: web.Request) -> web.Response:
        return web.json_response(asdict(load_config(config_path)))

    async def put_config(request: web.Request) -> web.Response:
        try:
            raw = await request.json()
            cfg = validate(raw)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        save_config(config_path, cfg)
        return web.json_response(asdict(cfg))

    async def post_check(_request: web.Request) -> web.Response:
        new_state = await runner.force_check()
        return web.json_response(
            _state_to_status(new_state, load_config(config_path))
        )

    async def post_install(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        result = await runner.install_now(
            ref=body.get("ref"), force=bool(body.get("force", False)),
        )
        return web.json_response({"result": result.value})

    async def post_rollback(_request: web.Request) -> web.Response:
        result = await runner.rollback()
        return web.json_response({"result": result.value})

    async def get_log(request: web.Request) -> web.Response:
        n = int(request.query.get("n", 200))
        state = state_store.load()
        if not state.last_attempt or not state.last_attempt.log_path:
            return web.Response(status=404, text="no install attempt yet")
        log_path = state_store._dir / state.last_attempt.log_path  # noqa: SLF001
        try:
            lines = log_path.read_text().splitlines()
        except FileNotFoundError:
            return web.Response(status=404, text="log file missing")
        tail = "\n".join(lines[-n:]) + "\n"
        return web.Response(text=tail, content_type="text/plain")

    app.router.add_get("/api/update/status", get_status)
    app.router.add_get("/api/update/config", get_config)
    app.router.add_put("/api/update/config", put_config)
    app.router.add_post("/api/update/check", post_check)
    app.router.add_post("/api/update/install", post_install)
    app.router.add_post("/api/update/rollback", post_rollback)
    app.router.add_get("/api/update/log", get_log)
    return app
