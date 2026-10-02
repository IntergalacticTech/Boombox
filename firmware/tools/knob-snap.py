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

Sharing the port with boombox-remote: the USB knob bridge (services/
knob_usb.py) normally holds the knob's port. For the length of a run this
script creates the bridge's pause file (PI_KNOB_PAUSE, default
/run/user/1000/boombox-knob.pause), waits until no other process has the tty
open, and removes the file when done — the bridge then reconnects and the
knob goes back to its USB link. If the knob sat paused for more than 12 s it
will have fallen back to BLE in the meantime; it returns to USB as soon as
the bridge pushes state again.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys

PI_HOST = os.environ.get("PI_HOST", "root@192.168.1.81")
# "auto": /dev/boombox-knob (the udev symlink) if present, else /dev/ttyACM0.
PI_TTY = os.environ.get("PI_TTY", "auto")
PI_KNOB_PAUSE = os.environ.get("PI_KNOB_PAUSE", "/run/user/1000/boombox-knob.pause")
PI_PYTHON = os.environ.get("PI_PYTHON", "/home/dietpi/.esptool/bin/python")

# Runs on the Pi. argv: tty, pause_file, wait_s, log_s, snap(0/1), cmds...
REMOTE = r'''
import os, sys, time, serial
tty, pause = sys.argv[1], sys.argv[2]
wait_s, log_s, snap = float(sys.argv[3]), float(sys.argv[4]), sys.argv[5] == "1"
cmds = sys.argv[6:]
out = sys.stdout
if tty == "auto":
    tty = "/dev/boombox-knob" if os.path.exists("/dev/boombox-knob") else "/dev/ttyACM0"

def holders(dev):
    """PIDs (other than ours) with `dev` open."""
    real, me, pids = os.path.realpath(dev), os.getpid(), []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.path.realpath(f"/proc/{pid}/fd/{fd}") == real:
                    pids.append(int(pid))
                    break
        except OSError:
            pass
    return pids

# Ask boombox-remote's knob bridge to let go of the port (it polls the pause
# file twice a second) and wait until it has.
paused = False
if pause and os.path.isdir(os.path.dirname(pause)):
    open(pause, "a").close()
    paused = True
    end = time.time() + 5
    while holders(tty) and time.time() < end:
        time.sleep(0.1)
    if holders(tty):
        sys.stderr.write(f"[knob-snap] {tty} still held by pid(s) {holders(tty)}\n")
last_touch = time.time()

def keep_paused():
    global last_touch
    if paused and time.time() - last_touch > 10:
        try:
            os.utime(pause)
        except OSError:
            pass
        last_touch = time.time()
# Default DTR/RTS (both asserted) is what the kernel already does on open,
# so pyserial changes nothing and the S3's USB-JTAG reset logic isn't poked.
try:
    s = serial.Serial(tty, 115200, timeout=0.02)
except Exception:
    if paused:
        os.unlink(pause)
    raise
def pump(seconds, stop=None):
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        keep_paused()
        chunk = s.read(65536)
        if not chunk:
            continue
        out.write(chunk.decode("utf-8", "replace"))
        out.flush()
        if stop:
            window = buf + chunk
            if stop in window:
                return True
            buf = window[-64:]
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
    if paused:
        try:
            os.unlink(pause)
        except OSError:
            pass
'''


def run_remote(cmds: list[str], wait_s: float, log_s: float, snap: bool) -> str:
    argv = ["ssh", PI_HOST, PI_PYTHON, "-", PI_TTY, PI_KNOB_PAUSE, str(wait_s),
            str(log_s), "1" if snap else "0", *cmds]
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


class SnapshotError(Exception):
    pass


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
    try:
        raw = base64.b64decode("".join(chunks))
    except ValueError as e:
        raise SnapshotError(f"snapshot corrupt: {e}") from e
    if len(raw) != n:
        raise SnapshotError(f"snapshot truncated: got {len(raw)} of {n} bytes")
    log = "\n".join(lines[:start] + lines[end + 1:])
    return (w, h, raw), log


_B64_LINE = re.compile(r"^[A-Za-z0-9+/=]{64,}$")


def clean_log(log: str) -> str:
    """Drop the tail of an earlier, abandoned snapshot stream."""
    return "\n".join(ln for ln in log.splitlines()
                     if not _B64_LINE.match(ln) and ln != "SNAPEND"
                     and not ln.startswith("SNAP "))


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
        try:
            img, log = decode_snapshot(text)
        except SnapshotError as e:
            # A dropped USB chunk; the screen is still there — grab it again
            # (without re-sending the commands).
            sys.stderr.write(f"[knob-snap] {e}; retrying snapshot\n")
            img, _ = decode_snapshot(run_remote([], a.wait, 0, True))
    log = clean_log(log)
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
