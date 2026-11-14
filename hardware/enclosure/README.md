# Boombox enclosure generator

One design file in, everything needed to build the box out.

```bash
cd hardware/enclosure
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python -m boombox_enclosure designs/mk1.json                  # writes out/mk1/
.venv/bin/python -m pytest                                              # checks
```

## What comes out (`out/<design>/`)

| File | Who it is for |
|---|---|
| `cut-sheet.html` | **The carpenter.** Shopping list, a picture of each plywood sheet with the parts outlined on it, numbered rip and crosscut order, then one drawing per panel with every hole measured from that panel's own corner. Inches first, mm in brackets. Prints to letter paper. |
| `bom.md` | Materials list: sheet goods, parts, and the extra hardware for each finish. |
| `cnc/sheet-*-front.dxf`, `-back.dxf` | **A CNC shop.** True-scale mm outlines, one file per sheet, layers by operation: `CUT_THROUGH`, `POCKET_<depth>mm`, `DRILL_<dia>mm`. Panels machined from both faces get a `-back` file, mirrored left to right, sharing two `REGISTRATION` holes with the front. Run the back file first: the front file cuts the parts free. No toolpaths: the shop's CAM adds those (and dog-bones any square inside corner). |
| `viewer.html` + `model-<finish>.glb` | Rotate the box in a browser and switch finishes. Serve the folder (`python3 -m http.server --directory out/mk1`); needs the internet for the viewer script. |
| `model.dae`, `model.stl` | SketchUp (import the `.dae`: every panel is a named part) and anything else. |
| `render-*.png` | Stills of each finish, written with `--render` (needs the `agent-browser` CLI). |

## Designs

- `designs/mk1.json`: the Mk I with the Hosyond 7" DSI screen. This is the one to build.
- `designs/mk1-revf.json`: the original Rev F numbers (official Pi display). Kept as the reference the tests
  check the generator against; do not build from it.

To make a variant, copy a design file, change the parts or cabinet numbers, and run it. The generator
refuses designs that cannot be built (screen falls through its window, driver does not fit its chamber,
cutouts collide, run off a panel or cut into a divider or chamber, a pocket too deep, a panel bigger than the
sheet) and says which number is wrong. It does not check that the electronics fit in the bay.

What moves when you change things: inside dimensions are fixed inputs; outside dimensions follow from them
plus the sheet thicknesses. Chamber width is worked out from `target_volume_l` so that changing chamber
height or depth keeps each speaker's air volume the same. Every optional part (`rfid`, `led_bar`,
`source_row`, `encoder`, `handle`) has `"enabled"`; switch one off and its cutouts, 3D part and BOM line go.

## Two things to know before cutting

- **The chamber volume is a rule of thumb.** Pioneer publishes no parameters for the TS-A1671F, so 12.2 L
  sealed per speaker is carried over from the Mk I spec, with the packed rear vents as the by-ear adjustment.
  If the driver is ever measured, change `target_volume_l` and regenerate.
- **Caliper the screen.** The pocket comes from the maker's published module size (164.89 × 102.00 mm).
  The window size (155 × 87 mm, centred) is provisional: measure the visible picture area and where it sits
  in the glass, set `window` and `window_offset`, and regenerate.

Finishes (`classic`, `wood`) only change colours, cosmetic parts and the BOM. They never change what is cut.
