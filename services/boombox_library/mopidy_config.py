"""Writes the [subsonic] block into mopidy.conf so Mopidy-Subsonic can
stream from Navidrome. The service rewrites this block whenever the user
saves new source credentials in Settings, then signals Mopidy to reload.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger("boombox-library.mopidy_config")

_SUBSONIC_BLOCK_RE = re.compile(
    r"^\[subsonic\][^\n]*\n(?:(?!^\[).*\n?)*",
    re.MULTILINE,
)
_BLOCK = """\
[subsonic]
hostname = {hostname}
port = {port}
username = {username}
password = {password}
ssl = {ssl}
context = rest
"""


def _split_url(url: str) -> tuple[str, int, bool]:
    """Parse a base URL into (hostname, port, ssl). Defaults port to 4533
    (Navidrome) for plain HTTP if absent, 443 for HTTPS."""
    from urllib.parse import urlparse
    p = urlparse(url)
    ssl = p.scheme == "https"
    host = p.hostname or ""
    port = p.port or (443 if ssl else 4533)
    return host, port, ssl


def write_subsonic_block(
    path: Path,
    url: str,
    username: str,
    password: str,
) -> None:
    """Idempotently write the [subsonic] block in mopidy.conf. Preserves
    all other sections and any comments. Atomic via .tmp + rename + fsync.
    Sets 0o600 on the tmp file before rename so a fresh-create doesn't
    leak the plaintext Subsonic password to world-readable mode."""
    host, port, ssl = _split_url(url)
    new_block = _BLOCK.format(
        hostname=host, port=port, username=username,
        password=password, ssl="true" if ssl else "false",
    )

    if path.exists():
        current = path.read_text()
        replaced, n = _SUBSONIC_BLOCK_RE.subn(new_block + "\n", current, count=1)
        if n == 0:
            # Append; ensure exactly one trailing newline between sections.
            replaced = current.rstrip() + "\n\n" + new_block
    else:
        replaced = new_block

    tmp = path.with_suffix(path.suffix + ".tmp")
    # Open with explicit 0o600 so a fresh-create doesn't expose the
    # plaintext Subsonic password to a world-readable umask default.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(replaced)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def reload_mopidy() -> bool:
    """Trigger Mopidy to reload its config. Returns True on success."""
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", "mopidy"],
            check=True, capture_output=True, timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("mopidy reload failed: %s", e)
        return False
