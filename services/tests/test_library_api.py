"""Tests for boombox_library.api — HTTP routes."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from boombox_library.api import _same_origin, build_app
from boombox_library.cache_drive import CacheDriveState
from boombox_library.config import (
    DEFAULT_CONFIG,
    LibraryConfig,
    SourceConfig,
)
from boombox_library.db import connect, migrate


class FakeContext:
    """In-memory stand-in for the service's runtime context."""
    def __init__(self, conn, cfg=None, cache_state=None, ping_ok=True,
                 art_cache_dir: Path | None = None,
                 snapshot_dir: Path | None = None):
        self.conn = conn
        self.cfg = cfg or DEFAULT_CONFIG
        self.cache_state = cache_state  # CacheDriveState
        self._ping_ok = ping_ok
        self.synced = 0
        # Phase 2 additions:
        self.last_sync_ts: float = 0.0
        self.syncing: bool = False
        self.adopted: list[str] = []
        self.streamed_enqueued: list[str] = []
        self.cleared_count = 0
        self._clear_returns = 0
        self.candidates: list[dict] = []
        # Phase 3: album-art proxy + browse snapshots
        self.art_cache_dir = art_cache_dir or Path("/tmp/boombox-art-test")
        self.snapshot_dir = snapshot_dir or Path("/tmp/boombox-snap-test")
        self.tested: list[tuple[str, str, str]] = []
        self.saved: list = []
        self.queue = None  # DownloadQueue stand-in (keep routes)

    async def is_online(self) -> bool:
        return self._ping_ok

    async def trigger_sync(self) -> None:
        self.synced += 1

    def cache_drive_state(self):
        return self.cache_state

    def save_config(self, cfg):
        self.saved.append(cfg)
        self.cfg = cfg

    async def test_source(self, url, username, password) -> tuple[bool, str]:
        self.tested.append((url, username, password))
        return (self._ping_ok, "" if self._ping_ok else "auth failed")

    # Phase 2 hooks consumed by api.py routes
    async def adopt_cache(self, mount_path: str) -> None:
        self.adopted.append(mount_path)

    def enqueue_streamed_download(self, track_id: str) -> None:
        self.streamed_enqueued.append(track_id)

    async def clear_streamed_cache(self) -> int:
        self.cleared_count += 1
        return self._clear_returns

    def cache_candidates(self) -> list[dict]:
        return self.candidates

    def download_queue(self):
        return self.queue


@pytest.fixture
async def client(tmp_path):
    conn = connect(tmp_path / "l.db"); migrate(conn)
    ctx = FakeContext(
        conn,
        art_cache_dir=tmp_path / "art-cache",
        snapshot_dir=tmp_path / "snapshots",
    )
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


def _seed_search(conn):
    conn.executemany(
        "INSERT INTO search_index(content_type,id,title,body) VALUES(?,?,?,?)",
        [("track", "t1", "Beat It", "Michael Jackson Thriller"),
         ("track", "t2", "Billie Jean", "Michael Jackson Thriller"),
         ("album", "al1", "Back in Black", "AC/DC rock 1980"),
         ("track", "t3", "Café del Mar", "Energy 52")],
    )


async def _search_ids(c, q):
    r = await c.get("/api/library/search", params={"q": q})
    assert r.status == 200
    return [i["id"] for i in (await r.json())["results"]]


@pytest.mark.asyncio
async def test_search_matches_word_prefixes(client):
    c, _, conn = client
    _seed_search(conn)
    assert await _search_ids(c, "beat") == ["t1"]
    assert await _search_ids(c, "bea") == ["t1"]
    assert set(await _search_ids(c, "mich thri")) == {"t1", "t2"}
    assert await _search_ids(c, "michael jean") == ["t2"]  # tokens ANDed
    assert await _search_ids(c, "caf") == ["t3"]           # unicode title


