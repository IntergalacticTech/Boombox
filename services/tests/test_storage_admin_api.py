"""/api/accounts/storage* — Admin → Storage (boombox-setup)."""
from __future__ import annotations

import builtins

import aiohttp
import pytest
import remote_files
from aiohttp.test_utils import TestClient, TestServer
from boombox_setup.accounts import ADMIN_KEY
from boombox_setup.api import build_app

from .test_accounts_api import FakeAccountsContext

LAN = {"X-Real-IP": "192.168.1.50", "X-Boombox-Host": "192.168.1.81:8090"}


class FakeStorageContext(FakeAccountsContext):
    def __init__(self) -> None:
        super().__init__()
        self.library_calls: list[tuple] = []
        self.library_reply: tuple[int, dict | None] = (
            200, {"drive": {"present": True}, "kept": [], "downloads": {}})

    async def library_call(self, method, path, body=None):
        self.library_calls.append((method, path, body))
        return self.library_reply


async def _noop() -> None:
    return None


@pytest.fixture
async def storage(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    (music / "Album").mkdir(parents=True)
    (music / "Album" / "track.mp3").write_bytes(b"id3data")
    monkeypatch.setenv("BOOMBOX_MUSIC_DIR", str(music))
    monkeypatch.setenv("BOOMBOX_VIDEO_DIR", str(tmp_path / "Videos"))
    monkeypatch.setattr(remote_files, "_trigger_scan", _noop)
    monkeypatch.setattr(remote_files, "_trigger_jellyfin_scan", _noop)
    ctx = FakeStorageContext()
    app = build_app(ctx)
    token, _ = app[ADMIN_KEY].issue()
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c, ctx, {**LAN, "Authorization": f"Bearer {token}"}, music
    await c.close()


def _song(name: str = "song.mp3", data: bytes = b"fake-audio-bytes") -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field("file", data, filename=name, content_type="audio/mpeg")
    return form


async def test_storage_needs_an_admin_session(storage):
    c, _ctx, auth, _ = storage
    assert (await c.get("/api/accounts/storage", headers=LAN)).status == 401
    assert (await c.get("/api/accounts/storage", headers={**auth, "X-Real-IP": "127.0.0.1"})).status == 403
    assert (await c.post("/api/accounts/storage/files/upload", data=_song(), headers=LAN)).status == 401


async def test_overview_proxies_the_library(storage):
    c, ctx, auth, _ = storage
    r = await c.get("/api/accounts/storage", headers=auth)
    assert r.status == 200 and (await r.json())["drive"]["present"] is True
    assert ctx.library_calls == [("GET", "/api/library/storage", None)]


@pytest.mark.parametrize("reply", [(0, None), (500, {"error": "x"}), (200, None)])
async def test_library_failure_is_502(storage, reply):
    c, ctx, auth, _ = storage
    ctx.library_reply = reply
    r = await c.get("/api/accounts/storage", headers=auth)
    assert r.status == 502 and (await r.json()) == {"ok": False, "error": "library service not answering"}


async def test_remove_and_retry_proxy(storage):
    c, ctx, auth, _ = storage
    ctx.library_reply = (409, {"ok": False, "error": "unstar in Navidrome to remove"})
    r = await c.post("/api/accounts/storage/remove", json={"kind": "album", "id": "al1"}, headers=auth)
    assert r.status == 409 and (await r.json())["error"] == "unstar in Navidrome to remove"
    assert ctx.library_calls[-1] == ("POST", "/api/library/storage/remove", {"kind": "album", "id": "al1"})
    ctx.library_reply = (200, {"ok": True, "retried": 2})
    r = await c.post("/api/accounts/storage/retry", json={}, headers=auth)
    assert (await r.json()) == {"ok": True, "retried": 2}
    assert ctx.library_calls[-1] == ("POST", "/api/library/storage/retry", {})
    for bad in ({"kind": "track", "id": "t1"}, {"kind": "album"}, ["al1"]):
        assert (await c.post("/api/accounts/storage/remove", json=bad, headers=auth)).status == 400


async def test_upload_is_admin_multipart_only_on_its_path(storage):
    c, _ctx, auth, music = storage
    r = await c.post("/api/accounts/storage/files/upload", data=_song(), headers=auth)
    assert r.status == 200 and (await r.json())["saved"] == ["uploads/song.mp3"]
    assert (music / "uploads" / "song.mp3").read_bytes() == b"fake-audio-bytes"
    r = await c.post("/api/accounts/storage/remove", data=_song(), headers=auth)
    assert r.status == 415


async def test_upload_cross_origin_is_refused(storage):
    c, _ctx, auth, _ = storage
    r = await c.post("/api/accounts/storage/files/upload", data=_song(),
                     headers={**auth, "Origin": "http://evil.example"})
    assert r.status == 403


async def test_upload_rejects_unsupported_type_and_over_cap(storage, monkeypatch):
    c, _ctx, auth, music = storage
    form = aiohttp.FormData()
    form.add_field("file", b"not media", filename="notes.txt", content_type="text/plain")
    assert (await c.post("/api/accounts/storage/files/upload", data=form, headers=auth)).status == 400
    monkeypatch.setattr(remote_files, "MAX_FILE_BYTES", 1024)
    r = await c.post("/api/accounts/storage/files/upload", data=_song("toobig.mp3", b"\0" * 4096), headers=auth)
    assert r.status == 413 and not (music / "uploads" / "toobig.mp3").exists()


async def test_upload_disk_full_is_507_and_leaves_no_partial(storage, monkeypatch):
    c, _ctx, auth, music = storage

    def full_open(path, mode="r", *a, **k):
        real = builtins.open(path, mode, *a, **k)

        class Full:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                real.close()
                return False

            def write(self, data):
                raise OSError(28, "No space left on device")

            def close(self):
                real.close()
        return Full()

    monkeypatch.setattr(remote_files, "open", full_open, raising=False)
    r = await c.post("/api/accounts/storage/files/upload", data=_song(), headers=auth)
    assert r.status == 507 and (await r.json())["error"] == "the boombox's disk is full or not writable"
    assert not (music / "uploads" / "song.mp3").exists()


async def test_admin_browse_and_delete(storage):
    c, _ctx, auth, music = storage
    r = await c.get("/api/accounts/storage/files/browse?path=", headers=auth)
    assert "Album" in [e["name"] for e in (await r.json())["entries"]]
    r = await c.post("/api/accounts/storage/files/delete", json={"path": "Album/track.mp3"}, headers=auth)
    assert r.status == 200 and not (music / "Album" / "track.mp3").exists()


async def test_delete_failure_is_409_not_500(storage, monkeypatch):
    import pathlib
    c, _ctx, auth, _ = storage

    def refuse(self, missing_ok=False):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(pathlib.Path, "unlink", refuse)
    r = await c.post("/api/accounts/storage/files/delete", json={"path": "Album/track.mp3"}, headers=auth)
    assert r.status == 409
