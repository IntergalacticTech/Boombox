"""BLE pair_request handling — shares the HTTP path's PIN state, so the
wrong-guess cap (remote_access.PAIR_MAX_ATTEMPTS) applies over BLE too, and
peers.json is written atomically with 0600."""
from __future__ import annotations

import json
import stat
import sys
from unittest.mock import MagicMock

# bless is only installed on the Pi; the handler under test never touches it
# (no server is started, so _set_pair_response only records the payload).
if "bless" not in sys.modules:
    try:
        import bless  # noqa: F401
    except ImportError:
        sys.modules["bless"] = MagicMock()

import ble_peripheral  # noqa: E402
import remote_access  # noqa: E402


def _hash(pin: str) -> str:
    return "h:" + pin


def _peripheral(tmp_path, pin="123456"):
    state = {"pin_hash": _hash(pin), "expires_at": 1e12, "attempts": 0}
    peers = tmp_path / "peers.json"
    p = ble_peripheral.BoomboxBlePeripheral(
        pair_state=state,
        peers_path_cb=lambda: str(peers),
        hash_pin_cb=_hash,
        aggregator=None, dispatcher=None, fire_cb=MagicMock(),
        boombox_id="boombox-test", boombox_name="Test",
    )
    return p, state, peers


def _resp(p) -> dict:
    return json.loads(p._last_pair_resp)


def test_ble_pair_success_writes_peer_0600(tmp_path):
    p, state, peers = _peripheral(tmp_path)
    p._handle_pair_write(b"123456")
    r = _resp(p)
    assert r["ok"] is True and len(r["auth_token"]) == 64
    assert r["auth_token"] in json.loads(peers.read_text())
    assert stat.S_IMODE(peers.stat().st_mode) == 0o600
    assert state["pin_hash"] is None                    # single use


def test_ble_pin_burned_after_max_wrong_attempts(tmp_path):
    p, state, peers = _peripheral(tmp_path)
    for _ in range(remote_access.PAIR_MAX_ATTEMPTS):
        p._handle_pair_write(b"000000")
        assert _resp(p)["error"] == "bad_pin"
    p._handle_pair_write(b"123456")
    assert _resp(p) == {"ok": False, "error": "no_active_pin"}
    assert not peers.exists()
