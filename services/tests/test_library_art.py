"""Tests for boombox_library.art — disk cache + Navidrome proxy."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from boombox_library.art import _safe_filename, fetch_art


def test_safe_filename_strips_weird_chars():
    assert _safe_filename("al-42", None) == "al-42.bin"
    assert _safe_filename("../etc/passwd", None).endswith(".bin")
    assert "/" not in _safe_filename("../etc/passwd", None)
    assert _safe_filename("al-42", 280) == "al-42_s280.bin"


@pytest.mark.asyncio
async def test_fetch_art_reads_disk_cache_first(tmp_path: Path):
    """If bytes are on disk, we don't touch the network — works offline."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "al-42.bin").write_bytes(b"jpeg-bytes")
    # base_url is bogus on purpose — we should never call it.
    result = await fetch_art(
        base_url="http://this-host-does-not-exist.invalid",
        auth_params={"u": "x", "t": "y", "s": "z", "v": "1", "c": "b", "f": "json"},
        art_id="al-42",
        cache_dir=cache_dir,
    )
    assert result is not None
    data, ctype = result
    assert data == b"jpeg-bytes"


@pytest.mark.asyncio
async def test_fetch_art_returns_none_when_offline_and_uncached(tmp_path: Path):
    """No cached bytes + unreachable upstream → None (caller renders fallback)."""
    result = await fetch_art(
        base_url="http://localhost:1",  # nothing listening
        auth_params={"u": "x", "t": "y", "s": "z", "v": "1", "c": "b", "f": "json"},
        art_id="missing",
        cache_dir=tmp_path,
        timeout_seconds=1.0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_art_writes_through_to_disk_cache(tmp_path: Path, aiohttp_server):
    """Successful upstream fetch is persisted; second call hits disk only."""
    served = {"hits": 0}

    async def cover(request: web.Request) -> web.Response:
        served["hits"] += 1
        return web.Response(body=b"\xff\xd8server-bytes", content_type="image/jpeg")

    app = web.Application()
    app.router.add_get("/rest/getCoverArt.view", cover)
    server = await aiohttp_server(app)
    base_url = str(server.make_url("")).rstrip("/")

    r1 = await fetch_art(
        base_url=base_url,
        auth_params={"u": "x", "t": "y", "s": "z", "v": "1", "c": "b", "f": "json"},
        art_id="al-99",
        cache_dir=tmp_path,
    )
    assert r1 is not None and r1[0].startswith(b"\xff\xd8")
    assert (tmp_path / "al-99.bin").exists()

    r2 = await fetch_art(
        base_url=base_url,
        auth_params={"u": "x", "t": "y", "s": "z", "v": "1", "c": "b", "f": "json"},
        art_id="al-99",
        cache_dir=tmp_path,
    )
    assert r2 is not None and r2[0] == r1[0]
    # Second call must have been served from disk, not from the HTTP server.
    assert served["hits"] == 1
