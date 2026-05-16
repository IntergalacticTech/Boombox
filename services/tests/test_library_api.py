"""Tests for boombox_library.api — HTTP routes."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from boombox_library.api import build_app
from boombox_library.config import (
    LibraryConfig, SourceConfig, SyncConfig, CacheConfig, DEFAULT_CONFIG,
)
from boombox_library.db import connect, migrate
from boombox_library.models import PinKind, PinSource


class FakeContext:
    """In-memory stand-in for the service's runtime context."""
    def __init__(self, conn, cfg=None, cache_state=None, ping_ok=True):
        self.conn = conn
        self.cfg = cfg or DEFAULT_CONFIG
        self.cache_state = cache_state  # CacheDriveState
        self._ping_ok = ping_ok
        self.synced = 0

    async def is_online(self) -> bool:
        return self._ping_ok

    async def trigger_sync(self) -> None:
        self.synced += 1

    def cache_drive_state(self):
        return self.cache_state

    def save_config(self, cfg):
        self.cfg = cfg

    async def test_source(self, url, username, password) -> tuple[bool, str]:
        return (self._ping_ok, "" if self._ping_ok else "auth failed")


@pytest.fixture
async def client(tmp_path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    ctx = FakeContext(conn)
    app = build_app(ctx)
    async with TestClient(TestServer(app)) as c:
        yield c, ctx, conn


@pytest.mark.asyncio
async def test_health_returns_status(client):
    c, ctx, _ = client
    r = await c.get("/api/library/health")
    assert r.status == 200
    body = await r.json()
    assert "navidrome_reachable" in body
    assert "cache_present" in body
    assert "service_version" in body


@pytest.mark.asyncio
async def test_source_get_does_not_expose_password(client):
    c, ctx, _ = client
    ctx.cfg = LibraryConfig(
        source=SourceConfig(url="http://nav:4533", username="u", password="secret"),
        sync=DEFAULT_CONFIG.sync,
        cache=DEFAULT_CONFIG.cache,
    )
    r = await c.get("/api/library/source")
    assert r.status == 200
    body = await r.json()
    assert body["url"] == "http://nav:4533"
    assert body["username"] == "u"
    assert "password" not in body
    assert "secret" not in str(body)


@pytest.mark.asyncio
async def test_source_test_returns_ok(client):
    c, ctx, _ = client
    r = await c.post("/api/library/source/test", json={
        "url": "http://nav:4533", "username": "u", "password": "p",
    })
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_browse_artists(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','ABBA','abba',6,0)")
    r = await c.get("/api/library/browse", params={"type": "artists"})
    assert r.status == 200
    body = await r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "ABBA"


@pytest.mark.asyncio
async def test_search_uses_fts5(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO search_index(content_type,id,title,body) "
                 "VALUES('album','al1','Back in Black','AC/DC rock 1980')")
    r = await c.get("/api/library/search", params={"q": "rock"})
    assert r.status == 200
    body = await r.json()
    assert any(i["id"] == "al1" for i in body["results"])
