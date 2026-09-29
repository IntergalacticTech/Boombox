"""/api/accounts/* — auth gate and card endpoints."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer
from boombox_setup.api import build_app

LAN = {"X-Real-IP": "192.168.1.50", "X-Boombox-User": "boombox",
       "X-Boombox-Host": "192.168.1.81:8090"}


class FakeAccountsContext:
    lan_port = 8090

    def __init__(self):
        self.applied: list[dict] = []
        self.apply_results: dict[str, dict] = {}
        self.music = {"url": "https://m.example", "username": "bb",
                      "configured": True, "reachable": True}
        self.health = {"navidrome_reachable": True, "last_sync_ts": 1.0,
                       "syncing": False, "prune_deferred": None}
        self.jf_env = {"BOOMBOX_JELLYFIN_BASE": "https://v.example",
                       "JELLYFIN_API_KEY": "k"}
        self.music_calls: list[tuple] = []
        self.restarted: list[list[str]] = []

    # setup Context surface used by build_app / status
    def read_identity(self):
        return {"name": "MarkII", "id": "boombox-markii", "hostname": "markii"}
    def wifi_status(self): return {"present": False, "connected": False, "ssid": "", "ip": ""}
    def video_status(self): return {"mode": "remote", "base": "https://v.example", "has_key": True}
    def is_complete(self): return True
    def mark_complete(self): pass
    def lan_host(self): return "192.168.1.81"
    def get_skin(self): return None
    def set_skin(self, s): return True
    async def remote_status(self): return {"enabled": False, "peers": []}
    async def remote_enable(self): return {"ok": True}
    async def remote_pair_start(self): return {"ok": True}

    async def apply(self, payload):
        self.applied.append(payload)
        return self.apply_results.get(payload["action"], {"ok": True})
    async def restart_units(self, units): self.restarted.append(units)
    async def music_get(self): return dict(self.music)
    async def music_test(self, url, username, password):
        self.music_calls.append(("test", url, username, password))
        return True, ""
    async def music_save(self, url, username, password):
        self.music_calls.append(("save", url, username, password))
        return True, ""
    async def library_health(self): return dict(self.health)
    def jellyfin_env(self): return dict(self.jf_env)


@pytest.fixture
async def ctx():
    return FakeAccountsContext()


@pytest.fixture
async def client(ctx):
    app = build_app(ctx)
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c
    await c.close()


async def test_accounts_requires_basic_auth_user(client):
    r = await client.get("/api/accounts/summary", headers={"X-Real-IP": "192.168.1.50"})
    assert r.status == 401


async def test_accounts_refuses_loopback_even_with_user(client):
    r = await client.get("/api/accounts/summary",
                         headers={"X-Real-IP": "127.0.0.1", "X-Boombox-User": "boombox"})
    assert r.status == 403
    r = await client.get("/api/accounts/summary", headers={"X-Boombox-User": "boombox"})
    assert r.status == 403  # no X-Real-IP = direct on-box call


async def test_accounts_mutation_needs_json_and_same_origin(client):
    r = await client.post("/api/accounts/music/test", data="x", headers=LAN)
    assert r.status == 415
    r = await client.post("/api/accounts/music/test", json={},
                          headers={**LAN, "Origin": "http://evil.example"})
    assert r.status == 403
    r = await client.post("/api/accounts/music/test", json={"url": "u", "username": "n"},
                          headers={**LAN, "Origin": "http://192.168.1.81:8090"})
    assert r.status == 200


async def test_setup_token_does_not_open_accounts(client):
    r = await client.get("/api/accounts/summary",
                         headers={"X-Real-IP": "192.168.1.50",
                                  "Authorization": "Bearer whatever"})
    assert r.status == 401


async def test_summary_shape(client):
    r = await client.get("/api/accounts/summary", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert set(body) == {"music", "video", "streaming", "web"}
    assert body["music"]["state"] == "ok"


async def test_summary_streaming_apply_raises_degrades(client, ctx):
    async def boom(payload):
        raise RuntimeError("helper socket gone")
    ctx.apply = boom
    r = await client.get("/api/accounts/summary", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert body["streaming"]["state"] == "problem"
    assert "socket" not in body["streaming"]["detail"]
    assert body["music"]["state"] == "ok"
    assert body["video"]["state"] == "ok"
    assert body["web"]["state"] == "ok"


async def test_summary_video_env_raises_degrades(client, ctx):
    def boom():
        raise OSError("env unreadable")
    ctx.jellyfin_env = boom
    r = await client.get("/api/accounts/summary", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert body["video"]["state"] == "problem"
    assert body["music"]["state"] == "ok"
    assert body["streaming"]["state"] in {"ok", "absent"}


async def test_summary_streaming_non_dict_subresult(client, ctx):
    ctx.apply_results["streaming-status"] = {
        "ok": True, "airplay": None, "spotify": {"installed": True}}
    r = await client.get("/api/accounts/summary", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert body["streaming"] == {"state": "ok", "detail": "spotify"}


async def test_music_get_merges_health_and_never_returns_password(client):
    r = await client.get("/api/accounts/music", headers=LAN)
    body = await r.json()
    assert body["url"] == "https://m.example" and body["reachable"] is True
    assert "password" not in body and body["last_sync_ts"] == 1.0


async def test_music_put_passes_blank_password_through(client, ctx):
    r = await client.put("/api/accounts/music", headers=LAN,
                         json={"url": "https://m2.example", "username": "bb"})
    assert r.status == 200
    assert ctx.music_calls[-1] == ("save", "https://m2.example", "bb", "")


async def test_music_get_library_down_degrades(client, ctx):
    async def boom():
        raise OSError("connection refused")
    ctx.music_get = boom
    r = await client.get("/api/accounts/music", headers=LAN)
    assert r.status == 200
    body = await r.json()
    assert body["configured"] is False and body["reachable"] is False
    assert body["error"]


async def test_music_put_rejects_bad_url_and_bad_json(client, ctx):
    r = await client.put("/api/accounts/music", headers=LAN,
                         json={"url": "m.example", "username": "bb"})
    assert r.status == 400 and (await r.json())["ok"] is False
    r = await client.put("/api/accounts/music", data="{not json",
                         headers={**LAN, "Content-Type": "application/json"})
    assert r.status == 400
    r = await client.post("/api/accounts/music/test", json=["x"], headers=LAN)
    assert r.status == 400
    assert ctx.music_calls == []


async def test_music_put_failure_scrubs_password(client, ctx):
    async def leaky(url, username, password):
        return False, f"auth failed ?p={password}"
    ctx.music_save = leaky
    r = await client.put("/api/accounts/music", headers=LAN,
                         json={"url": "https://m.example", "username": "bb",
                               "password": "hunter2"})
    assert r.status == 400
    assert "hunter2" not in (await r.text())
