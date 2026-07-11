"""Tests for boombox_library.api — HTTP routes."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from boombox_library.api import build_app
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
async def test_resolver_endpoint_returns_cache_uri(client):
    c, ctx, conn = client
    conn.execute("INSERT INTO artists(id,name,sort_name,album_count,updated_at) "
                 "VALUES('ar','X','x',1,0)")
    conn.execute("INSERT INTO albums(id,name,sort_name,artist_id,song_count,"
                 "duration_s,is_compilation,navidrome_starred,updated_at) "
                 "VALUES('al','A','a','ar',1,30,0,0,0)")
    conn.execute("INSERT INTO tracks(id,album_id,title,duration_s,suffix,"
                 "size_bytes,content_type,navidrome_starred,updated_at) "
                 "VALUES('t1','al','T',30,'mp3',1000,'audio/mpeg',0,0)")
    conn.execute("INSERT INTO cache_state(track_id,status,local_path,size_bytes,"
                 "downloaded_at) VALUES('t1','present','/x/audio/t1.mp3',1000,0)")
    r = await c.get("/api/library/track/t1/playback")
    assert r.status == 200
    body = await r.json()
    assert body["source"] == "cache"
    # Note: Task 12's fix changed the resolver URI format from `local:track:`
    # to `file://<urllib.parse.quote(path)>` so Mopidy's stream backend can
    # play directly without depending on Mopidy-Local's index.
    assert body["uri"] == "file:///x/audio/t1.mp3"


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