@pytest.mark.asyncio
async def test_search_ignores_content_type_column(client):
    c, _, conn = client
    _seed_search(conn)
    assert await _search_ids(c, "track") == []
    assert await _search_ids(c, "album") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("q", [
    '"', '""', 'beat"', '"beat', '*', 'beat*', '-', '-beat', 'beat -it',
    ':', 'title:beat', '{title}', '(', ')', '(beat', 'beat)', 'AND', 'OR',
    'NOT', 'NEAR(beat it)', '^beat', 'ac/dc', "it's", '+', 'café', '日本',
    '\u00e9\u0301', '🎵', 'a"b*c-d:e(f)g', '   ',
])
async def test_search_special_characters_never_500(client, q):
    c, _, conn = client
    _seed_search(conn)
    r = await c.get("/api/library/search", params={"q": q})
    assert r.status == 200
    assert isinstance((await r.json())["results"], list)


@pytest.mark.asyncio
async def test_search_punctuation_is_literal_text(client):
    c, _, conn = client
    _seed_search(conn)
    assert await _search_ids(c, "ac/dc") == ["al1"]
    assert await _search_ids(c, '"beat') == ["t1"]
    assert await _search_ids(c, "NOT") == []    # not an operator
    assert await _search_ids(c, "-") == []      # nothing searchable


@pytest.mark.asyncio
async def test_browse_albums(client):
    """Smoke-test the albums browse query (different columns than artists)."""
    c, ctx, conn = client
    # Seed an artist first (FK)
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','ABBA','abba',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,year,"
                 "song_count,duration_s,is_compilation,navidrome_starred,"
                 "art_id,updated_at) VALUES('al1','Arrival','arrival','ar1',"
                 "1976,1,30,0,0,'cover-art-1',0)")
    r = await c.get("/api/library/browse", params={"type": "albums"})
    assert r.status == 200
    body = await r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == "al1"
    assert item["name"] == "Arrival"
    assert item["year"] == 1976
    assert item["art_id"] == "cover-art-1"


@pytest.mark.asyncio
async def test_browse_playlists(client):
    """Smoke-test the playlists browse query."""
    c, ctx, conn = client
    conn.execute("INSERT INTO playlists(id,name,song_count,owner,public,"
                 "updated_at) VALUES('pl1','My Mix',5,'jwc',0,0)")
    r = await c.get("/api/library/browse", params={"type": "playlists"})
    assert r.status == 200
    body = await r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "My Mix"
    assert body["items"][0]["song_count"] == 5


@pytest.mark.asyncio
async def test_browse_unknown_type_returns_400(client):
    c, ctx, _ = client
    r = await c.get("/api/library/browse", params={"type": "garbage"})
    assert r.status == 400
    body = await r.json()
    assert "error" in body


@pytest.mark.asyncio
async def test_pin_inserts_row(client):
    c, ctx, conn = client
    # Seed a target so the pin is meaningful
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al", "mode": "pin",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT * FROM pins"))
    assert len(rows) == 1
    # Pin must trigger a sync (so downloads start immediately,
    # not on next hourly tick)
    assert ctx.synced >= 1


@pytest.mark.asyncio
async def test_unpin_removes_row(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO pins(target_kind,target_id,source,added_at) "
                 "VALUES('album','al','user',0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al", "mode": "unpin",
    })
    assert r.status == 200
    assert list(conn.execute("SELECT * FROM pins")) == []


@pytest.mark.asyncio
async def test_sync_run_triggers(client):
    c, ctx, conn = client
    r = await c.post("/api/library/sync/run")
    assert r.status == 200
    assert ctx.synced == 1


@pytest.mark.asyncio
async def test_resolver_endpoint_returns_cache_uri(client, tmp_path):
    c, ctx, conn = client
    cached = tmp_path / "x" / "audio" / "t1.mp3"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"ID3")
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',1000,'audio/mpeg',0,0)")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present',?,1000,0)", (str(cached),))
    r = await c.get("/api/library/track/t1/playback")
    assert r.status == 200
    body = await r.json()
    assert body["source"] == "cache"
    # Note: Task 12's fix changed the resolver URI format from `local:track:`
    # to `file://<urllib.parse.quote(path)>` so Mopidy's stream backend can
    # play directly without depending on Mopidy-Local's index.
    assert body["uri"] == f"file://{cached}"


