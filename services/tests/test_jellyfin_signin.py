"""jellyfin_signin HTTP helpers against a fake Jellyfin."""
from __future__ import annotations

import json

import pytest
from aiohttp import ClientSession, web
from boombox_setup import jellyfin_signin as jf

KEY = "apikey"


def fake_jellyfin(qc_enabled=True):
    state = {"authorized": set(), "devices": {}, "revoked": []}

    def keyed(req):
        return req.headers.get("X-Emby-Token") == KEY

    async def info(req):
        if not keyed(req):
            return web.Response(status=401)
        return web.json_response({"ServerName": "5CVideo", "Version": "10.10.7"})

    async def pub(req):
        return web.json_response({"Id": "srv1", "ServerName": "5CVideo"})

    async def users(req):
        return web.json_response([{"Id": "u1", "Name": "jwc",
                                   "Policy": {"IsAdministrator": True}}])

    async def initiate(req):
        if not qc_enabled:
            return web.Response(status=401, text="Quick connect is disabled")
        assert 'DeviceId="dev-kiosk"' in req.headers["Authorization"]
        return web.json_response({"Secret": "sec", "Code": "123456"})

    async def authorize(req):
        assert keyed(req) and req.query["code"] == "123456"
        state["authorized"].add(req.query["userId"])
        return web.json_response(True)

    async def auth_qc(req):
        body = await req.json()
        assert body == {"Secret": "sec"} and state["authorized"]
        state["devices"]["dev-kiosk"] = "jwc"
        return web.json_response({"AccessToken": "tok", "User": {"Id": "u1"}})

    async def devices_delete(req):
        state["revoked"].append(req.query["id"])
        return web.Response(status=204)

    async def device_info(req):
        name = state["devices"].get(req.query["id"])
        if not name:
            return web.Response(status=404)
        return web.json_response({"LastUserName": name})

    app = web.Application()
    app.router.add_get("/System/Info", info)
    app.router.add_get("/System/Info/Public", pub)
    app.router.add_get("/Users", users)
    app.router.add_post("/QuickConnect/Initiate", initiate)
    app.router.add_post("/QuickConnect/Authorize", authorize)
    app.router.add_post("/Users/AuthenticateWithQuickConnect", auth_qc)
    app.router.add_delete("/Devices", devices_delete)
    app.router.add_get("/Devices/Info", device_info)
    return app, state


@pytest.fixture
async def server(aiohttp_server):
    app, state = fake_jellyfin()
    srv = await aiohttp_server(app)
    return str(srv.make_url("")).rstrip("/"), state


async def test_system_info_bad_key(server):
    base, _ = server
    async with ClientSession() as s:
        with pytest.raises(jf.JellyfinError, match="API key"):
            await jf.system_info(s, base, "wrong")


async def test_list_users(server):
    base, _ = server
    async with ClientSession() as s:
        assert await jf.list_users(s, base, KEY) == [{"id": "u1", "name": "jwc", "admin": True}]


async def test_quick_connect_token_flow(server):
    base, state = server
    async with ClientSession() as s:
        tok = await jf.quick_connect_token(s, base, KEY, "u1", "dev-kiosk", "MarkII kiosk", "1.0")
        assert tok == "tok"
        assert await jf.device_user(s, base, KEY, "dev-kiosk") == "jwc"
        await jf.revoke_device(s, base, KEY, "dev-kiosk")
    assert state["revoked"] == ["dev-kiosk"]


async def test_quick_connect_disabled_message(aiohttp_server):
    app, _ = fake_jellyfin(qc_enabled=False)
    srv = await aiohttp_server(app)
    async with ClientSession() as s:
        with pytest.raises(jf.JellyfinError, match="Quick Connect"):
            await jf.quick_connect_token(s, str(srv.make_url("")).rstrip("/"), KEY,
                                         "u1", "dev-kiosk", "k", "1")


async def test_unreachable_server_is_jellyfin_error():
    async with ClientSession() as s:
        with pytest.raises(jf.JellyfinError, match="reach"):
            await jf.system_info(s, "http://127.0.0.1:9", KEY)



def test_mb_auth_strips_header_hazards():
    h = jf.mb_auth('dev"1', 'Mark\r\nII "kiosk"', "1\n0", 'to"k\r')
    assert "\r" not in h and "\n" not in h
    assert h.count('"') == 10  # only the 5 value delimiters (5 × 2)
    assert 'DeviceId="dev\'1"' in h and 'Device="Mark  II \'kiosk\'"' in h
    assert 'Version="1 0"' in h and 'Token="to\'k "' in h


def test_credentials_blob_shape():
    blob = json.loads(jf.credentials_blob("https://v.example", "srv1", "5CVideo",
                                          "u1", "tok", 1700000000000))
    s = blob["Servers"][0]
    assert s["ManualAddress"] == "https://v.example" and s["Id"] == "srv1"
    assert s["UserId"] == "u1" and s["AccessToken"] == "tok"


async def test_inject_kiosk_drives_cdp(aiohttp_server):
    sent: list[dict] = []

    async def json_list(req):
        port = req.url.port
        return web.json_response([{"type": "page", "url": "http://localhost/",
                                   "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/1"}])

    async def ws(req):
        w = web.WebSocketResponse()
        await w.prepare(req)
        async for msg in w:
            m = json.loads(msg.data)
            sent.append(m)
            result = {"result": {"value": "complete"}} if m["method"] == "Runtime.evaluate" else {}
            await w.send_str(json.dumps({"id": m["id"], "result": result.get("result", {})}))
        return w

    app = web.Application()
    app.router.add_get("/json", json_list)
    app.router.add_get("/devtools/page/1", ws)
    srv = await aiohttp_server(app)
    await jf.inject_kiosk(str(srv.make_url("")).rstrip("/"), "https://v.example",
                          "dev-kiosk", '{"Servers":[]}')
    methods = [m["method"] for m in sent]
    assert methods[0] == "Page.navigate" and sent[0]["params"]["url"] == "https://v.example/web/"
    js = " ".join(m["params"].get("expression", "") for m in sent if m["method"] == "Runtime.evaluate")
    assert "_deviceId2" in js and "jellyfin_credentials" in js and "dev-kiosk" in js
    assert sent[-1]["method"] == "Page.navigate" and sent[-1]["params"]["url"] == "http://localhost/"


async def test_inject_kiosk_unreachable():
    with pytest.raises(jf.JellyfinError, match="kiosk"):
        await jf.inject_kiosk("http://127.0.0.1:9", "https://v.example", "d", "{}")


def test_eval_value_accepts_flat_and_chrome_shapes():
    assert jf._eval_value({"value": "complete"}) == "complete"
    assert jf._eval_value({"result": {"type": "string", "value": "complete"}}) == "complete"
    assert jf._eval_value({}) is None
