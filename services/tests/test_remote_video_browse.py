"""/api/remote/video/{views,resume,items,image} — remote_video.JellyfinBrowser."""
from __future__ import annotations

import json

import aiohttp
import pytest
from aiohttp import web

AUTH = {"Authorization": "Bearer t"}
KEY = "sekrit-key-0123456789abcdef"
DEVICE = "boombox-markii-kiosk"
MOVIE = {"Id": "aa11", "Name": "Big Buck Bunny", "Type": "Movie", "ProductionYear": 2008,
         "RunTimeTicks": 5_960_000_000, "ImageTags": {"Primary": "tag"},
         "UserData": {"Played": False, "PlayedPercentage": 12.345,
                      "PlaybackPositionTicks": 736_000_000}}
EPISODE = {"Id": "bb22", "Name": "Pilot", "Type": "Episode", "SeriesName": "Show",
           "ParentIndexNumber": 1, "IndexNumber": 2, "RunTimeTicks": 26_000_000_000,
           "UserData": {"PlaybackPositionTicks": 7_540_000_000}}


class FakeJF:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str | None]] = []
        self.device_user: str | None = "u1"
        self.new_endpoints = True
        self.image_hits = 0
        self.items_status = 200

    def app(self) -> web.Application:
        async def handle(req: web.Request) -> web.StreamResponse:
            self.seen.append((req.method, req.path_qs, req.headers.get("X-Emby-Token")))
            p = req.path
            if p == "/Devices/Info":
                if req.query.get("id") != DEVICE:
                    return web.Response(status=404)
                return web.json_response({"Id": DEVICE, "LastUserId": self.device_user})
            if p == "/UserViews" and self.new_endpoints:
                return web.json_response({"Items": [
                    {"Id": "a1b2", "Name": "Movies", "Type": "CollectionFolder",
                     "CollectionType": "movies", "IsFolder": True,
                     "ImageTags": {"Primary": "x"}}]})
            if p == "/Users/u1/Views":
                return web.json_response({"Items": [
                    {"Id": "a9b9", "Name": "Old Movies", "CollectionType": "movies",
                     "IsFolder": True}]})
            if p == "/UserItems/Resume" and self.new_endpoints:
                return web.json_response({"Items": [EPISODE]})
            if p == "/Users/u1/Items/Resume":
                return web.json_response({"Items": [MOVIE]})
            if p == "/Items":
                if self.items_status != 200:
                    return web.Response(status=self.items_status)
                return web.json_response({"Items": [MOVIE], "TotalRecordCount": 131})
            if p == "/Items/aa11/Images/Primary":
                self.image_hits += 1
                return web.Response(body=b"\xff\xd8poster", content_type="image/jpeg")
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        return app


@pytest.fixture
async def video(aiohttp_server, aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    key = tmp_path / "jellyfin-api-key"
    key.write_text(KEY + "\n")
    monkeypatch.setenv("BOOMBOX_JELLYFIN_KEY", str(key))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_ENV", str(tmp_path / "jellyfin.env"))
    monkeypatch.setenv("BOOMBOX_JELLYFIN_DEVICE_ID", DEVICE)
    monkeypatch.delenv("JELLYFIN_USER_ID", raising=False)
    monkeypatch.setenv("BOOMBOX_REMOTE_VIDEO_CACHE", str(tmp_path / "video-cache"))
    jf = FakeJF()
    srv = await aiohttp_server(jf.app())
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", str(srv.make_url("")).rstrip("/"))
    import boombox_remote
    import remote_video
    app = boombox_remote.create_app()
    session = aiohttp.ClientSession()
    remote_video.add_routes(app, remote_video.JellyfinBrowser(session))
    client = await aiohttp_client(app)
    yield client, jf, key
    await session.close()


async def test_routes_require_pair_token(video):
    client, _jf, _key = video
    for path in ("/api/remote/video/views", "/api/remote/video/resume",
                 "/api/remote/video/items", "/api/remote/video/image/aa11"):
        assert (await client.get(path)).status == 401, path


async def test_views_browse_as_the_kiosk_user(video):
    client, jf, _ = video
    r = await client.get("/api/remote/video/views", headers=AUTH)
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    assert body["items"][0]["name"] == "Movies"
    assert body["items"][0]["collection_type"] == "movies"
    assert body["items"][0]["has_image"] is True
    assert ("GET", f"/Devices/Info?id={DEVICE}", KEY) in jf.seen
    assert ("GET", "/UserViews?userId=u1", KEY) in jf.seen


async def test_kiosk_user_is_cached(video):
    client, jf, _ = video
    await client.get("/api/remote/video/views", headers=AUTH)
    await client.get("/api/remote/video/views", headers=AUTH)
    assert sum(1 for s in jf.seen if s[1].startswith("/Devices/Info")) == 1


async def test_old_endpoints_are_used_when_new_ones_404(video):
    client, jf, _ = video
    jf.new_endpoints = False
    views = await (await client.get("/api/remote/video/views", headers=AUTH)).json()
    resume = await (await client.get("/api/remote/video/resume", headers=AUTH)).json()
    assert views["items"][0]["name"] == "Old Movies"
    assert resume["items"][0]["id"] == "aa11"


async def test_resume_items_are_normalized(video):
    client, _jf, _ = video
    body = await (await client.get("/api/remote/video/resume", headers=AUTH)).json()
    ep = body["items"][0]
    assert ep == {"id": "bb22", "name": "Pilot", "type": "Episode", "collection_type": None,
                  "is_folder": False, "year": None, "runtime_s": 2600,
                  "series_name": "Show", "season": 1, "episode": 2, "overview": None,
                  "has_image": False, "played": False, "progress": None, "resume_s": 754}


async def test_items_passes_paging_filters_and_search(video):
    client, jf, _ = video
    r = await client.get("/api/remote/video/items?parent_id=a1b2&type=Movie&start=60&limit=30",
                         headers=AUTH)
    body = await r.json()
    assert body["total"] == 131 and body["start"] == 60
    assert body["items"][0]["progress"] == 12.3 and body["items"][0]["resume_s"] == 73
    path = [s[1] for s in jf.seen if s[1].startswith("/Items?")][-1]
    for part in ("userId=u1", "parentId=a1b2", "includeItemTypes=Movie", "startIndex=60",
                 "limit=30", "recursive=true"):
        assert part in path, part
    await client.get("/api/remote/video/items?search=bunny", headers=AUTH)
    path = [s[1] for s in jf.seen if s[1].startswith("/Items?")][-1]
    assert "searchTerm=bunny" in path and "recursive=true" in path
    await client.get("/api/remote/video/items?parent_id=c3d4", headers=AUTH)
    path = [s[1] for s in jf.seen if s[1].startswith("/Items?")][-1]
    assert "recursive" not in path    # series → seasons is a plain folder listing


@pytest.mark.parametrize("qs", ["parent_id=../x", "type=Movie;drop", "limit=0", "limit=201",
                                "start=-1", "start=x", "search=" + "a" * 101])
async def test_items_rejects_bad_params(video, qs):
    client, jf, _ = video
    r = await client.get(f"/api/remote/video/items?{qs}", headers=AUTH)
    assert r.status == 400
    assert not any(s[1].startswith("/Items?") for s in jf.seen)


async def test_kiosk_not_signed_in_without_pin(video, monkeypatch):
    client, jf, _ = video
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    r = await client.get("/api/remote/video/views", headers=AUTH)
    assert r.status == 409
    assert (await r.json()) == {"ok": False, "error": "kiosk not signed in"}
    assert jf.seen == []


async def test_device_without_user_is_not_signed_in(video):
    client, jf, _ = video
    jf.device_user = None
    r = await client.get("/api/remote/video/views", headers=AUTH)
    assert r.status == 409


async def test_builtin_server_falls_back_to_bootstrapped_user(video, monkeypatch):
    import remote_video
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    monkeypatch.setenv("JELLYFIN_USER_ID", "u1")
    async with aiohttp.ClientSession() as s:
        assert await remote_video.JellyfinBrowser(s).kiosk_user() == "u1"  # fake is on 127.0.0.1
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "https://video.example.com")
    async with aiohttp.ClientSession() as s:
        with pytest.raises(remote_video.VideoError) as e:
            await remote_video.JellyfinBrowser(s).kiosk_user()
    assert e.value.status == 409


