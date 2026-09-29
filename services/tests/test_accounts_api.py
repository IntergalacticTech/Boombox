"""/api/accounts/* — auth gate and card endpoints."""
from __future__ import annotations

import aiohttp
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
        self._http_session: aiohttp.ClientSession | None = None

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
    async def http(self):
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        return self._http_session


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
    if ctx._http_session is not None:
        await ctx._http_session.close()


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


async def test_video_get_redacts_key(client, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    seen = []
    async def who(s, base, key, dev):
        seen.append((base, key, dev))
        return "jwc"
    monkeypatch.setattr(jf, "device_user", who)
    body = await (await client.get("/api/accounts/video", headers=LAN)).json()
    assert body["key_set"] is True and "k" not in str(body.get("api_key", ""))
    assert "api_key" not in body
    assert body["kiosk_device_id"] == "boombox-markii-kiosk"
    assert body["mode"] == "remote" and body["base"] == "https://v.example"
    assert body["kiosk_user"] == "jwc"
    assert seen == [("https://v.example", "k", "boombox-markii-kiosk")]


async def test_video_get_builtin_without_key_skips_lookup(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def boom(*a, **k): raise AssertionError("no lookup without a key")
    monkeypatch.setattr(jf, "device_user", boom)
    ctx.jf_env = {}
    body = await (await client.get("/api/accounts/video", headers=LAN)).json()
    assert body["mode"] == "builtin" and body["key_set"] is False
    assert body["base"] == "http://127.0.0.1:8096" and body["kiosk_user"] is None


async def test_video_save_blank_key_keeps_current(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def ok(*a, **k): return {"ServerName": "5CVideo"}
    monkeypatch.setattr(jf, "system_info", ok)
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://v2.example"})
    assert r.status == 200
    sent = ctx.applied[-1]
    assert sent["action"] == "jellyfin" and "api_key" not in sent
    assert ctx.restarted  # consumers restarted


async def test_video_save_refuses_failing_server_unless_forced(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def boom(*a, **k): raise jf.JellyfinError("Couldn't reach the Jellyfin server")
    monkeypatch.setattr(jf, "system_info", boom)
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://down.example"})
    assert r.status == 400 and (await r.json())["can_force"] is True
    assert not ctx.applied
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://down.example", "force": True})
    assert r.status == 200


async def test_video_save_rejects_bad_base(client):
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "ftp://x"})
    assert r.status == 400


async def test_video_save_tests_with_new_key_and_rejects_bad_json(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    keys = []
    async def ok(s, base, key):
        keys.append(key)
        return {}
    monkeypatch.setattr(jf, "system_info", ok)
    r = await client.put("/api/accounts/video", headers=LAN,
                         json={"mode": "remote", "base": "https://v2.example/",
                               "api_key": "newkey"})
    assert r.status == 200 and keys == ["newkey"]
    assert ctx.applied[-1] == {"action": "jellyfin", "mode": "remote",
                               "base": "https://v2.example", "api_key": "newkey"}
    r = await client.put("/api/accounts/video", headers=LAN, json=["x"])
    assert r.status == 400
    r = await client.put("/api/accounts/video", headers=LAN, json={"mode": "weird"})
    assert r.status == 400


async def test_video_save_builtin_and_apply_failure(client, ctx):
    r = await client.put("/api/accounts/video", headers=LAN, json={"mode": "builtin"})
    assert r.status == 200 and ctx.applied[-1] == {"action": "jellyfin", "mode": "builtin"}
    ctx.apply_results["jellyfin"] = {"ok": False, "error": "disk full"}
    n = len(ctx.restarted)
    r = await client.put("/api/accounts/video", headers=LAN, json={"mode": "builtin"})
    assert r.status == 400 and (await r.json())["error"] == "disk full"
    assert len(ctx.restarted) == n


async def test_video_test_endpoint(client, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    keys = []
    async def ok(s, base, key):
        keys.append(key)
        return {"ServerName": "5CVideo"}
    monkeypatch.setattr(jf, "system_info", ok)
    r = await client.post("/api/accounts/video/test", headers=LAN,
                          json={"base": "https://v.example"})
    assert await r.json() == {"ok": True, "error": "", "server_name": "5CVideo"}
    assert keys == ["k"]  # blank key = stored key
    r = await client.post("/api/accounts/video/test", headers=LAN, json={"base": "nope"})
    assert (await r.json())["ok"] is False
    async def boom(*a, **k): raise jf.JellyfinError("Jellyfin rejected the API key")
    monkeypatch.setattr(jf, "system_info", boom)
    r = await client.post("/api/accounts/video/test", headers=LAN,
                          json={"base": "https://v.example", "api_key": "bad"})
    assert r.status == 200
    assert await r.json() == {"ok": False, "error": "Jellyfin rejected the API key"}


async def test_video_users(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def users(s, base, key): return [{"id": "u1", "name": "jwc", "admin": True}]
    monkeypatch.setattr(jf, "list_users", users)
    body = await (await client.get("/api/accounts/video/users", headers=LAN)).json()
    assert body == {"users": [{"id": "u1", "name": "jwc", "admin": True}]}
    async def boom(*a, **k): raise jf.JellyfinError("Couldn't reach the Jellyfin server")
    monkeypatch.setattr(jf, "list_users", boom)
    body = await (await client.get("/api/accounts/video/users", headers=LAN)).json()
    assert body["users"] == [] and "reach" in body["error"]
    ctx.jf_env = {}
    body = await (await client.get("/api/accounts/video/users", headers=LAN)).json()
    assert body["users"] == [] and body["error"]


async def test_signin_revokes_device_when_kiosk_unreachable(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    revoked = []

    async def fake_token(*a, **k): return "tok"
    async def fake_pub(*a, **k): return {"Id": "srv1", "ServerName": "5CVideo"}
    async def fake_users(*a, **k): return [{"id": "u1", "name": "jwc", "admin": True}]
    async def fake_inject(*a, **k): raise jf.JellyfinError("kiosk not reachable — is the screen on?")
    async def fake_revoke(s, base, key, dev): revoked.append(dev)

    monkeypatch.setattr(jf, "quick_connect_token", fake_token)
    monkeypatch.setattr(jf, "public_info", fake_pub)
    monkeypatch.setattr(jf, "list_users", fake_users)
    monkeypatch.setattr(jf, "inject_kiosk", fake_inject)
    monkeypatch.setattr(jf, "revoke_device", fake_revoke)
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "u1"})
    body = await r.json()
    assert r.status == 502 and "kiosk" in body["error"]
    assert revoked == ["boombox-markii-kiosk"]
    assert not any(p.get("device_id") for p in ctx.applied)


async def test_signin_success_pins_device(client, ctx, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def fake_token(*a, **k): return "tok"
    async def fake_pub(*a, **k): return {"Id": "srv1", "ServerName": "5CVideo"}
    async def fake_users(*a, **k): return [{"id": "u1", "name": "jwc", "admin": True}]
    async def fake_inject(*a, **k): return None
    monkeypatch.setattr(jf, "quick_connect_token", fake_token)
    monkeypatch.setattr(jf, "public_info", fake_pub)
    monkeypatch.setattr(jf, "list_users", fake_users)
    monkeypatch.setattr(jf, "inject_kiosk", fake_inject)
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "u1"})
    assert r.status == 200 and (await r.json())["user"] == "jwc"
    pin = [p for p in ctx.applied if p["action"] == "jellyfin"][-1]
    assert pin["device_id"] == "boombox-markii-kiosk" and pin["mode"] == "remote"


async def test_signin_unknown_user_400(client, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    async def fake_users(*a, **k): return []
    monkeypatch.setattr(jf, "list_users", fake_users)
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "zz"})
    assert r.status == 400


async def test_signin_bad_body_and_no_key(client, ctx):
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json=[1])
    assert r.status == 400
    ctx.jf_env = {"BOOMBOX_JELLYFIN_BASE": "https://v.example"}
    r = await client.post("/api/accounts/video/kiosk-signin", headers=LAN, json={"user_id": "u1"})
    assert r.status == 400 and "API key" in (await r.json())["error"]


async def test_signout_revokes_and_clears_kiosk(client, monkeypatch):
    from boombox_setup import jellyfin_signin as jf
    calls: list = []

    async def fake_revoke(s, base, key, dev): calls.append(("revoke", dev))
    async def fake_inject(cdp, base, dev, creds, *a, **k): calls.append(("inject", dev, creds))
    monkeypatch.setattr(jf, "revoke_device", fake_revoke)
    monkeypatch.setattr(jf, "inject_kiosk", fake_inject)
    r = await client.post("/api/accounts/video/kiosk-signout", headers=LAN, json={})
    assert r.status == 200 and (await r.json())["ok"] is True
    assert calls == [("revoke", "boombox-markii-kiosk"),
                     ("inject", "boombox-markii-kiosk", None)]


async def test_signout_reports_errors(client, monkeypatch):
    from boombox_setup import jellyfin_signin as jf

    async def fake_revoke(*a, **k): raise jf.JellyfinError("Couldn't reach the Jellyfin server")
    async def fake_inject(*a, **k): raise jf.JellyfinError("kiosk not reachable")
    monkeypatch.setattr(jf, "revoke_device", fake_revoke)
    monkeypatch.setattr(jf, "inject_kiosk", fake_inject)
    r = await client.post("/api/accounts/video/kiosk-signout", headers=LAN, json={})
    body = await r.json()
    assert r.status == 200 and body["ok"] is False
    assert "reach" in body["error"] and "kiosk" in body["error"]
