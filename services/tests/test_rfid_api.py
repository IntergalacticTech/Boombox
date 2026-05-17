"""HTTP routes for boombox-rfid."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from boombox_rfid.api import build_app
from boombox_rfid.db import connect, migrate


class FakeContext:
    def __init__(self, conn):
        self.conn = conn
        self.last_unbound_uid = ""
        self.last_unbound_ts = 0.0
        self.last_tap_uid = ""
        self.last_tap_ts = 0.0

    def device_path(self):
        return "/dev/input/by-id/usb-IC_Reader_TEST-event-kbd"


@pytest.fixture
async def client(tmp_path):
    conn = connect(tmp_path / "lib.db"); migrate(conn)
    ctx = FakeContext(conn)
    app = build_app(ctx)
    async with TestClient(TestServer(app)) as c:
        yield c, ctx, conn


@pytest.mark.asyncio
async def test_status_reports_version_and_device(client):
    c, _, _ = client
    r = await c.get("/api/rfid/status")
    body = await r.json()
    assert "service_version" in body
    assert "TEST" in body["device_path"]


@pytest.mark.asyncio
async def test_bind_inserts_binding(client):
    c, ctx, conn = client
    r = await c.post("/api/rfid/bind", json={
        "uid": "1234", "kind": "album", "target_id": "al1", "label": "Arrival",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT * FROM rfid_bindings WHERE uid='1234'"))
    assert len(rows) == 1
    assert rows[0]["target_id"] == "al1"


@pytest.mark.asyncio
async def test_bind_rejects_invalid_kind(client):
    c, _, _ = client
    r = await c.post("/api/rfid/bind", json={
        "uid": "1234", "kind": "garbage", "target_id": "al1",
    })
    assert r.status == 400


@pytest.mark.asyncio
async def test_bind_rejects_missing_fields(client):
    c, _, _ = client
    r = await c.post("/api/rfid/bind", json={"kind": "album", "target_id": "al1"})
    assert r.status == 400
    r = await c.post("/api/rfid/bind", json={"uid": "1234", "kind": "album"})
    assert r.status == 400


@pytest.mark.asyncio
async def test_unbind_removes_binding(client):
    c, ctx, conn = client
    conn.execute(
        "INSERT INTO rfid_bindings(uid, kind, target_id, added_at) "
        "VALUES ('9999', 'album', 'al1', 0)"
    )
    r = await c.delete("/api/rfid/bind/9999")
    assert r.status == 200
    assert list(conn.execute("SELECT * FROM rfid_bindings")) == []


@pytest.mark.asyncio
async def test_unbind_returns_404_when_missing(client):
    c, _, _ = client
    r = await c.delete("/api/rfid/bind/nope")
    assert r.status == 404


@pytest.mark.asyncio
async def test_list_bindings_returns_array(client):
    c, ctx, conn = client
    conn.execute(
        "INSERT INTO rfid_bindings(uid, kind, target_id, label, added_at) "
        "VALUES ('1', 'album', 'al1', 'A', 100)"
    )
    r = await c.get("/api/rfid/bindings")
    body = await r.json()
    assert len(body["bindings"]) == 1
    assert body["bindings"][0]["label"] == "A"


@pytest.mark.asyncio
async def test_recent_reports_last_unbound(client):
    c, ctx, _ = client
    ctx.last_unbound_uid = "5678"
    ctx.last_unbound_ts = 12345.0
    r = await c.get("/api/rfid/recent")
    body = await r.json()
    assert body["uid"] == "5678"
    assert body["ts"] == 12345.0


@pytest.mark.asyncio
async def test_bind_clears_recent_for_same_uid(client):
    c, ctx, _ = client
    ctx.last_unbound_uid = "1234"
    ctx.last_unbound_ts = 99.0
    await c.post("/api/rfid/bind", json={
        "uid": "1234", "kind": "album", "target_id": "al1",
    })
    r = await c.get("/api/rfid/recent")
    body = await r.json()
    assert body["uid"] == ""
