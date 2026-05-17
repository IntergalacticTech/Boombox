"""Frozen dataclasses for RFID bindings."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BindingKind(str, Enum):
    ALBUM = "album"
    ARTIST = "artist"
    PLAYLIST = "playlist"
    TRACK = "track"


@dataclass(frozen=True)
class Binding:
    uid: str
    kind: BindingKind
    target_id: str
    label: Optional[str]
    added_at: float
    last_tap_ts: Optional[float]
    tap_count: int
