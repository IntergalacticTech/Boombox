"""RFID queueing: long streamed lists start fast and the tail streams in."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from boombox_rfid import mopidy_client as mc
from boombox_rfid.mopidy_client import MopidyClient, PendingTail, needs_split

from .fake_mopidy import FakeMopidy


def _http(n: int) -> list[str]:
    return [f"https://music.example.com/rest/stream.view?id=t{i}" for i in range(n)]


@pytest.fixture
async def mopidy(aiohttp_server):
    fake = FakeMopidy()
    srv = await aiohttp_server(fake.app())
    fake.url = str(srv.make_url("/mopidy/rpc"))  # type: ignore[attr-defined]
    return fake


def test_needs_split():
    assert not needs_split(_http(mc.SYNC_ADD_MAX))
    assert needs_split(_http(mc.SYNC_ADD_MAX + 1))
    assert not needs_split([f"file:///cache/t{i}.mp3" for i in range(200)])
    mixed = [f"file:///cache/t{i}.mp3" for i in range(50)] + _http(1)
    assert needs_split(mixed)


async def test_short_list_unchanged_single_add(mopidy):
    uris = _http(3)
    async with MopidyClient(mopidy.url) as m:
        tail = await m.play_uris(uris)
    assert tail is None
    assert mopidy.adds() == [{"uris": uris}]
    assert mopidy.uris() == uris
    assert mopidy.state == "playing" and mopidy.current == 1


async def test_file_uris_unchanged_single_add(mopidy):
    uris = [f"file:///cache/t{i}.mp3" for i in range(40)]
    async with MopidyClient(mopidy.url) as m:
        assert await m.play_uris(uris) is None
    assert len(mopidy.adds()) == 1
    assert mopidy.uris() == uris


async def test_long_streamed_list_plays_head_then_appends_tail(mopidy):
    uris = _http(57)
    async with MopidyClient(mopidy.url) as m:
        tail = await m.play_uris(uris)
        # Playback started with only the head queued.
        assert mopidy.uris() == uris[:mc.HEAD_COUNT]
        assert mopidy.state == "playing" and mopidy.current == 1
        assert tail is not None and tail.uris == uris[mc.HEAD_COUNT:]
        n = await m.append_tail(tail, gap_s=0)
    assert n == 57 - mc.HEAD_COUNT
    assert mopidy.uris() == uris
    sizes = [len(p["uris"]) for p in mopidy.adds()[1:]]
    assert max(sizes) <= mc.TAIL_CHUNK
    # Current track untouched by the background appends.
    assert mopidy.current == 1


async def test_tail_keeps_order_when_user_queues_meanwhile(mopidy):
    uris = _http(25)
    async with MopidyClient(mopidy.url) as m:
        tail = await m.play_uris(uris)
        injected = {"done": False}

        def user_adds(fake, _p):
            if not injected["done"]:
                injected["done"] = True
                fake.tl.append((999, "file:///user-queued.mp3"))
        mopidy.before_add = user_adds
        await m.append_tail(tail, gap_s=0)
    assert mopidy.uris() == uris + ["file:///user-queued.mp3"]


async def test_tail_stops_when_tracklist_replaced(mopidy):
    uris = _http(40)
    async with MopidyClient(mopidy.url) as m:
        tail = await m.play_uris(uris)
        calls = {"n": 0}

        def replace_after_first_chunk(fake, _p):
            calls["n"] += 1
            if calls["n"] == 2:
                # User played something else between chunk 1 and 2.
                fake.tl = [(500, "file:///other.mp3")]
        mopidy.before_add = replace_after_first_chunk
        n = await m.append_tail(tail, gap_s=0)
    # Chunk 2's add was in flight when the replace happened, so it landed in
    # the user's new queue; the next check notices the broken chain, removes
    # that stray chunk and stops.
    assert mopidy.uris() == ["file:///other.mp3"]
    assert n == mc.TAIL_CHUNK  # only chunk 1 counted as queued (then cleared)
    assert len(mopidy.adds()) == 3  # head + two chunks, nothing more


async def test_tail_anchor_missing_before_first_chunk(mopidy):
    async with MopidyClient(mopidy.url) as m:
        n = await m.append_tail(PendingTail(uris=_http(5), after_tlid=12345), gap_s=0)
    assert n == 0 and mopidy.adds() == []


async def test_scan_failure_falls_back_to_track_objects(mopidy):
    orig = mopidy.handle

    def handle(method, p):
        if method == "core.tracklist.add" and "uris" in p:
            mopidy.calls.append((method, p))
            return []  # Mopidy's scanner dropped every http URI
        return orig(method, p)
    mopidy.handle = handle
    uris = _http(12)
    async with MopidyClient(mopidy.url) as m:
        tail = await m.play_uris(uris)
        await m.append_tail(tail, gap_s=0)
    assert mopidy.uris() == uris


# ---- the service's tap handler ------------------------------------------------

def _load_rfid_service():
    path = Path(__file__).resolve().parent.parent / "boombox-rfid.py"
    spec = importlib.util.spec_from_file_location("boombox_rfid_service", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_tap_returns_before_tail_and_new_tap_supersedes(mopidy, monkeypatch):
    svc = _load_rfid_service()
    ctx = svc.ServiceContext.__new__(svc.ServiceContext)
    ctx.cfg = SimpleNamespace(mopidy_rpc=mopidy.url)
    ctx._tail_task = None
    ctx.conn = None
    uris_by_card = {"A": _http(60), "B": [f"file:///b{i}.mp3" for i in range(3)]}
    monkeypatch.setattr(svc, "get_binding",
                        lambda _c, uid: SimpleNamespace(
                            kind=SimpleNamespace(value="artist"), target_id=uid))
    monkeypatch.setattr(svc, "record_tap", lambda *_a: None)
    monkeypatch.setattr(svc, "expand_to_track_ids", lambda _c, _k, tid: [tid])
    monkeypatch.setattr(svc, "load_library_config",
                        lambda: SimpleNamespace(source=SimpleNamespace(
                            url="", username="", password="")))
    monkeypatch.setattr(svc, "resolve_uris",
                        lambda _c, ids, **_k: uris_by_card[ids[0]])
    # Slow the tail so the second tap lands mid-append.
    monkeypatch.setattr(mc, "TAIL_GAP_S", 0.05)

    await svc.ServiceContext._handle_tap(ctx, "A")
    assert mopidy.uris() == uris_by_card["A"][:mc.HEAD_COUNT]
    assert mopidy.state == "playing"
    assert ctx._tail_task is not None and not ctx._tail_task.done()
    await asyncio.sleep(0.02)

    first_task = ctx._tail_task
    await svc.ServiceContext._handle_tap(ctx, "B")
    assert first_task.cancelled() or first_task.done()
    await asyncio.sleep(0.2)
    # Card B's queue is intact; none of A's tail leaked in afterwards.
    assert mopidy.uris() == uris_by_card["B"]
    assert ctx._tail_task is None


async def test_head_path_waits_out_an_in_flight_tail_chunk(mopidy, monkeypatch):
    # A superseded card's chunk may still be scanning in Mopidy's core; the
    # new tap's clear + head add queue behind it, so they must not use the
    # 10 s session default.
    seen: list[tuple[str, float | None]] = []
    orig = MopidyClient._call

    async def spy(self, method, params=None, timeout=None):
        seen.append((method, timeout))
        return await orig(self, method, params, timeout=timeout)
    monkeypatch.setattr(MopidyClient, "_call", spy)
    async with MopidyClient(mopidy.url) as m:
        await m.play_uris(_http(20))
    by_method = dict(seen)
    assert by_method["core.tracklist.clear"] >= mc.TAIL_CALL_TIMEOUT_S
    assert by_method["core.tracklist.add"] >= mc.TAIL_CALL_TIMEOUT_S


def _tap_ctx(svc, mopidy, monkeypatch, uris_by_card):
    ctx = svc.ServiceContext.__new__(svc.ServiceContext)
    ctx.cfg = SimpleNamespace(mopidy_rpc=mopidy.url)
    ctx._tail_task = None
    ctx.conn = None
    monkeypatch.setattr(svc, "get_binding",
                        lambda _c, uid: SimpleNamespace(
                            kind=SimpleNamespace(value="artist"), target_id=uid))
    monkeypatch.setattr(svc, "record_tap", lambda *_a: None)
    monkeypatch.setattr(svc, "expand_to_track_ids", lambda _c, _k, tid: [tid])
    monkeypatch.setattr(svc, "load_library_config",
                        lambda: SimpleNamespace(source=SimpleNamespace(
                            url="", username="", password="")))
    monkeypatch.setattr(svc, "resolve_uris",
                        lambda _c, ids, **_k: uris_by_card[ids[0]])
    return ctx


async def test_tap_records_queue_intent_until_tail_done(mopidy, monkeypatch):
    import queue_intent
    svc = _load_rfid_service()
    uris = _http(30)
    ctx = _tap_ctx(svc, mopidy, monkeypatch, {"A": uris})
    monkeypatch.setattr(mc, "TAIL_GAP_S", 0.05)
    await svc.ServiceContext._handle_tap(ctx, "A")
    # Tail still streaming: resume would snapshot the whole card.
    assert queue_intent.read_intent() == uris
    await ctx._tail_task
    assert mopidy.uris() == uris
    assert queue_intent.read_intent() is None


async def test_new_short_tap_drops_previous_queue_intent(mopidy, monkeypatch):
    import queue_intent
    svc = _load_rfid_service()
    cards = {"A": _http(60), "B": [f"file:///b{i}.mp3" for i in range(3)]}
    ctx = _tap_ctx(svc, mopidy, monkeypatch, cards)
    monkeypatch.setattr(mc, "TAIL_GAP_S", 0.05)
    await svc.ServiceContext._handle_tap(ctx, "A")
    assert queue_intent.read_intent() == cards["A"]
    await svc.ServiceContext._handle_tap(ctx, "B")
    await asyncio.sleep(0.1)
    assert queue_intent.read_intent() is None
