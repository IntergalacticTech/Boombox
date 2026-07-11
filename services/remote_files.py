"""File surface for boombox-remote — browse / download / upload / delete.

Migrated from the retired boombox-uploader. The path-safety helpers are
unchanged from that service (security-reviewed); only the auth model
changed — these routes sit behind boombox-remote's bearer-token middleware
instead of the old PIN cookie.
"""
from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from pathlib import Path

from aiohttp import web
from jellyfin_env import jellyfin_base, jellyfin_token

log = logging.getLogger("boombox-remote")

HOME = Path(os.environ.get("HOME", str(Path.home())))


def _music_root() -> Path:
    return Path(os.environ.get("BOOMBOX_MUSIC_DIR", str(HOME / "Music")))


def _video_root() -> Path:
    return Path(os.environ.get("BOOMBOX_VIDEO_DIR", str(HOME / "Videos")))


AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wav", ".aiff", ".alac", ".wma",
}
VIDEO_EXTS = {
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".wmv",
    ".mpg", ".mpeg", ".ts", ".3gp",
}
ALLOWED_EXTS = AUDIO_EXTS | VIDEO_EXTS
MAX_FILE_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB cap per file (movies)
# Enforced in-handler during the streaming upload loop (see upload()).
# request.multipart() does NOT consult aiohttp's client_max_size, so the
# size limit lives here, not on the web.Application.
SCAN_TRIGGER_URL = "http://127.0.0.1:6681/library/scan"


def safe_filename(name: str) -> str:
    """Strip directory components, leave a sane filename."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = name.strip().lstrip(".")
    return name or "untitled"


def unique_path(target: Path) -> Path:
    """Return target if free, else target with -1, -2... before the ext."""
    if not target.exists():
        return target
    stem, ext = target.stem, target.suffix
    n = 1
    while True:
        cand = target.with_name(f"{stem}-{n}{ext}")
        if not cand.exists():
            return cand
        n += 1


def safe_compose(root: Path, rel_path: str) -> Path | None:
    """Compose root / rel_path, rejecting '..' segments or absolute paths.

    Deliberately does NOT call .resolve() — there are intentional symlinks
    under MUSIC_ROOT/.usb/ pointing at mounted USB drives; symlink targets
    are root-trusted. Returns None if the path is unsafe.
    """
    parts: list[str] = []
    for seg in rel_path.replace("\\", "/").split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            return None
        if "/" in seg or seg.startswith("/"):
            return None
        parts.append(seg)
    return root.joinpath(*parts) if parts else root


def under_root(p: Path, root: Path) -> bool:
    """True iff p resolves to somewhere inside root. Used for upload/delete
    targets, where we DO want resolve() to catch symlink tricks."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _count_audio_recursive(d: Path, limit: int = 5000) -> int:
    """Count audio files under d, capped so a multi-thousand-file drive
    doesn't make the listing slow."""
    n = 0
    try:
        for p in d.rglob("*"):
            try:
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                    n += 1
                    if n >= limit:
                        return n
            except OSError:
                continue
    except OSError:
        pass
    return n


def browse_dir(rel_path: str) -> dict:
    """Directory listing at MUSIC_ROOT / rel_path. Hidden entries skipped
    except the special '.usb' mount-link folder."""
    root = _music_root()
    target = safe_compose(root, rel_path)
    if target is None or not target.is_dir():
        return {"error": "not a directory"}
    rel_parts = [s for s in rel_path.replace("\\", "/").split("/")
                 if s and s != "."]
    rel_str = "/".join(rel_parts)
    parent_str = "/".join(rel_parts[:-1])
    dirs: list[dict] = []
    files: list[dict] = []
    try:
        for entry in target.iterdir():
            name = entry.name
            if name.startswith(".") and name != ".usb":
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": name, "kind": "dir",
                                 "tracks": _count_audio_recursive(entry)})
                elif entry.is_file() and entry.suffix.lower() in AUDIO_EXTS:
                    st = entry.stat()
                    files.append({
                        "name": name, "kind": "file", "size": st.st_size,
                        "mtime": int(st.st_mtime),
                        "deletable": under_root(entry, root),
                    })
            except (OSError, ValueError):
                continue
    except PermissionError:
        return {"error": "permission denied"}
    dirs.sort(key=lambda r: r["name"].lower())
    files.sort(key=lambda r: r["name"].lower())
    return {"path": rel_str, "parent": parent_str if rel_str else None,
            "entries": dirs + files}


