"""boombox-resume waits for boombox-library's stream proxy before
restoring a snapshot that holds proxy URLs."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parent.parent / "boombox-resume.py"
_spec = importlib.util.spec_from_file_location("boombox_resume_service", SERVICE)
resume = importlib.util.module_from_spec(_spec)
# @dataclass resolves annotations through sys.modules.
sys.modules[_spec.name] = resume
_spec.loader.exec_module(resume)

PROXY = "http://127.0.0.1:6687/api/library/stream"


def test_needs_stream_proxy(monkeypatch):
    monkeypatch.setattr(resume, "LIBRARY_STREAM_BASE", PROXY)
    assert resume.needs_stream_proxy({"track_uri": f"{PROXY}/t1", "tracklist": []})
    assert resume.needs_stream_proxy(
        {"track_uri": "file:///m/a.mp3", "tracklist": ["file:///m/a.mp3", f"{PROXY}/t2"]})
    assert not resume.needs_stream_proxy(
        {"track_uri": "file:///m/a.mp3", "tracklist": ["file:///m/a.mp3"]})
    assert not resume.needs_stream_proxy({"track_uri": "jellyfin:x"})


async def test_wait_for_stream_proxy(monkeypatch):
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(resume, "LIBRARY_STREAM_BASE",
                        f"http://127.0.0.1:{port}/api/library/stream")
    try:
        assert await resume.wait_for_stream_proxy(timeout=1) is True
    finally:
        server.close()
        await server.wait_closed()
    assert await resume.wait_for_stream_proxy(timeout=0) is False


async def test_restore_waits_then_proceeds(monkeypatch, tmp_path):
    """Proxy never comes up: restore still runs (cached entries play)."""
    snap = {"ts": 9e18, "state": "playing", "track_uri": f"{PROXY}/t1",
            "tracklist": [f"{PROXY}/t1"], "position_ms": 0}
    monkeypatch.setattr(resume, "read_snapshot", lambda: snap)
    waited: list[bool] = []

    async def fake_wait(timeout=0):
        waited.append(True)
        return False

    calls: list[str] = []

    async def fake_rpc(sess, method, params=None):
        calls.append(method)
        return "stopped" if method == "core.playback.get_state" else None

    monkeypatch.setattr(resume, "wait_for_stream_proxy", fake_wait)
    monkeypatch.setattr(resume, "rpc", fake_rpc)
    await resume.maybe_restore(None)
    assert waited == [True]
    assert "core.tracklist.add" in calls
