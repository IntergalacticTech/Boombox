"""Kiosk guard allow-list: loopback + configured Jellyfin host + env extras."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "boombox-kiosk-guard.py"
_spec = importlib.util.spec_from_file_location("boombox_kiosk_guard", _PATH)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    # Never read the real /etc/boombox/jellyfin.env from a dev box.
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    monkeypatch.delenv("BOOMBOX_JELLYFIN_BASE", raising=False)
    monkeypatch.delenv("BOOMBOX_KIOSK_ALLOWED_HOSTS", raising=False)


def test_loopback_and_internal_always_allowed():
    for url in ("http://localhost/", "http://127.0.0.1:8096/web/",
                "http://[::1]/", "about:blank", "chrome://newtab", ""):
        assert guard.is_on_target(url), url


def test_remote_host_bounced_when_not_configured():
    assert not guard.is_on_target("https://video.example.com/web/index.html")


def test_jellyfin_base_env_host_allowed(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")
    assert guard.is_on_target("https://video.example.com/web/index.html#/home")
    # Case-insensitive host, port-agnostic.
    assert guard.is_on_target("https://VIDEO.example.com:443/web/")


def test_jellyfin_base_from_file_allowed(tmp_path):
    # Setup wizard rewrote jellyfin.env after the guard started: the file's
    # value is honoured without a restart.
    (tmp_path / "jellyfin.env").write_text(
        'JELLYFIN_API_KEY=abc\nBOOMBOX_JELLYFIN_BASE="https://video.example.com/"\n')
    assert guard.is_on_target("https://video.example.com/web/")


def test_exact_hostname_only_no_suffix_tricks(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")
    for url in ("https://evil-video.example.com/",
                "https://video.example.com.evil.net/",
                "https://example.com/",
                "https://sub.video.example.com/",
                "https://evil.net/?next=https://video.example.com/",
                "https://video.example.com@evil.net/"):
        assert not guard.is_on_target(url), url
    # A trailing root dot is the same host, not a bypass.
    assert guard.is_on_target("https://video.example.com./web/")


def test_extra_hosts_env(monkeypatch):
    monkeypatch.setenv("BOOMBOX_KIOSK_ALLOWED_HOSTS",
                       " team.cloudflareaccess.com , Other.Example.org,, ")
    assert guard.is_on_target("https://team.cloudflareaccess.com/cdn-cgi/")
    assert guard.is_on_target("https://other.example.org/")
    assert not guard.is_on_target("https://x.team.cloudflareaccess.com/")


def test_default_local_jellyfin_adds_nothing_new():
    assert guard.allowed_hosts() == frozenset({"localhost", "127.0.0.1", "::1"})


def test_tick_leaves_allowed_jellyfin_tab_alone(monkeypatch):
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")
    pages = [{"type": "page", "id": "a", "url": "https://video.example.com/web/",
              "webSocketDebuggerUrl": "ws://x"}]
    monkeypatch.setattr(guard, "fetch_pages", lambda: pages)
    calls: list = []
    monkeypatch.setattr(guard, "navigate", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(guard, "close_tab", lambda *a: calls.append(a))
    guard.tick()
    assert calls == []


def test_tick_navigates_drifted_tab_home(monkeypatch):
    pages = [{"type": "page", "id": "a", "url": "https://elsewhere.example/",
              "webSocketDebuggerUrl": "ws://x"}]
    monkeypatch.setattr(guard, "fetch_pages", lambda: pages)
    calls: list = []
    monkeypatch.setattr(guard, "navigate", lambda *a: calls.append(a) or True)
    guard.tick()
    assert calls == [("ws://x", guard.HOME_URL)]
