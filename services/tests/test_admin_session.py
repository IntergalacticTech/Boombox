"""AdminSessions: token lifetime + global lockout; web password parsing."""
from __future__ import annotations

import pytest
from boombox_setup import admin_session as a
from boombox_setup.admin_session import AdminSessions


class Clock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_issue_and_verify_refreshes_idle_timer():
    clock = Clock()
    s = AdminSessions(clock=clock)
    token, expires_at = s.issue()
    assert len(token) == 64 and expires_at == clock.t + a.IDLE_TTL_S
    clock.t += a.IDLE_TTL_S - 1
    assert s.verify(token)            # used just before expiry → refreshed
    clock.t += a.IDLE_TTL_S - 1
    assert s.verify(token)
    clock.t += a.IDLE_TTL_S
    assert not s.verify(token)        # 12 h idle → gone
    assert not s.verify(token)


def test_verify_rejects_unknown_and_empty():
    s = AdminSessions(clock=Clock())
    s.issue()
    assert not s.verify("")
    assert not s.verify("0" * 64)


def test_revoke():
    s = AdminSessions(clock=Clock())
    token, _ = s.issue()
    s.revoke(token)
    assert not s.verify(token)
    s.revoke("never-issued")          # no error


def test_lockout_after_five_failures_within_window():
    clock = Clock()
    s = AdminSessions(clock=clock)
    for _ in range(4):
        assert s.record_failure() is False
        clock.t += 10
    assert s.locked_for() == 0
    assert s.record_failure() is True
    assert s.locked_for() == a.LOCKOUT_S
    clock.t += a.LOCKOUT_S - 1
    assert s.locked_for() == 1
    clock.t += 1
    assert s.locked_for() == 0


def test_old_failures_age_out():
    clock = Clock()
    s = AdminSessions(clock=clock)
    for _ in range(4):
        s.record_failure()
    clock.t += a.LOCKOUT_WINDOW_S     # the four are now 5 minutes old
    assert s.record_failure() is False
    assert s.locked_for() == 0


@pytest.mark.parametrize("supplied,expected,ok", [
    ("correct horse", "correct horse", True),
    ("correct horsE", "correct horse", False),
    ("pässwörd", "pässwörd", True),   # non-ASCII must not raise
    ("", "", False),                  # an unset password never matches
    (None, "x", False),
    (123, "123", False),
])
def test_password_matches(supplied, expected, ok):
    assert a.password_matches(supplied, expected) is ok


def test_read_web_password(tmp_path):
    env = tmp_path / "web-auth.env"
    assert a.read_web_password(env) is None
    env.write_text("BOOMBOX_WEB_PORT=8090\nBOOMBOX_WEB_USER=boombox\n"
                   "BOOMBOX_WEB_PASSWORD= s3cret=with=equals \n")
    assert a.read_web_password(env) == "s3cret=with=equals"
    env.write_text("BOOMBOX_WEB_PASSWORD=\n")
    assert a.read_web_password(env) is None


def test_unencodable_token_is_just_invalid():
    # aiohttp decodes non-UTF-8 header bytes with surrogateescape.
    s = AdminSessions(clock=Clock())
    s.issue()
    assert not s.verify("\udcff\udcfe")
    s.revoke("\udcff\udcfe")          # no-op, no error


def test_unencodable_password_is_a_non_match():
    assert a.password_matches("\udcff", "secret") is False
    assert a.password_matches("\udcff", "\udcff") is False  # unencodable never matches