@pytest.mark.asyncio
async def test_source_put_failure_does_not_leak_submitted_password(client, tmp_path):
    """Defense in depth: when test_source() reports failure, the error
    message returned to the client must NEVER contain the submitted
    password. Even if upstream code carelessly str(exception)s an aiohttp
    error that includes the URL+creds, the API layer should scrub it."""
    c, ctx, _ = client

    # Override the fake's test_source to simulate a "leaky" upstream
    # that returns the password in its error message.
    async def leaky_test(url, username, password):
        # Pretend an aiohttp error stringified the URL with creds:
        return (False, f"auth failed: GET http://nav/?p={password}&u={username}")
    ctx.test_source = leaky_test

    r = await c.put("/api/library/source", json={
        "url": "http://nav:4533",
        "username": "u",
        "password": "supersecret-do-not-leak",
    })
    assert r.status == 400
    body_text = await r.text()
    assert "supersecret-do-not-leak" not in body_text


# ----- Phase 2 additions -----

@pytest.mark.asyncio
async def test_pin_endpoint_accepts_source(client):
    """POST /api/library/pin with {source:'favorite'} stores source=favorite."""
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al1", "mode": "pin", "source": "favorite",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "favorite"


@pytest.mark.asyncio
async def test_pin_endpoint_defaults_source_to_user(client):
    """Omitting source field keeps backwards compat — stores source=user."""
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al1", "mode": "pin",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT source FROM pins WHERE target_id='al1'"))
    assert rows[0]["source"] == "user"


@pytest.mark.asyncio
async def test_health_reports_last_sync_ts_and_syncing(client):
    """UI's SyncIndicator polls /health for last_sync_ts + syncing flag."""
    c, ctx, _ = client
    ctx.last_sync_ts = 12345.0
    ctx.syncing = False
    r = await c.get("/api/library/health")
    body = await r.json()
    assert body["last_sync_ts"] == 12345.0
    assert body["syncing"] is False


@pytest.mark.asyncio
async def test_health_reports_syncing_true_during_sync(client):
    """While a sync is in flight syncing=true so the chip can pulse amber."""
    c, ctx, _ = client
    ctx.syncing = True
    r = await c.get("/api/library/health")
    body = await r.json()
    assert body["syncing"] is True


@pytest.mark.asyncio
async def test_cache_adopt_writes_marker(client, tmp_path):
    """POST /cache/adopt asks the service to bless a drive at the given path."""
    c, ctx, _ = client
    drive_path = str(tmp_path / "fake-drive")
    r = await c.post("/api/library/cache/adopt",
                     json={"mount_path": drive_path})
    assert r.status == 200
    assert ctx.adopted == [drive_path]


@pytest.mark.asyncio
async def test_cache_adopt_rejects_missing_mount_path(client):
    """Missing mount_path → 400."""
    c, _, _ = client
    r = await c.post("/api/library/cache/adopt", json={})
    assert r.status == 400


@pytest.mark.asyncio
async def test_cache_streamed_enqueues_track(client):
    """POST /cache/streamed?id=X enqueues a streamed (non-pinned) download."""
    c, ctx, conn = client
    r = await c.post("/api/library/cache/streamed?id=t1")
    assert r.status == 200
    assert ctx.streamed_enqueued == ["t1"]


@pytest.mark.asyncio
async def test_cache_streamed_rejects_missing_id(client):
    c, _, _ = client
    r = await c.post("/api/library/cache/streamed")
    assert r.status == 400


@pytest.mark.asyncio
async def test_cache_clear_calls_service(client):
    """POST /cache/clear invokes ServiceContext.clear_streamed_cache."""
    c, ctx, _ = client
    r = await c.post("/api/library/cache/clear")
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    assert ctx.cleared_count == 1


@pytest.mark.asyncio
async def test_cache_clear_returns_count(client):
    """Response includes the number of entries cleared, for UI feedback."""
    c, ctx, _ = client
    ctx._clear_returns = 7
    r = await c.post("/api/library/cache/clear")
    body = await r.json()
    assert body["cleared"] == 7


