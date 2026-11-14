"""USB bridge to the rotary knob (CrowPanel 2.1") plugged into the boombox.

Runs inside boombox-remote next to the BLE peripheral and shares its state
aggregator and action dispatcher. The knob's native USB-Serial/JTAG port
(/dev/ttyACM*, VID:PID 303a:1001) carries its debug console and log; this
bridge speaks a newline-delimited JSON protocol over the same port:

    host → knob  {"t":"hello"}
                 {"t":"state","d":{…compact consolidated state…}}
    knob → host  {"t":"hello","profile":"crowpanel-rotary-21","fw":"0.1.0"}
                 {"t":"cmd","action":"volume","value":0.42}

The knob also sends its hello unprompted at boot; the bridge answers any
hello by pushing state at once.

Protocol lines start with '{'; everything else from the knob is log output
and is ignored. There is no pairing over USB — the physical cable is the
trust boundary. While the knob hears state at least every 12 s it treats USB
as its active link and keeps BLE idle; when this bridge goes away it falls
back to BLE on its own.

Hardware-optional by design: no device, no permission, a knob that doesn't
answer hello, or an unplug mid-run all just mean "retry in RETRY_S", logged
once per change of situation. Stdlib only (os.open + termios + loop
add_reader) — no pyserial, and nothing here blocks the event loop.

Device discovery tries each entry of the path list in order (globs allowed,
default /dev/boombox-knob then /dev/serial/by-id/*Espressif*), opens it and
sends hello; the first one that answers with a knob profile wins. CH340
bridges (VID 1a86 — the CYD remotes, owned by cyd-autoflash) are never
opened.

Sharing the port with knob-snap: the bridge releases the port while the pause
file exists (default $XDG_RUNTIME_DIR/boombox-knob.pause) and is younger
than PAUSE_MAX_S, so a stale file left by a crashed tool can't wedge it.
firmware/tools/knob-snap.py and firmware/pi-flash-knob create it for the
duration of their session.

Env:
    BOOMBOX_REMOTE_KNOB_USB=1       0 disables the bridge
    BOOMBOX_KNOB_USB_PATHS=…        os.pathsep-separated paths/globs
    BOOMBOX_KNOB_PAUSE_FILE=…       pause-file path
"""
from __future__ import annotations

import asyncio
import errno
import glob
import json
import logging
import os
import re
import termios
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import remote_wire

log = logging.getLogger("boombox-remote-knob-usb")

DEFAULT_PATHS: tuple[str, ...] = (
    "/dev/boombox-knob",
    "/dev/serial/by-id/*Espressif*",
)
# Knob log lines worth surfacing: panics, resets and the firmware's boot banner.
_KNOB_ALERT = re.compile(
    rb"Guru Meditation|abort\(\)|Backtrace:|rst:0x|task_wdt|Brownout|"
    rb"=== boombox|ESP-ROM:|host link quiet")

# Profiles that identify a knob in the hello reply.
KNOB_PROFILES: frozenset[str] = frozenset({"crowpanel-rotary-21"})
# USB vendor IDs the bridge must never open (CH340 → CYD remotes).
NEVER_VENDORS: frozenset[str] = frozenset({"1a86"})

RETRY_S = 5.0          # between discovery attempts
POLL_S = 0.5           # state poll / pause-file check
RESEND_S = 5.0         # unchanged state is re-sent this often (knob window: 12 s)
GAP_WARN_S = 8.0       # warn when the knob has gone this long without a state
HELLO_TIMEOUT_S = 2.0
PAUSE_MAX_S = 300.0    # an older pause file is treated as stale
MAX_LINE = 8192        # knob → host; longer lines (none expected) are dropped
MAX_WBUF = 16384       # pending host → knob bytes before new lines are dropped


def usb_state_line(data: dict) -> bytes:
    """The state message for the knob, newline-terminated. Same field trim
    as the BLE copy but no length cap (USB has no 512-byte limit)."""
    return remote_wire.dumps_compact(
        {"t": "state", "d": remote_wire.compact_state(data)}) + b"\n"


def default_pause_file() -> str:
    run_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(run_dir, "boombox-knob.pause")


