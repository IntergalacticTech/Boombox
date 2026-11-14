"""Carpenter cut sheet: one self-contained HTML page (inline CSS + SVG), inches first, prints to letter."""
import math
from fractions import Fraction
from html import escape

from .derive import Cabinet, Panel

NOMINAL = {6: '1/4"', 9: '3/8"', 12: '1/2"', 15: '5/8"', 18: '3/4"'}
SHEET_FT = {"4x4": "4 × 4 ft", "4x8": "4 × 8 ft"}


def fmt_in(mm: float, up: bool = False) -> str:
    """Nearest 1/32 inch as a reduced fraction: 714 -> '28 1/8"'. up=True rounds up, for holes parts must pass."""
    n = mm / 25.4 * 32
    whole, frac = divmod(Fraction(math.ceil(round(n, 6)) if up else round(n), 32), 1)
    if not frac:
        return f'{whole}"'
    return f'{whole} {frac}"' if whole else f'{frac}"'


def dim(mm: float) -> str:
    """Inches first, mm in brackets: '28 1/8" [714]'."""
    return f"{fmt_in(mm)} [{round(mm, 1):g}]"


def ply(t: float) -> str:
    sold = next((f', sold as {n}' for mm, n in NOMINAL.items() if abs(t - mm) <= 0.75), "")
    return f"{t:g} mm ({fmt_in(t)}{sold}) plywood"


CSS = """
:root{--ink:#1b1b1b;--mute:#666;--line:#bbb;--accent:#b4530a;--paper:#fff;--part:#fdf6e9}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);}
body{font:15px/1.45 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:8in;margin:0 auto;padding:24px 16px 64px}
h1{font-size:28px;margin:0 0 4px}
h2{font-size:20px;margin:36px 0 8px;border-bottom:2px solid var(--ink);padding-bottom:4px}
h3{font-size:17px;margin:0 0 2px}
.sub{color:var(--mute);margin:0 0 12px}
table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
td:last-child{min-width:9.5em}
td.n,.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.warn{border:2px solid var(--accent);border-radius:6px;padding:10px 14px;margin:16px 0}
.warn strong{color:var(--accent)}.warn ul{margin:6px 0 0;padding-left:20px}
svg{width:100%;height:auto;display:block;font-family:inherit}
.sheet-diagram,.panel-drawing{margin:20px 0 28px}
.cut-step.rip td{font-weight:600;border-top:2px solid var(--ink)}
.cut-step.trim td{color:var(--accent)}
.key{font-size:13px;color:var(--mute);margin:4px 0 0}
.wide{overflow-x:auto}
@media print{@page{size:letter;margin:.5in}main{max-width:none;padding:0}
 .sheet-diagram,.panel-drawing,.cuts{break-before:page}.panel-drawing,.sheet-diagram{break-inside:avoid}
 h2{break-after:avoid}.wide{overflow:visible}}
"""


def _sheet_svg(lay, n: int) -> str:
    W, H = lay.sheet
    pad, right = 70, 190
    o = [f'<svg viewBox="{-pad} {-pad} {W + pad + right} {H + 2 * pad}" role="img" '
         f'aria-label="Sheet {n}: where each part lies on the plywood">',
         f'<defs><pattern id="off{n}" width="24" height="24" patternUnits="userSpaceOnUse" '
         'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="24" stroke="#c9c9c9" stroke-width="5"/>'
         '</pattern></defs>',
         f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#off{n})" stroke="#1b1b1b" stroke-width="4"/>',
         f'<text x="{W / 2}" y="-22" text-anchor="middle" font-size="34" font-weight="600">'
         f'{fmt_in(W)} × {fmt_in(H)} sheet</text>']
    for i, b in enumerate(lay.bands, 1):
        y = H - b.y - b.h
        o.append(f'<text x="{W + 18}" y="{y + b.h / 2 + 12}" font-size="32" font-weight="600" fill="#b4530a">'
                 f'rip {i}</text>'
                 f'<text x="{W + 18}" y="{y + b.h / 2 + 46}" font-size="24" fill="#666">{fmt_in(b.h)}</text>')
        for p in b.placements:
            px, py = p.x, H - p.y - p.h
            o.append(f'<rect x="{px:g}" y="{py:g}" width="{p.w:g}" height="{p.h:g}" fill="#fdf6e9" '
                     'stroke="#1b1b1b" stroke-width="3"/>')
            cx, cy = px + p.w / 2, py + p.h / 2
            narrow = p.w < 300
            lines = [(p.panel.id, 44, 700), (p.panel.name, 24, 400)]
            lines += [(fmt_in(p.w), 26, 400), ("× " + fmt_in(p.h), 26, 400)] if narrow else \
                     [(f"{fmt_in(p.w)} × {fmt_in(p.h)}", 28, 400)]
            if p.rotated:
                lines.append(("(turned)", 20, 400))
            y0 = cy - sum(s for _, s, _ in lines) * 0.6 + 26
            for text, size, weight in lines:
                o.append(f'<text x="{cx:g}" y="{y0:g}" text-anchor="middle" font-size="{size}" '
                         f'font-weight="{weight}">{escape(text, quote=False)}</text>')
                y0 += size * 1.25
    o.append(f'<path d="M {W * .3} {H + 34} H {W * .7} m -22 -12 l 22 12 l -22 12" fill="none" stroke="#1b1b1b" '
             f'stroke-width="4"/><text x="{W * .28}" y="{H + 45}" text-anchor="end" font-size="28">grain</text>')
    o.append("</svg>")
    return "".join(o)