@pytest.mark.asyncio
async def test_cache_candidates_returns_list(client):
    """GET /cache/candidates exposes mounted-but-unadopted drives."""
    c, ctx, _ = client
    ctx.candidates = [{
        "mount_path": "/media/DRIVE_B", "label": "DRIVE_B",
        "free_bytes": 230_000_000_000, "total_bytes": 250_000_000_000,
    }]
    r = await c.get("/api/library/cache/candidates")
    assert r.status == 200
    body = await r.json()
    assert body["candidates"] == ctx.candidates


@pytest.mark.asyncio
async def test_browse_serves_snapshot_when_present(client, tmp_path):
    """When a precomputed snapshot exists, /browse streams it (and ignores SQL)."""
    c, ctx, conn = client
    # Seed the DB so the SQL fallback would also work — but we want to
    # see the SNAPSHOT (which contains synthetic data the DB doesn't).
    snap_dir = ctx.snapshot_dir
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "albums.json").write_text(
        '{"items":[{"id":"snap","name":"FromSnapshot"}]}'
    )
    r = await c.get("/api/library/browse", params={"type": "albums"})
    assert r.status == 200
    body = await r.json()
    assert body["items"][0]["name"] == "FromSnapshot"
    assert r.headers.get("ETag")


@pytest.mark.asyncio
async def test_browse_returns_304_on_matching_etag(client):
    """Conditional GET with matching If-None-Match skips the body."""
    c, ctx, _ = client
    snap_dir = ctx.snapshot_dir
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "albums.json").write_text('{"items":[]}')
    r1 = await c.get("/api/library/browse", params={"type": "albums"})
    etag = r1.headers.get("ETag")
    assert etag
    r2 = await c.get(
        "/api/library/browse",
        params={"type": "albums"},
        headers={"If-None-Match": etag},
    )
    assert r2.status == 304


@pytest.mark.asyncio
async def test_browse_falls_back_to_sql_before_first_snapshot(client):
    """First-boot window: no snapshot file yet, but SQL still answers."""
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','Zed','zed',1,0)")
    # Note: snapshot_dir intentionally empty for this test
    r = await c.get("/api/library/browse", params={"type": "artists"})
    assert r.status == 200
    body = await r.json()
    assert body["items"][0]["name"] == "Zed"


@pytest.mark.asyncio
async def test_art_endpoint_serves_cached_bytes(client, tmp_path):
    """When the disk cache already has bytes for an art_id, the endpoint
    serves them directly without touching the network."""
    c, ctx, _ = client
    ctx.art_cache_dir.mkdir(parents=True, exist_ok=True)
    (ctx.art_cache_dir / "al-42.bin").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    r = await c.get("/api/library/art/al-42")
    assert r.status == 200
    assert (await r.read()).startswith(b"\xff\xd8")
    assert "max-age=31536000" in r.headers.get("Cache-Control", "")
    assert r.headers.get("ETag") == '"al-42"'


@pytest.mark.asyncio
async def test_art_endpoint_honors_if_none_match(client):
    """Conditional GETs get a 304, no body — keeps repeat renders cheap."""
    c, ctx, _ = client
    ctx.art_cache_dir.mkdir(parents=True, exist_ok=True)
    (ctx.art_cache_dir / "al-42.bin").write_bytes(b"\xff\xd8x")
    r = await c.get("/api/library/art/al-42", headers={"If-None-Match": '"al-42"'})
    assert r.status == 304


@pytest.mark.asyncio
async def test_art_endpoint_404_when_no_cache_and_offline(client):
    """No cached bytes + no configured source URL → 404 (UI shows gradient)."""
    c, ctx, _ = client
    # DEFAULT_CONFIG has source.url == ''. Cache dir is empty.
    r = await c.get("/api/library/art/missing-id")
    assert r.status == 404


@pytest.mark.asyncio
async def test_unpin_endpoint_accepts_source(client):
    """POST /api/library/pin with {mode:'unpin', source:'favorite'} respects filter."""
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar1','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al1','A','a','ar1',0,0,0,0,0)")
    conn.execute("INSERT INTO pins(target_kind,target_id,source,added_at) "
                 "VALUES('album','al1','user',0)")
    r = await c.post("/api/library/pin", json={
        "kind": "album", "id": "al1", "mode": "unpin", "source": "favorite",
    })
    assert r.status == 200
    rows = list(conn.execute("SELECT * FROM pins WHERE target_id='al1'"))
    assert len(rows) == 1


