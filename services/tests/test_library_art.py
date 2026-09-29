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


_AUTH = {"u": "x", "t": "y", "s": "z", "v": "1", "c": "b", "f": "json"}


@pytest.fixture(autouse=True)
async def _close_art_session():
    """fetch_art pools one module-level session; close it after each test
    so it never outlives the test's event loop."""
    yield
    from boombox_library.art import close_shared_session
    await close_shared_session()


async def _art_server(aiohttp_server, handler) -> str:
    app = web.Application()
    app.router.add_get("/rest/getCoverArt.view", handler)
    server = await aiohttp_server(app)
    return str(server.make_url("")).rstrip("/")


@pytest.mark.asyncio
async def test_fetch_art_timeout_is_clean_miss(tmp_path: Path, aiohttp_server):
    """A stalled upstream (total timeout → asyncio.TimeoutError, not a
    ClientError) returns None so the API answers 404, never a 500."""
    import asyncio

    async def slow(request: web.Request) -> web.Response:
        await asyncio.sleep(2)
        return web.Response(body=b"late", content_type="image/jpeg")

    base_url = await _art_server(aiohttp_server, slow)
    result = await fetch_art(base_url=base_url, auth_params=_AUTH,
                             art_id="al-slow", cache_dir=tmp_path,
                             timeout_seconds=0.2)
    assert result is None
    assert not (tmp_path / "al-slow.bin").exists()


@pytest.mark.asyncio
async def test_fetch_art_non_image_response_not_cached(tmp_path: Path, aiohttp_server):
    """A Cloudflare challenge page served as 200 text/html must not be
    cached forever as 'art' (nor handed to the UI)."""
    async def challenge(request: web.Request) -> web.Response:
        return web.Response(text="<html>Just a moment...</html>",
                            content_type="text/html")

    base_url = await _art_server(aiohttp_server, challenge)
    result = await fetch_art(base_url=base_url, auth_params=_AUTH,
                             art_id="al-cf", cache_dir=tmp_path)
    assert result is None
    assert not (tmp_path / "al-cf.bin").exists()


@pytest.mark.asyncio
async def test_fetch_art_reuses_shared_session(tmp_path: Path, aiohttp_server):
    from boombox_library.art import shared_session

    async def cover(request: web.Request) -> web.Response:
        return web.Response(body=b"\x89PNGbytes", content_type="image/png")

    base_url = await _art_server(aiohttp_server, cover)
    r1 = await fetch_art(base_url=base_url, auth_params=_AUTH,
                         art_id="al-1", cache_dir=tmp_path)
    s1 = shared_session()
    r2 = await fetch_art(base_url=base_url, auth_params=_AUTH,
                         art_id="al-2", cache_dir=tmp_path)
    assert r1 is not None and r1[1] == "image/png"
    assert r2 is not None
    assert shared_session() is s1
    assert not s1.closed  # fetch_art must not close the shared session


@pytest.mark.asyncio
async def test_fetch_art_uses_injected_session_and_leaves_it_open(
        tmp_path: Path, aiohttp_server):
    import aiohttp

    async def cover(request: web.Request) -> web.Response:
        return web.Response(body=b"\xff\xd8x", content_type="image/jpeg")

    base_url = await _art_server(aiohttp_server, cover)
    async with aiohttp.ClientSession() as session:
        r = await fetch_art(base_url=base_url, auth_params=_AUTH,
                            art_id="al-inj", cache_dir=tmp_path,
                            session=session)
        assert r is not None
        assert not session.closed
