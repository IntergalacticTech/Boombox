"""Tests for boombox_library.config — YAML config + Fernet password encryption."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from boombox_library.config import (
    LibraryConfig,
    SourceConfig,
    SyncConfig,
    CacheConfig,
    DEFAULT_CONFIG,
    load_config,
    save_config,
    _derive_key,
)


def test_default_config_shape():
    c = DEFAULT_CONFIG
    assert c.sync.interval_seconds == 3600
    assert c.sync.starred_auto_pin is True
    assert c.sync.max_concurrent_downloads == 2
    assert c.cache.marker_filename == ".boombox-cache"
    assert c.cache.reserve_bytes == 1073741824  # 1 GB


def test_round_trip_no_password(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    cfg = DEFAULT_CONFIG
    save_config(cfg, path=path)
    loaded = load_config(path=path)
    assert loaded.source.url == cfg.source.url
    assert loaded.source.username == cfg.source.username
    assert loaded.source.password == ""  # default empty


def test_round_trip_with_password(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    cfg = LibraryConfig(
        source=SourceConfig(url="http://192.168.1.223:4533",
                            username="jwc", password="turtle99"),
        sync=DEFAULT_CONFIG.sync,
        cache=DEFAULT_CONFIG.cache,
    )
    save_config(cfg, path=path)

    # Raw YAML must NOT contain the plain password.
    raw = path.read_text()
    assert "turtle99" not in raw
    assert "password_encrypted" in raw

    loaded = load_config(path=path)
    assert loaded.source.password == "turtle99"


def test_atomic_write_temp_file_cleaned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    save_config(DEFAULT_CONFIG, path=path)
    # Temp file must not be left behind
    assert not (tmp_path / "library.yml.tmp").exists()


def test_machine_id_derived_key_stable(monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    k1 = _derive_key()
    k2 = _derive_key()
    assert k1 == k2  # deterministic per machine
    assert len(k1) == 44  # Fernet base64 key length


def test_source_config_repr_does_not_leak_password():
    """Defense in depth: even if someone logs the config dataclass, the
    password must not appear in its string repr."""
    s = SourceConfig(url="http://x", username="u", password="hunter2")
    text = repr(s)
    assert "hunter2" not in text
    assert "url='http://x'" in text or "url=" in text
    assert "username='u'" in text or "username=" in text


def test_save_config_fsyncs_before_rename(tmp_path: Path, monkeypatch):
    """fsync the temp file before os.replace, so power-loss can't leave
    a renamed-but-empty file. We can't truly observe fsync, but we can
    verify save_config calls os.fsync on the tmp file's fd."""
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)

    fsync_calls: list[int] = []
    real_fsync = os.fsync
    def fake_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)
    monkeypatch.setattr("boombox_library.config.os.fsync", fake_fsync)

    save_config(DEFAULT_CONFIG, path=tmp_path / "library.yml")
    assert len(fsync_calls) >= 1, "save_config must call os.fsync on the tmp file"
