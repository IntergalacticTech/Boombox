"""Tests for the remote_enabled flag (services/remote_access.py)."""
from __future__ import annotations

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
