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


def browse_dir(rel_path: str) -> dict:
    """Return the directory listing at MUSIC_ROOT / rel_path.

    Hidden entries are skipped EXCEPT the special ".usb" mount-link folder so
    USB drives are visible in the browser.
    """
    target = (MUSIC_ROOT / rel_path).resolve()
    if not under_root(target, MUSIC_ROOT) or not target.is_dir():
        return {"error": "not a directory"}

    rel = target.relative_to(MUSIC_ROOT.resolve())
    rel_str = "" if str(rel) == "." else str(rel)
    parent_str = "" if not rel_str else str(Path(rel_str).parent)
    if parent_str == ".":
        parent_str = ""

    dirs: list[dict] = []
    files: list[dict] = []
    try:
        for entry in target.iterdir():
            name = entry.name
            if name.startswith(".") and name != ".usb":
                continue
            try:
                if entry.is_dir():
                    # Track count is best-effort: we look one level deep so
                    # the UI can show "(12 tracks)" without recursion cost.
                    n_audio = sum(
                        1 for c in entry.iterdir()
                        if c.is_file() and c.suffix.lower() in ALLOWED_EXTS
                    ) if entry.is_dir() else 0
                    dirs.append({"name": name, "kind": "dir", "tracks": n_audio})
                elif entry.is_file() and entry.suffix.lower() in ALLOWED_EXTS:
                    st = entry.stat()
                    files.append({
                        "name": name,
                        "kind": "file",
                        "size": st.st_size,
                        "mtime": int(st.st_mtime),
                    })
            except (OSError, ValueError):
                continue
    except PermissionError:
        return {"error": "permission denied"}

    dirs.sort(key=lambda r: r["name"].lower())
    files.sort(key=lambda r: r["name"].lower())

    return {
        "path": rel_str,
        "parent": parent_str if rel_str else None,
        "entries": dirs + files,
    }


