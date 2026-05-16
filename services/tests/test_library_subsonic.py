"""Tests for boombox_library.subsonic — Subsonic API client."""
from __future__ import annotations

import hashlib
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boombox_library.subsonic import (
    SubsonicAuthError,
    SubsonicClient,
    SubsonicError,
    SubsonicUnreachable,
    make_auth_params,
)


def test_make_auth_params_token_and_salt():
    params = make_auth_params(username="jwc", password="turtle99", salt="abc123")
    expected_token = hashlib.md5(b"turtle99abc123").hexdigest()
    assert params["u"] == "jwc"
    assert params["t"] == expected_token
    assert params["s"] == "abc123"
    assert params["v"] == "1.16.1"
    assert params["c"] == "boombox-library"
    assert params["f"] == "json"
    # Password must never appear
    assert "p" not in params
    assert "turtle99" not in str(params)


def test_make_auth_params_random_salt_each_call():
    p1 = make_auth_params(username="u", password="p")
    p2 = make_auth_params(username="u", password="p")
    assert p1["s"] != p2["s"]  # random per call
    assert p1["t"] != p2["t"]


def _mock_response(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


@pytest.mark.asyncio
async def test_ping_ok():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        ok = await client.ping()
    assert ok is True


@pytest.mark.asyncio
async def test_ping_auth_fail_raises():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="bad")
    payload = {"subsonic-response": {
        "status": "failed",
        "error": {"code": 40, "message": "Wrong username or password."},
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        with pytest.raises(SubsonicAuthError):
            await client.ping()


@pytest.mark.asyncio
async def test_ping_unreachable_raises():
    import aiohttp
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(side_effect=aiohttp.ClientConnectionError("nope"))
        with pytest.raises(SubsonicUnreachable):
            await client.ping()