async def test_not_configured_is_503(video):
    client, jf, key = video
    key.write_text("")
    r = await client.get("/api/remote/video/resume", headers=AUTH)
    assert r.status == 503
    assert (await r.json())["error"] == "video server not configured"
    assert jf.seen == []


async def test_upstream_error_is_502(video):
    client, jf, _ = video
    jf.items_status = 500
    r = await client.get("/api/remote/video/items", headers=AUTH)
    assert r.status == 502
    jf.items_status = 401
    r = await client.get("/api/remote/video/items", headers=AUTH)
    assert r.status == 502
    assert (await r.json())["error"] == "video server refused the stored API key"


async def test_unreachable_server_is_502(video, monkeypatch):
    client, _jf, _ = video
    monkeypatch.setenv("BOOMBOX_JELLYFIN_BASE", "http://127.0.0.1:1")
    import remote_video
    async with aiohttp.ClientSession() as s:
        with pytest.raises(remote_video.VideoError) as e:
            await remote_video.JellyfinBrowser(s).views()
    assert e.value.status == 502 and e.value.message == "video server unreachable"


async def test_image_is_proxied_and_cached(video, tmp_path):
    client, jf, _ = video
    for _ in range(2):
        r = await client.get("/api/remote/video/image/aa11?max_width=300", headers=AUTH)
        assert r.status == 200 and r.content_type == "image/jpeg"
        assert await r.read() == b"\xff\xd8poster"
    assert jf.image_hits == 1                        # second one came from disk
    assert (tmp_path / "video-cache" / "aa11-320.jpg").exists()   # 300 → 320 bucket
    path = [s[1] for s in jf.seen if "/Images/Primary" in s[1]][0]
    assert "maxWidth=320" in path and "format=Jpg" in path


async def test_image_missing_is_404_and_bad_id_400(video):
    client, _jf, _ = video
    assert (await client.get("/api/remote/video/image/ffff", headers=AUTH)).status == 404
    assert (await client.get("/api/remote/video/image/xyz", headers=AUTH)).status == 400


@pytest.mark.parametrize("raw,width", [(None, 320), ("", 320), ("1", 80), ("300", 320),
                                       ("320", 320), ("321", 400), ("99999", 1280), ("x", 320)])
def test_image_width_buckets(raw, width):
    import remote_video
    assert remote_video.image_width(raw) == width


async def test_api_key_never_in_responses(video, monkeypatch):
    client, jf, _ = video
    texts = []
    for path in ("/api/remote/video/views", "/api/remote/video/resume",
                 "/api/remote/video/items?search=x", "/api/remote/video/image/aa11"):
        r = await client.get(path, headers=AUTH)
        texts.append((await r.read()).decode("latin-1") + json.dumps(dict(r.headers)))
    jf.items_status = 500
    r = await client.get("/api/remote/video/items", headers=AUTH)
    texts.append(await r.text())
    monkeypatch.delenv("BOOMBOX_JELLYFIN_DEVICE_ID")
    r = await client.get("/api/remote/video/views", headers=AUTH)
    texts.append(await r.text())
    assert all(KEY not in t for t in texts)
