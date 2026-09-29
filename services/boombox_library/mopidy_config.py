"""Keeps /etc/mopidy/mopidy.conf free of a [subsonic] section.

Historical: this module used to write a [subsonic] block (Navidrome
hostname/username and the PLAINTEXT password) for Mopidy-Subsonic. That
plugin is Python-2 bit-rotten and is not installed, so the block did
nothing except leave a credential lying in mopidy.conf. Streaming now goes
through Mopidy's built-in stream backend against boombox-library's local
stream proxy (stream_proxy.py), which adds auth server-side — Mopidy needs
no source config at all.

Saving the library source now REMOVES any existing [subsonic] section
(scrubbing the password from installs that were configured before this
change) and never writes one.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger("boombox-library.mopidy_config")

# A [subsonic] header at line start plus every following line up to (not
# including) the next line-start [section] header. Values containing '['
# and comments mentioning "[subsonic]" don't match the header anchor.
_SUBSONIC_BLOCK_RE = re.compile(
    r"^\[subsonic\][^\n]*\n(?:(?!^\[).*\n?)*",
    re.MULTILINE,
)


def remove_subsonic_block(path: Path) -> bool:
    """Idempotently strip every [subsonic] section from mopidy.conf,
    preserving all other sections and comments. Atomic via .tmp + fsync +
    rename; the tmp file is created 0o600 like the original install.

    Returns True when the file was rewritten, False when there was nothing
    to remove (including when the file doesn't exist — never creates it).
    """
    if not path.exists():
        return False
    current = path.read_text()
    stripped, n = _SUBSONIC_BLOCK_RE.subn("", current)
    if n == 0:
        return False
    # Drop the blank-line run the removal can leave behind (and any
    # trailing whitespace if [subsonic] was the last section).
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).rstrip() + "\n"

    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(stripped)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    log.info("removed %d stale [subsonic] section(s) from %s", n, path)
    return True


def write_subsonic_block(
    path: Path,
    url: str = "",
    username: str = "",
    password: str = "",
) -> None:
    """Back-compat shim for callers that still "write" the Subsonic block
    on save: the credentials are deliberately ignored and any existing
    [subsonic] section is removed instead. Prefer remove_subsonic_block."""
    remove_subsonic_block(path)


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
