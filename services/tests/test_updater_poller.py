"""Tests for boombox_updater.poller — GitHub Releases / commits client."""
from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Union

import pytest
from aiohttp import web

from boombox_updater.poller import GitHubPoller, PollResult

Handler = Union[web.Response, Callable[[web.Request], Awaitable[web.Response]]]


@asynccontextmanager
async def fake_github(handlers: dict[str, Handler]):
    """Spin up an aiohttp server on a random port serving fixed responses.

    Each value in `handlers` is either a prebuilt `web.Response` or a
    coroutine `(request) -> Response` for tests that need to inspect the
    incoming request.
    """
    app = web.Application()

    async def handler(request: web.Request) -> web.Response:
        entry = handlers.get(request.path)
        if entry is None:
            return web.Response(status=404)
        if inspect.iscoroutinefunction(entry):
            return await entry(request)
        return entry

    app.router.add_route("GET", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_poll_stable_returns_tag_name() -> None:
    handlers = {
        "/repos/IntergalacticTech/Boombox/releases/latest": web.json_response(
            {"tag_name": "v0.4.2", "published_at": "2026-05-13T01:23:45Z"}
        ),
    }
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_stable()
    assert result == PollResult(version="v0.4.2", published_at="2026-05-13T01:23:45Z")


@pytest.mark.asyncio
async def test_poll_edge_returns_short_sha() -> None:
    handlers = {
        "/repos/IntergalacticTech/Boombox/commits/main": web.json_response(
            {"sha": "abcdef1234567890abcdef1234567890abcdef12",
             "commit": {"committer": {"date": "2026-05-13T02:34:56Z"}}}
        ),
    }
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_edge()
    assert result == PollResult(version="abcdef1", published_at="2026-05-13T02:34:56Z")


@pytest.mark.asyncio
async def test_poll_stable_404_returns_none() -> None:
    async with fake_github({}) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_stable()
    assert result is None


@pytest.mark.asyncio
async def test_poll_uses_user_agent_and_accept_headers() -> None:
    seen: dict[str, str] = {}

    async def capture(request: web.Request) -> web.Response:
        seen["ua"] = request.headers.get("User-Agent", "")
        seen["accept"] = request.headers.get("Accept", "")
        return web.json_response({"tag_name": "v0.4.2", "published_at": ""})

    handlers = {"/repos/IntergalacticTech/Boombox/releases/latest": capture}
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        await poller.poll_stable()

    assert seen["ua"].startswith("boombox-updater/")
    assert seen["accept"] == "application/vnd.github+json"


@pytest.mark.asyncio
async def test_poll_stable_missing_tag_returns_none() -> None:
    """A 200 with no tag_name (e.g. a draft release with no tag) is treated
    the same as a 404 — nothing to install."""
    handlers = {
        "/repos/IntergalacticTech/Boombox/releases/latest": web.json_response(
            {"published_at": "2026-05-13T01:23:45Z"}
        ),
    }
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_stable()
    assert result is None


@pytest.mark.asyncio
async def test_poll_edge_missing_sha_returns_none() -> None:
    handlers = {
        "/repos/IntergalacticTech/Boombox/commits/main": web.json_response(
            {"commit": {"committer": {"date": "2026-05-13T02:34:56Z"}}}
        ),
    }
    async with fake_github(handlers) as base:
        poller = GitHubPoller(base_url=base, repo="IntergalacticTech/Boombox")
        result = await poller.poll_edge()
    assert result is None
