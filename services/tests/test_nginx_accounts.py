# services/tests/test_nginx_accounts.py
from pathlib import Path

CONF = (Path(__file__).resolve().parents[2] / "install" / "config"
        / "nginx-boombox-common.conf").read_text()


def _block(prefix: str) -> str:
    start = CONF.index(prefix)
    return CONF[start:CONF.index("}", start)]


def test_api_accounts_keeps_basic_auth_and_forwards_identity():
    b = _block("location /api/accounts/")
    assert "auth_basic off" not in b
    assert "proxy_set_header X-Boombox-User $remote_user;" in b
    assert "proxy_set_header X-Real-IP $remote_addr;" in b
    assert "proxy_set_header X-Boombox-Host $http_host;" in b
    assert "127.0.0.1:6689/api/accounts/" in b
    assert 'proxy_set_header Authorization "";' in b


def test_accounts_page_served_from_setup_build():
    b = _block("location ^~ /accounts/")
    assert "auth_basic off" not in b
    assert "root /opt/boombox/current/setup-ui/dist;" in b
    assert "try_files /accounts.html =404;" in b
    # `alias <file>` 500s on /accounts/ (index module runs on the file).
    assert "alias" not in b