# ----- source save keeps fields the form doesn't send -----

@pytest.mark.asyncio
async def test_source_put_keeps_max_bitrate(client):
    """The Settings / wizard form only sends url+username+password; a
    hand-set source.max_bitrate_kbps must survive the save."""
    c, ctx, _ = client
    ctx.cfg = LibraryConfig(
        source=SourceConfig(url="http://old", username="o", password="x",
                            max_bitrate_kbps=192),
        sync=DEFAULT_CONFIG.sync, cache=DEFAULT_CONFIG.cache,
    )
    r = await c.put("/api/library/source", json={
        "url": "https://music.example", "username": "u", "password": "p",
    })
    assert r.status == 200
    assert ctx.cfg.source.url == "https://music.example"
    assert ctx.cfg.source.username == "u"
    assert ctx.cfg.source.password == "p"
    assert ctx.cfg.source.max_bitrate_kbps == 192


# ----- prune guard override + visibility -----

@pytest.mark.asyncio
async def test_sync_prune_sets_one_shot_force_and_triggers(client):
    c, ctx, conn = client
    r = await c.post("/api/library/sync/prune")
    assert r.status == 200
    assert ctx.synced == 1
    assert conn.execute(
        "SELECT value FROM sync_state WHERE key='prune_force'").fetchone()


@pytest.mark.asyncio
async def test_health_reports_prune_deferred(client):
    c, _, conn = client
    body = await (await c.get("/api/library/health")).json()
    assert body["prune_deferred"] is None
    conn.execute(
        "INSERT INTO sync_state(key, value) VALUES ('prune_deferred', ?)",
        ('{"fingerprint": "f", "albums": 200, "rounds": 1, "since": 5.0}',))
    body = await (await c.get("/api/library/health")).json()
    assert body["prune_deferred"]["albums"] == 200
    assert body["prune_deferred"]["rounds"] == 1


# ----- blank password = keep stored (Accounts page never receives it) -----

@pytest.mark.asyncio
async def test_source_put_blank_password_keeps_current(client):
    c, ctx, _ = client
    ctx.cfg = replace(ctx.cfg, source=replace(
        ctx.cfg.source, url="https://m.example", password="s3cret"))
    r = await c.put("/api/library/source",
                    json={"url": "https://m.example", "username": "bb", "password": ""})
    assert r.status == 200
    assert ctx.tested[-1][2] == "s3cret"          # tested with the stored password
    assert ctx.saved[-1].source.password == "s3cret"


@pytest.mark.asyncio
async def test_source_test_blank_password_uses_current(client):
    c, ctx, _ = client
    ctx.cfg = replace(ctx.cfg, source=replace(
        ctx.cfg.source, url="https://m.example", password="s3cret"))
    await c.post("/api/library/source/test",
                 json={"url": "https://m.example", "username": "bb"})
    assert ctx.tested[-1][2] == "s3cret"


@pytest.mark.parametrize(("a", "b", "same"), [
    ("https://m.example/rest", "https://m.example", True),     # path differs
    ("https://M.Example", "https://m.example/", True),         # case-insensitive
    ("https://other.example", "https://m.example", False),     # different host
    ("http://m.example", "https://m.example", False),          # scheme differs
    ("https://m.example:443", "https://m.example", True),      # default port
    ("http://m.example:80/x", "http://m.example", True),
    ("https://m.example:8443", "https://m.example", False),
    ("https://m.example", "", False),                          # nothing stored
    ("", "", False),
    ("m.example", "m.example", False),                         # no scheme/host
    ("https://m.example:notaport", "https://m.example", False),
])
def test_same_origin(a, b, same):
    assert _same_origin(a, b) is same


@pytest.mark.asyncio
async def test_source_put_blank_password_other_host_not_sent_stored(client):
    c, ctx, _ = client
    ctx.cfg = replace(ctx.cfg, source=replace(
        ctx.cfg.source, url="https://m.example", password="s3cret"))
    await c.put("/api/library/source",
                json={"url": "https://evil.example", "username": "bb", "password": ""})
    assert ctx.tested[-1] == ("https://evil.example", "bb", "")
    assert "s3cret" not in {s.source.password for s in ctx.saved}


