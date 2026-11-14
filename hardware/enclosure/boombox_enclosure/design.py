"""Load and validate a design file. The schema below is the whole contract."""
import json
from pathlib import Path


class DesignError(ValueError):
    """A design file is malformed or describes a cabinet that cannot be built."""


OPTIONAL_PARTS = ("source_row", "encoder", "led_bar", "rfid", "handle")

# None = any JSON value; dict = nested keys, all required. "enabled" is optional on OPTIONAL_PARTS.
SCHEMA = {
    "name": None,
    "parts": {
        "driver": {"name": None, "cutout_d": None, "frame_d": None, "mount_depth": None,
                   "target_volume_l": None, "vent_d": None},
        "screen": {"name": None, "module": None, "window": None, "window_offset": None,
                   "pocket_clearance": None, "pocket_depth": None},
        "transport": {"count": None, "d": None, "pitch": None, "keys": None},
        "source_row": {"count": None, "d": None, "pitch": None, "x0": None, "keys": None},
        "encoder": {"shaft_d": None, "knob_d": None, "x_from_right": None},
        "led_bar": {"w": None, "h": None, "depth": None, "gap_above_driver": None, "slot": None},
        "rfid": {"reader": None, "pocket_clearance": None, "web": None, "cy": None},
        "handle": {"bolt_d": None, "cy": None, "tube_d": None, "length": None},
        "battery": {"name": None, "size": None},
        "door": {"opening": None, "opening_cy": None, "leaf": None,
                 "usb_c": {"d": None, "cx": None, "cy": None},
                 "exhaust": {"d": None, "cy": None, "cx_list": None}},
        "intake": {"d": None, "count": None, "pitch": None},
        "wire_pass": {"driver": {"d": None, "from_baffle": None, "cy": None},
                      "channel": {"d": None, "from_baffle": None, "cy": None}},
    },
    "cabinet": {"t_shell": None, "t_baffle": None, "chamber_h": None, "chamber_d": None, "bay_w": None,
                "bay_clearance": None, "centreline_y": None, "control_strip_h": None,
                "sheet": None, "kerf": None, "sheet_margin": None,
                "cnc": {"bit_d": None, "bed": None}, "finishes": None},
    "overrides": None,
}


def _check(value, schema, path):
    if not isinstance(value, dict):
        raise DesignError(f"{path or 'design'} must be an object")
    allowed = set(schema) | ({"enabled"} if path.split(".")[-1] in OPTIONAL_PARTS else set())
    for key in value:
        if key not in allowed:
            raise DesignError(f"unknown key {path + '.' if path else ''}{key}")
    for key, sub in schema.items():
        full = f"{path + '.' if path else ''}{key}"
        if key not in value:
            raise DesignError(f"missing key {full}")
        if isinstance(sub, dict):
            _check(value[key], sub, full)


def load_design(path) -> dict:
    try:
        design = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise DesignError(f"{path} is not valid JSON: {e}") from e
    _check(design, SCHEMA, "")
    for part in OPTIONAL_PARTS:
        design["parts"][part].setdefault("enabled", True)
    return design
