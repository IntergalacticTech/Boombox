"""apply-release.sh keeps the nginx site + snippet in step; sudoers can't desync them."""
from __future__ import annotations

import os
import subprocess
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


# ---- An un-prepped device (old root helper) fails fast -------------------

SCRIPT_PATH = ROOT / "install" / "apply-release.sh"
OLD_HELPER_ANSWER = '{"ok": false, "error": "unknown action: nginx-sync"}'


def _fake_sudo(tmp_path: Path, answer: str, rc: int) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    sudo = bindir / "sudo"
    sudo.write_text(f"#!/bin/sh\ncat >/dev/null\necho '{answer}'\nexit {rc}\n")
    sudo.chmod(0o755)
    return bindir


def _run_nginx_sync(tmp_path: Path, answer: str, rc: int, *args: str):
    """Source the script's function header (everything before the
    subcommand dispatch) and call nginx_sync with a stubbed sudo."""
    header = SCRIPT[:SCRIPT.index('\ncmd="${1:-}"\n')]
    bindir = _fake_sudo(tmp_path, answer, rc)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "BOOMBOX_ROOT": str(tmp_path)}
    return subprocess.run(["bash", "-c", header + "\nnginx_sync " + " ".join(args)],
                          capture_output=True, text=True, env=env)


def test_strict_nginx_sync_fails_on_old_helper(tmp_path):
    r = _run_nginx_sync(tmp_path, OLD_HELPER_ANSWER, 2, "strict")
    assert r.returncode != 0
    assert "reinstall the root helper" in r.stderr
    assert "re-run install.sh" in r.stderr


def test_non_strict_nginx_sync_only_warns_on_old_helper(tmp_path):
    # revert must never be blocked by the helper.
    r = _run_nginx_sync(tmp_path, OLD_HELPER_ANSWER, 2)
    assert r.returncode == 0
    assert "nginx config not synced" in r.stderr


def test_strict_nginx_sync_ok_with_new_helper(tmp_path):
    r = _run_nginx_sync(tmp_path, '{"ok": true, "changed": false}', 0, "strict")
    assert r.returncode == 0, r.stderr


def test_swap_uses_strict_revert_does_not():
    assert "nginx_sync strict" in _case("swap")
    body = _case("revert")
    assert "nginx_sync" in body and "nginx_sync strict" not in body


def _preflight(tmp_path: Path, helper_text: str):
    helper = tmp_path / "boombox-setup-apply"
    helper.write_text(helper_text)
    (tmp_path / "releases" / "v9.9.9").mkdir(parents=True)
    env = {**os.environ, "BOOMBOX_ROOT": str(tmp_path),
           "BOOMBOX_SETUP_APPLY_BIN": str(helper)}
    return subprocess.run(["bash", str(SCRIPT_PATH), "preflight", "v9.9.9"],
                          capture_output=True, text=True, env=env)


def test_preflight_aborts_before_anything_on_old_helper(tmp_path):
    r = _preflight(tmp_path, 'ACTIONS = {"identity": f, "web-password": g}\n')
    assert r.returncode != 0
    assert "re-run install.sh" in r.stderr


def test_preflight_passes_probe_with_new_helper(tmp_path):
    r = _preflight(tmp_path, 'ACTIONS = {"nginx-sync": action_nginx_sync}\n')
    # Probe passes; preflight then stops at the (absent) built UI instead.
    assert r.returncode != 0
    assert "re-run install.sh" not in r.stderr
    assert "ui/dist/index.html missing" in r.stderr
