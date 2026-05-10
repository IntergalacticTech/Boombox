#!/usr/bin/env python3
"""Boombox uploader — LAN file drop with a PIN gate.

Disabled by default. The touchscreen Settings drawer toggles this service on
to expose a one-page web UI at http://<pi>/upload/ where guests can drop
audio files and download anything in the library.

PIN model: when the unit starts, generate a fresh 4-digit PIN, write it to
a runtime file the touchscreen can read. The PIN expires the moment the
service stops. The touchscreen displays it; the upload page asks for it.

Wire: 127.0.0.1:6683 (nginx forwards /upload/ → here).

Security posture: this is a LAN appliance. The PIN is a friction gate, not
a security boundary. Don't expose this service to the public internet.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import time
import urllib.parse
from pathlib import Path

from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-uploader")

PORT = int(os.environ.get("BOOMBOX_UPLOADER_PORT", "6683"))
HOME = Path(os.environ["HOME"])
MUSIC_ROOT = Path(os.environ.get("BOOMBOX_MUSIC_DIR", HOME / "Music"))
UPLOAD_DIR = MUSIC_ROOT / "uploads"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
PIN_FILE = RUNTIME_DIR / "boombox-uploader.pin"
SCAN_TRIGGER_URL = "http://127.0.0.1:6681/library/scan"

# Audio-ish file types we accept. Not exhaustive — the goal is to keep
# accidental .exe drops from filling the disk.
ALLOWED_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wav", ".aiff", ".alac", ".wma",
}
MAX_FILE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB cap per file
COOKIE_NAME = "bbx_pin"


# ---------------------------------------------------------------------------
# PIN management
# ---------------------------------------------------------------------------

def generate_pin() -> str:
    # 4 digits, not allowed to start with 0 (confusing to read off a screen)
    # so the user can type a 4-character number unambiguously.
    return f"{secrets.randbelow(9000) + 1000}"


def write_pin(pin: str) -> None:
    PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PIN_FILE.write_text(pin + "\n")
    PIN_FILE.chmod(0o600)


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    """Strip directory components, leave a sane filename."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = name.strip().lstrip(".")
    if not name:
        name = "untitled"
    return name


def unique_path(target: Path) -> Path:
    """Return target if free, else target with -1, -2... suffix before the ext."""
    if not target.exists():
        return target
    stem, ext = target.stem, target.suffix
    n = 1
    while True:
        cand = target.with_name(f"{stem}-{n}{ext}")
        if not cand.exists():
            return cand
        n += 1


