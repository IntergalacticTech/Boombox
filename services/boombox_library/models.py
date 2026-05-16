"""Frozen dataclasses for catalog entities, pins, and cache state.

These are the in-memory shape used by the rest of the service. SQLite
rows are mapped to and from these via simple helpers in db.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Artist:
    id: str
    name: str
    sort_name: str
    album_count: int
    art_id: Optional[str]


@dataclass(frozen=True)
class Album:
    id: str
    name: str
    sort_name: str
    artist_id: str
    year: Optional[int]
    genre: Optional[str]
    song_count: int
    duration_s: int
    art_id: Optional[str]
    is_compilation: bool
    navidrome_starred: bool


@dataclass(frozen=True)
class Track:
    id: str
    album_id: str
    title: str
    track_no: Optional[int]
    disc_no: Optional[int]
    duration_s: int
    suffix: str               # e.g. "mp3", "flac"
    size_bytes: int
    content_type: str         # e.g. "audio/mpeg"
    navidrome_starred: bool


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    song_count: int
    owner: str
    public: bool


class PinKind(str, Enum):
    ALBUM = "album"
    ARTIST = "artist"
    PLAYLIST = "playlist"
    TRACK = "track"


class PinSource(str, Enum):
    USER = "user"
    STARRED = "starred"
    RFID = "rfid"


@dataclass(frozen=True)
class Pin:
    target_kind: PinKind
    target_id: str
    source: PinSource
    added_at: float


class CacheStatus(str, Enum):
    ABSENT = "absent"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PRESENT = "present"
    ERROR = "error"


@dataclass(frozen=True)
class CacheEntry:
    track_id: str
    status: CacheStatus
    local_path: Optional[str]
    size_bytes: Optional[int]
    downloaded_at: Optional[float]
    error_message: Optional[str]
