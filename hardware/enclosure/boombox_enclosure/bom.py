"""Bill of materials as Markdown: sheet goods, parts from the design file, then hardware per finish."""
from .cutsheet import SHEET_FT, dim, ply
from .derive import Cabinet
from .finishes import FINISHES


def render_bom(cab: Cabinet, layouts: list) -> str:
    parts, c = cab.design["parts"], cab.design["cabinet"]
    on = {k: parts[k]["enabled"] for k in ("source_row", "encoder", "led_bar", "rfid", "handle")}
    drv, scr = parts["driver"], parts["screen"]
    buttons = parts["transport"]["count"] + (parts["source_row"]["count"] if on["source_row"] else 0)
    W, H, D = cab.outer

    o = [f"# {cab.name} — bill of materials", "",
         f"Finished box {dim(W)} × {dim(H)} × {dim(D)} (W × H × D). Speaker chambers: "
         f"{drv['target_volume_l']:.1f} L sealed each (rule of thumb, driver parameters unpublished).", "",
         "## Sheet goods", "", "| Qty | Item |", "|---|---|"]
    by_t = {}
    for lay in layouts:
        by_t[lay.t] = by_t.get(lay.t, 0) + 1
    o += [f"| {n} | {ply(t)}, {SHEET_FT[layouts[0].name]} |" for t, n in sorted(by_t.items())]

    rows = [(2, drv["name"], f"speaker driver, Ø {dim(drv['cutout_d'])} cutout"),
            (1, scr["name"], "touchscreen, {} × {} × {} mm module".format(*scr["module"])),
            (parts["transport"]["count"], f"{parts['transport']['d']} mm panel button",
             "transport: " + ", ".join(parts["transport"]["keys"]))]
    if on["source_row"]:
        s = parts["source_row"]
        rows.append((s["count"], f"{s['d']} mm LED-ring panel button", "source: " + ", ".join(s["keys"])))
    if on["encoder"]:
        e = parts["encoder"]
        rows.append((1, "Rotary encoder", f"Ø {e['shaft_d']} mm bushing; takes a Ø {e['knob_d']} mm knob"))
    if on["led_bar"]:
        led = parts["led_bar"]
        rows += [(1, "Addressable LED strip", f"{led['w'] - 7} mm long, in the front channel"),
                 (1, "Frosted acrylic diffuser, 3 mm", f"{led['w'] - 2} × {led['h'] - 2} mm")]
    if on["rfid"]:
        rows.append((1, "RFID reader", "{} × {} mm, under the top panel".format(*parts["rfid"]["reader"])))
    if on["handle"]:
        rows.append((2, "M6 × 60 post + threaded insert", "handle anchors in the divider top edges"))
    rows += [(1, parts["battery"]["name"], "power bank, {} × {} × {} mm, through the rear door".format(
                 *parts["battery"]["size"])),
             (1, "D-type USB-C panel socket", "charge inlet in the door"),
             (1, "Piano hinge + 2 magnetic catches + flush pull", "service door"),
             (6, "Rubber foot, Ø 38 mm", ""),
             (2, "Polyfill, about 100 g", "one per chamber, loose"),
             (1, "Closed-cell foam tape, 10 × 3 mm", "under the driver flanges and around the screen pocket"),
             (2, f"Vent screen + packing, Ø {drv['vent_d']} mm", "rear vents; start with them plugged"),
             (1, "Wood glue and paintable caulk", "every chamber seam is caulked airtight")]
    o += ["", "## Parts", "", "| Qty | Item | Notes |", "|---|---|---|"]
    o += [f"| {q} | {item} | {note} |" for q, item, note in rows]
    o += ["", "Amplifier, power and wiring are not part of the enclosure design file; see the electronics "
              "section of the build docs."]

    for key in c["finishes"]:
        f = FINISHES[key]
        o += ["", f"## {f.label} finish", "", "| Qty | Item | Notes |", "|---|---|---|"]
        for item, qty, note in f.bom:
            if "handle" in item.lower() or "strap" in item.lower():
                if not on["handle"]:
                    continue
            if "knob" in item.lower() and not on["encoder"]:
                continue
            o.append(f"| {qty or buttons} | {item} | {note} |")
    return "\n".join(o) + "\n"