def _depth(c) -> str:
    if c.mark_only:
        return "mark only, do not cut"
    if c.depth is None:
        return "through"
    return f"{dim(c.depth)} deep" + (", from the back face" if c.face == "back" else ", not through")


def _size(c) -> str:
    if c.kind == "circle":
        return f"Ø {fmt_in(c.d, up=True)} [{c.d:g}]"
    return f"{dim(c.w)} × {dim(c.h)}" + (f", corners R {fmt_in(c.r)}" if c.r else "")


def _panel_svg(p: Panel) -> str:
    s = max(p.w, p.h) / 700  # text and stroke scale so every drawing reads the same on paper
    pad = 62 * s
    fs = 15 * s
    vw, vh = p.w + 2 * pad, p.h + pad * 1.9
    tall = 440 if p.cutouts else 230  # px; keeps tall narrow panels from filling a page
    o = [f'<svg viewBox="{-pad:g} {-pad * .8:g} {vw:g} {vh:g}" '
         f'style="max-width:{min(760, tall * vw / vh):.0f}px" role="img" '
         f'aria-label="{p.id} {escape(p.name)} with its cutouts">',
         f'<rect x="0" y="0" width="{p.w:g}" height="{p.h:g}" fill="#fdf6e9" '
         f'stroke="#1b1b1b" stroke-width="{2.4 * s:g}"/>']
    labelled = set()
    for c in p.cutouts:
        y = p.h - c.cy
        dash = f' stroke-dasharray="{2 * s:g} {3 * s:g}"' if c.mark_only else \
            f' stroke-dasharray="{8 * s:g} {5 * s:g}"' if c.face == "back" else ""
        fill = "none" if c.mark_only or c.face == "back" else "#fff" if c.depth is None else "#e6dcc8"
        style = f'fill="{fill}" stroke="#1b1b1b" stroke-width="{1.6 * s:g}"{dash}'
        if c.kind == "circle":
            o.append(f'<circle cx="{c.cx:g}" cy="{y:g}" r="{c.d / 2:g}" {style}/>')
            small = c.d < 60
        else:
            o.append(f'<rect x="{c.cx - c.w / 2:g}" y="{y - c.h / 2:g}" width="{c.w:g}" height="{c.h:g}" '
                     f'rx="{c.r:g}" {style}/>')
            small = c.h < 30
        if not c.mark_only and c.id not in labelled:  # a row of identical holes is labelled once
            labelled.add(c.id)
            ty = y - (c.d / 2 if c.kind == "circle" else c.h / 2) - 5 * s if small else y + fs * .35
            if c.face == "back":
                ty = y - c.h / 2 + fs * 1.1
            if c.id == "C14":  # sits inside the LED channel, whose label is above
                ty = y + c.h / 2 + fs * 1.1
            o.append(f'<text x="{c.cx:g}" y="{ty:g}" text-anchor="middle" font-size="{fs:g}" font-weight="600">'
                     f'{c.id}</text>')
    yb = p.h + 26 * s  # overall width, below
    o.append(f'<path d="M 0 {yb:g} H {p.w:g} M 0 {yb - 7 * s:g} v {14 * s:g} M {p.w:g} {yb - 7 * s:g} v {14 * s:g}" '
             f'stroke="#666" stroke-width="{1.2 * s:g}" fill="none"/>'
             f'<text x="{p.w / 2:g}" y="{yb + 20 * s:g}" text-anchor="middle" font-size="{fs * 1.15:g}">'
             f'{dim(p.w)}</text>')
    xl = -24 * s  # overall height, left
    o.append(f'<path d="M {xl:g} 0 V {p.h:g} M {xl - 7 * s:g} 0 h {14 * s:g} M {xl - 7 * s:g} {p.h:g} h {14 * s:g}" '
             f'stroke="#666" stroke-width="{1.2 * s:g}" fill="none"/>'
             f'<text transform="translate({xl - 9 * s:g} {p.h / 2:g}) rotate(-90)" text-anchor="middle" '
             f'font-size="{fs * 1.15:g}">{dim(p.h)}</text>')
    o.append(f'<circle cx="0" cy="{p.h:g}" r="{5 * s:g}" fill="#b4530a"/>'
             f'<text x="{4 * s:g}" y="{p.h + 62 * s:g}" font-size="{fs:g}" fill="#b4530a">'
             '● measure every position from this corner</text>')
    up = "BACK OF BOX" if p.plane == "xy" else "UP"
    ax = p.w + 30 * s
    o.append(f'<path d="M {ax:g} {p.h * .5 + 40 * s:g} V {p.h * .5 - 40 * s:g} m {-9 * s:g} {14 * s:g} l {9 * s:g} '
             f'{-14 * s:g} l {9 * s:g} {14 * s:g}" fill="none" stroke="#1b1b1b" stroke-width="{2 * s:g}"/>'
             f'<text transform="translate({ax + 20 * s:g} {p.h * .5:g}) rotate(90)" text-anchor="middle" '
             f'font-size="{fs:g}" font-weight="600">{up}</text>')
    if p.grain == "w":
        gy = -22 * s
        o.append(f'<path d="M {p.w * .38:g} {gy:g} H {p.w * .62:g} m {-12 * s:g} {-7 * s:g} l {12 * s:g} {7 * s:g} '
                 f'l {-12 * s:g} {7 * s:g}" fill="none" stroke="#666" stroke-width="{1.6 * s:g}"/>'
                 f'<text x="{p.w * .36:g}" y="{gy + 5 * s:g}" text-anchor="end" font-size="{fs:g}" fill="#666">'
                 'grain</text>')
    o.append("</svg>")
    return "".join(o)


