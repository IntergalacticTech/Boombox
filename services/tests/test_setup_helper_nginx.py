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


# --------------------------------------------------------------------------- #
# Allowlist: root must never install a directive that can write files as root
# (log_format + access_log into /etc/cron.d, load_module, include elsewhere…).
# --------------------------------------------------------------------------- #
REPO_CONFIG = Path(__file__).resolve().parents[2] / "install" / "config"


def _untouched(box):
    assert box["site"].read_text() == "OLD SITE\n"
    assert box["snip"].read_text() == "OLD SNIPPET\n"
    assert box["runs"] == []


def _set(box, site=None, snippet=None):
    rel = Path(helper.RELEASE_CONFIG_DIR)
    if site is not None:
        (rel / "nginx.conf").write_text(site)
    if snippet is not None:
        (rel / "nginx-boombox-common.conf").write_text(snippet)


def _denied(r, name, where="nginx.conf line 1"):
    # The error names only the position — never any text from the file.
    assert r == {"ok": False,
                 "error": f"template uses a directive the boombox doesn't allow ({where})"}
    assert name not in r["error"]


@pytest.mark.parametrize("site,name", [
    ("log_format x escape=none '\\n* * * * * root id';\nserver { listen 127.0.0.1:80; }\n", "log_format"),
    ("server { listen 127.0.0.1:80; access_log /etc/cron.d/x x; }\n", "access_log"),
    ("server { listen 127.0.0.1:80; error_log /etc/cron.d/x; }\n", "error_log"),
    ("load_module /tmp/evil.so;\nserver { listen 127.0.0.1:80; }\n", "load_module"),
    ('server { listen 127.0.0.1:80; "access_log" /etc/cron.d/x; }\n', "access_log"),
])
def test_site_rejects_file_writing_directives(box, site, name):
    _set(box, site=site)
    _denied(helper.action_nginx_sync({}), name)
    _untouched(box)


def test_snippet_rejects_file_writing_directives(box):
    _set(box, snippet="location /a/ {\n  access_log /etc/cron.d/x;\n}\n")
    _denied(helper.action_nginx_sync({}), "access_log", "nginx-boombox-common.conf line 2")
    _untouched(box)


def test_include_only_of_the_snippet_and_only_in_the_site(box):
    _set(box, site="server { listen 127.0.0.1:80; include /etc/nginx/snippets/other.conf; }\n")
    _denied(helper.action_nginx_sync({}), "include")
    _untouched(box)
    _set(box, site="server { listen 127.0.0.1:80; include /etc/nginx/snippets/boombox-common.conf; }\n",
         snippet="include /etc/nginx/snippets/boombox-common.conf;\n")
    _denied(helper.action_nginx_sync({}), "include", "nginx-boombox-common.conf line 1")
    _untouched(box)
    _set(box, snippet="location /api/ {}\n")
    assert helper.action_nginx_sync({})["ok"] is True
    assert "include /etc/nginx/snippets/boombox-common.conf;" in box["site"].read_text()


def test_hash_inside_quotes_is_not_a_comment(box):
    _set(box, site='server { listen 127.0.0.1:80; add_header X "a # b"; access_log /etc/cron.d/x; }\n')
    _denied(helper.action_nginx_sync({}), "access_log")
    _untouched(box)


def test_hash_mid_word_is_not_a_comment(box):
    # nginx only starts a comment at a token boundary: `/x#` is one word.
    _set(box, site="server { listen 127.0.0.1:80; root /x#; access_log /etc/cron.d/x; }\n")
    _denied(helper.action_nginx_sync({}), "access_log")
    _untouched(box)


def test_quote_mid_word_does_not_open_a_string(box):
    _set(box, site='server { listen 127.0.0.1:80; root a"; access_log /etc/cron.d/x; root b"; }\n')
    _denied(helper.action_nginx_sync({}), "access_log")
    _untouched(box)


def test_real_comment_is_ignored(box):
    _set(box, site="server { listen 127.0.0.1:80; # access_log /etc/cron.d/x;\n}\n")
    assert helper.action_nginx_sync({})["ok"] is True


@pytest.mark.parametrize("snippet", [
    "location /a/ {}\n}\nlog_format x 'y';\nserver {\n",   # breaks out of server{}
    "location /a/ {\n",                                    # never closed
    "server { listen 2; }\n",                              # server is site-only
])
def test_snippet_must_stay_inside_the_including_server(box, snippet):
    _set(box, snippet=snippet)
    r = helper.action_nginx_sync({})
    assert r["ok"] is False
    _untouched(box)


