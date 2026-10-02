#!/usr/bin/env python3
"""knob-snap — see and drive the rotary knob over its serial debug console.

The knob is plugged into MarkII's USB, so this runs on the Mac and drives a
tiny pyserial script on the Pi over ssh (as root: dietpi isn't in dialout).
The Pi only shuttles bytes; decoding and PNG writing happen here (Pillow).

Examples:
  knob-snap.py                           # snapshot → knob-snap.png
  knob-snap.py -o face.png -c "enc +3"   # inject 3 detents, then snapshot
  knob-snap.py -c long -c "enc +1" --wait 0.5 -o menu.png
  knob-snap.py --no-snap -c info --log 2 # run commands, print the log
  knob-snap.py --log 20                  # just tail the serial log

Console framing (see src/devices/crowpanel-rotary-21/DebugConsole.h):
  SNAP <w> <h> <bytes> RGB565  /  base64 lines  /  SNAPEND
"""
from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys

PI_HOST = os.environ.get("PI_HOST", "root@192.168.1.81")
PI_TTY = os.environ.get("PI_TTY", "/dev/ttyACM0")
PI_PYTHON = os.environ.get("PI_PYTHON", "/home/dietpi/.esptool/bin/python")

# Runs on the Pi. argv: tty, wait_s, log_s, snap(0/1), cmds...
REMOTE = r'''
import sys, time, serial
tty, wait_s, log_s, snap = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4] == "1"
cmds = sys.argv[5:]
out = sys.stdout
# Default DTR/RTS (both asserted) is what the kernel already does on open,
# so pyserial changes nothing and the S3's USB-JTAG reset logic isn't poked.
s = serial.Serial(tty, 115200, timeout=0.2)
def pump(seconds, stop=None):
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        chunk = s.read(65536)
        if not chunk:
            continue
        out.write(chunk.decode("utf-8", "replace"))
        out.flush()
        if stop:
            buf = (buf + chunk)[-64:]
            if stop in buf:
                return True
    return False
try:
    s.reset_input_buffer()
    for c in cmds:
        s.write((c + "\n").encode())
        s.flush()
        pump(wait_s)
    if snap:
        s.write(b"snap\n")
        s.flush()
        if not pump(30, stop=b"SNAPEND"):
            out.write("\nKNOBSNAP-TIMEOUT\n")
        pump(0.3)
    if log_s > 0:
        pump(log_s)
finally:
    s.close()
'''


def run_remote(cmds: list[str], wait_s: float, log_s: float, snap: bool) -> str:
    argv = ["ssh", PI_HOST, PI_PYTHON, "-", PI_TTY, str(wait_s), str(log_s),
            "1" if snap else "0", *cmds]
    # ssh joins argv with spaces for the remote shell — quote each command.
    quoted = argv[:4] + [_shq(a) for a in argv[4:]]
    res = subprocess.run(quoted, input=REMOTE, capture_output=True, text=True,
                         timeout=120 + log_s + wait_s * len(cmds))
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(f"remote serial script failed ({res.returncode})")
    return res.stdout


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def decode_snapshot(text: str):
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("SNAP ") and ln.endswith("RGB565"):
            start = i
    if start is None:
        return None, text
    _, w, h, n, _ = lines[start].split()
    w, h, n = int(w), int(h), int(n)
    chunks = []
    end = start + 1
    while end < len(lines) and lines[end] != "SNAPEND":
        chunks.append(lines[end].strip())
        end += 1
    raw = base64.b64decode("".join(chunks))
    if len(raw) != n:
        raise SystemExit(f"snapshot truncated: got {len(raw)} of {n} bytes")
    log = "\n".join(lines[:start] + lines[end + 1:])
    return (w, h, raw), log


def rgb565_to_png(w: int, h: int, raw: bytes, path: str) -> None:
    from PIL import Image
    px = bytearray(w * h * 3)
    for i in range(w * h):
        v = raw[2 * i] | (raw[2 * i + 1] << 8)   # LVGL RGB565, little endian
        r, g, b = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
        px[3 * i] = (r << 3) | (r >> 2)
        px[3 * i + 1] = (g << 2) | (g >> 4)
        px[3 * i + 2] = (b << 3) | (b >> 2)
    Image.frombytes("RGB", (w, h), bytes(px)).save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=None,
                    help="PNG path (default knob-snap.png)")
    ap.add_argument("-c", "--cmd", action="append", default=[],
                    help="console command to send first (repeatable)")
    ap.add_argument("--wait", type=float, default=0.4,
                    help="seconds to wait after each command (default 0.4)")
    ap.add_argument("--log", type=float, default=0.0,
                    help="seconds of serial log to capture at the end")
    ap.add_argument("--no-snap", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="don't echo the serial log")
    a = ap.parse_args()

    # `--log N` on its own just tails the log; otherwise take a snapshot.
    snap = not a.no_snap and not (a.log > 0 and not a.cmd and a.out is None)
    out_path = a.out or "knob-snap.png"
    text = run_remote(a.cmd, a.wait, a.log, snap)
    img, log = (None, text)
    if snap:
        img, log = decode_snapshot(text)
    if not a.quiet and log.strip():
        print(log.rstrip())
    if snap:
        if img is None:
            raise SystemExit("no SNAP frame in the serial output")
        w, h, raw = img
        rgb565_to_png(w, h, raw, out_path)
        print(f"[knob-snap] wrote {out_path} ({w}x{h})")


if __name__ == "__main__":
    main()
