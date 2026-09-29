"""boombox-state's /power routes and the power block on /state."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import power as power_mod
import pytest

SERVICE = Path(__file__).resolve().parent.parent / "boombox-state.py"
_spec = importlib.util.spec_from_file_location("boombox_state_service", SERVICE)
state_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(state_svc)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A hookless PowerManager installed as the service's global."""
    pm = power_mod.PowerManager(grace_s=0, state_file=tmp_path / "power.json")
    monkeypatch.setattr(state_svc, "_power", pm)
    return pm


async def test_get_power_returns_the_snapshot(manager, aiohttp_client):
    client = await aiohttp_client(state_svc.make_app())
    r = await client.get("/power")
    assert r.status == 200
    assert (await r.json())["state"] == "awake"


@pytest.mark.parametrize("action,expected", [
    ("sleep", "asleep"), ("toggle", "asleep"), ("off", "asleep"), ("wake", "awake"),
])
async def test_power_actions_return_the_new_snapshot(manager, aiohttp_client,
                                                     action, expected):
    client = await aiohttp_client(state_svc.make_app())
    r = await client.post(f"/power/{action}")
    assert r.status == 200
    assert (await r.json())["state"] == expected
    assert manager.state == expected


async def test_unknown_power_action_is_rejected(manager, aiohttp_client):
    client = await aiohttp_client(state_svc.make_app())
    r = await client.post("/power/explode")
    assert r.status == 400


async def test_power_routes_503_without_a_manager(monkeypatch, aiohttp_client):
    monkeypatch.setattr(state_svc, "_power", None)
    client = await aiohttp_client(state_svc.make_app())
    assert (await client.get("/power")).status == 503
    assert (await client.post("/power/sleep")).status == 503


async def test_state_payload_carries_the_power_block(manager, aiohttp_client):
    client = await aiohttp_client(state_svc.make_app())
    body = await (await client.get("/state")).json()
    assert body["power"]["state"] == "awake"
    assert "status" in body          # the MPRIS aggregate is still there
    await manager.sleep()
    body = await (await client.get("/state")).json()
    assert body["power"]["state"] == "asleep"


async def test_state_payload_omits_power_without_a_manager(monkeypatch, aiohttp_client):
    monkeypatch.setattr(state_svc, "_power", None)
    client = await aiohttp_client(state_svc.make_app())
    assert "power" not in await (await client.get("/state")).json()


def test_grace_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("BOOMBOX_SLEEP_POWEROFF_S", "42")
    assert state_svc.build_power_manager(None).grace_s == 42.0


def test_grace_defaults_when_unset_or_garbage(monkeypatch):
    monkeypatch.delenv("BOOMBOX_SLEEP_POWEROFF_S", raising=False)
    assert state_svc.build_power_manager(None).grace_s == power_mod.DEFAULT_GRACE_S
    monkeypatch.setenv("BOOMBOX_SLEEP_POWEROFF_S", "soon")
    assert state_svc.build_power_manager(None).grace_s == power_mod.DEFAULT_GRACE_S
