#!/usr/bin/env python3
"""Boombox kiosk guard — keep Chromium pinned to the local boombox UI.

Polls Chromium's DevTools `/json` endpoint and, when any page tab is off the
local UI, navigates it back via WebSocket Page.navigate. The HTTP
`/json/page/<id>/navigate` endpoint was removed in modern Chromium (returns
404), so WebSocket is the only reliable way.

The kiosk launches with `--remote-debugging-port=9222` so the `pi` helper can
drive it; that same port lets anything in user space navigate the tab away.

Pause: touch `$XDG_RUNTIME_DIR/boombox-kiosk-guard.pause` to suppress the
guard (e.g. while another agent is driving the kiosk). Remove the file (or
restart the service) to resume.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kiosk-guard")

CDP_BASE = os.environ.get("BOOMBOX_KIOSK_CDP", "http://127.0.0.1:9222")
HOME_URL = os.environ.get("BOOMBOX_KIOSK_HOME", "http://localhost/")
POLL_INTERVAL_S = float(os.environ.get("BOOMBOX_KIOSK_POLL", "15"))
PAUSE_FILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"),
    "boombox-kiosk-guard.pause",
)
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
INTERNAL_SCHEMES = ("about:", "chrome:", "chrome-extension:", "devtools:", "data:")


def fetch_pages() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{CDP_BASE}/json", timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug("CDP fetch failed: %s", e)
        return []


def close_tab(target_id: str) -> None:
    # `/json/close/<id>` still works in modern Chromium even though /navigate
    # was removed.
    try:
        urllib.request.urlopen(f"{CDP_BASE}/json/close/{target_id}", timeout=3).read()
    except Exception as e:
        log.warning("close(%s) failed: %s", target_id, e)


async def _ws_navigate(ws_url: str, target_url: str) -> None:
    async with websockets.connect(ws_url, max_size=2**24, open_timeout=3) as ws:
        await ws.send(json.dumps({
            "id": 1, "method": "Page.navigate",
            "params": {"url": target_url},
        }))
        try:
            await asyncio.wait_for(ws.recv(), timeout=3)
        except asyncio.TimeoutError:
            pass


def navigate(ws_url: str, target_url: str) -> bool:
    try:
        asyncio.run(_ws_navigate(ws_url, target_url))
        return True
    except Exception as e:
        log.warning("ws navigate failed: %s", e)
        return False


def is_on_target(url: str) -> bool:
    if not url:
        return True
    if url.startswith(INTERNAL_SCHEMES):
        return True
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return host in ALLOWED_HOSTS


def tick() -> None:
    pages = [t for t in fetch_pages() if t.get("type") == "page"]
    if not pages:
        return

    drifted = [t for t in pages if not is_on_target(t.get("url", ""))]
    on_target = [t for t in pages if is_on_target(t.get("url", ""))]

    if drifted and on_target:
        # We already have a healthy tab — close the bad ones (kiosk shows the
        # surviving one fullscreen).
        for t in drifted:
            log.info("closing drifted tab %s (%s)", t.get("id"), t.get("url"))
            close_tab(t.get("id", ""))
        return

    if drifted and not on_target:
        # No healthy tab exists — navigate the active drifted tab back home,
        # then close any duplicates.
        primary, *rest = drifted
        log.info(
            "kiosk drifted to %r — navigating back to %s",
            primary.get("url"), HOME_URL,
        )
        ws = primary.get("webSocketDebuggerUrl")
        if ws and navigate(ws, HOME_URL):
            for t in rest:
                close_tab(t.get("id", ""))


def main() -> None:
    log.info(
        "kiosk guard active (cdp=%s home=%s poll=%.1fs pause-file=%s)",
        CDP_BASE, HOME_URL, POLL_INTERVAL_S, PAUSE_FILE,
    )
    while True:
        try:
            if os.path.exists(PAUSE_FILE):
                log.debug("paused via %s", PAUSE_FILE)
            else:
                tick()
        except Exception as e:
            log.warning("tick failed: %s", e)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
