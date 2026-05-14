"""GitHub Releases / commits poller.

Two methods, one per channel. Network errors and non-2xx responses are
folded into `None` (the caller logs and moves on); they never raise.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from . import __version__

log = logging.getLogger("boombox-updater")

DEFAULT_GITHUB_BASE = "https://api.github.com"
SHORT_SHA_LEN = 7


@dataclass(frozen=True)
class PollResult:
    version: str
    published_at: str  # ISO 8601, may be empty if the API omits it


class GitHubPoller:
    def __init__(
        self,
        *,
        repo: str,
        base_url: str = DEFAULT_GITHUB_BASE,
        timeout_s: float = 10.0,
    ) -> None:
        self._repo = repo
        self._base = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._headers = {
            "User-Agent": f"boombox-updater/{__version__}",
            "Accept": "application/vnd.github+json",
        }

    async def poll_stable(self) -> Optional[PollResult]:
        url = f"{self._base}/repos/{self._repo}/releases/latest"
        data = await self._get_json(url)
        if not data:
            return None
        tag = data.get("tag_name")
        if not tag:
            return None
        return PollResult(version=tag, published_at=data.get("published_at") or "")

    async def poll_edge(self) -> Optional[PollResult]:
        url = f"{self._base}/repos/{self._repo}/commits/main"
        data = await self._get_json(url)
        if not data:
            return None
        sha = data.get("sha", "")
        if not sha:
            return None
        published = (
            ((data.get("commit") or {}).get("committer") or {}).get("date") or ""
        )
        return PollResult(version=sha[:SHORT_SHA_LEN], published_at=published)

    async def _get_json(self, url: str) -> Optional[dict]:
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout, headers=self._headers
            ) as session:
                async with session.get(url) as resp:
                    if resp.status >= 400:
                        log.warning("github poll %s -> HTTP %d", url, resp.status)
                        return None
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("github poll %s failed: %s", url, exc)
            return None
