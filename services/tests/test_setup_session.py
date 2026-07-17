"""Tests for boombox_setup.session — setup-token minting and verification."""
from __future__ import annotations

from boombox_setup.session import TOKEN_TTL_S, SetupSession


def test_mint_then_verify():
    s = SetupSession()
    token, exp = s.mint(now=1000.0)
    assert exp == 1000.0 + TOKEN_TTL_S
    assert s.verify(token, now=1000.0)


def test_wrong_token_rejected():
    s = SetupSession()
    s.mint(now=0.0)
    assert not s.verify("not-the-token", now=1.0)


def test_expired_token_rejected():
    s = SetupSession()
    token, _ = s.mint(now=0.0)
    assert s.verify(token, now=TOKEN_TTL_S - 1)
    assert not s.verify(token, now=TOKEN_TTL_S + 1)


def test_empty_and_unminted_rejected():
    s = SetupSession()
    assert not s.verify("", now=0.0)          # unminted
    s.mint(now=0.0)
    assert not s.verify("", now=0.0)          # minted, but empty presented


def test_remint_invalidates_old():
    s = SetupSession()
    old, _ = s.mint(now=0.0)
    new, _ = s.mint(now=0.0)
    assert not s.verify(old, now=0.0)
    assert s.verify(new, now=0.0)


def test_clear():
    s = SetupSession()
    token, _ = s.mint(now=0.0)
    s.clear()
    assert not s.verify(token, now=0.0)
