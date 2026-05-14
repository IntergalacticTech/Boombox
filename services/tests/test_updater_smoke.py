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
