"""Underscore-named import shim for boombox-remote.py.

The shipped service is `boombox-remote.py`; Python's import doesn't
allow hyphens. Same pattern as `boombox_buttons.py`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_real = Path(__file__).resolve().parent / "boombox-remote.py"
if not _real.exists():
    raise ImportError(
        "services/boombox-remote.py not present yet — implement it before "
        "importing boombox_remote"
    )

_spec = importlib.util.spec_from_file_location("boombox_remote_impl", _real)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["boombox_remote_impl"] = _mod
_spec.loader.exec_module(_mod)

create_app   = _mod.create_app
require_auth = _mod.require_auth