@pytest.mark.asyncio
async def test_source_test_blank_password_other_origin_not_sent_stored(client):
    c, ctx, _ = client
    ctx.cfg = replace(ctx.cfg, source=replace(
        ctx.cfg.source, url="https://m.example", password="s3cret"))
    for url in ("https://evil.example", "http://m.example"):
        await c.post("/api/library/source/test", json={"url": url, "username": "bb"})
        assert ctx.tested[-1] == (url, "bb", "")


class KeepQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.snap = {"queued": 0, "in_flight": [], "paused": None}

    def enqueue(self, tid):
        if tid in self.enqueued:
            return False
        self.enqueued.append(tid)
        return True

    def cancel(self, ids):
        return 0

    def snapshot(self):
        return dict(self.snap)


def _seed_keep(conn):
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) VALUES('ar1','Joni','joni',2,0)")
    for al, name, starred in (("al1", "Blue", 0), ("al2", "Court and Spark", 1)):
        conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,duration_s,is_compilation,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,'ar1',2,60,0,?,0)", (al, name, name.lower(), starred))
    for tid, al in (("t1", "al1"), ("t2", "al1"), ("t3", "al1"), ("t4", "al2"), ("t5", "al2")):
        conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,size_bytes,content_type,"
                     "navidrome_starred,updated_at) VALUES(?,?,?,30,'mp3',1000,'audio/mpeg',0,0)",
                     (tid, al, tid.upper()))
    conn.execute("INSERT INTO playlists(id,name,song_count,owner,public,updated_at) VALUES('pl1','Mix',1,'u',0,0)")
    conn.execute("INSERT INTO playlist_tracks(playlist_id,track_id,position) VALUES('pl1','t2',0)")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,downloaded_at) "
                 "VALUES('t2','present','/m/t2.mp3',1000,0)")


async def test_keep_route_pins_enqueues_and_unkeeps(client):
    c, ctx, conn = client
    _seed_keep(conn)
    ctx.queue = KeepQueue()
    r = await c.post("/api/library/keep", json={"kind": "album", "id": "al1"})
    assert r.status == 200
    body = await r.json()
    assert body["queued"] == 3
    assert body["keep"] == {"state": "kept", "tracks_total": 3, "tracks_present": 1}
    r = await c.delete("/api/library/keep", json={"kind": "album", "id": "al1"})
    assert r.status == 200 and (await r.json())["keep"]["state"] == "none"


async def test_keep_route_validates(client):
    c, ctx, conn = client
    _seed_keep(conn)
    assert (await c.post("/api/library/keep", json={"kind": "track", "id": "t1"})).status == 400
    assert (await c.post("/api/library/keep", json={"kind": "album"})).status == 400
    assert (await c.post("/api/library/keep", data="nope")).status == 400
    r = await c.post("/api/library/keep", json={"kind": "album", "id": "zzz"})
    assert r.status == 404 and (await r.json()) == {"ok": False, "error": "album not found"}


async def test_keep_without_music_storage_still_pins(client):
    c, ctx, conn = client
    _seed_keep(conn)
    r = await c.post("/api/library/keep", json={"kind": "playlist", "id": "pl1"})
    assert (await r.json()) == {"ok": True, "queued": 0,
                                "keep": {"state": "kept", "tracks_total": 1, "tracks_present": 1}}


async def test_album_and_playlist_detail_carry_keep_and_offline(client):
    c, ctx, conn = client
    _seed_keep(conn)
    d = await (await c.get("/api/library/album/al1")).json()
    assert d["keep"] == {"state": "none", "tracks_total": 3, "tracks_present": 1}
    assert [(t["id"], t["offline"]) for t in d["tracks"]] == [("t1", False), ("t2", True), ("t3", False)]
    d = await (await c.get("/api/library/playlist/pl1")).json()
    assert d["keep"]["tracks_present"] == 1 and d["tracks"][0]["offline"] is True


