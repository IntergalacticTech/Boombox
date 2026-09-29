# services/tests/test_setup_helper_webpw.py
"""boombox-setup-apply: web-password rotation + jellyfin device_id."""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    loader = SourceFileLoader("boombox_setup_apply_webpw", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()


@pytest.mark.parametrize("bad", ["short", "x" * 129, "has\nnewline", "tab\there", None])
def test_validate_web_password_rejects(bad):
    with pytest.raises(ValueError):
        helper.validate_web_password(bad)


def test_validate_web_password_accepts_passphrase():
    assert helper.validate_web_password("correct horse battery") == "correct horse battery"


@pytest.fixture
def env(tmp_path, monkeypatch):
    webenv = tmp_path / "web-auth.env"
    webenv.write_text("BOOMBOX_WEB_PORT=8090\nBOOMBOX_WEB_USER=boombox\n"
                      "BOOMBOX_WEB_PASSWORD=123456\nBOOMBOX_SMB_USER=dietpi\n")
    htp = tmp_path / "boombox.htpasswd"
    htp.write_text("boombox:$2y$old\n")
    monkeypatch.setattr(helper, "WEB_AUTH_ENV", str(webenv))
    monkeypatch.setattr(helper, "HTPASSWD", str(htp))
    monkeypatch.setattr(helper, "JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    calls: list[list[str]] = []

    class R:
        def __init__(self, rc=0):
            self.returncode, self.stdout, self.stderr = rc, "", ""

    def fake_run(cmd, timeout=25, check=False, inp=None):
        calls.append(cmd)
        if cmd[0] == "htpasswd":
            Path(cmd[-2]).write_text(f"{cmd[-1]}:$2y$new\n")
        return R(0)

    monkeypatch.setattr(helper, "_run", fake_run)
    monkeypatch.setattr(helper, "_chown", lambda *a, **k: None)
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/bin/" + n)
    return {"webenv": webenv, "htp": htp, "calls": calls, "R": R}


def test_web_password_requires_current(env):
    r = helper.action_web_password({"current_password": "nope",
                                    "new_password": "correct horse battery"})
    assert r == {"ok": False, "error": "current password is incorrect"}
    assert env["calls"] == []


def test_web_password_updates_web_and_samba(env):
    r = helper.action_web_password({"current_password": "123456",
                                    "new_password": "correct horse battery"})
    assert r["ok"] and r["updated"] == ["web", "samba"]
    assert "BOOMBOX_WEB_PASSWORD=correct horse battery" in env["webenv"].read_text()
    assert [c[0] for c in env["calls"]] == ["htpasswd", "smbpasswd"]


def test_web_password_rolls_back_on_smb_failure(env, monkeypatch):
    R = env["R"]
    old_htp = env["htp"].read_text()

    def run(cmd, timeout=25, check=False, inp=None):
        env["calls"].append(cmd)
        if cmd[0] == "htpasswd":
            Path(cmd[-2]).write_text(f"{cmd[-1]}:$2y$new\n")
            return R(0)
        if cmd[0] == "smbpasswd" and inp and "correct horse" in inp:
            return R(1)
        return R(0)

    monkeypatch.setattr(helper, "_run", run)
    r = helper.action_web_password({"current_password": "123456",
                                    "new_password": "correct horse battery"})
    assert r["ok"] is False and "samba" in r["error"]
    assert env["htp"].read_text() == old_htp
    assert "BOOMBOX_WEB_PASSWORD=123456" in env["webenv"].read_text()


def test_jellyfin_device_id_written_and_removed(tmp_path, monkeypatch):
    jenv = tmp_path / "jellyfin.env"
    jenv.write_text("BOOMBOX_JELLYFIN_BASE=https://video.example\nJELLYFIN_API_KEY=abc\n")
    monkeypatch.setattr(helper, "JELLYFIN_ENV", str(jenv))
    monkeypatch.setattr(helper, "_chown_boombox_group", lambda p: None)
    r = helper.action_jellyfin({"mode": "remote", "base": "https://video.example",
                                "device_id": "boombox-markii-kiosk"})
    assert r["ok"]
    assert "BOOMBOX_JELLYFIN_DEVICE_ID=boombox-markii-kiosk" in jenv.read_text()
    assert "JELLYFIN_API_KEY=abc" in jenv.read_text()
    helper.action_jellyfin({"mode": "remote", "base": "https://video.example",
                            "device_id": ""})
    assert "DEVICE_ID" not in jenv.read_text()


@pytest.mark.parametrize("bad", ["has space", "a;b", "x" * 65, "$(id)"])
def test_jellyfin_device_id_rejected(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(helper, "JELLYFIN_ENV", str(tmp_path / "j.env"))
    monkeypatch.setattr(helper, "_chown_boombox_group", lambda p: None)
    r = helper.action_jellyfin({"mode": "remote", "base": "https://v.example",
                                "device_id": bad})
    assert r["ok"] is False
