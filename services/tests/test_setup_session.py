"""Tests for boombox_setup.session — setup-token minting and verification."""
from __future__ import annotations

from boombox_setup.session import CODE_MAX_ATTEMPTS, TOKEN_TTL_S, SetupSession


def test_mint_then_verify():
    s = SetupSession()
    token, code, exp = s.mint(now=1000.0)
    assert exp == 1000.0 + TOKEN_TTL_S
    assert s.verify(token, now=1000.0)
    assert len(code) == 6 and code.isdigit()


def test_wrong_token_rejected():
    s = SetupSession()
    s.mint(now=0.0)
    assert not s.verify("not-the-token", now=1.0)


def test_expired_token_rejected():
    s = SetupSession()
    token, _, _ = s.mint(now=0.0)
    assert s.verify(token, now=TOKEN_TTL_S - 1)
    assert not s.verify(token, now=TOKEN_TTL_S + 1)


def test_empty_and_unminted_rejected():
    s = SetupSession()
    assert not s.verify("", now=0.0)          # unminted
    s.mint(now=0.0)
    assert not s.verify("", now=0.0)          # minted, but empty presented


def test_mint_is_idempotent_while_live():
    # A kiosk reload re-mints; that must NOT log out a phone already using
    # the token.
    s = SetupSession()
    t1, c1, e1 = s.mint(now=0.0)
    t2, c2, e2 = s.mint(now=100.0)
    assert (t1, c1, e1) == (t2, c2, e2)
    assert s.verify(t1, now=100.0)


def test_mint_fresh_after_expiry():
    s = SetupSession()
    old, _, _ = s.mint(now=0.0)
    new, _, _ = s.mint(now=TOKEN_TTL_S + 1)
    assert new != old
    assert not s.verify(old, now=TOKEN_TTL_S + 2)
    assert s.verify(new, now=TOKEN_TTL_S + 2)


def test_clear():
    s = SetupSession()
    token, _, _ = s.mint(now=0.0)
    s.clear()
    assert not s.verify(token, now=0.0)


def test_redeem_code_exchanges_for_token():
    s = SetupSession()
    token, code, _ = s.mint(now=0.0)
    assert s.redeem_code(code, now=1.0) == token


def test_redeem_wrong_code_and_burnout():
    s = SetupSession()
    token, code, _ = s.mint(now=0.0)
    for _ in range(CODE_MAX_ATTEMPTS):
        assert s.redeem_code("000000" if code != "000000" else "111111", now=0.0) is None
    # Burned: even the right code no longer redeems…
    assert s.redeem_code(code, now=0.0) is None
    # …but the QR token itself still verifies.
    assert s.verify(token, now=0.0)


def test_redeem_expired_code():
    s = SetupSession()
    _, code, _ = s.mint(now=0.0)
    assert s.redeem_code(code, now=TOKEN_TTL_S + 1) is None


def test_burned_code_forces_fresh_mint():
    s = SetupSession()
    t1, code, _ = s.mint(now=0.0)
    for _ in range(CODE_MAX_ATTEMPTS):
        s.redeem_code("999999" if code != "999999" else "111111", now=0.0)
    # Code burned: the next kiosk mint issues a fresh session (new code on
    # screen) instead of keeping a dead one.
    t2, code2, _ = s.mint(now=0.0)
    assert t2 != t1 and code2 != code
    assert s.redeem_code(code2, now=0.0) == t2