EDGE_NOTE = {"yz": "Left edge is the front of the box.", "xy": "Bottom edge is the front of the box.", "xz": ""}


def _panel_section(p: Panel) -> str:
    o = [f'<section class="panel-drawing"><h3>{p.id} · {escape(p.name)}</h3>',
         f'<p class="sub">{dim(p.w)} × {dim(p.h)}, {ply(p.t)}. Drawn looking at the {escape(p.show_face)} face. '
         f'{EDGE_NOTE[p.plane]}</p>', _panel_svg(p)]
    if not p.cutouts:
        o.append('<p class="key">No cutouts. Cut to size only.</p></section>')
        return "".join(o)
    if any(c.face == "back" for c in p.cutouts):
        o.append('<p class="key">Dashed outline = machined from the back face. Flip the panel side to side; '
                 'positions are still given as seen in this drawing.</p>')
    o.append('<div class="wide"><table><tr><th>ID</th><th>What</th><th>From left</th><th>From bottom</th>'
             '<th>Size</th><th>Depth</th></tr>')
    for c in sorted(p.cutouts, key=lambda c: (c.mark_only, int(c.id[1:]), c.cx)):
        o.append(f'<tr><td>{c.id}</td><td>{escape(c.note)}</td><td class="n">{dim(c.cx)}</td>'
                 f'<td class="n">{dim(c.cy)}</td><td class="n">{_size(c)}</td><td>{_depth(c)}</td></tr>')
    o.append("</table></div></section>")
    return "".join(o)


