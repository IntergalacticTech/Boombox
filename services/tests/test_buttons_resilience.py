"""GPIO absence/failure must not take down the buttons HTTP API."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging

import boombox_buttons as bb
import pytest

impl = bb._mod  # the real boombox-buttons.py module


class _Dispatcher:
    disabled: set = set()

    async def dispatch(self, action, event):
        pass


class _Sleep:
    active_minutes = None


async def test_supervisor_survives_failures_and_warns_once(monkeypatch, caplog):
    calls = []

    async def failing_loop(cfg, dispatcher, stop, learn_state=None, gpio_status=None):
        calls.append(1)
        raise OSError("no /dev/gpiochip0")

    monkeypatch.setattr(impl, "gpio_loop", failing_loop)
    stop = asyncio.Event()
    status: dict = {"available": None, "error": None}
    with caplog.at_level(logging.DEBUG, logger="boombox-buttons"):
        task = asyncio.create_task(impl.gpio_supervisor(
            {}, _Dispatcher(), stop, gpio_status=status, retry_s=0.01))
        await asyncio.sleep(0.1)
        assert not task.done()  # never propagates
        stop.set()
        await asyncio.wait_for(task, 1)
    assert len(calls) >= 2  # retried
    assert status["available"] is False
    assert "gpiochip0" in status["error"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


async def test_supervisor_rewarns_after_recovery(monkeypatch, caplog):
    seq = iter(["fail", "ok-then-fail", "fail"])

    async def flaky(cfg, dispatcher, stop, learn_state=None, gpio_status=None):
        step = next(seq, None)
        if step == "ok-then-fail":
            gpio_status.update(available=True, error=None)
            raise impl.GpioUnavailable("reader died")
        if step is None:
            await stop.wait()
            return
        raise OSError("busy")

    monkeypatch.setattr(impl, "gpio_loop", flaky)
    stop = asyncio.Event()
    with caplog.at_level(logging.WARNING, logger="boombox-buttons"):
        task = asyncio.create_task(impl.gpio_supervisor(
            {}, _Dispatcher(), stop, gpio_status={}, retry_s=0.01))
        await asyncio.sleep(0.15)
        stop.set()
        await asyncio.wait_for(task, 1)
    # First failure warns; the post-recovery failure warns again; the third
    # (consecutive) failure does not.
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


@pytest.mark.skipif(importlib.util.find_spec("gpiod") is not None,
                    reason="gpiod installed; exercising the missing-module path needs it absent")
async def test_real_gpio_loop_without_gpiod_is_nonfatal():
    stop = asyncio.Event()
    status: dict = {}
    cfg = bb.default_config()
    task = asyncio.create_task(impl.gpio_supervisor(
        cfg, _Dispatcher(), stop, gpio_status=status, retry_s=5))
    await asyncio.sleep(0.05)
    assert status["available"] is False
    assert "gpiod" in status["error"]
    stop.set()
    await asyncio.wait_for(task, 1)


async def test_no_pins_needs_no_gpiod():
    cfg = bb.default_config()
    for e in cfg["pins"].values():
        e["enabled"] = False
    cfg["encoder"]["enabled"] = False
    stop = asyncio.Event()
    status: dict = {"available": False, "error": "old"}
    task = asyncio.create_task(impl.gpio_loop(cfg, _Dispatcher(), stop, gpio_status=status))
    await asyncio.sleep(0.02)
    assert not task.done()
    assert status == {"available": None, "error": None}
    stop.set()
    await asyncio.wait_for(task, 1)


@pytest.fixture
def api(tmp_path, monkeypatch, aiohttp_client):
    cfg_path = tmp_path / "buttons.json"
    monkeypatch.setattr(impl, "CONFIG_PATH", cfg_path)
    status = {"available": False, "error": "ModuleNotFoundError: No module named 'gpiod'"}
    app = impl.build_api_app([bb.default_config()], [_Dispatcher()],
                             {"action": None, "until": 0, "result": None},
                             _Sleep(), status)

    async def make():
        return await aiohttp_client(app), cfg_path
    return make


async def test_status_endpoint_reports_gpio(api):
    client, _ = await api()
    r = await client.get("/status")
    body = await r.json()
    assert body["gpio_available"] is False
    assert "gpiod" in body["gpio_error"]
    assert body["pins"] > 0
    # /config stays pure config (the UI POSTs it back verbatim).
    cfg = await (await client.get("/config")).json()
    assert "gpio_available" not in cfg


async def test_post_config_writes_atomically(api, tmp_path):
    client, cfg_path = await api()
    cfg_path.write_text("{}")
    new = {"long_press_ms": 800}
    r = await client.post("/config", json=new)
    assert r.status == 200
    assert json.loads(cfg_path.read_text()) == new
    assert cfg_path.stat().st_mode & 0o777 == 0o644
    # No temp files left behind.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["buttons.json"]


async def test_post_config_rejects_non_object(api):
    client, cfg_path = await api()
    r = await client.post("/config", json=[1, 2])
    assert r.status == 400
    assert not cfg_path.exists()


def test_write_config_atomic_failure_leaves_original(tmp_path, monkeypatch):
    p = tmp_path / "buttons.json"
    p.write_text('{"keep": true}')

    def boom(*_a):
        raise OSError("disk full")
    monkeypatch.setattr(impl.os, "replace", boom)
    with pytest.raises(OSError):
        impl.write_config_atomic(p, {"new": 1})
    assert json.loads(p.read_text()) == {"keep": True}
    assert sorted(x.name for x in tmp_path.iterdir()) == ["buttons.json"]


async def test_main_keeps_http_api_up_when_gpio_fails(tmp_path, monkeypatch, unused_tcp_port):
    """Regression: a GPIO failure used to end main() with exit code 0, which
    Restart=on-failure never restarts — killing the Settings API with it."""
    import sys
    import types

    import actions
    if importlib.util.find_spec("watchdog") is None:
        # Dev venvs may lack watchdog; the file-watcher isn't under test.
        class _Observer:
            def schedule(self, *a, **k): pass
            def start(self): pass
            def stop(self): pass
            def join(self): pass
        wd = types.ModuleType("watchdog")
        ev = types.ModuleType("watchdog.events")
        ev.FileSystemEventHandler = object  # type: ignore[attr-defined]
        obs = types.ModuleType("watchdog.observers")
        obs.Observer = _Observer  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "watchdog", wd)
        monkeypatch.setitem(sys.modules, "watchdog.events", ev)
        monkeypatch.setitem(sys.modules, "watchdog.observers", obs)
    import aiohttp

    monkeypatch.setattr(actions, "_HANDLERS", dict(actions._HANDLERS))
    monkeypatch.setattr(impl, "_HANDLERS", actions._HANDLERS)
    monkeypatch.setattr(impl, "CONFIG_PATH", tmp_path / "buttons.json")
    monkeypatch.setattr(impl, "BUTTONS_API_PORT", unused_tcp_port)
    monkeypatch.setattr(impl, "GPIO_RETRY_S", 0.01)

    async def failing_loop(cfg, dispatcher, stop, learn_state=None, gpio_status=None):
        raise ImportError("No module named 'gpiod'")
    monkeypatch.setattr(impl, "gpio_loop", failing_loop)

    task = asyncio.create_task(impl.main())
    try:
        body = None
        async with aiohttp.ClientSession() as s:
            for _ in range(50):
                await asyncio.sleep(0.05)
                try:
                    async with s.get(f"http://127.0.0.1:{unused_tcp_port}/status") as r:
                        body = await r.json()
                    if body.get("gpio_available") is False:
                        break
                except aiohttp.ClientError:
                    continue
        assert not task.done(), task.done() and task.exception()
        assert body and body["gpio_available"] is False
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
