"""remote-ui build config: served at /, own asset dir, a SW that stays in its lane."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VITE = (ROOT / "remote-ui" / "vite.config.ts").read_text()
DENYLIST = r"navigateFallbackDenylist: [/^\/(?:setup|api|remote|accounts|mopidy|local|audio)(?:\/|$)/]"


def test_served_from_root_with_distinct_assets_dir():
    assert 'base: "/"' in VITE
    assert 'assetsDir: "app-assets"' in VITE
    assert "/remote/" not in VITE.replace("|remote|", "")


def test_manifest_is_scoped_to_the_whole_app():
    for s in ('id: "/"', 'start_url: "/"', 'scope: "/"'):
        assert s in VITE, s


def test_service_worker_never_hijacks_other_paths():
    assert DENYLIST in VITE
    # Compile the literal that is actually in the config (JS `\/` is a valid
    # Python escape), so the path cases below exercise the shipped pattern.
    m = re.search(r"navigateFallbackDenylist: \[/(.+?)/\]", VITE)
    assert m, "denylist regex literal not found"
    deny = re.compile(m.group(1))
    for path in ("/setup", "/setup/", "/api/remote/state", "/remote/", "/accounts",
                 "/mopidy/rpc", "/local/x.jpg", "/audio/ws"):
        assert deny.match(path), path
    # nginx sends the no-slash forms to the SPA fallback on the LAN port, so
    # the worker must leave every bare prefix alone too.
    for path in ("/setup", "/api", "/remote", "/accounts", "/mopidy", "/local", "/audio"):
        assert deny.match(path), path
    for path in ("/", "/index.html", "/settings", "/apis", "/audiobooks", "/localhost",
                 "/remotes", "/mopidyx", "/setups"):
        assert not deny.match(path), path
