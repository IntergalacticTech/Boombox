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


@pytest.mark.asyncio
async def test_ping_http_401_raises_auth_error():
    """A fronting proxy that returns 401 must surface as SubsonicAuthError,
    not SubsonicUnreachable."""
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    resp = MagicMock()
    resp.status = 401
    resp.json = AsyncMock(return_value={})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=resp)
        with pytest.raises(SubsonicAuthError):
            await client.ping()


@pytest.mark.asyncio
async def test_ping_http_403_raises_subsonic_error():
    """Other non-Subsonic 4xx codes raise the base SubsonicError, NOT
    SubsonicUnreachable (which would mislead the user about the failure)."""
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    resp = MagicMock()
    resp.status = 403
    resp.json = AsyncMock(return_value={})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=resp)
        with pytest.raises(SubsonicError) as exc_info:
            await client.ping()
        # Specifically NOT the auth or unreachable subclass
        assert not isinstance(exc_info.value, SubsonicAuthError)
        assert not isinstance(exc_info.value, SubsonicUnreachable)


@pytest.mark.asyncio
async def test_ping_non_subsonic_json_raises():
    """If base_url is pointed at the wrong server (e.g., Jellyfin), the
    body parses but isn't a Subsonic envelope. Ping must fail, not lie."""
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"jellyfin": "hello"}  # not a Subsonic envelope
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        with pytest.raises(SubsonicError):
            await client.ping()


@pytest.mark.asyncio
async def test_call_generic_error_code_raises_base_error_not_auth():
    """Subsonic error codes other than 40/41 raise SubsonicError, not
    SubsonicAuthError — keeps the auth-vs-other distinction sharp."""
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {
        "status": "failed",
        "error": {"code": 50, "message": "Generic error"},
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        with pytest.raises(SubsonicError) as exc_info:
            await client.ping()
        assert not isinstance(exc_info.value, SubsonicAuthError)


@pytest.mark.asyncio
async def test_get_artists_parses_index_buckets():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {
        "status": "ok",
        "artists": {
            "index": [
                {"name": "A", "artist": [
                    {"id": "1", "name": "ABBA", "albumCount": 6},
                    {"id": "2", "name": "AC/DC", "albumCount": 31},
                ]},
                {"name": "B", "artist": [
                    {"id": "3", "name": "Beatles", "albumCount": 12},
                ]},
            ],
        },
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        artists = await client.get_artists()
    assert len(artists) == 3
    assert artists[0]["id"] == "1"
    assert artists[0]["name"] == "ABBA"
    assert artists[1]["name"] == "AC/DC"
    assert artists[2]["name"] == "Beatles"


@pytest.mark.asyncio
async def test_get_album_list_pages():
    client = SubsonicClient(base_url="http://nav.local:4533",
                            username="u", password="p")
    payload = {"subsonic-response": {
        "status": "ok",
        "albumList2": {"album": [{"id": "a1"}, {"id": "a2"}]},
    }}
    with patch.object(client, "_session", MagicMock()) as session:
        session.get = MagicMock(return_value=_mock_response(payload))
        albums = await client.get_album_list(offset=0, size=500)
    assert len(albums) == 2
