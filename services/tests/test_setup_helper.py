"""Tests for the boombox-setup-apply helper's pure functions.

The helper is a standalone root script under install/bin/; we import it by
path (it's stdlib-only) and exercise the input validation / parsing that runs
before any privileged side effect.
"""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    # The helper is an extensionless script, so give importlib an explicit
    # source loader rather than relying on suffix inference.
    loader = SourceFileLoader("boombox_setup_apply", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()


# ---- validate_name -----------------------------------------------------------
@pytest.mark.parametrize("name", [
    "Kitchen", "Living Room", "Kids' Room", "Living-Room 2", "boombox2", "A",
])
def test_valid_names(name):
    assert helper.validate_name(name) == name.strip()


@pytest.mark.parametrize("bad", [
    "", "   ", "x" * 33, "no\nnewline", "semi;colon", "$(rm -rf)", "a\tb",
    "back`tick", 123, None,
])
def test_invalid_names_rejected(bad):
    with pytest.raises(ValueError):
        helper.validate_name(bad)


# ---- slugify -----------------------------------------------------------------
@pytest.mark.parametrize("name,slug", [
    ("Living Room", "living-room"),
    ("Kids' Room", "kids-room"),
    ("boombox2", "boombox2"),
    ("  Den  ", "den"),
    ("A---B", "a-b"),
    ("!!!", "boombox"),          # nothing survives → fallback
    ("Café 9", "caf-9"),         # non-ascii dropped
])
def test_slugify(name, slug):
    assert helper.slugify(name) == slug


def test_slug_is_valid_hostname_label():
    s = helper.slugify("My Loud Living-Room Boombox #1")
    assert 1 <= len(s) <= 63
    assert s[0].isalnum() and s[-1].isalnum()
    assert all(ch.isalnum() or ch == "-" for ch in s)


# ---- parse_nmcli_scan --------------------------------------------------------
def test_parse_nmcli_scan_dedups_and_sorts():
    out = "\n".join([
        "HomeNet:72:WPA2",
        "HomeNet:40:WPA2",     # weaker dup — dropped
        "Open Guest:55:",      # open network
        ":88:WPA2",            # hidden SSID — dropped
        "Neighbor:20:WPA1 WPA2",
    ])
    nets = helper.parse_nmcli_scan(out)
    ssids = [n["ssid"] for n in nets]
    assert ssids == ["HomeNet", "Open Guest", "Neighbor"]   # strongest first
    assert nets[0]["signal"] == 72
    assert next(n for n in nets if n["ssid"] == "Open Guest")["secured"] is False
    assert nets[0]["secured"] is True


def test_parse_nmcli_scan_handles_escaped_colon():
    # nmcli -t escapes ':' inside a field as '\:'
    out = r"Weird\:Name:60:WPA2"
    nets = helper.parse_nmcli_scan(out)
    assert nets == [{"ssid": "Weird:Name", "signal": 60, "secured": True}]


# ---- action dispatch validation (no privileged side effects hit) -------------
def test_jellyfin_rejects_bad_mode():
    assert helper.action_jellyfin({"mode": "bogus"})["ok"] is False


def test_jellyfin_remote_requires_valid_base():
    assert helper.action_jellyfin({"mode": "remote", "base": "not-a-url"})["ok"] is False


def test_wifi_join_validates_ssid_and_psk():
    assert helper.action_wifi_join({"ssid": "", "psk": ""})["ok"] is False
    assert helper.action_wifi_join({"ssid": "Net", "psk": "short"})["ok"] is False


# ---- parse_iw_scan (DietPi path: no NetworkManager, no live supplicant) ------
IW_SAMPLE = """\
BSS aa:bb:cc:dd:ee:01(on wlan0)
\tsignal: -45.00 dBm
\tSSID: HomeNet
\tRSN:\t * Version: 1
BSS aa:bb:cc:dd:ee:02(on wlan0)
\tsignal: -72.00 dBm
\tSSID: HomeNet
\tRSN:\t * Version: 1
BSS aa:bb:cc:dd:ee:03(on wlan0)
\tsignal: -60.00 dBm
\tSSID: Open Guest
BSS aa:bb:cc:dd:ee:04(on wlan0)
\tsignal: -80.00 dBm
\tSSID: \\x00\\x00\\x00
\tRSN:\t * Version: 1
"""


def test_parse_iw_scan_dedup_sort_and_security():
    nets = helper.parse_iw_scan(IW_SAMPLE)
    assert [n["ssid"] for n in nets] == ["HomeNet", "Open Guest"]
    home = nets[0]
    assert home["signal"] == 100  # -45 dBm clamps to 100 via 2*(dbm+100)
    assert home["secured"] is True
    assert nets[1]["secured"] is False
    assert nets[1]["signal"] == 80


def test_parse_iw_scan_empty():
    assert helper.parse_iw_scan("") == []


def test_sq_escapes_single_quotes():
    assert helper._sq("it's") == "it'\\''s"


def test_parse_wpa_state():
    out = "bssid=aa:bb\nssid=HomeNet\nwpa_state=COMPLETED\nip_address=10.0.5.141"
    assert helper.parse_wpa_state(out) == "COMPLETED"
    assert helper.parse_wpa_state("wpa_state=4WAY_HANDSHAKE\n") == "4WAY_HANDSHAKE"
    assert helper.parse_wpa_state("no state here") == ""


# ---- Wi-Fi credential validation (root writes these into wpa_supplicant) -----
@pytest.mark.parametrize("ssid,psk", [
    ("HomeNet", "correct horse"),
    ("Open Guest", ""),                      # open network
    ("Café Wi-Fi", "p@ss'w$rd\\x"),          # unicode SSID; shell-ish PSK chars
    ("x" * 32, "y" * 63),
])
def test_wifi_credentials_accepted(ssid, psk):
    assert helper.validate_wifi_credentials(ssid, psk) == (ssid, psk)


@pytest.mark.parametrize("ssid,psk", [
    ("", "password1"),
    ("é" * 17, "password1"),                  # 34 UTF-8 bytes > 32
    ('Net"\n\tpsk="x', "password1"),          # quote/newline injection
    ("Net\nctrl_interface=/tmp", ""),
    ("Net\x00", "password1"),
    ("Net", "short"),
    ("Net", "p" * 64),
    ("Net", 'pass"word1'),
    ("Net", "pass\nword1"),
    ("Net", "pässword1"),                     # non-ASCII passphrase
    (None, ""),
    ("Net", None),
])
def test_wifi_credentials_rejected(ssid, psk):
    with pytest.raises(ValueError):
        helper.validate_wifi_credentials(ssid, psk)


def test_wifi_join_rejects_injection_before_side_effects(monkeypatch):
    # Validation must fail before the helper even looks for wlan0.
    monkeypatch.setattr(helper, "_wlan_present",
                        lambda: pytest.fail("reached side effects"))
    r = helper.action_wifi_join({"ssid": 'a"\nnetwork={', "psk": "password1"})
    assert r["ok"] is False


def test_wpa_network_block_is_hex_encoded():
    block = helper.wpa_network_block('we"ird', "password")
    assert '"' not in block
    assert "\tssid=" + 'we"ird'.encode().hex() + "\n" in block
    # IEEE 802.11i-2004 H.4 test vector: passphrase "password", SSID "IEEE".
    ref = helper.wpa_network_block("IEEE", "password")
    assert "psk=f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e" in ref
    assert helper.wpa_network_block("Open", "").count("key_mgmt=NONE") == 1


# ---- Jellyfin base URL (written unquoted; sourced by root shell code) --------
@pytest.mark.parametrize("base", [
    "http://x/$(id)", "https://h`id`", "https://h;reboot", "https://h\n",
    "https://h/a b", "https://h'x", 'https://h"x', "https://h|x", "ftp://h",
])
def test_jellyfin_base_rejects_shell_metachars(base):
    assert helper.action_jellyfin({"mode": "remote", "base": base})["ok"] is False


@pytest.mark.parametrize("base", [
    "https://video.coblr.io", "http://192.168.1.5:8096", "http://[fe80::1]:8096/jf",
])
def test_jellyfin_base_accepts_plain_urls(base):
    assert helper._BASE_URL_RE.fullmatch(base)
