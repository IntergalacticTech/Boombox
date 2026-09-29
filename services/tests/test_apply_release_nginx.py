"""apply-release.sh keeps the nginx site + snippet in step; sudoers can't desync them."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "install" / "apply-release.sh").read_text()
SUDOERS = (ROOT / "install" / "sudoers" / "boombox").read_text()


def _case(name: str) -> str:
    start = SCRIPT.index(f"\n  {name})\n")
    return SCRIPT[start:SCRIPT.index("\n    ;;\n", start)]


def _function(name: str) -> str:
    start = SCRIPT.index(f"\n{name}() {{\n")
    return SCRIPT[start:SCRIPT.index("\n}\n", start)]


def test_nginx_sync_goes_through_the_root_helper():
    fn = _function("nginx_sync")
    assert '{"action":"nginx-sync"}' in fn
    assert "sudo -n /usr/local/sbin/boombox-setup-apply" in fn


def test_swap_and_revert_sync_the_pair_never_the_snippet_alone():
    for name in ("swap", "revert"):
        body = _case(name)
        assert "nginx_sync" in body, name
        assert "/etc/nginx/snippets/boombox-common.conf" not in body, name


def test_verify_probes_the_lan_app_not_remote():
    body = _case("verify")
    assert "http://localhost/remote/" not in body
    assert 'probe "http://127.0.0.1:$lan_port/"' in body
    assert "BOOMBOX_WEB_PORT" in body


def test_sudoers_has_no_snippet_only_install_grant():
    assert "boombox-common.conf" not in SUDOERS
    assert "/usr/sbin/nginx -t" in SUDOERS
    assert "NOPASSWD: /usr/local/sbin/boombox-setup-apply" in SUDOERS
