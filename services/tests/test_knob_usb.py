"""knob_usb — the USB bridge to the rotary knob, against a fake knob on a pty.

The bridge opens the pty's slave side exactly as it would /dev/ttyACM0; the
fake knob sits on the master side, answers hello, reads state lines and can
send commands and log noise.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tty

import knob_usb
import pytest


class FakeAggregator:
    def __init__(self):
        self.state = {
            "boombox": {"id": "bb-1", "name": "MarkII", "version": 1},
            "source": "mopidy", "playing": True,
            "track": {"uri": "local:track:x.flac", "title": "A Song",
                      "artist": "Some Artist", "album": "Some Album",
                      "duration_s": 245, "position_s": 12},
            "art_url": "/local/abc.jpeg", "volume": 0.42, "shuffle": False,
            "repeat": "off", "recording": False, "mic_on": False,
            "sleep_timer_s": None, "sources_available": ["mopidy"],
            "theme": {"bg": "#000", "accent": "#f00", "font": "'Inter'"},
        }
        self.calls = 0

    async def consolidated_state(self):
        self.calls += 1
        return json.loads(json.dumps(self.state))


class FakeKnob:
    """The knob end of a pty pair."""

    def __init__(self, link_dir, name="boombox-knob", profile="crowpanel-rotary-21",
                 answer_hello=True):
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        os.set_blocking(self.master, False)
        self.path = str(link_dir / name)
        if os.path.lexists(self.path):
            os.unlink(self.path)
        os.symlink(os.ttyname(self.slave), self.path)
        self.profile = profile
        self.answer_hello = answer_hello
        self.lines: list[dict] = []
        self.hellos = 0
        self._buf = b""
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(self.master, self._readable)
        self.open = True

    def _readable(self):
        try:
            chunk = os.read(self.master, 65536)
        except OSError:
            return
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            msg = json.loads(line)
            if msg.get("t") == "hello":
                self.hellos += 1
                if self.answer_hello:
                    self._loop.create_task(self.send({"t": "hello", "profile": self.profile, "fw": "0.1.0"}))
            else:
                self.lines.append(msg)

    async def send(self, obj):
        await self.write((json.dumps(obj) + "\n").encode())

    async def write(self, raw: bytes):
        # The pty buffer is small (1 KB on macOS): yield until the bridge
        # has drained it.
        while raw:
            try:
                n = os.write(self.master, raw)
            except BlockingIOError:
                n = 0
            raw = raw[n:]
            if raw:
                await asyncio.sleep(0.005)

    @property
    def states(self):
        return [m for m in self.lines if m.get("t") == "state"]

    def unplug(self):
        if not self.open:
            return
        self.open = False
        self._loop.remove_reader(self.master)
        os.close(self.master)
        os.close(self.slave)
        if os.path.lexists(self.path):
            os.unlink(self.path)


async def until(cond, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.fixture
async def rig(tmp_path):
    knobs: list[FakeKnob] = []
    fired: list[dict] = []
    agg = FakeAggregator()

    async def fire(dispatcher, action, value=None, *, source="unknown"):
        fired.append({"action": action, "value": value, "source": source})
        return {"ok": True}

    task_box: dict = {}

    def start(paths=None, **kw):
        kw.setdefault("vendor_fn", lambda p: "303a")
        bridge = knob_usb.KnobUsbBridge(
            aggregator=agg, dispatcher=object(), fire_cb=fire,
            paths=paths if paths is not None else [str(tmp_path / "boombox-knob")],
            pause_file=str(tmp_path / "knob.pause"),
            retry_s=0.05, poll_s=0.02, resend_s=0.3, hello_timeout_s=0.3, **kw)
        task_box["t"] = asyncio.create_task(bridge.run())
        return bridge

    def knob(**kw):
        k = FakeKnob(tmp_path, **kw)
        knobs.append(k)
        return k

    class Rig:
        pass
    r = Rig()
    r.tmp, r.agg, r.fired, r.start, r.knob = tmp_path, agg, fired, start, knob
    yield r
    if "t" in task_box:
        task_box["t"].cancel()
        with pytest.raises(asyncio.CancelledError):
            await task_box["t"]
    for k in knobs:
        k.unplug()


# ---------------------------------------------------------------- payload
def test_state_line_is_compact_one_line_and_uncapped():
    long_title = "T" * 900
    line = knob_usb.usb_state_line({
        "boombox": {"id": "x"}, "art_url": "/a.jpg", "recording": False,
        "track": {"uri": "u", "title": long_title}, "volume": 0.5,
        "power": "asleep", "theme": {"bg": "#000", "font": "x"}})
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    msg = json.loads(line)
    assert msg["t"] == "state"
    d = msg["d"]
    assert d["track"] == {"title": long_title}        # no 512 B trim
    assert "boombox" not in d and "art_url" not in d and "recording" not in d
    assert d["theme"] == {"bg": "#000"}
    assert d["power"] == "asleep"                     # the knob follows it


# -------------------------------------------------------------- discovery
async def test_hello_detects_knob_and_pushes_state_at_once(rig):
    k = rig.knob()
    bridge = rig.start()
    await until(lambda: k.states)
    assert bridge.status == "connected:" + k.path
    assert bridge.profile == "crowpanel-rotary-21" and bridge.fw == "0.1.0"
    d = k.states[0]["d"]
    assert d["track"]["title"] == "A Song" and "uri" not in d["track"]
    assert d["volume"] == 0.42


async def test_wrong_profile_and_silent_devices_are_rejected(rig, caplog):
    caplog.set_level(logging.INFO, logger="boombox-remote-knob-usb")
    other = rig.knob(name="other", profile="some-other-esp32")
    mute = rig.knob(name="mute", answer_hello=False)
    bridge = rig.start(paths=[other.path, mute.path])
    await until(lambda: other.hellos >= 2 and mute.hellos >= 2)
    assert bridge.port is None
    assert bridge.status.startswith("unusable:")
    assert not other.states and not mute.states
    msgs = [r.getMessage() for r in caplog.records if "not usable" in r.getMessage()]
    assert len(msgs) == 1                     # logged once, not every retry
    assert "not a knob" in msgs[0] and "no hello reply" in msgs[0]


async def test_falls_through_path_list_to_glob(rig):
    k = rig.knob(name="usb-Espressif_USB_JTAG_serial_debug_unit_44:BD-if00")
    rig.start(paths=[str(rig.tmp / "boombox-knob"), str(rig.tmp / "*Espressif*")])
    await until(lambda: k.states)


async def test_ch340_is_never_opened(rig):
    k = rig.knob()
    opened = []

    def open_fn(path):
        opened.append(path)
        return knob_usb.open_raw(path)

    bridge = rig.start(open_fn=open_fn, vendor_fn=lambda p: "1a86")
    await until(lambda: bridge.status == "absent")
    await asyncio.sleep(0.2)
    assert opened == [] and k.hellos == 0


async def test_no_device_logs_once_and_keeps_retrying(rig, caplog):
    caplog.set_level(logging.INFO, logger="boombox-remote-knob-usb")
    bridge = rig.start(paths=[str(rig.tmp / "nope")])
    await until(lambda: bridge.status == "absent")
    await asyncio.sleep(0.3)                  # several retry periods
    absent = [r for r in caplog.records if "no knob on USB" in r.getMessage()]
    assert len(absent) == 1
    # …and it picks the knob up once it appears.
    k = rig.knob(name="nope")
    await until(lambda: k.states)


async def test_permission_denied_is_logged_once_not_raised(rig, caplog):
    caplog.set_level(logging.INFO, logger="boombox-remote-knob-usb")
    rig.knob()

    def denied(path):
        raise PermissionError(13, "Permission denied")

    bridge = rig.start(open_fn=denied)
    await until(lambda: bridge.status and "permission denied" in bridge.status)
    await asyncio.sleep(0.3)
    recs = [r for r in caplog.records if "permission denied" in r.getMessage()]
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING


# ------------------------------------------------------------------ state
async def test_change_pushes_and_unchanged_state_is_resent(rig):
    k = rig.knob()
    rig.start()
    await until(lambda: len(k.states) == 1)
    await asyncio.sleep(0.1)
    assert len(k.states) == 1                 # unchanged → no spam
    rig.agg.state["shuffle"] = True
    await until(lambda: len(k.states) == 2)
    assert k.states[1]["d"]["shuffle"] is True
    await until(lambda: len(k.states) == 3, timeout=1.0)   # resend_s = 0.3
    assert k.states[2] == k.states[1]


async def test_knob_hello_mid_session_forces_a_push(rig):
    k = rig.knob()
    rig.start()
    await until(lambda: len(k.states) == 1)
    await k.send({"t": "hello", "profile": "crowpanel-rotary-21", "fw": "0.1.0"})
    await until(lambda: len(k.states) == 2, timeout=0.25)   # before resend_s


# --------------------------------------------------------------- commands
async def test_commands_dispatch_with_usb_source_and_logs_are_ignored(rig):
    k = rig.knob()
    rig.start()
    await until(lambda: k.states)
    await k.write(b"[enc] detents=+1 raw=4\r\n")
    await k.write(b"SNAP 480 480 460800 RGB565\n")
    await k.write(b"{not json at all\n")
    await k.write(b"[1,2,3]\n")
    await k.write(b'{"t":"cmd"}\n')                 # no action
    await k.write(b"x" * 20000 + b"\n")            # overlong junk line
    await k.send({"t": "cmd", "action": "volume", "value": 0.42})
    await k.send({"t": "cmd", "action": "shuffle"})
    await until(lambda: len(rig.fired) == 2)
    assert rig.fired == [
        {"action": "volume", "value": 0.42, "source": "usb"},
        {"action": "shuffle", "value": None, "source": "usb"},
    ]


async def test_knob_crash_and_boot_lines_are_logged(rig, caplog):
    """A panic/WDT reset restarts the knob's CPU without dropping USB, so its
    console text is the only trace — surface it, but keep ordinary logs quiet."""
    k = rig.knob()
    rig.start()
    await until(lambda: k.states)
    caplog.clear()
    with caplog.at_level("WARNING"):
        await k.write(b"[enc] detents=+1 raw=4\r\n")
        await k.write(b"Guru Meditation Error: Core  1 panic'ed (LoadProhibited)\r\n")
        await k.write(b"=== boombox-remote firmware ===\r\n")
        await until(lambda: sum("knob:" in r.getMessage() for r in caplog.records) >= 2)
    msgs = [r.getMessage() for r in caplog.records if "knob:" in r.getMessage()]
    assert any("Guru Meditation" in m for m in msgs)
    assert any("=== boombox" in m for m in msgs)
    assert not any("[enc]" in m for m in msgs)


async def test_commands_after_a_partial_line_still_parse(rig):
    k = rig.knob()
    rig.start()
    await until(lambda: k.states)
    await k.write(b'{"t":"cmd","act')
    await asyncio.sleep(0.05)
    await k.write(b'ion":"next"}\n')
    await until(lambda: rig.fired)
    assert rig.fired[0]["action"] == "next"


# -------------------------------------------------------- unplug / replug
async def test_unplug_and_replug(rig, caplog):
    caplog.set_level(logging.INFO, logger="boombox-remote-knob-usb")
    k = rig.knob()
    bridge = rig.start()
    await until(lambda: k.states)
    k.unplug()
    await until(lambda: bridge.port is None and bridge.status in ("unplugged", "absent"))
    assert any("went away" in r.getMessage() for r in caplog.records)
    k2 = rig.knob()
    await until(lambda: k2.states)
    assert bridge.status == "connected:" + k2.path


# ------------------------------------------------------------ pause file
async def test_pause_file_releases_the_port_until_removed(rig):
    k = rig.knob()
    bridge = rig.start()
    await until(lambda: k.states)
    pause = rig.tmp / "knob.pause"
    pause.touch()
    await until(lambda: bridge.port is None and bridge.status == "paused")
    n = len(k.states)
    await asyncio.sleep(0.4)
    assert len(k.states) == n                 # nothing sent while paused
    pause.unlink()
    await until(lambda: len(k.states) > n)


async def test_stale_pause_file_is_ignored(rig):
    pause = rig.tmp / "knob.pause"
    pause.touch()
    old = knob_usb.time.time() - knob_usb.PAUSE_MAX_S - 10
    os.utime(pause, (old, old))
    k = rig.knob()
    rig.start()
    await until(lambda: k.states)
