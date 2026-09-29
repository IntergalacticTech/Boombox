# services/tests/test_setup_helper_streaming.py
"""boombox-setup-apply streaming actions (AirPlay / Spotify Connect)."""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    loader = SourceFileLoader("boombox_setup_apply_streaming", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()

DIETPI_CONF = """// Sample Configuration File for Shairport Sync
general =
{
//\tname = "%H"; // comment
//\tpassword = "secret";
\toutput_backend = "alsa";
};

alsa =
{
};
"""


def test_conf_path_prefers_existing(tmp_path, monkeypatch):
    usr = tmp_path / "usr-local-etc.conf"
    etc = tmp_path / "etc.conf"
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [str(etc), str(usr)])
    assert helper.shairport_conf_path() is None
    usr.write_text(DIETPI_CONF)
    assert helper.shairport_conf_path() == str(usr)
    etc.write_text(DIETPI_CONF)
    assert helper.shairport_conf_path() == str(etc)


@pytest.mark.parametrize("bad", ["", " lead", "a\nb", 'say "hi"', "back\\slash",
                                 "$HOME", "x" * 33, "Kitchen\n", None, 7])
def test_validate_receiver_name_rejects_hazards(bad):
    with pytest.raises(ValueError):
        helper.validate_receiver_name(bad)


def test_validate_receiver_name_accepts_room_names():
    assert helper.validate_receiver_name("Kids' Room 2") == "Kids' Room 2"


def test_shairport_set_uncomments_and_sets_name():
    out = helper.shairport_set(DIETPI_CONF, "name", "Kitchen")
    assert '\tname = "Kitchen";' in out
    assert helper.shairport_get(out, "name") == "Kitchen"
    # only one active name line
    assert sum(1 for ln in out.splitlines()
               if ln.strip().startswith("name =")) == 1


def test_airplay_password_escaped_and_cleared():
    out = helper.shairport_set(DIETPI_CONF, "password", 'p"a\\ss')
    assert helper.shairport_get(out, "password") == 'p"a\\ss'
    cleared = helper.shairport_set(out, "password", None)
    assert helper.shairport_get(cleared, "password") is None


@pytest.mark.parametrize("bad", ["short", "a\nb", "x" * 65, None])
def test_validate_receiver_password(bad):
    with pytest.raises(ValueError):
        helper.validate_receiver_password(bad)


def test_raspotify_name_roundtrip():
    conf = '#LIBRESPOT_NAME="Librespot"\nLIBRESPOT_BITRATE=320\n'
    out = helper.raspotify_set_name(conf, "Living Room")
    assert 'LIBRESPOT_NAME="Living Room"' in out
    assert helper.raspotify_get_name(out) == "Living Room"
    assert "LIBRESPOT_BITRATE=320" in out


def test_streaming_action_airplay(tmp_path, monkeypatch):
    conf = tmp_path / "shairport-sync.conf"
    conf.write_text(DIETPI_CONF)
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [str(conf)])
    monkeypatch.setattr(helper, "RASPOTIFY_CONF", str(tmp_path / "missing"))
    restarted = []
    monkeypatch.setattr(helper, "_restart_system_units", restarted.extend)
    r = helper.action_streaming({"airplay_name": "Den", "airplay_password": "hunter22"})
    assert r["ok"] and r["changed"] == ["airplay"]
    assert helper.shairport_get(conf.read_text(), "name") == "Den"
    assert helper.shairport_get(conf.read_text(), "password") == "hunter22"
    assert restarted == ["shairport-sync"]


def test_streaming_action_spotify_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [])
    monkeypatch.setattr(helper, "RASPOTIFY_CONF", str(tmp_path / "missing"))
    r = helper.action_streaming({"spotify_name": "Den"})
    assert r == {"ok": False, "error": "Spotify Connect is not installed"}


def test_streaming_status_reports_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "SHAIRPORT_CONF_CANDIDATES", [])
    monkeypatch.setattr(helper, "RASPOTIFY_CONF", str(tmp_path / "missing"))
    monkeypatch.setattr(helper, "_unit_active", lambda u: False)
    r = helper.action_streaming_status({})
    assert r["airplay"]["installed"] is False
    assert r["spotify"]["installed"] is False
