"""Async reader loop for a HID-keyboard RFID device.

Cheap USB RFID readers (vendor 'IC Reader IC Reader', etc.) present as a
standard HID keyboard. When a card is tapped they type the decimal UID
followed by KEY_ENTER. We grab the device exclusively (EVIOCGRAB) so the
digits don't leak to the kiosk's focused window.

read_uids(device_path) is an async generator yielding UID strings.
auto_detect_device() returns the first /dev/input/by-id alias that looks
like an RFID reader, or None.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import struct
from typing import AsyncGenerator, Optional

log = logging.getLogger("boombox-rfid.reader")

# struct input_event from <linux/input.h>: timeval (long sec, long usec)
# + uint16 type + uint16 code + int32 value. On 64-bit Linux long = 8 bytes.
_EVENT_FMT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)

EV_KEY = 0x01
KEY_DOWN = 1

# linux/input-event-codes.h
_KEY_TO_CHAR = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
}
_KEY_ENTER = 28
_KEY_KPENTER = 96

# EVIOCGRAB ioctl number — _IOW('E', 0x90, int).
# See <linux/input.h>. Hard-coded for portability without ctypes.
EVIOCGRAB = 0x40044590


def auto_detect_device(by_id_dir: str = "/dev/input/by-id") -> Optional[str]:
    """Return the first /dev/input/by-id alias for an RFID reader.

    Matches any *-event-kbd whose path contains 'IC_Reader' (case-insensitive).
    Tweak the substring set if you bring in a differently-branded reader.
    """
    aliases = sorted(glob.glob(f"{by_id_dir}/*-event-kbd"))
    for a in aliases:
        if "ic_reader" in a.lower() or "rfid" in a.lower():
            return a
    return None


async def read_uids(
    device_path: str,
    grab_exclusive: bool = True,
) -> AsyncGenerator[str, None]:
    """Yield UID strings (decimal digits) as cards are tapped.

    Opens device_path read-only, EVIOCGRAB so the keystrokes don't leak,
    and accumulates digit keypresses until KEY_ENTER. Non-digit / non-enter
    keys are ignored. Reader auto-reopens on EIO (USB unplug + replug).
    """
    while True:
        try:
            fd = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            log.warning("device %s not present yet; retrying in 5s", device_path)
            await asyncio.sleep(5)
            continue
        log.info("opened RFID device %s", device_path)
        try:
            if grab_exclusive:
                try:
                    import fcntl
                    fcntl.ioctl(fd, EVIOCGRAB, 1)
                    log.info("grabbed RFID device exclusively (EVIOCGRAB)")
                except OSError as e:
                    log.warning("EVIOCGRAB failed (%s); keystrokes may leak to kiosk", e)

            loop = asyncio.get_running_loop()
            buf = bytearray()
            digits: list[str] = []
            while True:
                try:
                    chunk = await loop.run_in_executor(None, os.read, fd, _EVENT_SIZE * 16)
                except OSError as e:
                    log.warning("read failed (%s); reopening", e)
                    break
                if not chunk:
                    await asyncio.sleep(0.05)
                    continue
                buf.extend(chunk)
                while len(buf) >= _EVENT_SIZE:
                    _, _, ev_type, code, value = struct.unpack(
                        _EVENT_FMT, bytes(buf[:_EVENT_SIZE])
                    )
                    del buf[:_EVENT_SIZE]
                    if ev_type != EV_KEY or value != KEY_DOWN:
                        continue
                    ch = _KEY_TO_CHAR.get(code)
                    if ch is not None:
                        digits.append(ch)
                        continue
                    if code in (_KEY_ENTER, _KEY_KPENTER) and digits:
                        uid = "".join(digits)
                        digits.clear()
                        yield uid
        finally:
            try: os.close(fd)
            except OSError: pass
            log.info("closed RFID device; reopening in 2s")
            await asyncio.sleep(2)
