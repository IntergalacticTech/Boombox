"""Test fixtures shared across boombox-* service tests."""
from __future__ import annotations

import sys
from pathlib import Path

# The service modules live alongside the tests dir. Add the parent to sys.path
# so `import boombox_buttons` works without packaging.
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))