def render_cut_sheet(cab: Cabinet, layouts: list) -> str:
    c = cab.design["cabinet"]
    W, H, D = cab.outer
    vol = cab.design["parts"]["driver"]["target_volume_l"]
    by_t = {}
    for lay in layouts:
        by_t[lay.t] = by_t.get(lay.t, 0) + 1
    o = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         f"<title>{escape(cab.name)} · Cut Sheet</title><style>{CSS}</style></head><body><main>",
         f"<h1>{escape(cab.name)} — cut sheet</h1>",
         f'<p class="sub">Finished box {dim(W)} wide × {dim(H)} tall × {dim(D)} deep. '
         f"Speaker chambers: {vol:.1f} L sealed each (rule of thumb, driver parameters unpublished). "
         "All sizes are finished sizes, inches first with millimetres in brackets.</p>",
         "<h2>1 · What to buy</h2><table><tr><th>Qty</th><th>Sheet</th><th>Makes</th></tr>"]
    for t, n in sorted(by_t.items()):
        ids = sorted({p.panel.id for lay in layouts if lay.t == t for b in lay.bands for p in b.placements},
                     key=lambda i: int(i[1:]))
        need = ""
        if n == 1:  # say how small a piece would do, so nobody buys a full sheet for one panel
            ps = [p for lay in layouts if lay.t == t for b in lay.bands for p in b.placements]
            m = c["sheet_margin"]
            used = fmt_in(max(p.x + p.w for p in ps) + m), fmt_in(max(p.y + p.h for p in ps) + m)
            need = f"<br>Uses {used[0]} × {used[1]} of it."
        o.append(f'<tr><td class="n">{n}</td><td>{ply(t)}, {SHEET_FT[layouts[0].name]}{need}</td>'
                 f'<td>{", ".join(ids)}</td></tr>')
    o.append("</table>")
    o.append('<div class="warn"><strong>Before the first cut</strong><ul>'
             "<li>Measure your actual plywood thickness. If it is not what this sheet says, tell whoever made "
             "the design file and regenerate: the inside sizes stay fixed and the outside sizes move.</li>"
             "<li>Caliper the screen's picture area before cutting the window (C3). The window size here is "
             "provisional; the pocket (C4) is from the maker's published module size.</li>"
             "<li>Hole sizes in inches are rounded up to the next 1/32\". Use the metric bit if you have it.</li>"
             "<li>Check the thread length of the buttons and the volume knob's bushing against "
             f"the {cab.panels[4].t:g} mm front. Where a thread is too short to take its nut, counterbore from the back.</li>"
             "<li>Speaker screw holes are marked from the driver's own template, not from this sheet.</li>"
             f"<li>Rips are spaced for a {fmt_in(c['kerf'])} [{c['kerf']:g}] blade. Rip a hair fat and trim to the "
             "number.</li></ul></div>")

    o.append("<h2>2 · Sheet layouts</h2>")
    step, cuts = 0, []
    for n, lay in enumerate(layouts, 1):
        o.append(f'<section class="sheet-diagram"><h3>Sheet {n} · {ply(lay.t)}</h3>'
                 '<p class="sub">Hatched area is offcut. Grain runs left to right on every part.</p>'
                 f"{_sheet_svg(lay, n)}</section>")
        cuts.append(f'<tr><th colspan="3">Sheet {n} · {ply(lay.t)}</th></tr>')
        step += 1
        cuts.append(f'<tr class="cut-step prep"><td class="n">{step}</td><td>Square up</td><td>Trim the bottom and '
                    f'left factory edges square, about {fmt_in(c["sheet_margin"])} off each.</td></tr>')
        for i, b in enumerate(lay.bands, 1):
            step += 1
            cuts.append(f'<tr class="cut-step rip"><td class="n">{step}</td><td>Rip {i}</td>'
                        f"<td>Rip a strip {dim(b.h)} wide off the sheet.</td></tr>")
            for p in b.placements:
                step += 1
                cuts.append(f'<tr class="cut-step cross"><td class="n">{step}</td><td>Crosscut</td>'
                            f"<td>{dim(p.w)} → <b>{p.panel.id}</b> {escape(p.panel.name)}</td></tr>")
                if p.h < b.h:
                    step += 1
                    cuts.append(f'<tr class="cut-step trim"><td class="n">{step}</td><td>Trim</td>'
                                f"<td>Rip {p.panel.id} down to {dim(p.h)}.</td></tr>")
    o.append('<h2 class="cuts">3 · Cut order</h2><p class="sub">Every cut runs edge to edge, so a table saw or '
             "track saw does all of it. Pencil the ID and an UP arrow on each part as it comes off.</p>"
             f'<table><tr><th>#</th><th>Cut</th><th>To</th></tr>{"".join(cuts)}</table>')

    o.append("<h2>4 · Panels</h2><p class=\"sub\">One drawing per panel. Every position is the centre of the "
             "feature, measured from that panel's own bottom-left corner as drawn. Machine all cutouts flat on "
             "the bench before glue-up.</p>")
    o += [_panel_section(p) for p in cab.panels]
    o.append("</main></body></html>")
    return "".join(o)