def under_root(p: Path, root: Path) -> bool:
    """True iff p resolves to somewhere inside root. Defends against ../ tricks."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def list_library() -> list[dict]:
    """Return a flat list of audio files in MUSIC_ROOT, with relative paths.

    Follows symlinks so USB-mounted drives (linked under .usb/) appear.
    """
    out: list[dict] = []
    for p in MUSIC_ROOT.rglob("*"):
        try:
            if not p.is_file():
                continue
            if p.suffix.lower() not in ALLOWED_EXTS:
                continue
            rel = p.relative_to(MUSIC_ROOT)
            st = p.stat()
            out.append({
                "path": str(rel),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
        except (OSError, ValueError):
            continue
    out.sort(key=lambda r: r["path"].lower())
    return out


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

PIN: str = ""  # set in main()


def request_authed(req: web.Request) -> bool:
    cookie_pin = req.cookies.get(COOKIE_NAME, "")
    if cookie_pin and secrets.compare_digest(cookie_pin, PIN):
        return True
    header_pin = req.headers.get("X-Boombox-Pin", "")
    if header_pin and secrets.compare_digest(header_pin, PIN):
        return True
    return False


def set_pin_cookie(resp: web.Response) -> None:
    resp.set_cookie(COOKIE_NAME, PIN, max_age=60 * 60 * 12, httponly=True, samesite="Lax")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

INDEX_HTML = """\
<!doctype html>
<html lang=en>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Boombox · Drop</title>
<style>
  :root { color-scheme: dark; }
  body { font: 16px/1.4 -apple-system, system-ui, sans-serif; background: #0c0c0c;
         color: #f3f1ff; margin: 0; padding: 24px; min-height: 100vh; box-sizing: border-box; }
  h1 { font-size: 28px; letter-spacing: -0.01em; margin: 0 0 4px; }
  .sub { color: #9892b8; margin-bottom: 24px; }
  .card { background: #1a1830; border: 1px solid rgba(255,255,255,0.08);
          border-radius: 14px; padding: 20px; margin-bottom: 20px; }
  label { display: block; font-size: 12px; letter-spacing: 0.2em;
          text-transform: uppercase; color: #9892b8; margin-bottom: 8px; }
  input[type=text], input[type=password] {
    width: 100%; box-sizing: border-box; background: #100d1c; border: 1px solid rgba(255,255,255,0.16);
    color: #f3f1ff; font-size: 18px; padding: 12px 14px; border-radius: 10px;
    -webkit-appearance: none; appearance: none;
  }
  input[type=text]:focus, input[type=password]:focus { outline: 2px solid #5be7ff; }
  button {
    background: #8b5cf6; color: #fff; font-size: 16px; font-weight: 600;
    border: 0; padding: 12px 22px; border-radius: 10px; cursor: pointer;
  }
  button:hover { background: #a78bfa; }
  button[disabled] { opacity: 0.5; cursor: progress; }
  .drop {
    border: 2px dashed rgba(255,255,255,0.2); border-radius: 12px; padding: 40px;
    text-align: center; transition: background 0.15s, border-color 0.15s;
  }
  .drop.over { background: rgba(139,92,246,0.12); border-color: #8b5cf6; }
  .file-row { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
  .file-row:last-child { border-bottom: 0; }
  .file-row .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .file-row .size { color: #9892b8; font-variant-numeric: tabular-nums; }
  .file-row a { color: #5be7ff; text-decoration: none; }
  .file-row a:hover { text-decoration: underline; }
  .filter { width: 100%; box-sizing: border-box; background: transparent; border: 0;
            border-bottom: 1px solid rgba(255,255,255,0.16); padding: 8px 0; color: #f3f1ff; font-size: 16px; }
  .pill { display: inline-block; padding: 2px 10px; border-radius: 999px;
          background: rgba(91,231,255,0.12); color: #5be7ff; font-size: 12px; letter-spacing: 0.18em;
          text-transform: uppercase; }
  .err { color: #ff7878; margin-top: 8px; min-height: 1em; }
  .ok  { color: #7afcb0; margin-top: 8px; min-height: 1em; }
  .progress { height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; margin-top: 8px; overflow: hidden; }
  .progress > div { height: 100%; width: 0%; background: #8b5cf6; transition: width 0.1s; }
</style>

<h1>Boombox · Drop</h1>
<div class="sub">Upload tracks to the boombox, or grab files off it.</div>

<div id="auth-card" class=card hidden>
  <label for=pin>4-digit PIN (shown on the touchscreen)</label>
  <input id=pin type=password inputmode=numeric autocomplete=one-time-code maxlength=4 placeholder="••••">
  <div class=err id=auth-err></div>
</div>

<div id=upload-card class=card hidden>
  <label>Upload</label>
  <div id=drop class=drop>
    <div>Drop audio files here, or <button type=button id=pick>choose files</button></div>
    <input id=picker type=file accept="audio/*,.flac,.opus,.alac" multiple hidden>
  </div>
  <div id=upload-list></div>
  <div class=ok  id=upload-ok></div>
  <div class=err id=upload-err></div>
</div>

<div id=lib-card class=card hidden>
  <label>Library <span id=lib-count class=pill>—</span></label>
  <input class=filter id=lib-filter placeholder="filter…">
  <div id=lib-list style="max-height: 50vh; overflow: auto; margin-top: 8px;"></div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let authed = false;
let library = [];

function show(authedNow) {
  authed = authedNow;
  $('auth-card').hidden = authedNow;
  $('upload-card').hidden = !authedNow;
  $('lib-card').hidden = !authedNow;
}

async function tryPin(p) {
  const r = await fetch('upload', { method: 'POST', headers: { 'X-Boombox-Pin': p }, body: new FormData() });
  // Empty body returns 400 ("no files"), but also confirms PIN. Anything other
  // than 401 means the PIN was accepted.
  if (r.status === 401) return false;
  document.cookie = 'bbx_pin=' + p + '; max-age=43200; path=/; SameSite=Lax';
  return true;
}

$('pin').addEventListener('input', async (e) => {
  const v = e.target.value.replace(/\\D/g, '').slice(0, 4);
  e.target.value = v;
  if (v.length === 4) {
    if (await tryPin(v)) {
      show(true);
      loadLibrary();
    } else {
      $('auth-err').textContent = 'Wrong PIN.';
      e.target.value = '';
    }
  }
});

const drop = $('drop');
['dragenter', 'dragover'].forEach(ev =>
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); })
);
['dragleave', 'drop'].forEach(ev =>
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); })
);
drop.addEventListener('drop', e => upload([...e.dataTransfer.files]));
$('pick').addEventListener('click', () => $('picker').click());
$('picker').addEventListener('change', () => upload([...$('picker').files]));

async function upload(files) {
  if (!files.length) return;
  $('upload-err').textContent = '';
  $('upload-ok').textContent = '';
  const list = $('upload-list');
  for (const f of files) {
    const row = document.createElement('div');
    row.className = 'file-row';
    row.innerHTML = `<div class=name></div><div class=size>—</div><div class=progress><div></div></div>`;
    row.querySelector('.name').textContent = f.name;
    list.appendChild(row);
    const bar = row.querySelector('.progress > div');
    try {
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', 'upload');
        xhr.upload.addEventListener('progress', e => {
          if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100).toFixed(1) + '%';
        });
        xhr.onload = () => xhr.status === 200 ? resolve() : reject(new Error(xhr.statusText || ('HTTP ' + xhr.status)));
        xhr.onerror = () => reject(new Error('network error'));
        const fd = new FormData(); fd.append('file', f);
        xhr.send(fd);
      });
      bar.style.width = '100%';
      row.querySelector('.size').textContent = '✓';
    } catch (err) {
      row.querySelector('.size').textContent = '✗';
      $('upload-err').textContent = `${f.name}: ${err.message}`;
    }
  }
  $('upload-ok').textContent = 'Done — boombox is rescanning the library.';
  loadLibrary();
}

async function loadLibrary() {
  const r = await fetch('list');
  if (!r.ok) return;
  library = await r.json();
  $('lib-count').textContent = library.length + ' files';
  renderLibrary('');
}
$('lib-filter').addEventListener('input', e => renderLibrary(e.target.value.toLowerCase()));

function renderLibrary(filter) {
  const list = $('lib-list');
  list.innerHTML = '';
  let shown = 0;
  for (const f of library) {
    if (filter && !f.path.toLowerCase().includes(filter)) continue;
    if (++shown > 500) break;
    const row = document.createElement('div');
    row.className = 'file-row';
    const sizeMB = (f.size / 1048576).toFixed(1) + ' MB';
    row.innerHTML = `<div class=name></div><div class=size>${sizeMB}</div><a></a>`;
    row.querySelector('.name').textContent = f.path;
    const a = row.querySelector('a');
    a.href = 'download/' + encodeURI(f.path);
    a.textContent = 'download';
    a.setAttribute('download', '');
    list.appendChild(row);
  }
}

// Boot.
(async () => {
  // If the cookie is already set, the first /list call succeeds — skip the PIN.
  const r = await fetch('list', { credentials: 'include' });
  if (r.ok) { show(true); library = await r.json(); $('lib-count').textContent = library.length + ' files'; renderLibrary(''); }
  else { show(false); }
})();
</script>
"""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def index(_request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def upload_handler(request: web.Request) -> web.Response:
    if not request_authed(request):
        return web.json_response({"error": "pin required"}, status=401)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    reader = await request.multipart()
    async for part in reader:
        if part.name != "file" or not part.filename:
            continue
        name = safe_filename(part.filename)
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            return web.json_response({"error": f"unsupported type: {ext}"}, status=400)

        target = unique_path(UPLOAD_DIR / name)
        if not under_root(target, MUSIC_ROOT):
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
                    return web.json_response({"error": "file too large"}, status=413)
                f.write(chunk)
        log.info("uploaded %s (%d bytes)", target, size)
        saved.append(str(target.relative_to(MUSIC_ROOT)))

    # Best-effort: ask boombox-state to kick a Mopidy library scan. We don't
    # block the response on it — the user gets their 200 and the library
    # refresh happens in the background.
    if saved:
        asyncio.create_task(_trigger_scan())

    if not saved:
        # Empty upload (the UI uses this as a PIN-probe). Still return 200 so
        # the UI knows the PIN was accepted.
        resp = web.json_response({"saved": []})
    else:
        resp = web.json_response({"saved": saved})
    set_pin_cookie(resp)
    return resp


async def _trigger_scan() -> None:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(SCAN_TRIGGER_URL, timeout=aiohttp.ClientTimeout(total=2))
    except Exception as e:
        log.debug("scan trigger failed (boombox-state down?): %s", e)


async def list_handler(request: web.Request) -> web.Response:
    if not request_authed(request):
        return web.json_response({"error": "pin required"}, status=401)
    files = list_library()
    resp = web.json_response(files)
    set_pin_cookie(resp)
    return resp


async def download_handler(request: web.Request) -> web.StreamResponse:
    if not request_authed(request):
        return web.json_response({"error": "pin required"}, status=401)
    rel = request.match_info.get("path", "")
    rel = urllib.parse.unquote(rel)
    target = (MUSIC_ROOT / rel).resolve()
    if not under_root(target, MUSIC_ROOT) or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(target)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "pin_present": bool(PIN)})


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def make_app() -> web.Application:
    app = web.Application(client_max_size=MAX_FILE_BYTES + 1024)
    app.router.add_get("/", index)
    app.router.add_post("/upload", upload_handler)
    app.router.add_get("/list", list_handler)
    app.router.add_get("/download/{path:.+}", download_handler)
    app.router.add_get("/health", health)
    return app


async def main() -> None:
    global PIN
    PIN = generate_pin()
    write_pin(PIN)
    log.info("PIN: %s (written to %s)", PIN, PIN_FILE)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    log.info("listening on http://127.0.0.1:%d/", PORT)

    started_at = time.time()
    while True:
        await asyncio.sleep(60)
        log.debug("alive for %.0fs", time.time() - started_at)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Clear the PIN file on stop so consumers can tell the service is down.
        try:
            PIN_FILE.unlink(missing_ok=True)
        except Exception:
            pass
