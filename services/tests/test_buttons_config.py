"""Config loading: schema, defaults, validation, disable rules."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

buttons = importlib.import_module("boombox-buttons".replace("-", "_"))
# Service file is `boombox-buttons.py`; importlib can't import hyphenated
# names directly. The service ships a symlink-friendly name via conftest's
# sys.path entry plus a one-line shim. We rely on the renamed import below.


def test_defaults_have_every_action():
    cfg = buttons.default_config()
    assert set(cfg["pins"].keys()) == {
        "play_pause", "stop", "previous", "next", "shuffle", "repeat",
        "sleep_timer", "skin_cycle", "library", "airplay", "spotify",
        "bluetooth", "movies", "web", "mic_karaoke", "record", "power",
    }
    assert "encoder" in cfg
    assert cfg["long_press_ms"] == 600
    assert cfg["power_hold_ms"] == 2000


def test_load_merges_user_overrides(tmp_path: Path):
    user = {"long_press_ms": 800, "pins": {"play_pause": {"pin": 99, "enabled": False}}}
    f = tmp_path / "buttons.json"
    f.write_text(json.dumps(user))
    cfg = buttons.load_config(f)
    assert cfg["long_press_ms"] == 800
    assert cfg["pins"]["play_pause"] == {"pin": 99, "enabled": False}
    # Untouched defaults preserved
    assert cfg["pins"]["stop"]["enabled"] is True


def test_load_missing_file_returns_defaults(tmp_path: Path):
    cfg = buttons.load_config(tmp_path / "does-not-exist.json")
    assert cfg == buttons.default_config()


def test_load_malformed_file_returns_defaults(tmp_path: Path, caplog):
    f = tmp_path / "buttons.json"
    f.write_text("{ not json")
    import logging
    with caplog.at_level(logging.WARNING):
        cfg = buttons.load_config(f)
    assert cfg == buttons.default_config()
    assert any("could not read" in r.message for r in caplog.records)


def test_load_rejects_null_override_of_dict_section(tmp_path: Path):
    """User typo `{"pins": null}` must not clobber the default pins dict."""
    f = tmp_path / "buttons.json"
    f.write_text(json.dumps({"pins": None}))
    cfg = buttons.load_config(f)
    assert isinstance(cfg["pins"], dict)
    assert "play_pause" in cfg["pins"]


def test_enabled_pins_filters_correctly():
    cfg = buttons.default_config()
    cfg["pins"]["stop"]["enabled"] = False
    cfg["pins"]["record"]["pin"] = None
    enabled = buttons.enabled_pins(cfg)
    assert "play_pause" in enabled
    assert "stop" not in enabled       # disabled flag
    assert "record" not in enabled     # null pin
    assert "encoder_a" in enabled      # encoder phases included
    assert "encoder_b" in enabled
    assert "encoder_push" in enabled


def test_pin_conflict_detected():
    cfg = buttons.default_config()
    cfg["pins"]["play_pause"]["pin"] = 99
    cfg["pins"]["stop"]["pin"] = 99
    conflicts = buttons.pin_conflicts(cfg)
    assert (99, ["play_pause", "stop"]) in conflicts


def test_pin_conflicts_empty_for_default_config():
    """The spec's default pin map must be internally consistent."""
    assert buttons.pin_conflicts(buttons.default_config()) == []