async def _trigger_scan() -> None:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(SCAN_TRIGGER_URL,
                         timeout=aiohttp.ClientTimeout(total=2))
    except Exception as e:
        log.debug("scan trigger failed: %s", e)


async def _trigger_jellyfin_scan() -> None:
    # Refreshes whichever Jellyfin BOOMBOX_JELLYFIN_BASE points at (local or
    # remote). When Jellyfin is remote, this only surfaces the new file if the
    # server can see it — i.e. the upload dir is a share/mount the server also
    # reads. See docs/HOME-SERVERS.md for the video-storage models.
    token = jellyfin_token()
    if not token:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(f"{jellyfin_base()}/Library/Refresh",
                         headers={"X-MediaBrowser-Token": token},
                         timeout=aiohttp.ClientTimeout(total=3))
    except Exception as e:
        log.debug("jellyfin scan trigger failed: %s", e)


# ---- handlers (bearer-token gated by boombox-remote's middleware) --------

async def browse(request: web.Request) -> web.Response:
    rel = (request.query.get("path", "") or "").strip("/").replace("\\", "/")
    result = browse_dir(rel)
    if "error" in result:
        return web.json_response(result, status=404)
    return web.json_response(result)


async def download(request: web.Request) -> web.StreamResponse:
    rel = urllib.parse.unquote(request.match_info.get("path", ""))
    target = safe_compose(_music_root(), rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(target)


async def upload(request: web.Request) -> web.Response:
    music_uploads = _music_root() / "uploads"
    video_uploads = _video_root() / "uploads"
    music_uploads.mkdir(parents=True, exist_ok=True)
    video_uploads.mkdir(parents=True, exist_ok=True)
    saved_audio: list[str] = []
    saved_video: list[str] = []
    reader = await request.multipart()
    async for part in reader:
        if part.name != "file" or not part.filename:
            continue
        name = safe_filename(part.filename)
        ext = Path(name).suffix.lower()
        if ext in AUDIO_EXTS:
            dest_dir, dest_root, bucket = (music_uploads, _music_root(),
                                           saved_audio)
        elif ext in VIDEO_EXTS:
            dest_dir, dest_root, bucket = (video_uploads, _video_root(),
                                           saved_video)
        else:
            return web.json_response(
                {"error": f"unsupported type: {ext}"}, status=400)
        target = unique_path(dest_dir / name)
        if not under_root(target, dest_root):
            return web.json_response({"error": "bad path"}, status=400)
        size = 0
        with open(target, "wb") as f:
            while True:
                chunk = await part.read_chunk(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    f.close()
                    target.unlink(missing_ok=True)
                    return web.json_response(
                        {"error": "file too large"}, status=413)
                f.write(chunk)
        log.info("uploaded %s (%d bytes)", target, size)
        bucket.append(str(target.relative_to(dest_root)))
    if saved_audio:
        asyncio.create_task(_trigger_scan())
    if saved_video:
        asyncio.create_task(_trigger_jellyfin_scan())
    return web.json_response({"saved": saved_audio + saved_video})


async def delete(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    rel = str(body.get("path", "") or "").strip("/").replace("\\", "/")
    root = _music_root()
    target = safe_compose(root, rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    if not under_root(target, root):
        return web.json_response(
            {"error": "USB and symlinked files are read-only"}, status=403)
    if target.suffix.lower() not in ALLOWED_EXTS:
        return web.json_response({"error": "unsupported file type"},
                                 status=400)
    try:
        target.unlink()
    except OSError as e:
        return web.json_response({"error": str(e)}, status=500)
    asyncio.create_task(_trigger_scan())
    return web.json_response({"deleted": rel})


def add_routes(app: web.Application) -> None:
    """Register /api/remote/files/* on the given app."""
    app.router.add_get("/api/remote/files/browse", browse)
    app.router.add_get("/api/remote/files/download/{path:.+}", download)
    app.router.add_post("/api/remote/files/upload", upload)
    app.router.add_post("/api/remote/files/delete", delete)
