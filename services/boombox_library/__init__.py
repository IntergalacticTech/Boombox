"""Boombox home-library service.

Maintains a local SQLite catalog of a Navidrome (Subsonic API) library,
downloads pinned content to a USB cache drive, opportunistically caches
streamed playback (FIFO eviction), and exposes an HTTP API on :6687
consumed by the UI and the playback resolver.

Subpackages are small and pure where possible so unit tests can exercise
auth, sync, pin reconciliation, eviction, and the resolver without
touching the network or the filesystem outside their own tempdirs.
"""
from __future__ import annotations

__version__ = "0.1.0"
