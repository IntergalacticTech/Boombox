"""Which apply-release.sh runs each install step.

build/preflight/swap run the TARGET release's script
(<root>/releases/<ref>/install/apply-release.sh) once fetch has put it
on disk, so a release's fixes to those steps (e.g. building setup-ui,
`npm ci`) take effect on the very update that ships them rather than one
release later. Everything else — fetch, restart, verify, revert,
cleanup, prune — runs `current`'s script (after swap, current IS the
target).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .version import valid_ref

SCRIPT_RELPATH = Path("install") / "apply-release.sh"


def target_apply_script(root: Path, ref: str) -> Optional[Path]:
    """The fetched release's apply-release.sh, or None to fall back.

    Only returned when `ref` is a valid release id and the script resolves
    (symlinks followed) to an executable regular file inside the releases
    tree — a symlinked release dir or script can't point it elsewhere.
    """
    if not valid_ref(ref):
        return None
    try:
        releases = (root / "releases").resolve(strict=True)
        script = (root / "releases" / ref / SCRIPT_RELPATH).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not script.is_relative_to(releases / ref):
        return None
    if not script.is_file() or not os.access(script, os.X_OK):
        return None
    return script
