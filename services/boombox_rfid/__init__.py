"""Boombox RFID service.

Reads UID strings from a USB HID-keyboard-emulating RFID reader, looks up
the user's binding for that UID (album / artist / playlist / track), and
plays it through Mopidy. Unbound taps surface a transient "recent" UID that
the touchscreen or PWA can pick up to prompt the user to bind it.

The reader device is grabbed exclusively (EVIOCGRAB) so keystrokes don't
leak to the kiosk Chromium.

Bindings live in the boombox-library SQLite DB (rfid_bindings table) as an
additive migration on top of Phase 1's schema. A bind also writes a pin
row with source='rfid' so the bound content is pre-cached for offline play.
"""
from __future__ import annotations

__version__ = "0.1.0"
