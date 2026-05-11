#!/usr/bin/env python3
"""Boombox uploader — PIN-gated LAN remote and file drop.

Disabled by default. The touchscreen Settings drawer toggles this service on
to expose a one-page web UI at http://<pi>/upload/ where guests can control
playback, make playlists, drop audio files, and download library content.

PIN model: when the unit starts, generate a fresh 4-digit PIN, write it to
a runtime file the touchscreen can read. The PIN expires the moment the
service stops. The touchscreen displays it; the remote page asks for it.

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
VIDEO_ROOT = Path(os.environ.get("BOOMBOX_VIDEO_DIR", HOME / "Videos"))
MUSIC_UPLOAD_DIR = MUSIC_ROOT / "uploads"
VIDEO_UPLOAD_DIR = VIDEO_ROOT / "uploads"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
PIN_FILE = RUNTIME_DIR / "boombox-uploader.pin"
SCAN_TRIGGER_URL = "http://127.0.0.1:6681/library/scan"
JELLYFIN_KEY_FILE = Path(os.environ.get("BOOMBOX_JELLYFIN_KEY", "/etc/boombox/jellyfin-api-key"))

# File types we accept. Audio lands in ~/Music/uploads (Mopidy scans).
# Video lands in ~/Videos/uploads (Jellyfin scans). Anything else: 400.
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


def safe_compose(root: Path, rel_path: str) -> Path | None:
    """Compose root / rel_path, rejecting any '..' segments or absolute paths.

    We deliberately do NOT call .resolve() — that would follow symlinks, and
    we have intentional symlinks under MUSIC_ROOT/.usb/ pointing at mounted
    USB drives outside the music root. Symlink targets are root-trusted
    (only the udev-driven mount script creates them).

    Returns None if the path is unsafe.
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
    """True iff p resolves to somewhere inside root. Used only for upload
    targets, where we *do* want resolve() to catch tricks — uploads must
    land in MUSIC_ROOT/uploads, not anywhere a symlink could redirect."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _count_audio_recursive(d: Path, limit: int = 5000) -> int:
    """Count audio files under d, capped so a multi-thousand-file drive
    doesn't make the directory listing slow. Returns the count, possibly
    truncated at limit."""
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
    """Return the directory listing at MUSIC_ROOT / rel_path.

    Hidden entries are skipped EXCEPT the special ".usb" mount-link folder so
    USB drives are visible in the browser.
    """
    target = safe_compose(MUSIC_ROOT, rel_path)
    if target is None or not target.is_dir():
        return {"error": "not a directory"}

    # Display path stays in posix form, relative to MUSIC_ROOT.
    rel_parts = [s for s in rel_path.replace("\\", "/").split("/") if s and s != "."]
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
                    # Track count walks the whole subtree (capped at 5000)
                    # so album-folder drives don't show "0 tracks".
                    n_audio = _count_audio_recursive(entry)
                    dirs.append({"name": name, "kind": "dir", "tracks": n_audio})
                elif entry.is_file() and entry.suffix.lower() in AUDIO_EXTS:
                    st = entry.stat()
                    files.append({
                        "name": name,
                        "kind": "file",
                        "size": st.st_size,
                        "mtime": int(st.st_mtime),
                        "deletable": under_root(entry, MUSIC_ROOT),
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
  h1 {{ font-size: 28px; letter-spacing: 0; margin: 0 0 4px; font-weight: 800; }}
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

  .remote-grid {{
    display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(220px, 0.75fr);
    gap: 14px;
  }}
  @media (max-width: 720px) {{
    .remote-grid {{ grid-template-columns: 1fr; }}
  }}
  .now-title {{
    font-size: clamp(26px, 7vw, 54px); line-height: 0.98;
    font-weight: 850; letter-spacing: 0;
    overflow-wrap: anywhere;
  }}
  .now-sub {{ color: var(--ink2); margin-top: 8px; font-size: 15px; }}
  .button-row {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .transport {{
    min-width: 48px; height: 48px; padding: 0 16px; border-radius: 999px;
    display: inline-flex; align-items: center; justify-content: center;
  }}
  .transport.primary {{ min-width: 64px; background: var(--accent2); }}
  .remote-pill {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 10px; border: 1px solid var(--rule); border-radius: 999px;
    color: var(--ink2); font-family: var(--mono); font-size: 11px;
    letter-spacing: 0.12em; text-transform: uppercase;
  }}
  .dot {{
    width: 9px; height: 9px; border-radius: 99px; background: var(--accent);
    box-shadow: 0 0 10px color-mix(in srgb, var(--accent) 60%, transparent);
  }}
  .range {{
    width: 100%; accent-color: var(--accent); min-height: 42px;
  }}
  .split {{
    display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 0.95fr);
    gap: 14px;
  }}
  @media (max-width: 760px) {{
    .split {{ grid-template-columns: 1fr; }}
  }}
  .mini-list {{
    border: 1px solid var(--rule); border-radius: 12px;
    overflow: hidden; background: color-mix(in srgb, var(--panel) 76%, var(--bg));
  }}
  .mini-list .row {{
    display: grid; grid-template-columns: 24px minmax(0, 1fr) minmax(80px, 0.8fr) auto;
  }}
  .mini-list .row .name, .mini-list .row .meta {{
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .mini-list-scroll {{ max-height: 310px; overflow: auto; }}
  .mini-empty {{
    padding: 18px; color: var(--ink2); font-family: var(--mono);
    font-size: 12px; letter-spacing: 0.05em;
  }}
  .row button.inline {{
    min-height: 34px; padding: 8px 10px; border-radius: 8px;
    font-size: 12px; flex-shrink: 0;
  }}
  .row button.danger {{
    background: transparent; color: #ff9a9a; border: 1px solid rgba(255,120,120,0.30);
  }}
</style>

<h1>Boombox <span class=skin-tag>{skin_name}</span></h1>
<div class="sub">Control playback, build playlists, drop tracks, or grab anything from its library.</div>

<div id="auth-card" class=card hidden>
  <label for=pin>4-digit PIN (shown on the touchscreen)</label>
  <input id=pin type=password inputmode=numeric autocomplete=one-time-code maxlength=4 placeholder="••••">
  <div class=err id=auth-err></div>
</div>

<div id=remote-card class=card hidden>
  <div style="display:flex;align-items:center;gap:10px;justify-content:space-between;margin-bottom:14px;">
    <label style="margin:0;">Remote</label>
    <span class=remote-pill><span class=dot></span><span id=remote-source>loading</span></span>
  </div>
  <div class=remote-grid>
    <div>
      <div class=now-title id=remote-title>—</div>
      <div class=now-sub id=remote-sub>Waiting for Mopidy…</div>
      <div class=button-row style="margin-top:18px;">
        <button class=transport id=btn-prev type=button>‹‹</button>
        <button class="transport primary" id=btn-toggle type=button>▶</button>
        <button class=transport id=btn-next type=button>››</button>
        <button class=transport id=btn-stop type=button>STOP</button>
        <button class=ghost id=btn-add-current type=button>Add to playlist draft</button>
      </div>
    </div>
    <div>
      <label>System volume <span id=remote-vol-label class=pill>—</span></label>
      <input id=remote-volume class=range type=range min=0 max=100 value=50>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px;">
        <div class=remote-pill>Queue · <span id=remote-queue>0</span></div>
        <div class=remote-pill>Status · <span id=remote-state>—</span></div>
      </div>
    </div>
  </div>
</div>

<div id=playlist-card class=card hidden>
  <div style="display:flex;align-items:center;gap:10px;justify-content:space-between;margin-bottom:14px;">
    <label style="margin:0;">Playlist studio</label>
    <span class=pill id=builder-count>0 tracks</span>
  </div>
  <div class=split>
    <div>
      <label for=pl-search>Find tracks</label>
      <input id=pl-search type=text placeholder="artist, album, or song">
      <div class=mini-list style="margin-top:10px;">
        <div id=pl-results class=mini-list-scroll>
          <div class=mini-empty>Search your library to add tracks.</div>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">
        <button class=ghost id=btn-load-current-queue type=button>Use current queue</button>
        <button class=ghost id=btn-clear-builder type=button>Clear draft</button>
      </div>
    </div>
    <div>
      <label for=pl-name>Draft playlist name</label>
      <input id=pl-name type=text placeholder="Road trip, garage night, Saturday…">
      <div class=mini-list style="margin-top:10px;">
        <div id=pl-builder class=mini-list-scroll>
          <div class=mini-empty>No tracks in the draft yet.</div>
        </div>
      </div>
      <div class=button-row style="margin-top:10px;">
        <button id=btn-save-playlist type=button>Save playlist</button>
        <button class=ghost id=btn-play-draft type=button>Play draft</button>
      </div>
      <div class=ok id=pl-ok></div>
      <div class=err id=pl-err></div>
    </div>
  </div>
  <div style="margin-top:16px;">
    <label>Saved playlists</label>
    <div class=mini-list>
      <div id=playlist-list class=mini-list-scroll>
        <div class=mini-empty>Loading playlists…</div>
      </div>
    </div>
  </div>
</div>

<div id=upload-card class=card hidden>
  <label>Upload</label>
  <div id=drop class=drop>
    <div>Drop audio or video files here, or <button type=button id=pick>choose files</button></div>
    <input id=picker type=file accept="audio/*,video/*,.flac,.opus,.alac,.mkv,.m4v" multiple hidden>
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
let rpcId = 1;
let remoteExternal = false;
let remoteState = "stopped";
let currentTrack = null;
let playlistDraft = [];
let remoteTimer = null;

function show(authedNow) {{
  authed = authedNow;
  $('auth-card').hidden = authedNow;
  $('remote-card').hidden = !authedNow;
  $('playlist-card').hidden = !authedNow;
  $('upload-card').hidden = !authedNow;
  $('lib-card').hidden = !authedNow;
}}

async function rpc(method, params = {{}}) {{
  const r = await fetch('mopidy/rpc', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ jsonrpc: '2.0', id: rpcId++, method, params }}),
  }});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || JSON.stringify(j.error));
  return j.result;
}}

function artistText(track) {{
  return (track?.artists || []).map(a => a?.name).filter(Boolean).join(', ');
}}

function trackLabel(track) {{
  return {{
    title: track?.name || track?.title || track?.uri || 'Untitled',
    artist: artistText(track) || track?.artist || '',
    album: track?.album?.name || track?.album || '',
  }};
}}

function mmss(ms) {{
  const sec = Math.max(0, Math.floor((ms || 0) / 1000));
  return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
}}

async function refreshRemote() {{
  try {{
    const [track, state, pos, queue, ext] = await Promise.all([
      rpc('core.playback.get_current_track').catch(() => null),
      rpc('core.playback.get_state').catch(() => 'stopped'),
      rpc('core.playback.get_time_position').catch(() => 0),
      rpc('core.tracklist.get_tl_tracks').catch(() => []),
      fetch('api/state', {{ cache: 'no-store' }}).then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    remoteExternal = !!(ext?.source && (ext.status === 'playing' || ext.status === 'paused'));
    remoteState = remoteExternal ? ext.status : state;
    currentTrack = remoteExternal ? null : track;
    const label = remoteExternal
      ? {{
          title: ext.track?.title || ext.label || ext.source || 'External source',
          artist: ext.track?.artist || ext.label || '',
          album: ext.track?.album || '',
        }}
      : trackLabel(track);
    $('remote-title').textContent = label.title || '—';
    $('remote-sub').textContent = [
      label.artist,
      label.album,
      remoteExternal ? 'external source' : mmss(pos),
    ].filter(Boolean).join(' · ') || 'No track loaded';
    $('remote-source').textContent = remoteExternal ? (ext.label || ext.source || 'external') : 'library';
    $('remote-state').textContent = remoteState;
    $('remote-queue').textContent = String(queue?.length || 0);
    $('btn-toggle').textContent = remoteState === 'playing' ? '❚❚' : '▶';
    const vol = await fetch('api/volume', {{ cache: 'no-store' }}).then(r => r.ok ? r.json() : null).catch(() => null);
    if (vol && typeof vol.volume === 'number') {{
      const pct = Math.round(Math.max(0, Math.min(1.5, vol.volume)) * 100);
      $('remote-volume').value = String(Math.min(100, pct));
      $('remote-vol-label').textContent = pct + '%';
    }}
  }} catch (err) {{
    $('remote-title').textContent = 'Offline';
    $('remote-sub').textContent = String(err.message || err);
  }}
}}

function startRemote() {{
  refreshRemote();
  loadPlaylists();
  if (!remoteTimer) remoteTimer = setInterval(refreshRemote, 2500);
}}

async function remoteAction(action) {{
  try {{
    if (remoteExternal) {{
      await fetch('api/control/' + action, {{ method: 'POST' }});
    }} else if (action === 'toggle') {{
      await rpc(remoteState === 'playing' ? 'core.playback.pause' : 'core.playback.play');
    }} else if (action === 'next') {{
      await rpc('core.playback.next');
    }} else if (action === 'previous') {{
      await rpc('core.playback.previous');
    }} else if (action === 'stop') {{
      await rpc('core.playback.stop');
    }}
  }} finally {{
    setTimeout(refreshRemote, 250);
  }}
}}

$('btn-prev').addEventListener('click', () => remoteAction('previous'));
$('btn-toggle').addEventListener('click', () => remoteAction('toggle'));
$('btn-next').addEventListener('click', () => remoteAction('next'));
$('btn-stop').addEventListener('click', () => remoteAction('stop'));
$('remote-volume').addEventListener('input', e => {{
  const pct = Number(e.target.value) || 0;
  $('remote-vol-label').textContent = pct + '%';
  fetch('api/volume', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ volume: pct / 100 }}),
  }}).catch(() => {{}});
}});

function addTrackToDraft(track) {{
  if (!track?.uri) return;
  playlistDraft.push(track);
  renderDraft();
}}

$('btn-add-current').addEventListener('click', () => {{
  if (currentTrack) addTrackToDraft(currentTrack);
}});

function renderTrackRow(track, actionLabel, action) {{
  const label = trackLabel(track);
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = '<div class=icon>♪</div><div class=name></div><div class=meta></div><button class=inline type=button></button>';
  row.querySelector('.name').textContent = label.title;
  row.querySelector('.meta').textContent = [label.artist, label.album].filter(Boolean).join(' · ');
  const btn = row.querySelector('button');
  btn.textContent = actionLabel;
  btn.onclick = action;
  return row;
}}

function renderDraft() {{
  $('builder-count').textContent = `${{playlistDraft.length}} track${{playlistDraft.length === 1 ? '' : 's'}}`;
  const root = $('pl-builder');
  root.innerHTML = '';
  if (!playlistDraft.length) {{
    root.innerHTML = '<div class=mini-empty>No tracks in the draft yet.</div>';
    return;
  }}
  playlistDraft.forEach((track, idx) => {{
    const row = renderTrackRow(track, 'Remove', () => {{
      playlistDraft.splice(idx, 1);
      renderDraft();
    }});
    const icon = row.querySelector('.icon');
    icon.textContent = String(idx + 1).padStart(2, '0');
    root.appendChild(row);
  }});
}}

let searchTimer = null;
$('pl-search').addEventListener('input', e => {{
  const q = e.target.value.trim();
  clearTimeout(searchTimer);
  if (!q) {{
    $('pl-results').innerHTML = '<div class=mini-empty>Search your library to add tracks.</div>';
    return;
  }}
  searchTimer = setTimeout(() => searchPlaylistTracks(q), 260);
}});

async function searchPlaylistTracks(q) {{
  const root = $('pl-results');
  root.innerHTML = '<div class=mini-empty>Searching…</div>';
  try {{
    const results = await rpc('core.library.search', {{ query: {{ any: [q] }} }});
    const tracks = (results || []).flatMap(r => r.tracks || []).slice(0, 60);
    root.innerHTML = '';
    if (!tracks.length) {{
      root.innerHTML = '<div class=mini-empty>No matching tracks.</div>';
      return;
    }}
    tracks.forEach(track => root.appendChild(renderTrackRow(track, 'Add', () => addTrackToDraft(track))));
  }} catch (err) {{
    root.innerHTML = '<div class=mini-empty>Search failed.</div>';
  }}
}}

$('btn-clear-builder').addEventListener('click', () => {{
  playlistDraft = [];
  renderDraft();
}});

$('btn-load-current-queue').addEventListener('click', async () => {{
  try {{
    const q = await rpc('core.tracklist.get_tl_tracks');
    playlistDraft = (q || []).map(t => t.track).filter(Boolean);
    renderDraft();
  }} catch {{
    $('pl-err').textContent = 'Could not read current queue.';
  }}
}});

$('btn-play-draft').addEventListener('click', async () => {{
  if (!playlistDraft.length) return;
  await playUris(playlistDraft.map(t => t.uri));
}});

async function playUris(uris) {{
  await rpc('core.tracklist.clear');
  await rpc('core.tracklist.add', {{ uris }});
  await rpc('core.playback.play');
  refreshRemote();
}}

$('btn-save-playlist').addEventListener('click', async () => {{
  $('pl-ok').textContent = '';
  $('pl-err').textContent = '';
  const name = $('pl-name').value.trim();
  if (!name) {{ $('pl-err').textContent = 'Name the playlist first.'; return; }}
  if (!playlistDraft.length) {{ $('pl-err').textContent = 'Add at least one track.'; return; }}
  try {{
    let playlist = await rpc('core.playlists.create', {{ name, uri_scheme: 'm3u' }});
    if (!playlist) throw new Error('Mopidy did not create a playlist.');
    playlist.tracks = playlistDraft;
    const saved = await rpc('core.playlists.save', {{ playlist }});
    if (!saved) throw new Error('Mopidy did not save the playlist.');
    await rpc('core.playlists.refresh', {{ uri_scheme: 'm3u' }}).catch(() => {{}});
    $('pl-ok').textContent = `Saved "${{saved.name || name}}" with ${{playlistDraft.length}} tracks.`;
    $('pl-name').value = '';
    playlistDraft = [];
    renderDraft();
    loadPlaylists();
  }} catch (err) {{
    $('pl-err').textContent = 'Save failed: ' + (err.message || err);
  }}
}});

async function loadPlaylists() {{
  const root = $('playlist-list');
  try {{
    const refs = await rpc('core.playlists.as_list');
    root.innerHTML = '';
    if (!refs?.length) {{
      root.innerHTML = '<div class=mini-empty>No saved playlists yet.</div>';
      return;
    }}
    refs.forEach(ref => {{
      const row = document.createElement('div');
      row.className = 'row';
      row.innerHTML = '<div class=icon>▸</div><div class=name></div><div class=meta></div><button class=inline type=button>Play</button>';
      row.querySelector('.name').textContent = ref.name || ref.uri;
      row.querySelector('.meta').textContent = ref.uri || '';
      row.querySelector('button').onclick = async () => {{
        const items = await rpc('core.playlists.get_items', {{ uri: ref.uri }});
        const uris = (items || []).map(x => x.uri).filter(Boolean);
        if (uris.length) await playUris(uris);
      }};
      root.appendChild(row);
    }});
  }} catch {{
    root.innerHTML = '<div class=mini-empty>Could not load playlists.</div>';
  }}
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
    if (await tryPin(v)) {{ show(true); loadDir(""); startRemote(); }}
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

async function deletePath(rel, name) {{
  if (!confirm(`Delete "${{name}}" from the boombox library?`)) return;
  $('upload-err').textContent = '';
  $('upload-ok').textContent = '';
  const r = await fetch('delete', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ path: rel }}),
  }});
  if (!r.ok) {{
    const j = await r.json().catch(() => ({{ error: 'delete failed' }}));
    $('upload-err').textContent = j.error || 'delete failed';
    return;
  }}
  $('upload-ok').textContent = `Deleted "${{name}}" — boombox is rescanning the library.`;
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
      row.innerHTML = `<div class=icon>♪</div><div class=name></div><div class=meta>${{sizeMB}}</div><a class=dl></a><button class="inline danger" type=button></button>`;
      row.querySelector('.name').textContent = e.name;
      const a = row.querySelector('.dl');
      const dlPath = cwd ? cwd + '/' + e.name : e.name;
      a.href = 'download/' + encodeURI(dlPath);
      a.textContent = '⤓';
      a.title = 'download';
      a.setAttribute('download', '');
      const del = row.querySelector('button.danger');
      if (e.deletable) {{
        del.textContent = 'Delete';
        del.onclick = () => deletePath(dlPath, e.name);
      }} else {{
        del.textContent = 'USB';
        del.disabled = true;
        del.title = 'USB files are read-only from the web UI.';
      }}
    }}
    list.appendChild(row);
  }}
}}

// Boot. If cookie is already set, browse will succeed.
(async () => {{
  const r = await fetch('browse?path=', {{ credentials: 'include' }});
  if (r.ok) {{ show(true); const j = await r.json(); cwd = j.path; entries = j.entries; renderCrumbs(); renderEntries(); startRemote(); }}
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

    MUSIC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    saved_audio: list[str] = []
    saved_video: list[str] = []
    reader = await request.multipart()
    async for part in reader:
        if part.name != "file" or not part.filename:
            continue
        name = safe_filename(part.filename)
        ext = Path(name).suffix.lower()
        if ext in AUDIO_EXTS:
            dest_dir, dest_root, bucket = MUSIC_UPLOAD_DIR, MUSIC_ROOT, saved_audio
        elif ext in VIDEO_EXTS:
            dest_dir, dest_root, bucket = VIDEO_UPLOAD_DIR, VIDEO_ROOT, saved_video
        else:
            return web.json_response({"error": f"unsupported type: {ext}"}, status=400)

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
                    return web.json_response({"error": "file too large"}, status=413)
                f.write(chunk)
        log.info("uploaded %s (%d bytes)", target, size)
        bucket.append(str(target.relative_to(dest_root)))

    saved = saved_audio + saved_video
    # Kick whichever library scans are relevant. Both are best-effort —
    # the user gets their 200 either way and the refresh runs in the
    # background.
    if saved_audio:
        asyncio.create_task(_trigger_scan())
    if saved_video:
        asyncio.create_task(_trigger_jellyfin_scan())

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


async def _trigger_jellyfin_scan() -> None:
    """Kick Jellyfin's library refresh after a video upload.

    The token lives in /etc/boombox/jellyfin-api-key (mode 0640, group
    boombox so the user-side service can read it). If Jellyfin isn't
    boombox-managed yet the file is absent and we just no-op.
    """
    try:
        token = JELLYFIN_KEY_FILE.read_text().strip()
    except (FileNotFoundError, OSError):
        return
    if not token:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(
                "http://127.0.0.1:8096/Library/Refresh",
                headers={"X-MediaBrowser-Token": token},
                timeout=aiohttp.ClientTimeout(total=3),
            )
    except Exception as e:
        log.debug("jellyfin scan trigger failed: %s", e)


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
    target = safe_compose(MUSIC_ROOT, rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(target)


async def delete_handler(request: web.Request) -> web.Response:
    if not request_authed(request):
        return web.json_response({"error": "pin required"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    rel = str(body.get("path", "") or "").strip("/").replace("\\", "/")
    target = safe_compose(MUSIC_ROOT, rel)
    if target is None or not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    if not under_root(target, MUSIC_ROOT):
        return web.json_response({"error": "USB and symlinked files are read-only from the web UI"}, status=403)
    if target.suffix.lower() not in ALLOWED_EXTS:
        return web.json_response({"error": "unsupported file type"}, status=400)
    try:
        target.unlink()
    except OSError as e:
        return web.json_response({"error": str(e)}, status=500)

    asyncio.create_task(_trigger_scan())
    resp = web.json_response({"deleted": rel})
    set_pin_cookie(resp)
    return resp


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "pin_present": bool(PIN)})


# ---------------------------------------------------------------------------
# Reverse proxy for /api/, /mopidy/, /audio/
#
# The upload page makes calls like fetch('/api/state') and fetch('/mopidy/rpc')
# to drive playback. Those routes on nginx port 8090 require HTTP Basic auth
# (LAN-wide gate), but the upload page is reached via the PIN, not Basic
# auth — so guests would get a credential modal mid-session. We forward the
# same requests through the uploader (PIN-gated) so the remote stays inside
# /upload/ for its lifetime.
# ---------------------------------------------------------------------------

PROXY_BACKENDS = {
    "api":    "http://127.0.0.1:6681",
    "mopidy": "http://127.0.0.1:6680/mopidy",   # nginx prepends /mopidy/
    "audio":  "http://127.0.0.1:6682",
}


async def proxy_handler(request: web.Request) -> web.StreamResponse:
    if not request_authed(request):
        return web.json_response({"error": "pin required"}, status=401)
    backend_key = request.match_info["backend"]
    base = PROXY_BACKENDS.get(backend_key)
    if not base:
        return web.json_response({"error": "unknown backend"}, status=404)
    tail = request.match_info.get("tail", "")
    target = base + "/" + tail
    if request.query_string:
        target += "?" + request.query_string

    import aiohttp
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length", "accept-encoding")}

    body = await request.read() if request.can_read_body else None
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.request(
                request.method, target, data=body, headers=headers,
                allow_redirects=False,
            ) as up:
                resp = web.StreamResponse(status=up.status, headers={
                    k: v for k, v in up.headers.items()
                    if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
                })
                await resp.prepare(request)
                async for chunk in up.content.iter_chunked(64 * 1024):
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
    except Exception as e:
        log.warning("proxy %s %s failed: %s", request.method, target, e)
        return web.json_response({"error": str(e)}, status=502)


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
    app.router.add_post("/delete", delete_handler)
    app.router.add_get("/health", health)
    # Reverse proxy: /upload/{api,mopidy,audio}/<anything> → backend port.
    # The page uses relative paths so all traffic stays inside /upload/.
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        app.router.add_route(method, "/{backend:api|mopidy|audio}/{tail:.*}", proxy_handler)
    return app


async def main() -> None:
    global PIN
    PIN = generate_pin()
    write_pin(PIN)
    log.info("PIN: %s (written to %s)", PIN, PIN_FILE)

    MUSIC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
