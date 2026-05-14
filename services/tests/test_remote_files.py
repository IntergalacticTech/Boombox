"""Tests for /api/remote/files/* (services/remote_files.py)."""
from __future__ import annotations

import json

import aiohttp
import pytest


@pytest.fixture
def files_app(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    (music / "Album").mkdir(parents=True)
    (music / "Album" / "track.mp3").write_bytes(b"id3data")
    monkeypatch.setenv("BOOMBOX_MUSIC_DIR", str(music))
    monkeypatch.setenv("BOOMBOX_VIDEO_DIR", str(tmp_path / "Videos"))
    peers = tmp_path / "peers.json"
    peers.write_text(json.dumps({"t": {"label": "x", "paired_at": 0}}))
    monkeypatch.setenv("BOOMBOX_REMOTE_PEERS", str(peers))
    import boombox_remote
    return boombox_remote.create_app(), music


@pytest.mark.asyncio
async def test_browse_lists_dir(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/browse?path=",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    names = [e["name"] for e in body["entries"]]
    assert "Album" in names


@pytest.mark.asyncio
async def test_browse_rejects_traversal(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/browse?path=../../etc",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_browse_requires_token(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/browse?path=")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_download_streams_file(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    resp = await client.get("/api/remote/files/download/Album/track.mp3",
                            headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert await resp.read() == b"id3data"


@pytest.mark.asyncio
async def test_delete_removes_file(files_app, aiohttp_client):
    app, music = files_app
    client = await aiohttp_client(app)
    resp = await client.post("/api/remote/files/delete",
                             json={"path": "Album/track.mp3"},
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    assert not (music / "Album" / "track.mp3").exists()


@pytest.mark.asyncio
async def test_upload_audio_file(files_app, aiohttp_client):
    app, music = files_app
    client = await aiohttp_client(app)
    data = aiohttp.FormData()
    data.add_field("file", b"fake-audio-bytes", filename="song.mp3",
                   content_type="audio/mpeg")
    resp = await client.post("/api/remote/files/upload", data=data,
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 200
    body = await resp.json()
    assert body["saved"] == ["uploads/song.mp3"]
    assert (music / "uploads" / "song.mp3").read_bytes() == b"fake-audio-bytes"


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_type(files_app, aiohttp_client):
    app, _ = files_app
    client = await aiohttp_client(app)
    data = aiohttp.FormData()
    data.add_field("file", b"not media", filename="notes.txt",
                   content_type="text/plain")
    resp = await client.post("/api/remote/files/upload", data=data,
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_upload_rejects_file_over_cap(files_app, aiohttp_client,
                                            monkeypatch):
    # The real size gate is the in-handler MAX_FILE_BYTES check, enforced
    # while streaming. Lower the cap and confirm an over-cap upload is
    # rejected 413 AND the partial file is cleaned up off disk.
    import remote_files
    monkeypatch.setattr(remote_files, "MAX_FILE_BYTES", 1024)
    app, music = files_app
    client = await aiohttp_client(app)
    data = aiohttp.FormData()
    data.add_field("file", b"\0" * 4096, filename="toobig.mp3",
                   content_type="audio/mpeg")
    resp = await client.post("/api/remote/files/upload", data=data,
                             headers={"Authorization": "Bearer t"})
    assert resp.status == 413
    assert not (music / "uploads" / "toobig.mp3").exists()
