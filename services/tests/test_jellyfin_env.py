"""Jellyfin endpoint resolution — local default vs off-device override."""
from __future__ import annotations

import jellyfin_env
import pytest


@pytest.fixture(autouse=True)
def _no_real_env_file(tmp_path, monkeypatch) -> None:
    # jellyfin_base() falls back to jellyfin.env; never read the host's copy.
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))


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


def test_base_falls_back_to_env_file(tmp_path, monkeypatch) -> None:
    # A process whose unit doesn't load jellyfin.env still resolves it.
    monkeypatch.delenv("BOOMBOX_JELLYFIN_BASE", raising=False)
    (tmp_path / "jellyfin.env").write_text(
        "# managed\nJELLYFIN_API_KEY=abc\n"
        "BOOMBOX_JELLYFIN_BASE='https://video.example.com/'\n")
    assert jellyfin_env.jellyfin_base() == "https://video.example.com"
    assert jellyfin_env.jellyfin_base_from_file() == "https://video.example.com"


def test_env_var_wins_over_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://a.example.com")
    (tmp_path / "jellyfin.env").write_text("BOOMBOX_JELLYFIN_BASE=https://b.example.com\n")
    assert jellyfin_env.jellyfin_base() == "https://a.example.com"


def test_empty_env_var_falls_through_to_default(monkeypatch) -> None:
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "")
    assert jellyfin_env.jellyfin_base() == "http://127.0.0.1:8096"


def test_env_file_without_base_is_none(tmp_path) -> None:
    (tmp_path / "jellyfin.env").write_text("JELLYFIN_API_KEY=abc\n")
    assert jellyfin_env.jellyfin_base_from_file() is None
