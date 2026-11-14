"""CNC export: one DXF per sheet (mm, true scale), layers by operation. No toolpaths; that is the CAM's job."""
from math import pi, tan
from pathlib import Path

import ezdxf

from .derive import Cutout
from .nest import Placement

DRILL_MAX = 20  # through holes up to this diameter are drilled, not profiled
BULGE = tan(pi / 8)  # quarter-circle arc


def on_sheet(c: Cutout, pl: Placement) -> tuple:
    """Cutout centre and size in sheet coordinates (front view), turning with a rotated part."""
    w, h = (c.d, c.d) if c.kind == "circle" else (c.w, c.h)
    if pl.rotated:  # quarter turn anticlockwise: (x, y) -> (panel.h - y, x)
        return pl.x + pl.panel.h - c.cy, pl.y + c.cx, h, w
    return pl.x + c.cx, pl.y + c.cy, w, h


def _rect(msp, layer, cx, cy, w, h, r=0):
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    if r:
        pts = [(x0 + r, y0, 0), (x1 - r, y0, BULGE), (x1, y0 + r, 0), (x1, y1 - r, BULGE),
               (x1 - r, y1, 0), (x0 + r, y1, BULGE), (x0, y1 - r, 0), (x0, y0 + r, BULGE)]
    else:
        pts = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
    msp.add_lwpolyline(pts, format="xyb", close=True, dxfattribs={"layer": layer})


def _layer(c: Cutout) -> str:
    if c.depth is not None:
        return f"POCKET_{c.depth:g}mm"
    if c.kind == "circle" and c.d <= DRILL_MAX:
        return f"DRILL_{c.d:g}mm"
    return "CUT_THROUGH"


def _doc(lay, margin):
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    W, H = lay.sheet
    _rect(msp, "SHEET", W / 2, H / 2, W, H)
    for y in (margin / 2, H - margin / 2):  # on the flip axis, so both faces share them
        msp.add_circle((W / 2, y), 2, dxfattribs={"layer": "REGISTRATION"})
    return doc, msp


def write_dxfs(layouts: list, out_dir, margin: float = 10) -> list:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for lay in layouts:
        W = lay.sheet[0]
        front, fm = _doc(lay, margin)
        back, bm = _doc(lay, margin)
        has_back = False
        for b in lay.bands:
            for pl in b.placements:
                _rect(fm, "CUT_THROUGH", pl.x + pl.w / 2, pl.y + pl.h / 2, pl.w, pl.h)
                for c in pl.panel.cutouts:
                    if c.mark_only:
                        continue
                    x, y, w, h = on_sheet(c, pl)
                    msp = fm
                    if c.face == "back" and c.depth is not None:
                        msp, x, has_back = bm, W - x, True  # the sheet is flipped left to right
                    if c.kind == "circle":
                        msp.add_circle((x, y), c.d / 2, dxfattribs={"layer": _layer(c)})
                    else:
                        _rect(msp, _layer(c), x, y, w, h, c.r)
        for doc, side in ((front, "front"),) + (((back, "back"),) if has_back else ()):
            path = out_dir / f"sheet-{lay.t:g}mm-{lay.index + 1}-{side}.dxf"
            for name in {e.dxf.layer for e in doc.modelspace()}:
                if name not in doc.layers:
                    doc.layers.add(name)
            doc.saveas(path)
            paths.append(path)
    return paths
