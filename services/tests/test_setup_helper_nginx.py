"""boombox-setup-apply nginx-sync: site + snippet installed together."""
from __future__ import annotations

import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "install" / "bin" / "boombox-setup-apply"


def _load():
    loader = SourceFileLoader("boombox_setup_apply_nginx", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


helper = _load()


@pytest.fixture
def box(tmp_path, monkeypatch):
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / "nginx.conf").write_text("server { listen __REMOTE_WEB_PORT__; }\n")
    (rel / "nginx-boombox-common.conf").write_text("location /api/ {}\n")
    etc = tmp_path / "etc"
    (etc / "sites-available").mkdir(parents=True)
    (etc / "snippets").mkdir()
    site = etc / "sites-available" / "boombox"
    snip = etc / "snippets" / "boombox-common.conf"
    site.write_text("OLD SITE\n")
    snip.write_text("OLD SNIPPET\n")
    auth = tmp_path / "web-auth.env"
    auth.write_text("BOOMBOX_WEB_PORT=8091\nBOOMBOX_WEB_PASSWORD=x\n")
    monkeypatch.setattr(helper, "RELEASE_CONFIG_DIR", str(rel))
    monkeypatch.setattr(helper, "NGINX_SITE", str(site))
    monkeypatch.setattr(helper, "NGINX_SNIPPET", str(snip))
    monkeypatch.setattr(helper, "WEB_AUTH_ENV", str(auth))
    runs: list[list[str]] = []
    result = {"rc": 0, "err": ""}

    def fake_run(cmd, timeout=25, check=False, inp=None):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, result["rc"], "", result["err"])

    monkeypatch.setattr(helper, "_run", fake_run)
    return {"site": site, "snip": snip, "auth": auth, "runs": runs, "result": result}


def test_installs_rendered_site_and_snippet_together(box):
    r = helper.action_nginx_sync({})
    assert r == {"ok": True, "changed": True}
    assert box["site"].read_text() == "server { listen 8091; }\n"
    assert box["snip"].read_text() == "location /api/ {}\n"
    assert box["runs"] == [[helper.NGINX_BIN, "-t"]]


def test_unchanged_pair_is_a_noop(box):
    helper.action_nginx_sync({})
    box["runs"].clear()
    assert helper.action_nginx_sync({}) == {"ok": True, "changed": False}
    assert box["runs"] == []


def test_restores_both_files_when_nginx_t_fails(box):
    box["result"].update(rc=1, err='nginx: [emerg] duplicate location "/" in x:3\n')
    r = helper.action_nginx_sync({})
    assert r["ok"] is False and "restored" in r["error"]
    assert "duplicate location" in r["detail"]
    assert box["site"].read_text() == "OLD SITE\n"
    assert box["snip"].read_text() == "OLD SNIPPET\n"


def test_restore_removes_a_file_that_did_not_exist(box):
    box["site"].unlink()
    box["result"].update(rc=1, err="bad")
    helper.action_nginx_sync({})
    assert not box["site"].exists()
    assert box["snip"].read_text() == "OLD SNIPPET\n"


def test_port_defaults_to_8090(box):
    box["auth"].write_text("BOOMBOX_WEB_PASSWORD=x\n")
    helper.action_nginx_sync({})
    assert "listen 8090;" in box["site"].read_text()


@pytest.mark.parametrize("bad", ["80;evil", "0", "65536", "80 443", "-1", "abc"])
def test_rejects_bad_port_and_touches_nothing(box, bad):
    box["auth"].write_text(f"BOOMBOX_WEB_PORT={bad}\n")
    with pytest.raises(ValueError):
        helper.action_nginx_sync({})
    assert box["site"].read_text() == "OLD SITE\n" and box["runs"] == []


def test_action_is_registered():
    assert helper.ACTIONS["nginx-sync"] is helper.action_nginx_sync
