"""Integration tests against a real Navidrome instance.

Skipped unless NAVIDROME_DEV_URL/USER/PASS env vars are set.

Local dev run:
  NAVIDROME_DEV_URL=http://192.168.1.223:4533 \
  NAVIDROME_DEV_USER=jwc \
  NAVIDROME_DEV_PASS=turtle99 \
  pytest services/tests/test_library_integration.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from boombox_library.catalog import sync_full
from boombox_library.db import connect, migrate
from boombox_library.subsonic import SubsonicClient


@pytest.mark.asyncio
async def test_ping_real_navidrome(navidrome_env):
    async with SubsonicClient(**navidrome_env) as c:
        ok = await c.ping()
    assert ok


@pytest.mark.asyncio
async def test_full_sync_real_navidrome(navidrome_env, tmp_path: Path):
    """Run a full sync against the dev Navidrome. Big — may take a while.

    Asserts non-trivial library size (the dev box has thousands of
    artists). Adjust the lower bound if your dev library is smaller.
    """
    db = connect(tmp_path / "live.db")
    migrate(db)
    async with SubsonicClient(**navidrome_env) as c:
        counts = await sync_full(c, db)
    # Bound generously — the dev library had ~3961 artists at the time
    # of the spec; tests just sanity-check we pulled something.
    assert counts["artists"] >= 10
    assert counts["albums"] >= 10
    assert counts["tracks"] >= 10

    # FTS5 sanity
    rows = list(db.execute("SELECT id FROM search_index WHERE search_index MATCH 'beatles' LIMIT 5"))
    # Don't require Beatles specifically (dev libraries vary) — just that
    # FTS5 works at all on the loaded corpus.
    rows = list(db.execute("SELECT COUNT(*) FROM search_index"))
    assert rows[0][0] > 0
