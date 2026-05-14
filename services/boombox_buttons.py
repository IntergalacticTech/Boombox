"""Underscore-named import shim so tests can `import boombox_buttons`.

The shipped service is `boombox-buttons.py` (hyphenated to match systemd
unit naming). Python imports don't allow hyphens, so this shim loads the
real file by path and re-exports its public names -- including names that
were extracted into the sibling modules `actions` and `clients`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_real = Path(__file__).resolve().parent / "boombox-buttons.py"
_spec = importlib.util.spec_from_file_location("boombox_buttons_impl", _real)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["boombox_buttons_impl"] = _mod
_spec.loader.exec_module(_mod)

# Config + input-processing helpers still live in boombox-buttons.py.
default_config = _mod.default_config
load_config = _mod.load_config
enabled_pins = _mod.enabled_pins
pin_conflicts = _mod.pin_conflicts
PressClassifier = _mod.PressClassifier
EncoderDecoder = _mod.EncoderDecoder

# Dispatcher now lives in actions.py -- source it from there directly.
import actions  # noqa: E402

Dispatcher = actions.Dispatcher