async def test_artist_detail_albums_carry_offline(client):
    c, ctx, conn = client
    _seed_keep(conn)
    d = await (await c.get("/api/library/artist/ar1")).json()
    assert {a["id"]: a["offline"] for a in d["albums"]} == {"al1": True, "al2": False}
    assert d["keep"] == {"state": "none", "tracks_total": 5, "tracks_present": 1}


async def test_search_results_carry_offline(client):
    c, ctx, conn = client
    _seed_keep(conn)
    conn.execute("INSERT INTO search_index(content_type,id,title,body) VALUES('album','al1','Blue','Blue')")
    conn.execute("INSERT INTO search_index(content_type,id,title,body) VALUES('album','al2','Court','Court')")
    blue = (await (await c.get("/api/library/search?q=blue")).json())["results"]
    court = (await (await c.get("/api/library/search?q=court")).json())["results"]
    assert blue[0]["offline"] is True and court[0]["offline"] is False


async def test_offline_ids_route(client):
    c, ctx, conn = client
    _seed_keep(conn)
    assert (await (await c.get("/api/library/offline")).json()) == {
        "album_ids": ["al1"], "artist_ids": ["ar1"], "playlist_ids": ["pl1"]}


async def test_health_reports_internal_storage(client):
    c, ctx, _ = client
    assert (await (await c.get("/api/library/health")).json())["internal_storage"] is False
    ctx.cache_state = CacheDriveState(present=True, mount_path=Path("/opt/boombox/storage/music"),
                                      free_bytes=1, total_bytes=2, internal=True)
    assert (await (await c.get("/api/library/health")).json())["internal_storage"] is True


async def test_storage_route_overview(client):
    c, ctx, conn = client
    _seed_keep(conn)
    ctx.queue = KeepQueue()
    ctx.cache_state = CacheDriveState(present=True, mount_path=Path("/opt/boombox/storage/music"),
                                      free_bytes=5, total_bytes=9, internal=True)
    await c.post("/api/library/keep", json={"kind": "playlist", "id": "pl1"})  # pins present t2
    o = await (await c.get("/api/library/storage")).json()
    assert o["drive"]["internal"] is True and o["drive"]["reserve_bytes"] == ctx.cfg.cache.reserve_bytes
    assert o["drive"]["kept_tracks"] == 1 and o["downloads"]["active"] is True


async def test_storage_remove_route(client):
    c, ctx, conn = client
    _seed_keep(conn)
    await c.post("/api/library/keep", json={"kind": "album", "id": "al1"})
    r = await c.post("/api/library/storage/remove", json={"kind": "album", "id": "al1"})
    assert r.status == 200 and (await r.json())["ok"] is True
    r = await c.post("/api/library/storage/remove", json={"kind": "starred_tracks", "id": ""})
    assert r.status == 409 and (await r.json())["error"] == "unstar in Navidrome to remove"
    assert (await c.post("/api/library/storage/remove", json={"kind": "track", "id": "t1"})).status == 400


async def test_storage_retry_route(client):
    c, ctx, conn = client
    r = await c.post("/api/library/storage/retry", json={})
    assert r.status == 409 and (await r.json())["ok"] is False
    ctx.queue = KeepQueue()
    r = await c.post("/api/library/storage/retry", json={})
    assert (await r.json()) == {"ok": True, "retried": 0}


async def test_resolve_batch_offline_returns_kept_file_and_drops_the_rest(client, tmp_path):
    c, ctx, conn = client
    _seed_keep(conn)
    f = tmp_path / "t2.mp3"
    f.write_bytes(b"x")
    conn.execute("UPDATE cache_state SET local_path=? WHERE track_id='t2'", (str(f),))
    ctx._ping_ok = False                       # Navidrome unreachable
    ctx.cfg = replace(ctx.cfg, source=SourceConfig(url="https://m.example", username="u", password="p"))
    items = (await (await c.post("/api/library/resolve", json={"ids": ["t1", "t2"]})).json())["items"]
    assert [(i["id"], i["source"]) for i in items] == [("t1", "offline_miss"), ("t2", "cache")]
    assert items[1]["uri"] == f"file://{f}"
