"""Jellyfin endpoint resolution — local default vs off-device override."""
from __future__ import annotations

import jellyfin_env


def test_base_defaults_to_local(monkeypatch) -> None:
    monkeypatch.delenv("BOOMBOX_JELLYFIN_BASE", raising=False)
    assert jellyfin_env.jellyfin_base() == "http://127.0.0.1:8096"


def test_base_honors_env_override(monkeypatch) -> None:
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")
    assert jellyfin_env.jellyfin_base() == "https://video.example.com"


def test_base_strips_trailing_slash(monkeypatch) -> None:
    # Callers build "{base}/Sessions" etc.; a trailing slash would double up.
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com/")
    assert jellyfin_env.jellyfin_base() == "https://video.example.com"


def test_token_none_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(tmp_path / "nope"))
    assert jellyfin_env.jellyfin_token() is None


def test_token_read_and_stripped(tmp_path, monkeypatch) -> None:
    key = tmp_path / "key"
    key.write_text("  abc123\n")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    assert jellyfin_env.jellyfin_token() == "abc123"


def test_token_none_when_file_empty(tmp_path, monkeypatch) -> None:
    key = tmp_path / "key"
    key.write_text("   \n")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    assert jellyfin_env.jellyfin_token() is None
