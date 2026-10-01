"""/api/remote/home/* — Home Library pass-through + play (remote_home.py)."""
from __future__ import annotations

import asyncio
import contextlib
import json

import aiohttp
import pytest
from aiohttp import web
from boombox_rfid.mopidy_client import PendingTail

AUTH = {"Authorization": "Bearer t"}


class FakeLibrary:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.resolve_items: list[dict] = []
        self.resolved_ids: list[str] | None = None
        self.force_status: int | None = None
        self.health: dict = {"navidrome_reachable": True, "internal_storage": True}
        self.keep_calls: list[tuple[str, dict]] = []

    def app(self) -> web.Application:
        async def handle(req: web.Request) -> web.StreamResponse:
            self.requests.append((req.method, req.path_qs, dict(req.headers)))
            if self.force_status:
                return web.json_response({"error": "boom"}, status=self.force_status)
            p = req.path
            if p == "/api/library/browse":
                if req.headers.get("If-None-Match") == '"v1"':
                    return web.Response(status=304, headers={"ETag": '"v1"'})
                return web.json_response(
                    {"items": [{"id": "al1", "name": "Blue", "art_id": "al-1"}]},
                    headers={"ETag": '"v1"', "Cache-Control": "no-cache"})
            if p == "/api/library/search":
                return web.json_response({"results": [
                    {"content_type": "album", "id": "al1", "title": "Blue"}]})
            if p == "/api/library/album/al1":
                return web.json_response({"album": {"id": "al1", "name": "Blue"},
                                          "tracks": [{"id": "t1"}, {"id": "t2"}]})
            if p == "/api/library/art/al-1":
                return web.Response(body=b"\xff\xd8jpeg", content_type="image/jpeg",
                                    headers={"Cache-Control": "public, max-age=31536000, immutable",
                                             "ETag": '"al-1-320"'})
            if p == "/api/library/resolve":
                self.resolved_ids = (await req.json())["ids"]
                return web.json_response({"items": self.resolve_items})
            if p == "/api/library/health":
                return web.json_response(self.health)
            if p == "/api/library/offline":
                return web.json_response({"album_ids": ["al1"], "artist_ids": [], "playlist_ids": []})
            if p == "/api/library/keep":
                body = await req.json()
                self.keep_calls.append((req.method, body))
                if body.get("id") == "missing":
                    return web.json_response({"ok": False, "error": "album not found"}, status=404)
                state = "kept" if req.method == "POST" else "none"
                return web.json_response({"ok": True, "queued": 3, "keep": {
                    "state": state, "tracks_total": 3, "tracks_present": 0}})
            return web.json_response({"error": "not found"}, status=404)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        return app


class FakePlayer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail = False

    async def play(self, uris):
        if self.fail:
            raise RuntimeError("mopidy down")
        self.calls.append(("play", list(uris)))

    async def queue(self, uris):
        self.calls.append(("queue", list(uris)))


