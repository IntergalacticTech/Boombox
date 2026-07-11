"""Tests for boombox_library.config — YAML config + Fernet password encryption."""
from __future__ import annotations

import os
from pathlib import Path

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


def test_write_mopidy_subsonic_block_creates(tmp_path: Path):
    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"
    mopidy_conf.write_text(
        "[core]\n"
        "data_dir = /var/lib/mopidy\n"
        "\n"
        "[local]\n"
        "media_dir = /opt/boombox/cache-mount/audio\n"
    )
    write_subsonic_block(
        path=mopidy_conf,
        url="http://192.168.1.223:4533",
        username="boombox",
        password="hunter2",
    )
    text = mopidy_conf.read_text()
    assert "[subsonic]" in text
    assert "hostname = 192.168.1.223" in text
    assert "port = 4533" in text
    assert "username = boombox" in text
    assert "password = hunter2" in text
    # Idempotent: original blocks preserved
    assert "[local]" in text
    assert "[core]" in text


def test_write_mopidy_subsonic_block_replaces(tmp_path: Path):
    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"
    mopidy_conf.write_text(
        "[subsonic]\n"
        "hostname = old.example\n"
        "port = 4533\n"
        "username = old\n"
        "password = old\n"
        "ssl = false\n"
        "\n"
        "[local]\n"
        "media_dir = /tmp\n"
    )
    write_subsonic_block(
        path=mopidy_conf,
        url="http://new:4533",
        username="new",
        password="newpass",
    )
    text = mopidy_conf.read_text()
    assert text.count("[subsonic]") == 1
    assert "hostname = new" in text
    assert "username = new" in text
    assert "password = newpass" in text
    assert "old.example" not in text
    assert "[local]" in text


def test_write_mopidy_subsonic_block_preserves_brackets_in_values(tmp_path: Path):
    """Edge case: an existing [subsonic] block has a value containing '['
    (e.g., a password with a bracket, or an IPv6 hostname). The regex
    must consume the WHOLE block until the next [section] header — not
    truncate at the first '[' inside a value."""
    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"
    mopidy_conf.write_text(
        "[core]\n"
        "data_dir = /var/lib/mopidy\n"
        "\n"
        "[subsonic]\n"
        "hostname = 192.168.1.223\n"
        "port = 4533\n"
        "username = boombox\n"
        "password = some[weird]value\n"   # bracket inside value
        "ssl = false\n"
        "\n"
        "[local]\n"
        "media_dir = /tmp\n"
    )
    write_subsonic_block(
        path=mopidy_conf,
        url="http://new.example:4533",
        username="new",
        password="newpass",
    )
    text = mopidy_conf.read_text()
    # Old bracket-bearing value must be gone
    assert "some[weird]value" not in text
    # New value present
    assert "username = new" in text
    assert "password = newpass" in text
    # [local] section preserved
    assert "[local]" in text
    assert "media_dir = /tmp" in text
    # Only ONE [subsonic] block
    assert text.count("[subsonic]") == 1


def test_write_mopidy_subsonic_block_ignores_commented_subsonic(tmp_path: Path):
    """Edge case: a comment line containing '[subsonic]' above the real
    section. The writer must NOT mistake the comment for the section to
    replace — credentials would silently never update."""
    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"
    mopidy_conf.write_text(
        "[core]\n"
        "data_dir = /var/lib/mopidy\n"
        "\n"
        "# tried [subsonic] but rolled back\n"   # decoy comment
        "\n"
        "[subsonic]\n"
        "hostname = old.example\n"
        "username = old\n"
        "password = old\n"
        "\n"
        "[local]\n"
        "media_dir = /tmp\n"
    )
    write_subsonic_block(
        path=mopidy_conf,
        url="http://new:4533",
        username="new",
        password="newpass",
    )
    text = mopidy_conf.read_text()
    assert "old.example" not in text
    assert "username = old" not in text
    assert "username = new" in text
    # Decoy comment preserved verbatim
    assert "# tried [subsonic] but rolled back" in text
    # Only ONE [subsonic] (real) section
    assert text.count("\n[subsonic]") == 1 or text.count("[subsonic]") == 2
    # ^ the second form accepts the decoy + the real section together;
    # the first form counts only line-start [subsonic] headers


def test_write_mopidy_subsonic_block_sets_owner_only_perms_on_create(tmp_path: Path):
    """If mopidy.conf doesn't exist yet (fresh install), the writer must
    create it with 0o600 perms — the file contains the plaintext
    Subsonic password and shouldn't be world-readable."""
    import stat as _stat

    from boombox_library.mopidy_config import write_subsonic_block

    mopidy_conf = tmp_path / "mopidy.conf"  # does not exist
    write_subsonic_block(
        path=mopidy_conf,
        url="http://nav:4533",
        username="u",
        password="p",
    )
    mode = _stat.S_IMODE(mopidy_conf.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got 0o{mode:o}"
