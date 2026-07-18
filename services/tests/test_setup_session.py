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


def test_remint_invalidates_old():
    s = SetupSession()
    old, _, _ = s.mint(now=0.0)
    new, _, _ = s.mint(now=0.0)
    assert not s.verify(old, now=0.0)
    assert s.verify(new, now=0.0)


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


def test_remint_invalidates_code():
    s = SetupSession()
    old_token, old_code, _ = s.mint(now=0.0)
    new_token, _, _ = s.mint(now=0.0)
    # The old code can never yield the old token after a re-mint. (In the
    # 1-in-10^6 case the fresh code collides with the old one, redeeming
    # legitimately returns the NEW token — allow that.)
    assert s.redeem_code(old_code, now=0.0) in (None, new_token)
