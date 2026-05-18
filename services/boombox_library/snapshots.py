"""Precomputed JSON snapshots of the browse responses.

The /api/library/browse endpoint is read on every drawer open and every
re-render of the touchscreen Library panel; the catalog itself only
changes when sync writes it. Recomputing the response from SQLite every
read pays:

  - an ORDER BY sort_name scan over ~8.7 k rows
  - a Python list() materialisation of every row
  - a second pass to JSON-encode the list

…all for bytes that don't change between syncs. After each successful
sync we materialise the three browse responses as files on disk; the API
streams them with an ETag derived from mtime+size. SQLite remains the
canonical store and the source for search/resolver/pins.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from sqlite3 import Connection

log = logging.getLogger("boombox-library.snapshots")

SNAPSHOT_QUERIES = {
    "albums":    "SELECT id, name, artist_id, year, art_id FROM albums ORDER BY sort_name",
    "artists":   "SELECT id, name, album_count, art_id FROM artists ORDER BY sort_name",
    "playlists": "SELECT id, name, song_count FROM playlists ORDER BY name",
}


def snapshot_path(snapshot_dir: Path, kind: str) -> Path:
    return snapshot_dir / f"{kind}.json"


def write_snapshots(conn: Connection, snapshot_dir: Path) -> dict[str, int]:
    """Materialise every browse response to disk. Returns {kind: row_count}.

    Atomic per file (.tmp + os.replace) so a crash mid-write can't leave
    a half-written file masquerading as a valid snapshot — the API would
    then serve truncated JSON to every browse until the next sync.
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for kind, sql in SNAPSHOT_QUERIES.items():
        rows = list(conn.execute(sql))
        payload = {"items": [dict(r) for r in rows]}
        target = snapshot_path(snapshot_dir, kind)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, target)
        counts[kind] = len(rows)
    log.info("snapshots written: %s", counts)
    return counts


def compute_etag(snap: Path) -> str:
    """ETag = "{mtime_ms:hex}-{size:hex}". Cheap to compute (one stat),
    changes whenever the snapshot is rewritten."""
    st = snap.stat()
    return f'"{int(st.st_mtime * 1000):x}-{st.st_size:x}"'
