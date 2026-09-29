"""boombox-resume: long streamed queues restore current-track-first."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import aiohttp
import pytest

from .fake_mopidy import FakeMopidy

_PATH = Path(__file__).resolve().parent.parent / "boombox-resume.py"


def _load():
    spec = importlib.util.spec_from_file_location("boombox_resume_under_test", _PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


def _http(n: int) -> list[str]:
    return [f"https://music.example.com/rest/stream.view?id=t{i}" for i in range(n)]


@pytest.fixture
async def env(aiohttp_server, tmp_path, monkeypatch):
    resume = _load()
    fake = FakeMopidy()
    srv = await aiohttp_server(fake.app())
    monkeypatch.setattr(resume, "MOPIDY_RPC", str(srv.make_url("/mopidy/rpc")))
    monkeypatch.setattr(resume, "SNAPSHOT_PATH", tmp_path / "last.json")
    monkeypatch.setattr(resume, "RESTORE_GAP_S", 0)
    monkeypatch.setattr(resume.asyncio, "sleep", _fast_sleep)
    return resume, fake


_real_sleep = asyncio.sleep


async def _fast_sleep(_s, *a, **k):
    await _real_sleep(0)


def _snap(resume, tracklist, current, state="playing", pos=42_000):
    resume.SNAPSHOT_PATH.write_text(json.dumps({
        "ts": time.time(), "state": state, "track_uri": current,
        "tracklist": tracklist, "position_ms": pos}))


async def test_short_queue_restores_one_shot(env):
    resume, fake = env
    uris = _http(4)
    _snap(resume, uris, uris[2])
    async with aiohttp.ClientSession() as s:
        tail = await resume.maybe_restore(s)
    assert tail is None
    assert fake.adds() == [{"uris": uris}]
    assert fake.uris() == uris
    assert fake.current == 3 and fake.position == 42_000 and fake.state == "playing"


async def test_file_queue_restores_one_shot(env):
    resume, fake = env
    uris = [f"file:///c/t{i}.mp3" for i in range(80)]
    _snap(resume, uris, uris[40])
    async with aiohttp.ClientSession() as s:
        assert await resume.maybe_restore(s) is None
    assert len(fake.adds()) == 1 and fake.uris() == uris


async def test_long_streamed_queue_current_first_then_background(env):
    resume, fake = env
    uris = _http(47)
    _snap(resume, uris, uris[20], state="paused", pos=91_000)
    async with aiohttp.ClientSession() as s:
        tail = await resume.maybe_restore(s)
        # Only the current track was queued before playback + seek.
        assert fake.adds()[0] == {"uris": [uris[20]]}
        assert fake.uris() == [uris[20]]
        assert fake.position == 91_000
        assert fake.state == "paused"  # pause semantics kept
        assert tail is not None and tail.current_tlid == fake.current
        n = await resume.append_restore_tail(s, tail, gap_s=0)
    assert n == 46
    assert fake.uris() == uris  # full order restored around the current track
    assert fake.current == tail.current_tlid
    assert all(len(p["uris"]) <= resume.RESTORE_CHUNK for p in fake.adds())


async def test_restore_stops_and_cleans_up_when_user_replaces_queue(env):
    resume, fake = env
    uris = _http(30)
    _snap(resume, uris, uris[0])
    n_adds = {"n": 0}

    def replace_on_second_chunk(f, _p):
        n_adds["n"] += 1
        if n_adds["n"] == 2:  # chunk 1 lands, chunk 2 races the replace
            f.tl = [(900, "file:///other.mp3")]
    async with aiohttp.ClientSession() as s:
        tail = await resume.maybe_restore(s)
        fake.before_add = replace_on_second_chunk
        n = await resume.append_restore_tail(s, tail, gap_s=0)
    assert fake.uris() == ["file:///other.mp3"]
    assert n == resume.RESTORE_CHUNK
    assert len(fake.adds()) == 3  # current + two chunks, nothing more


def test_snapshot_during_restore_keeps_full_queue(env):
    resume, _fake = env
    full = _http(30)
    tail = resume.RestoreTail(before=full[:5], after=full[6:], current_tlid=1, full=full)
    partial = {"track_uri": full[5], "tracklist": full[5:9], "position_ms": 1}
    assert resume.merge_in_flight(partial, tail)["tracklist"] == full
    assert resume.merge_in_flight(partial, None)["tracklist"] == full[5:9]
    other = {"track_uri": "file:///x.mp3", "tracklist": ["file:///x.mp3"]}
    assert resume.merge_in_flight(other, tail) == other


async def test_restorer_runs_tail_in_background(env):
    resume, fake = env
    uris = _http(25)
    _snap(resume, uris, uris[3])
    async with aiohttp.ClientSession() as s:
        r = resume._Restorer(s)
        await r.restore()
        assert r.in_flight() is not None
        for _ in range(200):
            if r.in_flight() is None:
                break
            await _real_sleep(0.01)
    assert fake.uris() == uris