def test_site_must_be_brace_balanced(box):
    _set(box, site="server { listen 127.0.0.1:80;\n")
    assert helper.action_nginx_sync({})["ok"] is False
    _untouched(box)


def test_map_entries_must_be_key_value_pairs(box):
    _set(box, site="map $a $b { default x; access_log /etc/cron.d/x x; }\nserver { listen 127.0.0.1:80; }\n")
    assert helper.action_nginx_sync({})["ok"] is False
    _untouched(box)


@pytest.mark.parametrize("site", [
    "root:$6$secrethash:19000:0:99999:7:::\n",          # tokenizer error
    "secretword;\n",                                    # name-shaped first token
    "server { listen 127.0.0.1:80; secretword x; }\n",
    "server { secretword { } }\n",                      # misplaced block
    'server { listen 127.0.0.1:80; add_header X "secretword',     # unterminated string
])
def test_error_never_echoes_file_content(box, site):
    _set(box, site=site)
    r = helper.action_nginx_sync({})
    assert r["ok"] is False
    assert "secret" not in str(r)
    _untouched(box)


@pytest.mark.parametrize("entry", [
    "include /etc/shadow;",
    '"include" /etc/shadow;',
    "hostnames;",
    "volatile;",
    "a b c;",
])
def test_map_rejects_include_and_non_pair_entries(box, entry):
    _set(box, site=f"map $a $b {{ default x; {entry} }}\nserver {{ listen 127.0.0.1:80; }}\n")
    assert helper.action_nginx_sync({})["ok"] is False
    _untouched(box)


def test_map_default_and_empty_key_are_fine(box):
    _set(box, site="map $a $b {\n    default upgrade;\n    ''      close;\n}\n"
                   "server { listen 127.0.0.1:80; }\n")
    assert helper.action_nginx_sync({})["ok"] is True


@pytest.mark.parametrize("listen", [
    "listen unix:/etc/cron.d/x;",
    "listen unix:/tmp/sock default_server;",
    "listen 22;",
    "listen 80;",                                  # all interfaces on :80 — kiosk is loopback-only
    "listen 127.0.0.1:8091;",                                  # neither 80 nor the LAN port
    "listen 0.0.0.0:8091;",                        # address not used by the templates
    "listen 10.0.0.5:80;",
    "listen 127.0.0.1:80 ssl;",                            # flag not used by the templates
    "listen 127.0.0.1:80 default_server reuseport;",
    "listen [::1]:80 so_keepalive=on;",
    "listen [::1]:8091 backlog=1;",
    "listen;",
])
def test_listen_is_restricted_to_the_template_forms(box, listen):
    _set(box, site=f"server {{ {listen} }}\n")
    assert helper.action_nginx_sync({})["ok"] is False
    _untouched(box)


@pytest.mark.parametrize("listen", [
    "listen 127.0.0.1:80 default_server;",
    "listen [::1]:80 default_server;",
    "listen __REMOTE_WEB_PORT__ default_server;",
    "listen [::]:__REMOTE_WEB_PORT__ default_server;",
    "listen __REMOTE_WEB_PORT__;",
])
def test_listen_forms_the_templates_use_are_fine(box, listen):
    _set(box, site=f"server {{ {listen} }}\n")
    assert helper.action_nginx_sync({})["ok"] is True


def test_listen_is_site_only(box):
    _set(box, snippet="listen 127.0.0.1:80;\n")
    assert helper.action_nginx_sync({})["ok"] is False
    _untouched(box)


@pytest.mark.parametrize("which", ["nginx.conf", "nginx-boombox-common.conf"])
def test_symlinked_template_is_refused(box, tmp_path, which):
    rel = Path(helper.RELEASE_CONFIG_DIR)
    real = tmp_path / "elsewhere"
    real.write_text((rel / which).read_text())
    (rel / which).unlink()
    (rel / which).symlink_to(real)
    r = helper.action_nginx_sync({})
    assert r["ok"] is False and "regular file" in r["error"]
    _untouched(box)


def test_real_repo_templates_pass_the_allowlist():
    site = helper.render_site((REPO_CONFIG / "nginx.conf").read_text(), "8090")
    snippet = (REPO_CONFIG / "nginx-boombox-common.conf").read_text()
    helper.check_nginx_template(site, site=True, port="8090")
    helper.check_nginx_template(snippet, site=False, port="8090")
