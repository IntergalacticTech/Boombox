"""Design file -> Cabinet: panels with panel-local cutouts.

One layout family: chamber | bay | chamber, control strip across the top (Mk I).
Cabinet coordinates (mm): X width, Y depth from the front face, Z up.
Cutout coordinates are panel-local, from the panel's bottom-left as seen from its show face.
"""
from dataclasses import dataclass, field

from .design import DesignError

EDGE_MIN = 10  # mm of wood left between any cut feature and its panel edge
NESTED = {frozenset(("C3", "C4")), frozenset(("C13", "C14"))}  # window in pocket, wire slot in LED channel


@dataclass
class Cutout:
    id: str
    kind: str  # "circle" | "rect"
    cx: float
    cy: float
    d: float = 0
    w: float = 0
    h: float = 0
    r: float = 0
    depth: float | None = None  # None = through
    face: str = "front"  # "front" = show face, "back" = the other face
    note: str = ""
    mark_only: bool = False  # drawn on the cut sheet, never cut

    @property
    def box(self):
        hw, hh = (self.d / 2, self.d / 2) if self.kind == "circle" else (self.w / 2, self.h / 2)
        return self.cx - hw, self.cy - hh, self.cx + hw, self.cy + hh


@dataclass
class Panel:
    id: str
    name: str
    w: float
    h: float
    t: float
    grain: str  # "w" = grain along w, may not rotate in the nest; "any" = may rotate
    show_face: str
    origin: tuple
    plane: str  # "xz" | "xy" | "yz"
    cutouts: list = field(default_factory=list)
    mirror: bool = False  # show face looks back along the cabinet axis, so local x runs against it


@dataclass
class Cabinet:
    name: str
    outer: tuple
    chamber: tuple
    chamber_volume_l: float
    panels: list
    design: dict


def _n(x):
    x = round(x, 2)
    return int(x) if x == int(x) else x


def _circle(cid, cx, cy, d, **kw):
    return Cutout(cid, "circle", _n(cx), _n(cy), d=d, **kw)


def _rect(cid, cx, cy, w, h, r=0, **kw):
    return Cutout(cid, "rect", _n(cx), _n(cy), w=_n(w), h=_n(h), r=r, **kw)


def _row(cid, n, pitch, centre, cy, d, notes):
    x0 = centre - pitch * (n - 1) / 2
    return [_circle(cid, x0 + i * pitch, cy, d, note=notes[i] if i < len(notes) else "") for i in range(n)]


