"""Sanity check that the boombox_updater package is importable and
exposes its version string."""
from __future__ import annotations


def test_package_imports() -> None:
    import boombox_updater
    assert hasattr(boombox_updater, "__version__")
    # __version__ is read from /opt/boombox/current/VERSION on a real install,
    # but in dev/test it falls back to the repo-root VERSION file.
    assert isinstance(boombox_updater.__version__, str)
    assert boombox_updater.__version__  # non-empty


def test_unreadable_paths_fall_through(tmp_path, monkeypatch) -> None:
    """If the production VERSION path errors out (broken symlink, permission,
    etc.), the package still imports and exposes a non-empty __version__."""
    import boombox_updater
    # Point both candidate paths at a broken symlink and a missing file.
    broken_link = tmp_path / "broken"
    broken_link.symlink_to(tmp_path / "does-not-exist" / "VERSION")
    missing = tmp_path / "also-missing"
    monkeypatch.setattr(boombox_updater, "_INSTALLED_VERSION_FILE", broken_link)
    monkeypatch.setattr(boombox_updater, "_DEV_VERSION_FILE", missing)
    # Call the resolver directly; it should not raise and should return "unknown".
    assert boombox_updater._read_version() == "unknown"
