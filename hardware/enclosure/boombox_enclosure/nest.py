"""Lay panels out on sheets using straight edge-to-edge (guillotine) cuts: full-width rips, then crosscuts."""
from dataclasses import dataclass, field

from .derive import Cabinet, Panel
from .design import DesignError

SHEETS = {"4x4": (1219.2, 1219.2), "4x8": (2438.4, 1219.2)}  # w runs along the grain


@dataclass
class Placement:
    panel: Panel
    x: float  # sheet coordinates of the part's bottom-left corner
    y: float
    w: float
    h: float
    rotated: bool


@dataclass
class Band:  # one rip
    y: float
    h: float
    placements: list = field(default_factory=list)


@dataclass
class SheetLayout:
    t: float
    sheet: tuple
    index: int
    bands: list = field(default_factory=list)
    name: str = "4x4"


def nest(cab: Cabinet, *, sheet: str, gap: float, margin: float) -> list:
    if sheet not in SHEETS:
        raise DesignError(f"unknown sheet size {sheet!r}; use one of {', '.join(SHEETS)}")
    W, H = SHEETS[sheet]
    right, top = W - margin, H - margin
    layouts = []
    for t in sorted({p.t for p in cab.panels}):
        sheets = [SheetLayout(t, (W, H), 0, name=sheet)]
        for p in sorted((p for p in cab.panels if p.t == t), key=lambda p: (-p.h, -p.w)):
            shapes = [(p.w, p.h, False)] + ([(p.h, p.w, True)] if p.grain == "any" and p.w != p.h else [])
            shapes = [s for s in shapes if s[0] <= right - margin and s[1] <= top - margin]
            if not shapes:
                raise DesignError(f"{p.id} {p.name} ({p.w:g} x {p.h:g} mm) does not fit a {sheet} sheet"
                                  + ("" if p.grain == "any" else " with its grain running the long way"))
            placed = False
            for lay in sheets:  # first band with room
                for b in lay.bands:
                    x = b.placements[-1].x + b.placements[-1].w + gap
                    for w, h, rot in shapes:
                        if h <= b.h and x + w <= right:
                            b.placements.append(Placement(p, x, b.y, w, h, rot))
                            placed = True
                            break
                    if placed:
                        break
                if placed:
                    break
            if placed:
                continue
            w, h, rot = shapes[0]
            lay = sheets[-1]
            y = lay.bands[-1].y + lay.bands[-1].h + gap if lay.bands else margin
            if y + h > top:
                lay, y = SheetLayout(t, (W, H), len(sheets), name=sheet), margin
                sheets.append(lay)
            lay.bands.append(Band(y, h, [Placement(p, margin, y, w, h, rot)]))
        layouts += sheets
    return layouts


def saw_nest(cab: Cabinet) -> list:
    c = cab.design["cabinet"]
    return nest(cab, sheet=c["sheet"], gap=c["kerf"], margin=c["sheet_margin"])


def cnc_nest(cab: Cabinet) -> list:
    c = cab.design["cabinet"]
    return nest(cab, sheet=c["cnc"]["bed"], gap=c["cnc"]["bit_d"] + 6, margin=c["sheet_margin"])
