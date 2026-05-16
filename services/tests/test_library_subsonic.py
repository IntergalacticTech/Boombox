"""Tests for boombox_library.subsonic — Subsonic API client."""
from __future__ import annotations

import hashlib

import pytest

from boombox_library.subsonic import make_auth_params


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