async def fetch_theme() -> dict:
    """Pull the active theme from boombox-state. Falls back to a sane dark
    default if the service is down."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get("http://127.0.0.1:6681/theme",
                             timeout=aiohttp.ClientTimeout(total=1.5)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception:
        pass
    return {
        "skinId": "default", "name": "Boombox",
        "theme": {
            "bg": "#0c0c0c", "panel": "#1a1830", "ink": "#f3f1ff", "ink2": "#9892b8",
            "accent": "#8b5cf6", "accent2": "#5be7ff", "rule": "rgba(255,255,255,0.08)",
            "font": "'Inter', system-ui, sans-serif",
            "mono": "'JetBrains Mono', ui-monospace, monospace",
        },
    }


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

INDEX_HTML_TEMPLATE = """\
<!doctype html>
<html lang=en>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Boombox · Drop</title>
<style>
  :root {{
    --bg:      {bg};
    --panel:   {panel};
    --ink:     {ink};
    --ink2:    {ink2};
    --accent:  {accent};
    --accent2: {accent2};
    --rule:    {rule};
    --font:    {font};
    --mono:    {mono};
    color-scheme: {color_scheme};
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    font: 16px/1.4 var(--font); background: var(--bg); color: var(--ink);
    margin: 0; padding: 0; min-height: 100vh;
  }}
  body {{ padding: 22px 18px 60px; max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 28px; letter-spacing: -0.01em; margin: 0 0 4px; font-weight: 800; }}
  .sub {{ color: var(--ink2); margin-bottom: 20px; }}
  .pill {{
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent); font-family: var(--mono);
    font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase;
    vertical-align: middle;
  }}

  .card {{
    background: var(--panel); border: 1px solid var(--rule);
    border-radius: 14px; padding: 18px; margin-bottom: 16px;
  }}

  label {{
    display: block; font-family: var(--mono);
    font-size: 11px; letter-spacing: 0.22em;
    text-transform: uppercase; color: var(--ink2); margin-bottom: 10px;
  }}

  input[type=text], input[type=password], .filter {{
    width: 100%; background: var(--bg); border: 1px solid var(--rule);
    color: var(--ink); font: 18px var(--font);
    padding: 12px 14px; border-radius: 10px;
    -webkit-appearance: none; appearance: none;
  }}
  input:focus, .filter:focus {{ outline: 2px solid var(--accent); }}

  button {{
    background: var(--accent); color: var(--bg);
    font: 600 14px/1 var(--font); letter-spacing: 0.04em;
    border: 0; padding: 12px 18px; border-radius: 10px; cursor: pointer;
    min-height: 44px;
  }}
  button:hover {{ filter: brightness(1.10); }}
  button[disabled] {{ opacity: 0.5; cursor: progress; }}
  .ghost {{
    background: transparent; color: var(--ink);
    border: 1px solid var(--rule);
  }}

  .drop {{
    border: 2px dashed color-mix(in srgb, var(--ink) 22%, transparent);
    border-radius: 12px; padding: 36px 18px; text-align: center;
    transition: background 0.15s, border-color 0.15s;
  }}
  .drop.over {{
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    border-color: var(--accent);
  }}
  .drop button {{ background: var(--accent2); }}

  .crumbs {{
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
    font-family: var(--mono); font-size: 13px;
    margin-bottom: 6px;
  }}
  .crumbs a {{
    color: var(--accent); cursor: pointer; text-decoration: none;
    padding: 4px 6px; border-radius: 6px;
  }}
  .crumbs a:hover {{ background: color-mix(in srgb, var(--accent) 12%, transparent); }}
  .crumbs .sep {{ color: var(--ink2); }}
  .crumbs .here {{ color: var(--ink); padding: 4px 6px; }}

  .row {{
    display: flex; align-items: center; gap: 10px;
    padding: 10px 8px; border-bottom: 1px solid var(--rule);
    cursor: default; min-height: 44px;
  }}
  .row.click {{ cursor: pointer; border-radius: 8px; }}
  .row.click:hover {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}
  .row .icon {{ flex: 0 0 24px; color: var(--ink2); font-family: var(--mono); }}
  .row.dir .icon {{ color: var(--accent); }}
  .row .name {{
    flex: 1; min-width: 0; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }}
  .row .meta {{ color: var(--ink2); font-family: var(--mono); font-size: 12px;
                font-variant-numeric: tabular-nums; }}
  .row .dl {{
    color: var(--accent2); text-decoration: none; font-family: var(--mono); font-size: 12px;
    padding: 6px 10px; border-radius: 6px;
  }}
  .row .dl:hover {{ background: color-mix(in srgb, var(--accent2) 14%, transparent); }}

  .err {{ color: #ff7878; margin-top: 8px; min-height: 1em; font-family: var(--mono); font-size: 13px; }}
  .ok  {{ color: var(--accent); margin-top: 8px; min-height: 1em; font-family: var(--mono); font-size: 13px; }}

  .progress {{ height: 4px; background: var(--rule); border-radius: 2px; margin-top: 8px; overflow: hidden; flex: 1 1 80px; }}
  .progress > div {{ height: 100%; width: 0%; background: var(--accent); transition: width 0.1s; }}

  .skin-tag {{
    display: inline-block; font-family: var(--mono); font-size: 10px;
    letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink2);
    margin-left: 8px;
  }}
</style>

<h1>Boombox <span class=skin-tag>{skin_name}</span></h1>
<div class="sub">Drop tracks onto the boombox, or grab anything from its library.</div>

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
  <div id=crumbs class=crumbs></div>
  <input class=filter id=lib-filter placeholder="filter this folder…">
  <div id=lib-list style="max-height: 56vh; overflow: auto; margin-top: 8px;"></div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let authed = false;
let cwd = "";        // current relative path inside MUSIC_ROOT
let entries = [];    // last browse() result
let filterText = "";

function show(authedNow) {{
  authed = authedNow;
  $('auth-card').hidden = authedNow;
  $('upload-card').hidden = !authedNow;
  $('lib-card').hidden = !authedNow;
}}

async function tryPin(p) {{
  const r = await fetch('upload', {{ method: 'POST', headers: {{ 'X-Boombox-Pin': p }}, body: new FormData() }});
  if (r.status === 401) return false;
  document.cookie = 'bbx_pin=' + p + '; max-age=43200; path=/; SameSite=Lax';
  return true;
}}

$('pin').addEventListener('input', async (e) => {{
  const v = e.target.value.replace(/\\D/g, '').slice(0, 4);
  e.target.value = v;
  if (v.length === 4) {{
    if (await tryPin(v)) {{ show(true); loadDir(""); }}
    else {{ $('auth-err').textContent = 'Wrong PIN.'; e.target.value = ''; }}
  }}
}});

const drop = $('drop');
['dragenter', 'dragover'].forEach(ev =>
  drop.addEventListener(ev, e => {{ e.preventDefault(); drop.classList.add('over'); }})
);
['dragleave', 'drop'].forEach(ev =>
  drop.addEventListener(ev, e => {{ e.preventDefault(); drop.classList.remove('over'); }})
);
drop.addEventListener('drop', e => upload([...e.dataTransfer.files]));
$('pick').addEventListener('click', () => $('picker').click());
$('picker').addEventListener('change', () => upload([...$('picker').files]));

async function upload(files) {{
  if (!files.length) return;
  $('upload-err').textContent = '';
  $('upload-ok').textContent = '';
  const list = $('upload-list');
  for (const f of files) {{
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<div class=name></div><div class=progress><div></div></div><div class=meta>—</div>`;
    row.querySelector('.name').textContent = f.name;
    list.appendChild(row);
    const bar = row.querySelector('.progress > div');
    const meta = row.querySelector('.meta');
    try {{
      await new Promise((resolve, reject) => {{
        const xhr = new XMLHttpRequest();
        xhr.open('POST', 'upload');
        xhr.upload.addEventListener('progress', e => {{
          if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100).toFixed(1) + '%';
        }});
        xhr.onload = () => xhr.status === 200 ? resolve() : reject(new Error(xhr.statusText || ('HTTP ' + xhr.status)));
        xhr.onerror = () => reject(new Error('network error'));
        const fd = new FormData(); fd.append('file', f);
        xhr.send(fd);
      }});
      bar.style.width = '100%';
      meta.textContent = '✓';
    }} catch (err) {{
      meta.textContent = '✗';
      $('upload-err').textContent = `${{f.name}}: ${{err.message}}`;
    }}
  }}
  $('upload-ok').textContent = 'Done — boombox is rescanning the library.';
  loadDir(cwd);
}}

async function loadDir(rel) {{
  const r = await fetch('browse?path=' + encodeURIComponent(rel || ''));
  if (!r.ok) return;
  const j = await r.json();
  if (j.error) {{ alert(j.error); return; }}
  cwd = j.path;
  entries = j.entries;
  filterText = "";
  $('lib-filter').value = "";
  renderCrumbs();
  renderEntries();
}}

function renderCrumbs() {{
  const c = $('crumbs');
  c.innerHTML = '';
  const root = document.createElement('a');
  root.textContent = '~';
  root.onclick = () => loadDir('');
  c.appendChild(root);
  if (cwd) {{
    const parts = cwd.split('/').filter(Boolean);
    let acc = '';
    for (let i = 0; i < parts.length; i++) {{
      acc = acc ? acc + '/' + parts[i] : parts[i];
      const sep = document.createElement('span'); sep.className = 'sep'; sep.textContent = '/';
      c.appendChild(sep);
      if (i === parts.length - 1) {{
        const here = document.createElement('span');
        here.className = 'here'; here.textContent = parts[i];
        c.appendChild(here);
      }} else {{
        const a = document.createElement('a'); a.textContent = parts[i];
        const target = acc; a.onclick = () => loadDir(target);
        c.appendChild(a);
      }}
    }}
  }}
}}

$('lib-filter').addEventListener('input', e => {{
  filterText = e.target.value.toLowerCase();
  renderEntries();
}});

function renderEntries() {{
  const list = $('lib-list');
  list.innerHTML = '';
  // Synthetic ".." row when not at root.
  if (cwd) {{
    const up = document.createElement('div');
    up.className = 'row click dir';
    up.innerHTML = '<div class=icon>↑</div><div class=name>..</div>';
    const parent = cwd.includes('/') ? cwd.slice(0, cwd.lastIndexOf('/')) : '';
    up.onclick = () => loadDir(parent);
    list.appendChild(up);
  }}

  const matched = entries.filter(e => !filterText || e.name.toLowerCase().includes(filterText));
  $('lib-count').textContent = `${{matched.filter(e=>e.kind==='file').length}} tracks`
    + (matched.filter(e=>e.kind==='dir').length ? ` · ${{matched.filter(e=>e.kind==='dir').length}} folders` : '');

  let shown = 0;
  for (const e of matched) {{
    if (++shown > 1000) break;
    const row = document.createElement('div');
    if (e.kind === 'dir') {{
      row.className = 'row click dir';
      row.innerHTML = `<div class=icon>▸</div><div class=name></div><div class=meta>${{e.tracks}} tracks</div>`;
      row.querySelector('.name').textContent = e.name;
      const target = cwd ? cwd + '/' + e.name : e.name;
      row.onclick = () => loadDir(target);
    }} else {{
      row.className = 'row';
      const sizeMB = (e.size / 1048576).toFixed(1) + ' MB';
      row.innerHTML = `<div class=icon>♪</div><div class=name></div><div class=meta>${{sizeMB}}</div><a class=dl></a>`;
      row.querySelector('.name').textContent = e.name;
      const a = row.querySelector('.dl');
      const dlPath = cwd ? cwd + '/' + e.name : e.name;
      a.href = 'download/' + encodeURI(dlPath);
      a.textContent = '⤓';
      a.title = 'download';
      a.setAttribute('download', '');
    }}
    list.appendChild(row);
  }}
}}

// Boot. If cookie is already set, browse will succeed.
(async () => {{
  const r = await fetch('browse?path=', {{ credentials: 'include' }});
  if (r.ok) {{ show(true); const j = await r.json(); cwd = j.path; entries = j.entries; renderCrumbs(); renderEntries(); }}
  else {{ show(false); }}
}})();
</script>
"""


def _is_light(hex_color: str) -> bool:
    """Naive luminance check on a #rrggbb so we set color-scheme correctly."""
    c = hex_color.lstrip("#")
    if len(c) != 6:
        return False
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) > 160


async def render_index() -> str:
    payload = await fetch_theme()
    t = payload.get("theme") or {}
    skin_name = payload.get("name") or "Boombox"
    bg = t.get("bg", "#0c0c0c")
    return INDEX_HTML_TEMPLATE.format(
        bg=bg,
        panel=t.get("panel", "#1a1830"),
        ink=t.get("ink", "#f3f1ff"),
        ink2=t.get("ink2", "#9892b8"),
        accent=t.get("accent", "#8b5cf6"),
        accent2=t.get("accent2", "#5be7ff"),
        rule=t.get("rule", "rgba(255,255,255,0.08)"),
        font=t.get("font", "'Inter', system-ui, sans-serif"),
        mono=t.get("mono", "'JetBrains Mono', ui-monospace, monospace"),
        color_scheme="light" if _is_light(bg) else "dark",
        skin_name=skin_name,
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def index(_request: web.Request) -> web.Response:
    html = await render_index()
    return web.Response(text=html, content_type="text/html",
                        headers={"Cache-Control": "no-store"})


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


async def browse_handler(request: web.Request) -> web.Response:
    if not request_authed(request):
        return web.json_response({"error": "pin required"}, status=401)
    rel = request.query.get("path", "") or ""
    rel = rel.strip("/").replace("\\", "/")
    result = browse_dir(rel)
    if "error" in result:
        return web.json_response(result, status=404)
    resp = web.json_response(result)
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
    app.router.add_get("/browse", browse_handler)
    # Keep /list around as a deprecated alias so any old browser session
    # that hasn't reloaded the page yet still authenticates correctly. It
    # routes to browse() at the root.
    app.router.add_get("/list", browse_handler)
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
