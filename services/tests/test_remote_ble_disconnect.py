"""ble_peripheral.disconnect_stale_centrals — drop centrals that connected
before the GATT table was (re)registered.

A remote that stayed connected across a boombox-remote restart keeps the old
attribute handles cached; its PIN writes then land on nothing and pairing
reports "no response". Kicking every connected central at start makes them
reconnect and rediscover.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# bless is only installed on the Pi; the helper under test never touches it.
if "bless" not in sys.modules:
    try:
        import bless  # noqa: F401
    except ImportError:
        sys.modules["bless"] = MagicMock()

import ble_peripheral  # noqa: E402


def _runner(script: dict[tuple[str, ...], tuple[int, str]]):
    calls: list[tuple[str, ...]] = []

    async def run(*argv: str) -> tuple[int, str]:
        calls.append(argv)
        return script.get(argv, (0, ""))

    return run, calls


def test_disconnects_every_connected_central():
    run, calls = _runner({
        ("bluetoothctl", "devices", "Connected"): (
            0,
            "Device 6C:C8:40:07:06:4E 6C-C8-40-07-06-4E\n"
            "Device AA:BB:CC:DD:EE:FF My Phone\n",
        ),
    })
    dropped = asyncio.run(ble_peripheral.disconnect_stale_centrals(run=run))
    assert dropped == ["6C:C8:40:07:06:4E", "AA:BB:CC:DD:EE:FF"]
    assert ("bluetoothctl", "disconnect", "6C:C8:40:07:06:4E") in calls
    assert ("bluetoothctl", "disconnect", "AA:BB:CC:DD:EE:FF") in calls


def test_nothing_connected_is_a_noop():
    run, calls = _runner({("bluetoothctl", "devices", "Connected"): (0, "")})
    assert asyncio.run(ble_peripheral.disconnect_stale_centrals(run=run)) == []
    assert calls == [("bluetoothctl", "devices", "Connected")]


def test_listing_failure_is_tolerated():
    run, _ = _runner({("bluetoothctl", "devices", "Connected"): (1, "No default controller")})
    assert asyncio.run(ble_peripheral.disconnect_stale_centrals(run=run)) == []


def test_runner_exception_is_tolerated():
    async def run(*argv: str) -> tuple[int, str]:
        raise FileNotFoundError("bluetoothctl")
    assert asyncio.run(ble_peripheral.disconnect_stale_centrals(run=run)) == []


def test_ignores_malformed_lines():
    run, calls = _runner({
        ("bluetoothctl", "devices", "Connected"): (0, "garbage\nDevice\nDevice 11:22:33:44:55:66 X\n"),
    })
    assert asyncio.run(ble_peripheral.disconnect_stale_centrals(run=run)) == ["11:22:33:44:55:66"]


@pytest.mark.parametrize("rc", [0, 1])
def test_disconnect_failure_does_not_abort_others(rc):
    run, calls = _runner({
        ("bluetoothctl", "devices", "Connected"): (0, "Device 11:11:11:11:11:11 a\nDevice 22:22:22:22:22:22 b\n"),
        ("bluetoothctl", "disconnect", "11:11:11:11:11:11"): (rc, "Failed"),
    })
    asyncio.run(ble_peripheral.disconnect_stale_centrals(run=run))
    assert ("bluetoothctl", "disconnect", "22:22:22:22:22:22") in calls
