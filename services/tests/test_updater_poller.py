"""Tests for boombox_updater.poller — GitHub Releases / commits client."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from boombox_updater.poller import GitHubPoller, PollResult


@asynccontextmanager
async def fake_github(handlers: dict[str, web.Response]):
    """Spin up an aiohttp server on a random port serving fixed responses."""
    app = web.Application()

    async def handler(request: web.Request) -> web.Response:
        key = request.path
        if key in handlers:
            return handlers[key]
        return web.Response(status=404)

    app.router.add_route("GET", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
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

    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", capture)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        poller = GitHubPoller(
            base_url=f"http://127.0.0.1:{port}",
            repo="IntergalacticTech/Boombox",
        )
        await poller.poll_stable()
    finally:
        await runner.cleanup()

    assert seen["ua"].startswith("boombox-updater/")
    assert seen["accept"] == "application/vnd.github+json"
