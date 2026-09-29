"""Tests for boombox_library.mopidy_config — the [subsonic] scrubber.

mopidy.conf must never carry the Navidrome password: saving the source
removes any [subsonic] section and never writes one.
"""
from __future__ import annotations

import stat
from pathlib import Path

from boombox_library.mopidy_config import remove_subsonic_block, write_subsonic_block

_LEGACY = (
    "[core]\n"
    "data_dir = /var/lib/mopidy\n"
    "\n"
    "[subsonic]\n"
    "hostname = music.example\n"
    "port = 443\n"
    "username = admin\n"
    "password = hunter2\n"
    "ssl = true\n"
    "context = rest\n"
    "\n"
    "[local]\n"
    "media_dir = /opt/boombox/cache-mount/audio\n"
)


def test_remove_strips_section_and_password(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    conf.write_text(_LEGACY)
    assert remove_subsonic_block(conf) is True
    text = conf.read_text()
    assert "[subsonic]" not in text
    assert "hunter2" not in text
    assert "music.example" not in text
    # Neighbouring sections survive intact.
    assert "[core]\ndata_dir = /var/lib/mopidy\n" in text
    assert "[local]\nmedia_dir = /opt/boombox/cache-mount/audio\n" in text
    assert "\n\n\n" not in text


def test_remove_is_idempotent_and_leaves_clean_file_untouched(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    conf.write_text(_LEGACY)
    remove_subsonic_block(conf)
    once = conf.read_text()
    mtime = conf.stat().st_mtime_ns
    assert remove_subsonic_block(conf) is False
    assert conf.read_text() == once
    assert conf.stat().st_mtime_ns == mtime


def test_remove_missing_file_is_noop(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    assert remove_subsonic_block(conf) is False
    assert not conf.exists()


def test_remove_handles_brackets_in_values(tmp_path: Path):
    """A value containing '[' must not end the section early and leave
    half the credentials behind."""
    conf = tmp_path / "mopidy.conf"
    conf.write_text(
        "[subsonic]\n"
        "hostname = 192.168.1.223\n"
        "password = some[weird]value\n"
        "ssl = false\n"
        "\n"
        "[local]\n"
        "media_dir = /tmp\n"
    )
    remove_subsonic_block(conf)
    text = conf.read_text()
    assert "some[weird]value" not in text
    assert "192.168.1.223" not in text
    assert text == "[local]\nmedia_dir = /tmp\n"


def test_remove_keeps_comment_mentioning_subsonic(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    conf.write_text(
        "# tried [subsonic] but rolled back\n"
        "[core]\n"
        "data_dir = /x\n"
        "\n"
        "[subsonic]\n"
        "password = old\n"
    )
    remove_subsonic_block(conf)
    text = conf.read_text()
    assert "# tried [subsonic] but rolled back" in text
    assert "password = old" not in text
    assert text.endswith("data_dir = /x\n")


def test_remove_strips_duplicate_sections(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    conf.write_text("[subsonic]\npassword = a\n\n[core]\nx = 1\n\n[subsonic]\npassword = b\n")
    remove_subsonic_block(conf)
    assert conf.read_text() == "[core]\nx = 1\n"


def test_rewritten_file_is_owner_only(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    conf.write_text(_LEGACY)
    conf.chmod(0o600)
    remove_subsonic_block(conf)
    assert stat.S_IMODE(conf.stat().st_mode) == 0o600
    assert not (tmp_path / "mopidy.conf.tmp").exists()


def test_write_shim_never_writes_credentials(tmp_path: Path):
    """The legacy entry point (still called by the service on source save)
    must scrub, not write — even when handed a password."""
    conf = tmp_path / "mopidy.conf"
    conf.write_text(_LEGACY)
    write_subsonic_block(conf, "https://music.example", "admin", "n3wpass")
    text = conf.read_text()
    assert "[subsonic]" not in text
    assert "n3wpass" not in text and "hunter2" not in text


def test_write_shim_does_not_create_file(tmp_path: Path):
    conf = tmp_path / "mopidy.conf"
    write_subsonic_block(conf, "http://nav:4533", "u", "p")
    assert not conf.exists()


def test_shipped_template_has_no_subsonic_section():
    template = Path(__file__).resolve().parents[2] / "install" / "config" / "mopidy.conf"
    lines = template.read_text().splitlines()
    assert "[subsonic]" not in [ln.strip() for ln in lines]
    assert not any(ln.strip().startswith("password") for ln in lines)
