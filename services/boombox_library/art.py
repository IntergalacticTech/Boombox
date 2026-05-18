"""Album-art fetch + on-disk cache.

The UI shows cover art for every visible album row. Without a local cache
the touchscreen previously fanned out one HTTPS call per row to iTunes
Search (services/boombox-state.py:album_art), which iTunes rate-limits
into 403s once the request rate climbs past a handful per second — exactly
what happens when 8 k+ rows mount at once.

This module proxies Navidrome's cover-art endpoint via the Subsonic
`art_id` we already store in `albums.art_id`. Bytes are cached on disk
so subsequent loads (and any load when Navidrome is offline) skip the
network entirely.

Subsonic art_ids are content-stable in practice — a new piece of art
gets a new id — so we serve with `Cache-Control: immutable` in the API
layer and never invalidate the disk cache.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("boombox-library.art")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.\-]")


def _safe_filename(art_id: str, size: Optional[int]) -> str:
    """Map an art_id (+ optional size) to a safe filename inside cache_dir.

    Subsonic ids are usually `al-<digits>` or hex; this is defensive
    against odd characters and limits length so we can't accidentally
    blow past PATH_MAX with a pathological id.
    """
    base = _SAFE_NAME.sub("_", art_id)[:128]
    if size:
        base = f"{base}_s{int(size)}"
    return f"{base}.bin"


async def fetch_art(
    base_url: str,
    auth_params: dict,
    art_id: str,
    cache_dir: Path,
    size: Optional[int] = None,
    timeout_seconds: float = 6.0,
    session: aiohttp.ClientSession | None = None,
) -> Optional[tuple[bytes, str]]:
    """Return (bytes, content_type) from disk cache, falling back to a
    fresh Navidrome fetch on miss. Returns None if both fail.

    Disk write is atomic (`.tmp` + rename) so a crash mid-write can't
    leave a half-written file masquerading as a valid cache entry.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / _safe_filename(art_id, size)

    if cache_path.exists():
        try:
            data = cache_path.read_bytes()
            if data:
                return (data, "image/jpeg")
        except OSError as e:
            log.warning("art cache read %s: %s", cache_path, e)

    if not base_url:
        return None

    params = {**auth_params, "id": art_id}
    if size is not None:
        params["size"] = size
    url = f"{base_url.rstrip('/')}/rest/getCoverArt.view"
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    own_session = session is None
    if session is None:
        session = aiohttp.ClientSession(timeout=timeout)
    try:
        async with session.get(url, params=params, timeout=timeout) as r:
            if r.status != 200:
                log.info("navidrome art %s -> http %d", art_id, r.status)
                return None
            data = await r.read()
            ctype = r.headers.get("Content-Type", "image/jpeg")
    except aiohttp.ClientError as e:
        log.info("navidrome art %s fetch failed: %s", art_id, e)
        return None
    finally:
        if own_session:
            await session.close()

    if not data:
        return None

    try:
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(cache_path)
    except OSError as e:
        log.warning("art cache write %s: %s", cache_path, e)

    return (data, ctype)
