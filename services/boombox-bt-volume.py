#!/usr/bin/env python3
"""Boombox BT volume bridge — AVRCP absolute volume → bluez_input node volume.

WirePlumber 0.5 on Trixie does not propagate AVRCP 1.6 absolute-volume from a
connected phone (A2DP source) to the corresponding bluez_input node when the
Pi is the A2DP sink: BlueZ correctly updates org.bluez.MediaTransport1.Volume
(0..127) on each phone-side slider change, but the bluez5 SPA plugin does not
mirror that into the node's PipeWire volume, so the slider only mutes/unmutes.

This service listens on D-Bus for MediaTransport1.Volume PropertiesChanged
signals and reflects them onto the live bluez_input node via `wpctl set-volume`.
"""
from __future__ import annotations

import logging
import re
import subprocess

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bt-volume")

# AVRCP 1.6 absolute volume is a uint8 in [0, 127].
AVRCP_MAX = 127.0


def find_bluez_input_id() -> str | None:
    """Return the wpctl object id of the live bluez_input node, or None."""
    try:
        out = subprocess.check_output(["wpctl", "status"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    # Match either "  91. bluez_input..." or the tree-prefixed variant under Streams.
    m = re.search(r"(\d+)\.\s+bluez_input", out)
    return m.group(1) if m else None


def set_node_volume(node_id: str, vol: float) -> None:
    vol = max(0.0, min(1.0, vol))
    subprocess.run(
        ["wpctl", "set-volume", node_id, f"{vol:.3f}"],
        check=False,
        capture_output=True,
    )


def on_properties_changed(interface, changed, _invalidated, path):
    if interface != "org.bluez.MediaTransport1":
        return
    if "Volume" not in changed:
        return
    raw = int(changed["Volume"])
    node = find_bluez_input_id()
    if not node:
        log.debug("MediaTransport1.Volume=%d on %s but no live bluez_input node", raw, path)
        return
    vol = raw / AVRCP_MAX
    log.info("AVRCP %d/127 → node %s = %.3f", raw, node, vol)
    set_node_volume(node, vol)


def main() -> None:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    bus.add_signal_receiver(
        on_properties_changed,
        bus_name="org.bluez",
        signal_name="PropertiesChanged",
        dbus_interface="org.freedesktop.DBus.Properties",
        path_keyword="path",
    )
    log.info("listening for BlueZ MediaTransport1.Volume changes")
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
