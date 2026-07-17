"""Tests for boombox_setup.api — routing, auth gating, and proxy dispatch."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer
from boombox_setup.api import build_app


class FakeContext:
    lan_port = 8090

    def __init__(self):
        self.applied: list[dict] = []
        self.restarted: list[list[str]] = []
        self.complete = False
        self.music = {"url": "", "username": "", "configured": False, "reachable": False}
        self.remote = {"enabled": False, "peers": []}
        self.apply_result = {"ok": True}
        self.save_ok = True

    def read_identity(self):
        return {"name": "boombox2", "id": "boombox-boombox2", "hostname": "boombox2"}

    def wifi_status(self):
        return {"present": True, "connected": False, "ssid": "", "ip": ""}

    def video_status(self):
        return {"mode": "builtin", "base": "http://127.0.0.1:8096", "has_key": False}

    def is_complete(self):
        return self.complete

    def mark_complete(self):
        self.complete = True

    def lan_host(self):
        return "192.168.1.81"

    async def apply(self, payload):
        self.applied.append(payload)
        return self.apply_result

    async def restart_units(self, units):
        self.restarted.append(units)

    async def music_get(self):
        return self.music

    async def music_test(self, url, username, password):
        return (True, "")

    async def music_save(self, url, username, password):
        return (self.save_ok, "" if self.save_ok else "auth failed")

    async def remote_status(self):
        return self.remote

    async def remote_enable(self):
        self.remote["enabled"] = True
        return {"ok": True, "enabled": True}

    async def remote_pair_start(self):
        return {"ok": True, "pin": "123456", "expires_at": 999}


@pytest.fixture
async def client():
    ctx = FakeContext()
    app = build_app(ctx)
    async with TestClient(TestServer(app)) as c:
        yield c, ctx


# ---- localhost header helpers ------------------------------------------------
LAN = {"X-Real-IP": "192.168.1.50"}     # a phone on the LAN
LOCAL = {"X-Real-IP": "127.0.0.1"}      # the kiosk


@pytest.mark.asyncio
async def test_status_is_open(client):
    c, _ = client
    r = await c.get("/api/setup/status", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert body["complete"] is False
    assert body["identity"]["name"] == "boombox2"
    assert "music" in body and "remote" in body and "wifi" in body


@pytest.mark.asyncio
async def test_session_mint_is_localhost_only(client):
    c, _ = client
    # From the LAN: refused.
    r = await c.post("/api/setup/session", headers=LAN)
    assert r.status == 403
    # From the kiosk: minted, and the QR url embeds the token.
    r = await c.post("/api/setup/session", headers=LOCAL)
    assert r.status == 200
    body = await r.json()
    assert body["token"]
    assert body["url"].startswith("http://192.168.1.81:8090/setup/#t=")


@pytest.mark.asyncio
async def test_mutations_require_token_from_lan(client):
    c, _ = client
    # No token from the LAN → 401.
    r = await c.put("/api/setup/identity", json={"name": "Kitchen"}, headers=LAN)
    assert r.status == 401


@pytest.mark.asyncio
async def test_lan_client_with_valid_token_can_mutate(client):
    c, ctx = client
    # Kiosk mints a token…
    r = await c.post("/api/setup/session", headers=LOCAL)
    token = (await r.json())["token"]
    # …the phone presents it and is allowed through.
    r = await c.put("/api/setup/identity", json={"name": "Kitchen", "rename_host": True},
                    headers={**LAN, "Authorization": f"Bearer {token}"})
    assert r.status == 200
    assert ctx.applied[-1] == {"action": "identity", "name": "Kitchen", "rename_host": True}
    # identity change re-registers mDNS.
    assert ctx.restarted[-1] == ["boombox-remote"]


@pytest.mark.asyncio
async def test_localhost_mutates_without_token(client):
    c, ctx = client
    r = await c.put("/api/setup/identity", json={"name": "Den"}, headers=LOCAL)
    assert r.status == 200
    assert ctx.applied[-1]["name"] == "Den"


@pytest.mark.asyncio
async def test_identity_apply_failure_is_400(client):
    c, ctx = client
    ctx.apply_result = {"ok": False, "error": "name must be 1–32 chars"}
    r = await c.put("/api/setup/identity", json={"name": ""}, headers=LOCAL)
    assert r.status == 400
    assert not ctx.restarted  # no restart on failure


@pytest.mark.asyncio
async def test_music_put_proxies_and_redacts(client):
    c, ctx = client
    ctx.save_ok = False
    r = await c.put("/api/setup/music",
                    json={"url": "http://nav", "username": "u", "password": "hunter2"},
                    headers=LOCAL)
    assert r.status == 400


@pytest.mark.asyncio
async def test_video_remote_forwards_base_and_key(client):
    c, ctx = client
    r = await c.put("/api/setup/video",
                    json={"mode": "remote", "base": "https://v.example.com", "api_key": "abc123"},
                    headers=LOCAL)
    assert r.status == 200
    assert ctx.applied[-1]["action"] == "jellyfin"
    assert ctx.applied[-1]["base"] == "https://v.example.com"
    assert ctx.restarted[-1] == ["boombox-remote"]


@pytest.mark.asyncio
async def test_remote_enable_and_pair(client):
    c, ctx = client
    r = await c.post("/api/setup/remote/enable", headers=LOCAL)
    assert r.status == 200 and (await r.json())["enabled"] is True
    r = await c.post("/api/setup/remote/pair", headers=LOCAL)
    assert (await r.json())["pin"] == "123456"


@pytest.mark.asyncio
async def test_complete_marks_and_persists(client):
    c, ctx = client
    r = await c.post("/api/setup/complete", headers=LOCAL)
    assert r.status == 200
    assert ctx.complete is True
