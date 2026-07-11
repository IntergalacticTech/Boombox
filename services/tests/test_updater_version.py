"""Tests for boombox_updater.version — channel-aware version comparison."""
from __future__ import annotations

import pytest
from boombox_updater.version import (
    UpdateAvailable,
    compare_edge,
    compare_stable,
    parse_stable,
    valid_ref,
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

    def test_long_installed_vs_short_available(self) -> None:
        # Reverse of the existing short-vs-long test — exercises a.startswith(b).
        assert compare_edge(installed="abc1234567890", available="abc1234") is None

    def test_empty_operand_is_outdated(self) -> None:
        # Defensive: a blank installed/available value should surface, not silently
        # be treated as up-to-date.
        assert compare_edge(installed="", available="abc1234") is not None
        assert compare_edge(installed="abc1234", available="") is not None

    def test_case_insensitive_match(self) -> None:
        # Git shas are hex; comparison must not be case-sensitive.
        assert compare_edge(installed="ABC1234", available="abc1234") is None


class TestValidRef:
    def test_stable_tags_pass(self) -> None:
        assert valid_ref("v0.5.0")
        assert valid_ref("v0.5.0-rc1")
        assert valid_ref("v1.2.3-dev")

    def test_short_and_long_shas_pass(self) -> None:
        # Edge channel installs a 7-char short sha; the API may hand back a long one.
        assert valid_ref("a1b2c3d")
        assert valid_ref("deadbeef" * 5)  # 40 hex

    def test_path_traversal_rejected(self) -> None:
        assert not valid_ref("../../etc")
        assert not valid_ref("v1/../../x")
        assert not valid_ref("../../home/boombox/.config")

    def test_shell_metacharacters_rejected(self) -> None:
        assert not valid_ref("main;rm -rf /")
        assert not valid_ref("v1 && reboot")

    def test_git_option_injection_rejected(self) -> None:
        # A leading dash could be read as a git-clone flag.
        assert not valid_ref("--upload-pack=touch /tmp/x")

    def test_branch_names_and_empty_rejected(self) -> None:
        # The updater only ever installs a version tag or a sha, never a branch.
        assert not valid_ref("main")
        assert not valid_ref("")
        assert not valid_ref("0.5.0-dev")  # no leading v → not a valid tag ref
