"""Tests for /api/remote/art/{hash}.jpg."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image


def _make_jpeg(color: str = "red") -> bytes:
    img = Image.new("RGB", (500, 500), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture
async def app_with_art_cache(tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "art-test", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    cache_dir = tmp_path / "art-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("BOOMBOX_REMOTE_ART_CACHE", str(cache_dir))

    raw = _make_jpeg("red")
    art_hash = hashlib.sha1(raw).hexdigest()
    (cache_dir / f"{art_hash}.src").write_bytes(raw)

    import boombox_remote
    app = boombox_remote.create_app()
    return app, art_hash


@pytest.mark.asyncio
async def test_art_returns_resized_jpeg(app_with_art_cache, aiohttp_client):
    app, art_hash = app_with_art_cache
    client = await aiohttp_client(app)
    resp = await client.get(f"/api/remote/art/{art_hash}.jpg",
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/jpeg"
    assert resp.headers.get("ETag") == f'"{art_hash}"'
    body = await resp.read()
    img = Image.open(io.BytesIO(body))
    assert img.size == (240, 240)


@pytest.mark.asyncio
async def test_art_304_on_etag_match(app_with_art_cache, aiohttp_client):
    app, art_hash = app_with_art_cache
    client = await aiohttp_client(app)
    resp = await client.get(f"/api/remote/art/{art_hash}.jpg",
                             headers={"Authorization": "Bearer t",
                                      "If-None-Match": f'"{art_hash}"'})
    assert resp.status == 304


@pytest.mark.asyncio
async def test_art_unknown_hash_404(app_with_art_cache, aiohttp_client):
    app, _ = app_with_art_cache
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/art/deadbeef.jpg",
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 404
