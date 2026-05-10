#!/usr/bin/env python3
"""Boombox audio visualizer service.

Captures the system's default sink monitor (whatever PipeWire is currently
playing — Mopidy / AirPlay / Spotify / Bluetooth, all mixed) and streams
real spectrum + VU data to any WebSocket clients connected to /ws.

Why this lives in its own process:
  - It runs at ~20 Hz (much faster than boombox-state's 2 Hz status poll)
  - It holds an audio capture subprocess and would complicate that service's
    restart semantics
  - WS broadcast pattern is naturally separate from the state RPC pattern

Wire format (one JSON message per chunk):
  {
    "bins":  [...64 floats 0..1...],   # log-scaled magnitude per bin
    "peaks": [...64 floats 0..1...],   # peak-hold envelope
    "rms":   [<L>, <R>],               # 0..1 instantaneous L/R RMS
    "ts":    <unix-time-float>,
  }
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Set

import numpy as np
from aiohttp import WSMsgType, web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boombox-audio")

SAMPLE_RATE = 22050     # plenty for music spectrum; lower CPU than 44.1k
CHANNELS = 2
CHUNK = 1024            # ~46 ms windows → ~21 fps frames
N_BINS = 64

# Visualizer mapping: instantaneous FFT magnitudes for music are *very* spread
# across bins, so a linear scale stays in the 0..0.15 range — the bars barely
# move. We map magnitudes through a perceptual (square-root / dB-ish) curve and
# multiply hard so typical music fills 50–100 % of the bar range. The clip at
# 1.0 takes care of the loudest transients.
LEVEL_SCALE = 4.0       # tuned so a normal-loudness song fills 60–90 % of bars
PEAK_DECAY = 0.88       # slower decay so peak-hold lingers visibly
RMS_GAIN = 1.8          # VU outputs hit 1.0 only on actual loud transients

clients: Set[web.WebSocketResponse] = set()
_last_payload: str = "{}"


def detect_monitor_source() -> str | None:
    """Find the default sink's monitor source via pactl (best-effort)."""
    import subprocess
    try:
        # pactl get-default-sink → e.g. "alsa_output.platform-soc...stereo-fallback"
        sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        if sink:
            return f"{sink}.monitor"
    except Exception as e:
        log.warning("could not auto-detect default sink: %s", e)
    # Fall back to whatever .monitor source the box is most likely to have.
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        for line in out.splitlines():
            cols = line.split("\t")
            if len(cols) >= 2 and cols[1].endswith(".monitor"):
                return cols[1]
    except Exception:
        pass
    return None


async def capture_loop() -> None:
    """Run parec, read samples, broadcast FFT/RMS forever (with auto-restart)."""
    global _last_payload
    bin_edges = np.unique(
        np.logspace(np.log10(2), np.log10(CHUNK // 2 - 1), N_BINS + 1).astype(int)
    )
    # If unique() collapsed bins (small CHUNK), pad with linear edges.
    while len(bin_edges) < N_BINS + 1:
        bin_edges = np.append(bin_edges, bin_edges[-1] + 1)
    window = np.hanning(CHUNK).astype(np.float32)
    peaks = np.zeros(N_BINS, dtype=np.float32)
    bytes_per_chunk = CHUNK * CHANNELS * 2  # s16le

    while True:
        monitor = detect_monitor_source()
        if not monitor:
            log.warning("no monitor source available, retrying in 2 s")
            await asyncio.sleep(2)
            continue

        log.info("starting parec on %s", monitor)
        proc = await asyncio.create_subprocess_exec(
            "parec",
            "--device", monitor,
            "--format=s16le",
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--latency-msec=40",
            "--raw",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            assert proc.stdout is not None
            while True:
                # readexactly with timeout: if parec stops producing data — e.g.
                # because PipeWire/Wireplumber was restarted out from under it
                # and parec is now talking to a node that no longer exists —
                # we want to bail and re-detect the monitor source rather than
                # block forever. ~46 ms per chunk × 2x slack → 5 s is generous.
                buf = await asyncio.wait_for(
                    proc.stdout.readexactly(bytes_per_chunk),
                    timeout=5.0,
                )
                samples = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
                stereo = samples.reshape(-1, CHANNELS)
                left = stereo[:, 0]
                right = stereo[:, 1]
                mono = (left + right) * 0.5

                spec = np.abs(np.fft.rfft(mono * window))
                # Perceptual: sqrt(magnitude) compresses high peaks while
                # boosting low-energy bins so quiet music still moves bars.
                spec_perc = np.sqrt(spec)
                bins = np.zeros(N_BINS, dtype=np.float32)
                for i in range(N_BINS):
                    lo, hi = bin_edges[i], bin_edges[i + 1]
                    if hi > lo:
                        bins[i] = float(np.mean(spec_perc[lo:hi]))
                bins = np.nan_to_num(bins, nan=0.0)
                bins = np.clip(bins * LEVEL_SCALE / np.sqrt(CHUNK), 0.0, 1.0)
                peaks = np.maximum(peaks * PEAK_DECAY, bins)

                rms_l = float(np.clip(np.sqrt(np.mean(left ** 2)) * RMS_GAIN, 0, 1))
                rms_r = float(np.clip(np.sqrt(np.mean(right ** 2)) * RMS_GAIN, 0, 1))

                payload = {
                    "bins": [round(float(x), 3) for x in bins],
                    "peaks": [round(float(x), 3) for x in peaks],
                    "rms": [round(rms_l, 3), round(rms_r, 3)],
                    "ts": time.time(),
                }
                msg = json.dumps(payload)
                _last_payload = msg
                if clients:
                    dead = []
                    for ws in clients:
                        if ws.closed:
                            dead.append(ws); continue
                        try:
                            await ws.send_str(msg)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        clients.discard(ws)
        except asyncio.IncompleteReadError:
            log.warning("parec stream ended; restarting")
        except asyncio.TimeoutError:
            log.warning("parec produced no data for 5 s; restarting")
        except Exception as e:
            log.warning("capture error: %s", e)
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await asyncio.sleep(0.5)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)
    clients.add(ws)
    log.info("client connected (total=%d)", len(clients))
    # Send the most-recent frame immediately so the UI doesn't show flat bars
    # for the first 50 ms.
    try:
        await ws.send_str(_last_payload)
    except Exception:
        pass
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        clients.discard(ws)
        log.info("client gone (total=%d)", len(clients))
    return ws


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "clients": len(clients)})


async def main() -> None:
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 6682)
    await site.start()
    log.info("listening on http://127.0.0.1:6682/")
    await capture_loop()


if __name__ == "__main__":
    asyncio.run(main())
