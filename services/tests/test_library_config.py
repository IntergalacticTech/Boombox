"""Tests for boombox_library.config — YAML config + Fernet password encryption."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from boombox_library.config import (
    DEFAULT_CONFIG,
    LibraryConfig,
    SourceConfig,
    _derive_key,
    load_config,
    save_config,
)


def test_default_config_shape():
    c = DEFAULT_CONFIG
    assert c.sync.interval_seconds == 3600
    assert c.sync.starred_auto_pin is True
    assert c.sync.max_concurrent_downloads == 2
    assert c.cache.marker_filename == ".boombox-cache"
    assert c.cache.reserve_bytes == 20 * 1024 ** 3  # 20 GiB
    assert c.cache.internal_path == "/opt/boombox/storage/music"


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

def _mode(p: Path) -> int:
    return os.stat(p).st_mode & 0o777


def test_save_config_creates_file_0600(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    old_umask = os.umask(0o022)  # a permissive umask must not widen the mode
    try:
        path = tmp_path / "library.yml"
        save_config(DEFAULT_CONFIG, path=path)
    finally:
        os.umask(old_umask)
    assert _mode(path) == 0o600
    assert not (tmp_path / "library.yml.tmp").exists()


def test_save_config_restores_0600_on_every_save(tmp_path: Path, monkeypatch):
    """A file loosened out-of-band (or a stale world-readable .tmp) is put
    back to 0600 by the next save."""
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    path = tmp_path / "library.yml"
    save_config(DEFAULT_CONFIG, path=path)
    os.chmod(path, 0o644)
    stale = tmp_path / "library.yml.tmp"
    stale.write_text("junk")
    os.chmod(stale, 0o666)
    save_config(DEFAULT_CONFIG, path=path)
    assert _mode(path) == 0o600
    assert not stale.exists()
    assert load_config(path=path).sync.interval_seconds == 3600


def test_max_bitrate_defaults_to_zero_and_round_trips(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id",
                        lambda: "deadbeef" * 4)
    assert DEFAULT_CONFIG.source.max_bitrate_kbps == 0
    path = tmp_path / "library.yml"
    cfg = LibraryConfig(
        source=SourceConfig(url="https://music.example", username="u",
                            password="p", max_bitrate_kbps=192),
        sync=DEFAULT_CONFIG.sync,
        cache=DEFAULT_CONFIG.cache,
    )
    save_config(cfg, path=path)
    assert "max_bitrate_kbps: 192" in path.read_text()
    loaded = load_config(path=path)
    assert loaded.source.max_bitrate_kbps == 192
    assert loaded.source.password == "p"


def test_max_bitrate_missing_or_junk_parses_as_zero(tmp_path: Path):
    path = tmp_path / "library.yml"
    path.write_text("source:\n  url: https://music.example\n")
    assert load_config(path=path).source.max_bitrate_kbps == 0
    path.write_text("source:\n  max_bitrate_kbps: lots\n")
    assert load_config(path=path).source.max_bitrate_kbps == 0
    path.write_text("source:\n  max_bitrate_kbps: -5\n")
    assert load_config(path=path).source.max_bitrate_kbps == 0
    path.write_text("source:\n  max_bitrate_kbps: '320'\n")
    assert load_config(path=path).source.max_bitrate_kbps == 320


REPO = Path(__file__).resolve().parents[2]


def test_legacy_1gib_reserve_is_upgraded_to_20gib(tmp_path: Path):
    p = tmp_path / "library.yml"
    p.write_text("cache:\n  reserve_bytes: 1073741824\n")
    assert load_config(path=p).cache.reserve_bytes == 21474836480


def test_chosen_reserve_is_kept_and_junk_falls_back(tmp_path: Path):
    p = tmp_path / "library.yml"
    p.write_text("cache:\n  reserve_bytes: 5368709120\n")
    assert load_config(path=p).cache.reserve_bytes == 5368709120
    for junk in ("lots", "-1"):
        p.write_text(f"cache:\n  reserve_bytes: {junk}\n")
        assert load_config(path=p).cache.reserve_bytes == 21474836480


def test_internal_path_default_disable_and_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("boombox_library.config._machine_id", lambda: "deadbeef" * 4)
    p = tmp_path / "library.yml"
    p.write_text("cache:\n  search_paths: [/media]\n")
    assert load_config(path=p).cache.internal_path == "/opt/boombox/storage/music"
    p.write_text('cache:\n  internal_path: ""\n')
    assert load_config(path=p).cache.internal_path == ""
    p.write_text("cache:\n  internal_path:\n")
    assert load_config(path=p).cache.internal_path == ""
    cfg = replace(DEFAULT_CONFIG, cache=replace(DEFAULT_CONFIG.cache, internal_path="/srv/music"))
    save_config(cfg, path=p)
    assert load_config(path=p).cache.internal_path == "/srv/music"


def test_template_carries_the_new_defaults():
    cfg = load_config(path=REPO / "install" / "config" / "library.yml.template")
    assert cfg.cache.internal_path == "/opt/boombox/storage/music"
    assert cfg.cache.reserve_bytes == 21474836480


def test_install_creates_internal_storage_owned_by_the_service_user():
    sh = (REPO / "install" / "install.sh").read_text()
    assert ('sudo install -d -o "$BOOMBOX_USER" -g "$BOOMBOX_USER" -m 0755 '
            '/opt/boombox/storage /opt/boombox/storage/music') in sh


def test_legacy_migration_never_moves_internal_storage_into_a_release(tmp_path: Path):
    """migrate_legacy_layout moves the old checkout into releases/legacy-<sha>/,
    which later auto-update prunes delete — so /opt/boombox/storage (kept
    music, created by install.sh) must stay put, like state/."""
    if not shutil.which("git") or not shutil.which("bash"):
        pytest.skip("needs git and bash")
    sh = (REPO / "install" / "install.sh").read_text()
    fn = re.search(r"^migrate_legacy_layout\(\) \{\n.*?^\}\n", sh, re.S | re.M)
    assert fn, "migrate_legacy_layout not found in install.sh"
    root = tmp_path / "boombox"
    (root / "services").mkdir(parents=True)
    (root / "storage" / "music" / "audio").mkdir(parents=True)
    (root / "storage" / "music" / "audio" / "t1.flac").write_bytes(b"x")
    (root / "state").mkdir()
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "services" / "a.py").write_text("x\n")
    subprocess.run([*git, "add", "services"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    script = (
        "set -euo pipefail\n"
        f'BOOMBOX_ROOT="{root}"\n'
        'RELEASES_DIR="$BOOMBOX_ROOT/releases"\n'
        'CURRENT_LINK="$BOOMBOX_ROOT/current"\n'
        'STATE_DIR="$BOOMBOX_ROOT/state"\n'
        "log() { :; }\n" + fn.group(0) + "migrate_legacy_layout\n"
    )
    subprocess.run(["bash", "-c", script], check=True)
    assert (root / "storage" / "music" / "audio" / "t1.flac").read_bytes() == b"x"
    (release,) = (root / "releases").iterdir()
    assert (release / "services" / "a.py").exists()  # the checkout did move
    assert not (release / "storage").exists()
    assert (root / "state").is_dir()
