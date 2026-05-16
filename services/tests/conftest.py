"""Test fixtures shared across boombox-* service tests."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# The service modules live alongside the tests dir. Add the parent to sys.path
# so `import boombox_buttons` works without packaging.
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))


@pytest.fixture(autouse=True)
def _remote_enabled_by_default(tmp_path_factory, monkeypatch):
    """Default the remote_enabled flag ON for the test suite so the access
    gate doesn't 403 every existing remote test. Tests that exercise the
    *disabled* path override BOOMBOX_REMOTE_STATE in their own fixture,
    which runs after this autouse fixture and so wins."""
    state = tmp_path_factory.mktemp("remote-access") / "state.json"
    state.write_text(json.dumps({"enabled": True}))
    monkeypatch.setenv("BOOMBOX_REMOTE_STATE", str(state))


@pytest.fixture
def navidrome_env():
    """Skip an integration test unless real Navidrome creds are in the env.

    Set NAVIDROME_DEV_URL/USER/PASS to enable; otherwise tests are skipped
    (lets CI run without a NAS).
    """
    url = os.environ.get("NAVIDROME_DEV_URL")
    user = os.environ.get("NAVIDROME_DEV_USER")
    pwd = os.environ.get("NAVIDROME_DEV_PASS")
    if not (url and user and pwd):
        pytest.skip("set NAVIDROME_DEV_URL/USER/PASS to enable integration tests")
    # Keys match SubsonicClient kwargs so tests can do `SubsonicClient(**env)`.
    return {"base_url": url, "username": user, "password": pwd}