def derive(design: dict) -> Cabinet:
    parts, cab = design["parts"], design["cabinet"]
    drv, scr = parts["driver"], parts["screen"]
    t, tb = cab["t_shell"], cab["t_baffle"]
    ch, cd = cab["chamber_h"], cab["chamber_d"]
    cw = round(drv["target_volume_l"] * 1e6 / (ch * cd))
    W, H, D = _n(4 * t + 2 * cw + cab["bay_w"]), _n(3 * t + ch + cab["control_strip_h"]), _n(tb + cd + t)
    inner_h = H - 2 * t
    on = {k: parts[k]["enabled"] for k in ("source_row", "encoder", "led_bar", "rfid", "handle")}

    mw, mh = scr["module"][:2]
    clr = scr["pocket_clearance"]  # per side; a number, or [x, y]
    clr_x, clr_y = clr if isinstance(clr, list) else (clr, clr)
    ww, wh = scr["window"]
    if ww >= mw or wh >= mh:
        raise DesignError(f"screen window {ww} x {wh} must be smaller than the screen module {mw} x {mh}, "
                          "or the screen falls through")
    if drv["frame_d"] + EDGE_MIN > cw:
        raise DesignError(f"driver frame {drv['frame_d']} does not fit a {cw} wide chamber "
                          "(raise target_volume_l or lower chamber_h / chamber_d)")
    if drv["mount_depth"] + 15 > cd:
        raise DesignError(f"driver mount depth {drv['mount_depth']} needs more than the {cd} chamber depth")
    if cab["bay_w"] < mw + 2 * cab["bay_clearance"]:
        raise DesignError(f"bay width {cab['bay_w']} is narrower than the screen module {mw} plus clearance")

    cl = cab["centreline_y"]
    strip_cy = t + ch + t + cab["control_strip_h"] / 2
    drv_x = t + cw / 2

    # ── P5 baffle (local = face - t) ────────────────────────────────
    f = [
        _circle("C1", drv_x - t, cl - t, drv["cutout_d"], note="driver L"),
        _circle("C2", W - drv_x - t, cl - t, drv["cutout_d"], note="driver R"),
        _circle("M1", drv_x - t, cl - t, drv["frame_d"], mark_only=True,
                note="driver frame: mark screw holes from the driver's template"),
        _circle("M2", W - drv_x - t, cl - t, drv["frame_d"], mark_only=True,
                note="driver frame: mark screw holes from the driver's template"),
        _rect("C3", W / 2 + scr["window_offset"][0] - t, cl + scr["window_offset"][1] - t, ww, wh, r=6,
              note="screen window"),
        _rect("C4", W / 2 - t, cl - t, mw + 2 * clr_x, mh + 2 * clr_y, r=8,
              depth=scr["pocket_depth"], face="back", note="screen pocket"),
    ]
    if on["led_bar"]:
        led = parts["led_bar"]
        led_cy = cl + drv["frame_d"] / 2 + led["gap_above_driver"] + led["h"] / 2
        if led_cy + led["h"] / 2 > t + ch:
            raise DesignError(f"LED bar top ({_n(led_cy + led['h'] / 2)}) is above the chamber ceiling ({t + ch})")
        f += [_rect("C13", W / 2 - t, led_cy - t, led["w"], led["h"], r=4, depth=led["depth"],
                    note="LED channel, not through"),
              _rect("C14", W / 2 - t, led_cy - t, *led["slot"], note="LED wire slot")]
    tr = parts["transport"]
    f += _row("C5", tr["count"], tr["pitch"], W / 2 - t, strip_cy - t, tr["d"], tr["keys"])
    if on["source_row"]:
        s = parts["source_row"]
        f += [_circle("C18", s["x0"] + i * s["pitch"] - t, strip_cy - t, s["d"], note=s["keys"][i])
              for i in range(s["count"])]
    if on["encoder"]:
        e = parts["encoder"]
        f.append(_circle("C17", W - e["x_from_right"] - t, strip_cy - t, e["shaft_d"], note="volume encoder shaft"))

    # ── P6 back and P9 door (seen from the rear) ────────────────────
    door = parts["door"]
    back = [_circle("C6", drv_x - t, ch / 2, drv["vent_d"], note="vent, packed + screened"),
            _circle("C7", W - drv_x - t, ch / 2, drv["vent_d"], note="vent, packed + screened"),
            _rect("C8", W / 2 - t, door["opening_cy"] - t, *door["opening"], r=6, note="door opening")]
    leaf = [_circle("C9", door["usb_c"]["cx"], door["usb_c"]["cy"], door["usb_c"]["d"], note="USB-C charge inlet")]
    leaf += [_circle("C10", x, door["exhaust"]["cy"], door["exhaust"]["d"], note="exhaust")
             for x in door["exhaust"]["cx_list"]]

    # ── P1 top, P2 bottom (seen from above, front edge down) ────────
    top = []
    if on["rfid"]:
        r = parts["rfid"]
        top.append(_rect("C15", W / 2, r["cy"], r["reader"][0] + r["pocket_clearance"],
                         r["reader"][1] + r["pocket_clearance"], r=6, depth=_n(t - r["web"]), face="back",
                         note=f"RFID pocket, leave {r['web']} mm web"))
    if on["handle"]:
        hd = parts["handle"]
        div_x = t + cw + t / 2
        top += [_circle("C16", x, hd["cy"], hd["bolt_d"], note="handle bolt") for x in (div_x, W - div_x)]
    ik = parts["intake"]
    bottom = _row("C11", ik["count"], ik["pitch"], W / 2, D / 2, ik["d"], ["intake"] * ik["count"])

    # ── P7/P8 dividers (local x = distance from the baffle; y given as cabinet height) ──
    wp = parts["wire_pass"]
    div = [_circle("C12", wp["driver"]["from_baffle"], wp["driver"]["cy"] - t, wp["driver"]["d"],
                   note="driver wire, grommet + sealant")]
    if on["source_row"] or on["encoder"]:
        div.append(_circle("C19", wp["channel"]["from_baffle"], wp["channel"]["cy"] - t, wp["channel"]["d"],
                           note="control-channel wire pass"))

    lw, lh = door["leaf"]
    P = Panel
    panels = [
        P("P1", "Top", W, D, t, "w", "top (from above)", (0, 0, H - t), "xy", top),
        P("P2", "Bottom", W, D, t, "w", "inside (from above)", (0, 0, 0), "xy", bottom),
        P("P3", "Side L", D, inner_h, t, "w", "outside", (0, 0, t), "yz"),
        P("P4", "Side R", D, inner_h, t, "w", "outside", (W - t, 0, t), "yz"),
        P("P5", "Front baffle", W - 2 * t, inner_h, tb, "w", "front", (t, 0, t), "xz", f),
        P("P6", "Back", W - 2 * t, inner_h, t, "w", "rear", (t, D - t, t), "xz", back, mirror=True),
        P("P7", "Divider L", cd, inner_h, t, "any", "bay side", (t + cw, tb, t), "yz", list(div)),
        P("P8", "Divider R", cd, inner_h, t, "any", "bay side", (W - 2 * t - cw, tb, t), "yz", list(div)),
        P("P9", "Service door", lw, lh, t, "w", "rear", ((W - lw) / 2, D, 10), "xz", leaf, mirror=True),
        P("P11", "Chamber ceiling L", cw, cd, t, "any", "top (from above)", (t, tb, t + ch), "xy"),
        P("P12", "Chamber ceiling R", cw, cd, t, "any", "top (from above)", (W - t - cw, tb, t + ch), "xy"),
    ]
    for p in panels:
        p.w, p.h = _n(p.w), _n(p.h)

    for cid, pos in design["overrides"].items():
        hits = [c for p in panels for c in p.cutouts if c.id == cid]
        if not hits:
            raise DesignError(f"overrides.{cid}: no such cutout")
        for c in hits:
            c.cx, c.cy = pos.get("cx", c.cx), pos.get("cy", c.cy)

    for p in panels:
        cuts = [c for c in p.cutouts if not c.mark_only]
        for c in cuts:
            x0, y0, x1, y1 = c.box
            if min(x0, y0, p.w - x1, p.h - y1) < EDGE_MIN:
                raise DesignError(f"{c.id} ({c.note}) is closer than {EDGE_MIN} mm to the edge of {p.id} {p.name}")
        for i, a in enumerate(cuts):
            for b in cuts[i + 1:]:
                if frozenset((a.id, b.id)) in NESTED:
                    continue
                ax0, ay0, ax1, ay1 = a.box
                bx0, by0, bx1, by1 = b.box
                if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                    raise DesignError(f"{a.id} ({a.note}) overlaps {b.id} ({b.note}) on {p.id} {p.name}")

    return Cabinet(design["name"], (W, H, D), (cw, ch, cd), cw * ch * cd / 1e6, panels, design)