@pytest.fixture
async def home(aiohttp_server, aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    lib = FakeLibrary()
    srv = await aiohttp_server(lib.app())
    import boombox_remote
    import remote_home
    app = boombox_remote.create_app()
    player = FakePlayer()
    session = aiohttp.ClientSession()
    remote_home.add_routes(app, session, player, base=str(srv.make_url("")).rstrip("/"))
    client = await aiohttp_client(app)
    yield client, lib, player
    await session.close()


async def test_routes_require_pair_token(home):
    client, _lib, _player = home
    for path in ("/api/remote/home/browse?type=albums", "/api/remote/home/album/al1",
                 "/api/remote/home/art/al-1", "/api/remote/home/search?q=blue"):
        assert (await client.get(path)).status == 401, path
    assert (await client.post("/api/remote/home/play", json={"ids": ["t1"]})).status == 401


async def test_browse_passes_body_and_etag_through(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/browse?type=albums", headers=AUTH)
    assert r.status == 200 and r.headers["ETag"] == '"v1"'
    assert (await r.json())["items"][0]["name"] == "Blue"
    r = await client.get("/api/remote/home/browse?type=albums",
                         headers={**AUTH, "If-None-Match": '"v1"'})
    assert r.status == 304
    assert lib.requests[-1][2].get("If-None-Match") == '"v1"'


async def test_browse_rejects_unknown_type(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/browse?type=tracks", headers=AUTH)
    assert r.status == 400 and lib.requests == []


async def test_search_and_detail_pass_through(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/search?q=blue%20moon", headers=AUTH)
    assert (await r.json())["results"][0]["id"] == "al1"
    assert lib.requests[-1][1] == "/api/library/search?q=blue%20moon"
    r = await client.get("/api/remote/home/search?q=", headers=AUTH)
    assert (await r.json()) == {"results": []}
    r = await client.get("/api/remote/home/album/al1", headers=AUTH)
    assert [t["id"] for t in (await r.json())["tracks"]] == ["t1", "t2"]
    r = await client.get("/api/remote/home/album/nope", headers=AUTH)
    assert r.status == 404


async def test_detail_rejects_bad_kind_and_id(home):
    client, lib, _ = home
    assert (await client.get("/api/remote/home/track/t1", headers=AUTH)).status == 404
    assert (await client.get("/api/remote/home/album/a%20b", headers=AUTH)).status == 400
    assert lib.requests == []


async def test_art_bytes_and_cache_headers(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/art/al-1?size=320", headers=AUTH)
    assert r.status == 200 and r.content_type == "image/jpeg"
    assert await r.read() == b"\xff\xd8jpeg"
    assert "immutable" in r.headers["Cache-Control"]
    assert lib.requests[-1][1] == "/api/library/art/al-1?size=320"
    r = await client.get("/api/remote/home/art/missing", headers=AUTH)
    assert r.status == 404


async def test_upstream_5xx_is_502(home):
    client, lib, _ = home
    lib.force_status = 500
    r = await client.get("/api/remote/home/browse?type=albums", headers=AUTH)
    assert r.status == 502
    assert (await r.json()) == {"ok": False, "error": "library service not answering"}


async def test_library_down_is_502(aiohttp_client, tmp_path, monkeypatch):
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    import remote_home
    app = boombox_remote.create_app()
    async with aiohttp.ClientSession() as session:
        remote_home.add_routes(app, session, FakePlayer(), base="http://127.0.0.1:1")
        client = await aiohttp_client(app)
        for method, path, body in (("GET", "/api/remote/home/browse?type=artists", None),
                                   ("POST", "/api/remote/home/play", {"ids": ["t1"]})):
            r = await client.request(method, path, json=body, headers=AUTH)
            assert r.status == 502, path


async def test_play_drops_offline_miss_and_reports_skipped(home):
    client, lib, player = home
    lib.resolve_items = [
        {"id": "t1", "source": "cache", "uri": "file:///m/t1.flac", "cache_status": "present"},
        {"id": "t2", "source": "offline_miss", "uri": None, "cache_status": "absent"},
        {"id": "t3", "source": "stream", "uri": "http://127.0.0.1:6687/api/library/stream/t3",
         "cache_status": "absent"},
    ]
    r = await client.post("/api/remote/home/play",
                          json={"ids": ["t1", "t2", "t3"], "mode": "play"}, headers=AUTH)
    assert r.status == 200
    assert (await r.json()) == {"ok": True, "count": 2, "skipped": 1}
    assert lib.resolved_ids == ["t1", "t2", "t3"]
    assert player.calls == [("play", ["file:///m/t1.flac",
                                      "http://127.0.0.1:6687/api/library/stream/t3"])]


async def test_queue_mode_appends(home):
    client, lib, player = home
    lib.resolve_items = [{"id": "t1", "source": "cache", "uri": "file:///m/t1.flac"}]
    r = await client.post("/api/remote/home/play", json={"ids": ["t1"], "mode": "queue"},
                          headers=AUTH)
    assert r.status == 200 and player.calls == [("queue", ["file:///m/t1.flac"])]


async def test_play_all_offline_is_409_and_never_touches_mopidy(home):
    client, lib, player = home
    lib.resolve_items = [{"id": "t1", "source": "offline_miss", "uri": None}]
    r = await client.post("/api/remote/home/play", json={"ids": ["t1"]}, headers=AUTH)
    assert r.status == 409
    assert "can play right now" in (await r.json())["error"]
    assert player.calls == []


@pytest.mark.parametrize("body", [
    {}, {"ids": []}, {"ids": "t1"}, {"ids": [1]}, {"ids": ["a b"]},
    {"ids": ["t1"], "mode": "shuffle"}, {"ids": ["t"] * 1001}, ["t1"],
])
async def test_play_rejects_bad_bodies(home, body):
    client, lib, player = home
    r = await client.post("/api/remote/home/play", json=body, headers=AUTH)
    assert r.status == 400
    assert lib.resolved_ids is None and player.calls == []


async def test_player_failure_is_502(home):
    client, lib, player = home
    lib.resolve_items = [{"id": "t1", "source": "cache", "uri": "file:///m/t1.flac"}]
    player.fail = True
    r = await client.post("/api/remote/home/play", json={"ids": ["t1"]}, headers=AUTH)
    assert r.status == 502
    assert (await r.json())["error"] == "the music player isn't answering"


# ---- HomePlayer ------------------------------------------------------------

class FakeMopidyClient:
    instances: list["FakeMopidyClient"] = []
    gate: asyncio.Event | None = None

    def __init__(self, url: str) -> None:
        self.url = url
        self.played: list[str] | None = None
        self.appended: list[PendingTail] = []
        FakeMopidyClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def play_uris(self, uris):
        self.played = list(uris)
        return PendingTail(uris=list(uris[1:]), after_tlid=7) if len(uris) > 5 else None

    async def append_tail(self, tail):
        self.appended.append(tail)
        if FakeMopidyClient.gate is not None:
            await FakeMopidyClient.gate.wait()
        return len(tail.uris)


@pytest.fixture
def fake_mopidy():
    FakeMopidyClient.instances = []
    FakeMopidyClient.gate = None
    return FakeMopidyClient


async def test_long_play_queues_tail_in_background_and_new_play_cancels_it(fake_mopidy):
    import queue_intent
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=fake_mopidy)
    fake_mopidy.gate = asyncio.Event()
    uris = [f"http://127.0.0.1:6687/api/library/stream/t{i}" for i in range(200)]
    await player.play(uris)
    assert fake_mopidy.instances[0].played == uris
    await asyncio.sleep(0)
    tail = fake_mopidy.instances[1].appended[0]
    assert tail.uris == uris[1:] and tail.after_tlid == 7
    assert queue_intent.read_intent() == uris        # resume snapshots the whole list
    first_task = player._tail_task
    assert first_task is not None
    await player.play(["file:///m/a.flac"])          # a new play supersedes the tail
    with contextlib.suppress(asyncio.CancelledError):
        await first_task
    assert first_task.cancelled()
    assert queue_intent.read_intent() is None


async def test_short_play_has_no_tail(fake_mopidy):
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=fake_mopidy)
    await player.play(["file:///m/a.flac", "file:///m/b.flac"])
    assert player._tail_task is None and len(fake_mopidy.instances) == 1


async def test_queue_appends_at_end(fake_mopidy):
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=fake_mopidy)
    await player.queue(["file:///m/a.flac"])
    tail = fake_mopidy.instances[0].appended[0]
    assert tail.uris == ["file:///m/a.flac"] and tail.after_tlid is None


class OrderedMopidy:
    """Records Mopidy side effects in order; appends land only after `gate`
    opens (a cancelled append never lands). play_uris yields mid-call so
    unlocked concurrent plays would interleave."""
    events: list[tuple] = []
    gate: asyncio.Event

    def __init__(self, url: str) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def play_uris(self, uris):
        OrderedMopidy.events.append(("play-start", uris[0]))
        for _ in range(3):
            await asyncio.sleep(0)
        OrderedMopidy.events.append(("play-end", uris[0]))
        return PendingTail(uris=list(uris[1:]), after_tlid=1) if len(uris) > 5 else None

    async def append_tail(self, tail):
        await OrderedMopidy.gate.wait()
        OrderedMopidy.events.append(("append", tail.uris[0]))
        return len(tail.uris)


@pytest.fixture
def ordered_mopidy():
    OrderedMopidy.events = []
    OrderedMopidy.gate = asyncio.Event()
    return OrderedMopidy


async def _drain() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_play_cancels_a_long_queue_all_so_it_never_lands(ordered_mopidy):
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=ordered_mopidy)
    album_a = [f"file:///m/a{i}.flac" for i in range(200)]
    await player.queue(album_a)                       # long → background append
    await _drain()
    assert len(player._queue_tasks) == 1
    queued = next(iter(player._queue_tasks))
    await player.play(["file:///m/b0.flac", "file:///m/b1.flac"])
    assert queued.cancelled()
    assert not player._queue_tasks
    ordered_mopidy.gate.set()
    await _drain()
    assert ("append", "file:///m/a0.flac") not in ordered_mopidy.events
    assert ordered_mopidy.events == [("play-start", "file:///m/b0.flac"),
                                     ("play-end", "file:///m/b0.flac")]


async def test_concurrent_plays_serialise_and_only_latest_tail_runs(ordered_mopidy):
    import queue_intent
    import remote_home
    player = remote_home.HomePlayer(rpc_url="http://mopidy", client_factory=ordered_mopidy)
    first = [f"file:///m/x{i}.flac" for i in range(20)]
    second = [f"file:///m/y{i}.flac" for i in range(20)]
    await asyncio.gather(player.play(first), player.play(second))
    ev = ordered_mopidy.events
    # Not interleaved: each play_uris finishes before the next starts.
    assert ev[:4] == [("play-start", first[0]), ("play-end", first[0]),
                      ("play-start", second[0]), ("play-end", second[0])]
    ordered_mopidy.gate.set()
    await _drain()
    appends = [e for e in ev if e[0] == "append"]
    assert appends == [("append", second[1])]         # only the latest tail
    assert queue_intent.read_intent() is None         # tail done → intent cleared


async def test_keep_status_offline_require_pair_token(home):
    client, _lib, _ = home
    body = {"kind": "album", "id": "al1"}
    assert (await client.post("/api/remote/home/keep", json=body)).status == 401
    assert (await client.delete("/api/remote/home/keep", json=body)).status == 401
    for path in ("/api/remote/home/status", "/api/remote/home/offline"):
        assert (await client.get(path)).status == 401, path


async def test_keep_and_unkeep_proxy_to_the_library(home):
    client, lib, _ = home
    body = {"kind": "album", "id": "al1"}
    r = await client.post("/api/remote/home/keep", json=body, headers=AUTH)
    assert r.status == 200 and (await r.json())["keep"]["state"] == "kept"
    r = await client.delete("/api/remote/home/keep", json=body, headers=AUTH)
    assert r.status == 200 and (await r.json())["keep"]["state"] == "none"
    assert lib.keep_calls == [("POST", body), ("DELETE", body)]


@pytest.mark.parametrize("body", [{"kind": "track", "id": "t1"}, {"kind": "album", "id": "a b"},
                                  {"kind": "album"}, ["al1"],
                                  {"kind": ["album"], "id": "al1"},
                                  {"kind": {"a": 1}, "id": "al1"}])
async def test_keep_validates_before_calling_the_library(home, body):
    client, lib, _ = home
    assert (await client.post("/api/remote/home/keep", json=body, headers=AUTH)).status == 400
    assert lib.keep_calls == []


async def test_keep_passes_a_library_404_through(home):
    client, _lib, _ = home
    r = await client.post("/api/remote/home/keep", json={"kind": "album", "id": "missing"}, headers=AUTH)
    assert r.status == 404 and (await r.json()) == {"ok": False, "error": "album not found"}


async def test_keep_and_status_library_failure_is_502(home):
    client, lib, _ = home
    lib.force_status = 500
    r = await client.post("/api/remote/home/keep", json={"kind": "album", "id": "al1"}, headers=AUTH)
    assert r.status == 502 and (await r.json()) == {"ok": False, "error": "library service not answering"}
    assert (await client.get("/api/remote/home/status", headers=AUTH)).status == 502
    assert (await client.get("/api/remote/home/offline", headers=AUTH)).status == 502


async def test_status_maps_the_library_health(home):
    client, lib, _ = home
    r = await client.get("/api/remote/home/status", headers=AUTH)
    assert (await r.json()) == {"online": True, "internal_storage": True}
    lib.health = {"navidrome_reachable": False, "internal_storage": True}
    r = await client.get("/api/remote/home/status", headers=AUTH)
    assert (await r.json()) == {"online": False, "internal_storage": True}


async def test_offline_ids_pass_through(home):
    client, _lib, _ = home
    r = await client.get("/api/remote/home/offline", headers=AUTH)
    assert (await r.json()) == {"album_ids": ["al1"], "artist_ids": [], "playlist_ids": []}


async def test_keep_status_offline_403_when_remote_disabled(home, tmp_path, monkeypatch):
    client, lib, _ = home
    state = tmp_path / "disabled-state.json"
    state.write_text(json.dumps({"enabled": False}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))
    body = {"kind": "album", "id": "al1"}
    for r in (await client.post("/api/remote/home/keep", json=body, headers=AUTH),
              await client.delete("/api/remote/home/keep", json=body, headers=AUTH),
              await client.get("/api/remote/home/status", headers=AUTH),
              await client.get("/api/remote/home/offline", headers=AUTH)):
        assert r.status == 403
        assert (await r.json())["error"] == "remote_disabled"
    assert lib.requests == []