def configured_paths() -> list[str]:
    raw = os.environ.get("BOOMBOX_KNOB_USB_PATHS", "")
    paths = [p for p in raw.split(os.pathsep) if p.strip()]
    return paths or list(DEFAULT_PATHS)


def usb_vendor(dev_path: str) -> Optional[str]:
    """USB idVendor of a tty device from sysfs, or None if unknown (a pty,
    a non-USB tty, no sysfs)."""
    try:
        name = os.path.basename(os.path.realpath(dev_path))
        node = Path(os.path.realpath(f"/sys/class/tty/{name}/device"))
    except OSError:
        return None
    for d in (node, *node.parents):
        f = d / "idVendor"
        if f.is_file():
            try:
                return f.read_text().strip().lower()
            except OSError:
                return None
        if d == Path("/sys"):
            break
    return None


def open_raw(path: str) -> int:
    """Open a tty non-blocking in raw 8N1 mode at 115200. HUPCL is cleared
    so closing the port doesn't drop DTR/RTS (the S3's USB-JTAG reset lines
    stay where the kernel put them on open). Raises OSError."""
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK
                      | termios.ISTRIP | termios.INLCR | termios.IGNCR
                      | termios.ICRNL | termios.IXON | termios.IXOFF
                      | termios.IXANY)
        attrs[1] &= ~termios.OPOST
        attrs[2] &= ~(termios.CSIZE | termios.PARENB | termios.HUPCL)
        attrs[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON
                      | termios.ISIG | termios.IEXTEN)
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (OSError, termios.error) as e:
        os.close(fd)
        if isinstance(e, OSError):
            raise
        raise OSError(errno.ENOTTY, f"not a tty: {e}") from e
    return fd


