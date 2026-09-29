"""Tests for services/remote_access.py — the remote_enabled flag, atomic
JSON writes (peers.json), and the shared pairing-PIN check."""
from __future__ import annotations

import json
import stat

import pytest
import remote_access


def test_missing_file_reads_as_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(tmp_path / "state.json"))
    assert remote_access.is_enabled() is False


def test_set_enabled_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(tmp_path / "state.json"))
    remote_access.set_enabled(True)
    assert remote_access.is_enabled() is True
    remote_access.set_enabled(False)
    assert remote_access.is_enabled() is False


def test_malformed_file_reads_as_disabled(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("{not json")
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    assert remote_access.is_enabled() is False


def test_non_dict_json_reads_as_disabled(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("[]")
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    assert remote_access.is_enabled() is False


def test_set_enabled_creates_parent_dir(tmp_path, monkeypatch):
    state = tmp_path / "nested" / "dir" / "state.json"
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    remote_access.set_enabled(True)
    assert state.exists()


# ---- write_json_atomic -------------------------------------------------------
def test_write_json_atomic_is_0600_and_leaves_no_tmp(tmp_path):
    path = tmp_path / "cfg" / "peers.json"
    remote_access.write_json_atomic(path, {"tok": {"label": "x"}})
    assert json.loads(path.read_text()) == {"tok": {"label": "x"}}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["peers.json"]


def test_write_json_atomic_failure_keeps_old_file(tmp_path):
    path = tmp_path / "peers.json"
    path.write_text('{"old": {}}')
    with pytest.raises(TypeError):
        remote_access.write_json_atomic(path, {"bad": object()})
    assert json.loads(path.read_text()) == {"old": {}}
    assert [p.name for p in tmp_path.iterdir()] == ["peers.json"]


# ---- redeem_pin --------------------------------------------------------------
def _h(pin: str) -> str:
    return "h:" + pin


def _state(pin="123456", expires_at=100.0):
    return {"pin_hash": _h(pin), "expires_at": expires_at, "attempts": 0}


def test_redeem_pin_success_consumes():
    st = _state()
    assert remote_access.redeem_pin(st, "123456", _h, now=1.0) is None
    assert st["pin_hash"] is None
    assert remote_access.redeem_pin(st, "123456", _h, now=1.0) == "no_active_pin"


def test_redeem_pin_expired():
    assert remote_access.redeem_pin(_state(), "123456", _h, now=101.0) == "no_active_pin"


def test_redeem_pin_burns_after_max_attempts():
    st = _state()
    for _ in range(remote_access.PAIR_MAX_ATTEMPTS - 1):
        assert remote_access.redeem_pin(st, "000000", _h, now=1.0) == "bad_pin"
    assert st["pin_hash"] is not None           # still live after N-1 misses
    assert remote_access.redeem_pin(st, "000000", _h, now=1.0) == "bad_pin"
    # Burned: even the right PIN no longer pairs.
    assert remote_access.redeem_pin(st, "123456", _h, now=1.0) == "no_active_pin"


def test_redeem_pin_tolerates_legacy_state_without_attempts():
    st = {"pin_hash": _h("123456"), "expires_at": 100.0}
    assert remote_access.redeem_pin(st, "000000", _h, now=1.0) == "bad_pin"
    assert st["attempts"] == 1
