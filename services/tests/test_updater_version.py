"""Tests for boombox_updater.version — channel-aware version comparison."""
from __future__ import annotations

import pytest

from boombox_updater.version import (
    UpdateAvailable,
    compare_stable,
    compare_edge,
    parse_stable,
)


class TestParseStable:
    def test_strips_v_prefix(self) -> None:
        assert str(parse_stable("v0.5.0")) == "0.5.0"

    def test_accepts_no_prefix(self) -> None:
        assert str(parse_stable("0.5.0")) == "0.5.0"

    def test_dev_suffix_is_pre_release(self) -> None:
        assert parse_stable("0.5.0-dev") < parse_stable("0.5.0")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_stable("not-a-version")


class TestCompareStable:
    def test_newer_tag_is_available(self) -> None:
        assert compare_stable(installed="v0.4.1", available="v0.4.2") == \
            UpdateAvailable(available="v0.4.2", installed="v0.4.1")

    def test_same_tag_is_none(self) -> None:
        assert compare_stable(installed="v0.4.2", available="v0.4.2") is None

    def test_double_digit_minor(self) -> None:
        # v0.4.10 must be newer than v0.4.2 (string compare would invert this).
        assert compare_stable(installed="v0.4.2", available="v0.4.10") is not None

    def test_legacy_installed_is_always_outdated(self) -> None:
        # Migrated installs have VERSION == "legacy"; any release should win.
        assert compare_stable(installed="legacy", available="v0.4.0") is not None

    def test_unknown_installed_is_always_outdated(self) -> None:
        assert compare_stable(installed="unknown", available="v0.4.0") is not None

    def test_dev_installed_loses_to_release(self) -> None:
        assert compare_stable(installed="v0.5.0-dev", available="v0.5.0") is not None

    def test_invalid_available_raises(self) -> None:
        with pytest.raises(ValueError):
            compare_stable(installed="v0.4.1", available="garbage")


class TestCompareEdge:
    def test_different_sha_is_available(self) -> None:
        assert compare_edge(installed="abc1234", available="def5678") == \
            UpdateAvailable(available="def5678", installed="abc1234")

    def test_same_sha_is_none(self) -> None:
        assert compare_edge(installed="abc1234", available="abc1234") is None

    def test_short_vs_long_sha_match(self) -> None:
        # Edge installs always store the short sha; the API may return long.
        assert compare_edge(installed="abc1234", available="abc1234567890") is None