class _Port:
    """One open knob port: line reader, buffered writer, disconnect flag.
    Lives on the event loop; all I/O is non-blocking via add_reader/writer."""

    def __init__(self, loop: asyncio.AbstractEventLoop, fd: int, path: str,
                 on_line: Callable[[bytes], None]):
        self.loop, self.fd, self.path = loop, fd, path
        self._on_line = on_line
        self._rbuf = bytearray()
        self._skip = False            # inside an overlong line
        self._wbuf = bytearray()
        self._writing = False
        self.closed = asyncio.Event()
        self.error: Optional[str] = None
        loop.add_reader(fd, self._readable)

    def _readable(self) -> None:
        try:
            chunk = os.read(self.fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:
            self._fail(e.strerror or str(e))
            return
        if not chunk:
            self._fail("end of file")
            return
        self._rbuf += chunk
        while True:
            nl = self._rbuf.find(b"\n")
            if nl < 0:
                break
            line = bytes(self._rbuf[:nl]).rstrip(b"\r")
            del self._rbuf[:nl + 1]
            if self._skip:
                self._skip = False
                continue
            self._on_line(line)
        if len(self._rbuf) > MAX_LINE:
            self._rbuf.clear()
            self._skip = True

    def write(self, data: bytes) -> bool:
        """Queue whole lines; drops the line (returns False) rather than
        letting a knob that isn't reading grow the buffer without bound."""
        if self.closed.is_set():
            return False
        if len(self._wbuf) + len(data) > MAX_WBUF:
            return False
        self._wbuf += data
        self._flush()
        return True

    def _flush(self) -> None:
        while self._wbuf:
            try:
                n = os.write(self.fd, self._wbuf)
            except BlockingIOError:
                n = 0
            except OSError as e:
                self._fail(e.strerror or str(e))
                return
            if n <= 0:
                break
            del self._wbuf[:n]
        if self._wbuf and not self._writing:
            self.loop.add_writer(self.fd, self._flush)
            self._writing = True
        elif not self._wbuf and self._writing:
            self.loop.remove_writer(self.fd)
            self._writing = False

    def _fail(self, why: str) -> None:
        if self.error is None:
            self.error = why
        self.close()

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        self.loop.remove_reader(self.fd)
        if self._writing:
            self.loop.remove_writer(self.fd)
            self._writing = False
        try:
            os.close(self.fd)
        except OSError:
            pass


class KnobUsbBridge:
    """Finds the knob, keeps it fed with state, and dispatches its commands."""

    def __init__(self, *, aggregator: Any, dispatcher: Any,
                 fire_cb: Callable[..., Awaitable[Any]],
                 paths: Optional[list[str]] = None,
                 pause_file: Optional[str] = None,
                 profiles: frozenset[str] = KNOB_PROFILES,
                 retry_s: float = RETRY_S, poll_s: float = POLL_S,
                 resend_s: float = RESEND_S,
                 hello_timeout_s: float = HELLO_TIMEOUT_S,
                 clock: Callable[[], float] = time.monotonic,
                 open_fn: Callable[[str], int] = open_raw,
                 vendor_fn: Callable[[str], Optional[str]] = usb_vendor):
        self._aggregator = aggregator
        self._dispatcher = dispatcher
        self._fire_cb = fire_cb
        self._paths = list(paths) if paths is not None else configured_paths()
        self._pause_file = pause_file or os.environ.get(
            "BOOMBOX_KNOB_PAUSE_FILE") or default_pause_file()
        self._profiles = profiles
        self._retry_s, self._poll_s = retry_s, poll_s
        self._resend_s, self._hello_timeout_s = resend_s, hello_timeout_s
        self._clock = clock
        self._open = open_fn
        self._vendor = vendor_fn
        self._status: Optional[str] = None
        self._tasks: set[asyncio.Task] = set()
        # Current connection (for tests / diagnostics).
        self.port: Optional[_Port] = None
        self.profile: Optional[str] = None
        self.fw: Optional[str] = None
        self._hello: Optional[asyncio.Event] = None
        self._force_push = False

    # --- logging: once per change of situation ---------------------------
    def _set_status(self, key: str, msg: str, level: int = logging.INFO) -> None:
        if key != self._status:
            self._status = key
            log.log(level, "[knob-usb] %s", msg)

    @property
    def status(self) -> Optional[str]:
        return self._status

    # --- pause file -----------------------------------------------------
    def paused(self) -> bool:
        try:
            age = time.time() - os.stat(self._pause_file).st_mtime
        except OSError:
            return False
        return age < PAUSE_MAX_S

    # --- discovery ------------------------------------------------------
    def candidates(self) -> list[str]:
        """Expand the path list; de-duplicate by real path, skip CH340s."""
        seen: set[str] = set()
        out: list[str] = []
        for pat in self._paths:
            matches = sorted(glob.glob(pat)) if glob.has_magic(pat) else [pat]
            for p in matches:
                if not os.path.exists(p):
                    continue
                real = os.path.realpath(p)
                if real in seen:
                    continue
                seen.add(real)
                if self._vendor(p) in NEVER_VENDORS:
                    continue
                out.append(p)
        return out

    def _on_line(self, line: bytes) -> None:
        if not line.startswith(b"{"):
            # Knob log / console output is ignored, except crash and boot
            # markers: an ESP32-S3 panic or watchdog reset restarts the CPU
            # without dropping USB, so this is the only trace of it here.
            if _KNOB_ALERT.search(line):
                log.warning("[knob-usb] knob: %s",
                            line[:200].decode("utf-8", "replace").strip())
            return
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        t = msg.get("t")
        if t == "hello":
            profile = msg.get("profile")
            self.profile = profile if isinstance(profile, str) else None
            fw = msg.get("fw")
            self.fw = fw if isinstance(fw, str) else None
            if self._hello is not None:
                self._hello.set()
            # A hello mid-session means the knob (re)booted: push now.
            self._force_push = True
        elif t == "cmd":
            action = msg.get("action")
            if not isinstance(action, str) or not action:
                return
            if self.port is None:
                return                     # not identified yet
            value = msg.get("value")
            log.info("[knob-usb] command action=%s value=%r", action, value)
            task = asyncio.ensure_future(self._fire(action, value))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _fire(self, action: str, value: Any) -> None:
        try:
            await self._fire_cb(self._dispatcher, action, value, source="usb")
        except Exception as e:
            log.warning("[knob-usb] command %s failed: %s", action, e)

    async def _try_open(self, path: str) -> tuple[Optional[_Port], str]:
        """Open `path` and handshake. Returns (port, "") or (None, reason)."""
        try:
            fd = self._open(path)
        except PermissionError:
            return None, f"{path}: permission denied"
        except OSError as e:
            return None, f"{path}: {e.strerror or e}"
        loop = asyncio.get_running_loop()
        self.profile = self.fw = None
        self._hello = asyncio.Event()
        port = _Port(loop, fd, path, self._on_line)
        port.write(b'{"t":"hello"}\n')
        closed = asyncio.ensure_future(port.closed.wait())
        hello = asyncio.ensure_future(self._hello.wait())
        try:
            await asyncio.wait({closed, hello}, timeout=self._hello_timeout_s,
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            closed.cancel()
            hello.cancel()
        if port.closed.is_set():
            return None, f"{path}: {port.error or 'closed'}"
        if not self._hello.is_set():
            port.close()
            return None, f"{path}: no hello reply"
        if self.profile not in self._profiles:
            port.close()
            return None, f"{path}: not a knob (profile {self.profile!r})"
        return port, ""

    async def _discover(self) -> Optional[_Port]:
        cands = self.candidates()
        if not cands:
            self._set_status("absent", "no knob on USB (looking for "
                             + ", ".join(self._paths) + "); retrying every "
                             f"{self._retry_s:g} s")
            return None
        reasons = []
        for path in cands:
            port, why = await self._try_open(path)
            if port is not None:
                return port
            reasons.append(why)
        self._set_status("unusable:" + ";".join(reasons),
                         "knob not usable: " + "; ".join(reasons)
                         + f"; retrying every {self._retry_s:g} s",
                         logging.WARNING)
        return None

    # --- connected session ----------------------------------------------
    async def _session(self, port: _Port) -> None:
        self.port = port
        self._set_status("connected:" + port.path,
                         f"knob connected on {port.path} "
                         f"(profile {self.profile}, fw {self.fw})")
        last: Optional[bytes] = None
        last_sent = float("-inf")
        gap_warned = False
        try:
            while not port.closed.is_set():
                if self.paused():
                    self._set_status("paused", "paused: releasing the knob port "
                                     f"while {self._pause_file} exists")
                    return
                t0 = self._clock()
                try:
                    data = await self._aggregator.consolidated_state()
                    line = usb_state_line(data)
                except Exception as e:
                    log.debug("[knob-usb] state poll: %s", e)
                    line = None
                now = self._clock()
                # The knob calls the link lost after KNOB_WINDOW_S without a
                # state, so say when we get close and why (slow state fetch?).
                if (last_sent != float("-inf") and now - last_sent > GAP_WARN_S
                        and not gap_warned):
                    gap_warned = True
                    log.warning("[knob-usb] %.1f s since the last state sent "
                                "(state fetch took %.1f s%s)", now - last_sent,
                                now - t0, "" if line is not None else ", failed")
                if self._force_push:
                    self._force_push = False
                    last = None
                if line is not None and (line != last
                                         or now - last_sent >= self._resend_s):
                    if port.write(line):
                        last, last_sent = line, now
                        gap_warned = False
                try:
                    await asyncio.wait_for(port.closed.wait(), self._poll_s)
                except asyncio.TimeoutError:
                    pass
            self._set_status("unplugged", f"knob on {port.path} went away "
                             f"({port.error or 'closed'}); retrying every "
                             f"{self._retry_s:g} s")
        finally:
            port.close()
            self.port = None

    async def run(self) -> None:
        """Runs forever (or until cancelled). Never raises on device trouble."""
        try:
            while True:
                if self.paused():
                    self._set_status("paused", "paused: knob port released "
                                     f"while {self._pause_file} exists")
                    await asyncio.sleep(self._poll_s)
                    continue
                try:
                    port = await self._discover()
                except Exception as e:     # never let discovery kill the bridge
                    self._set_status(f"error:{e}", f"discovery error: {e}",
                                     logging.WARNING)
                    port = None
                if port is None:
                    await asyncio.sleep(self._retry_s)
                    continue
                await self._session(port)
                if self._status == "unplugged":
                    await asyncio.sleep(self._retry_s)
        finally:
            if self.port is not None:
                self.port.close()
            for t in list(self._tasks):
                t.cancel()


async def run_knob_usb(*, aggregator, dispatcher, fire_cb, **kw) -> None:
    """Start the USB knob bridge. Runs forever (or until cancelled)."""
    await KnobUsbBridge(aggregator=aggregator, dispatcher=dispatcher,
                        fire_cb=fire_cb, **kw).run()
