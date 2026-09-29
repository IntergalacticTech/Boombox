"""Static checks: kiosk vs LAN app server blocks, redirects, shared snippet."""
from __future__ import annotations

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "install" / "config"
SITE = (CONFIG / "nginx.conf").read_text()
SNIPPET = (CONFIG / "nginx-boombox-common.conf").read_text()


def _block_at(text: str, start: int) -> str:
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise ValueError("unbalanced braces")


def _servers() -> tuple[str, str]:
    starts = [m.start() for m in re.finditer(r"^server \{", SITE, re.M)]
    kiosk, lan = (_block_at(SITE, s) for s in starts)
    return kiosk, lan


def _location(block: str, header: str) -> str:
    return _block_at(block, block.index(header))


def test_kiosk_server_serves_kiosk_ui_at_root():
    kiosk, _ = _servers()
    assert "listen 127.0.0.1:80 default_server;" in kiosk
    assert "root /opt/boombox/current/ui/dist;" in kiosk
    assert "try_files $uri $uri/ /index.html;" in _location(kiosk, "location / {")
    assert "try_files $uri =404;" in _location(kiosk, r"location ~* \.(?:js|css")
    assert "include /etc/nginx/snippets/boombox-common.conf;" in kiosk
    assert "auth_basic" not in kiosk


def test_lan_server_serves_the_app_without_basic_auth():
    _, lan = _servers()
    assert "listen __REMOTE_WEB_PORT__ default_server;" in lan
    assert 'auth_basic "Boombox";' in lan              # everything else keeps it
    assert "root /opt/boombox/current/remote-ui/dist;" in lan
    root = _location(lan, "location / {")
    assert "auth_basic off;" in root and "try_files $uri $uri/ /index.html;" in root
    assert 'add_header Cache-Control "no-cache" always;' in root
    assets = _location(lan, "location ^~ /app-assets/ {")
    assert "auth_basic off;" in assets and "immutable" in assets
    assert "try_files $uri =404;" in assets
    assert "include /etc/nginx/snippets/boombox-common.conf;" in lan


def test_lan_redirects_old_urls_into_the_app():
    _, lan = _servers()
    for header in ("location = /remote {", "location ^~ /remote/ {"):
        loc = _location(lan, header)
        assert "auth_basic off;" in loc and "return 301 /?from=remote;" in loc
    for header in ("location = /accounts {", "location ^~ /accounts/ {"):
        loc = _location(lan, header)
        assert "auth_basic off;" in loc and "return 301 /#/accounts;" in loc


def test_old_pwa_service_worker_gets_kill_switch():
    _, lan = _servers()
    loc = _location(lan, "location = /remote/sw.js {")
    assert "auth_basic off;" in loc
    assert "try_files /legacy-remote-sw.js =404;" in loc
    assert 'add_header Cache-Control "no-cache" always;' in loc


def test_snippet_no_longer_owns_the_root_or_old_pages():
    assert not re.search(r"^root ", SNIPPET, re.M)
    assert "location / {" not in SNIPPET
    assert r"location ~* \.(?:js" not in SNIPPET
    assert "/remote/" not in re.sub(r"/api/remote/", "", SNIPPET)
    assert "location ^~ /accounts/" not in SNIPPET
    assert "accounts.html" not in SNIPPET


def test_api_accounts_relies_on_the_admin_session():
    b = _location(SNIPPET, "location /api/accounts/ {")
    assert "auth_basic off;" in b
    assert "proxy_pass http://127.0.0.1:6689/api/accounts/;" in b
    assert "proxy_set_header X-Real-IP $remote_addr;" in b
    assert "proxy_set_header X-Boombox-Host $http_host;" in b
    assert "X-Boombox-User" not in b
    assert "Authorization" not in b                    # the admin bearer token must pass


def test_other_lan_routes_keep_basic_auth():
    for header in ("location /api/ {", "location /mopidy/ {", "location /api/library/ {",
                   "location /api/update/ {", "location /api/buttons/ {"):
        assert "auth_basic off" not in _location(SNIPPET, header), header
    for header in ("location /api/remote/ {", "location /api/setup/ {",
                   "location ^~ /setup/ {", "location ^~ /local/ {"):
        assert "auth_basic off;" in _location(SNIPPET, header), header
