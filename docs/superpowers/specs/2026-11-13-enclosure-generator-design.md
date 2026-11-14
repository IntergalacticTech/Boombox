# Enclosure generator — design

Date: 2026-11-13 · Status: draft for approval

## Intent

The Mk I enclosure plan (BBX-ENC-01 Rev F, `hardware/enclosure/build_model.py`) is a
good reference design, but it exists as one hand-written script and two claude.ai
artifacts. The owner wants to (1) build it with the screen he actually has,
(2) see it in two looks before building, and (3) hand his wife, a carpenter, cut
instructions she can work from. Later the same tool produces alternative sizes for
the public site and backs a published skill so other builders with Claude can adapt
a reference design to their own parts.

This doc covers **stage 1 only**: the generator, with Mk I as its first design.

## Goals

- One design file in, everything else out: 3D model, two finish renders, carpenter
  cut sheet, bill of materials, CNC files.
- Mk I rebuilt through the generator with the Hosyond 7" DSI screen
  (Amazon B0D3QB7X4Z) instead of the official Pi display.
- Two finishes rendered: **Classic** (silver face, black body, chrome trim, speaker
  grilles) and **Wood** (clear-finished ply or veneer, minimal hardware).
- A cut sheet a carpenter can use without the spec open beside it.
- Resizing keeps each speaker chamber at its target volume.

## Non-goals (later rounds, each its own design)

- Site gallery page (`site/`), with a rotatable 3D view and downloads.
- Alternative designs for smaller and larger screens.
- The published skill.
- An in-browser configurator.
- Other cabinet layouts (buttons on top / below the screen). Stage 1 supports the
  Mk I layout family only.

## Anti-goals

- A cut sheet that needs a second document to find a hole position.
- Output that looks authoritative about speaker tuning when it is a rule of thumb.
- Changing Mk I geometry by accident: with Rev F inputs the generator must
  reproduce Rev F.

## Constraints

- Speaker: Pioneer TS-A1671F. Pioneer publishes no T/S parameters, so the chamber
  target (12.18 L gross, sealed, Ø50 packed rear vent) is carried over from Rev F as
  a stated rule of thumb, not computed. The design file holds `target_volume_l`;
  if measured parameters ever exist, that number changes and nothing else does.
- Screen: Hosyond 7" IPS DSI, 800×480. From the Amazon listing for B0D3QB7X4Z
  (read 2026-11-13): "Module Size 164.89*102.00*12.25(mm)"; the packing-list image
  dimensions the front as 165 × 103 mm. The Pi mounts on the back on standoffs.
  This is much smaller than the official Pi display Rev F assumed (194.7 × 110.8),
  so the Rev F pocket (197 × 113) and window (185 × 101) are both too big: the
  screen would fall through the window. Mk I gets a pocket of module + 2 mm and a
  window smaller than the glass.
  Not published: active-area size and its offset within the glass (the bottom
  bezel is visibly thicker), and the mounting-hole pattern. The screen is retained
  by corner blocks in the pocket, as in Rev F, so no hole pattern is needed. The
  window size and offset are design-file inputs with a provisional default
  (155 × 87, centred) flagged "caliper before cutting" on page one of the cut
  sheet.
- Stock is 4×4 ft or 4×8 ft sheet, not the 5×5 ft Baltic birch Rev F assumed.
  Actual thickness of "1/2 in" and "3/4 in" ply varies, so thickness is an input
  and internal dimensions are the invariants (as Rev F §9 already states).
- Python deps (trimesh, manifold3d, pycollada) are not installed on this machine;
  the generator gets a `requirements.txt` and runs in a venv.
- Every hardware-coupled feature is optional (project rule): RFID pocket, LED bar,
  source-button row, encoder, handle can each be switched off in the design file
  and the outputs stay valid.

## Approaches considered

- **A. In-browser studio.** Everything computed in the page. Best for visitors
  without Claude; most work; fit rules vary too much per part set for a form.
- **B. Generator + reference designs (chosen).** Design file → outputs, iterated
  in the repo; site and skill consume the outputs later. Fastest route to a
  buildable box, and every published design is one that was actually checked.
- **C. B, then a light studio** exposing only safe controls. Left possible; not
  planned.

The owner picked B.

## Design

### Layout

```
hardware/enclosure/
  boombox_enclosure/       the generator (Python package)
  designs/mk1.json         Mk I + Hosyond screen
  out/mk1/                 generated; committed so the site can link to it later
  requirements.txt
  README.md                updated
  build_model.py           deleted once the generator reproduces it
```

Run: `python -m boombox_enclosure designs/mk1.json` writes `out/mk1/`.

### Design file

Built on the shape of Rev F §9. Three blocks:

- `parts`: driver (cutout Ø, mount depth, frame Ø, `target_volume_l`), screen
  (module w/h/t, window w/h), RFID reader, buttons, encoder, LED bar, battery,
  handle. Each optional part has `"enabled": true|false`.
- `cabinet`: sheet thicknesses (shell, baffle), chamber depth, bay width, sheet
  size (`4x4` | `4x8`), kerf, finish list.
- `overrides`: explicit cutout positions where the derived default is not wanted.

### Derivation (one layout family)

Chamber | bay | chamber, control strip across the top, as Mk I. Derived, in order:

Inputs (in `cabinet`, all with Rev F values as defaults): chamber height (282),
chamber depth (180), driver/screen centreline height (140), LED-bar gap above the
driver frame (22), control-strip height (42), bay side clearance around the screen
module, bay width (210). Bay width is an input, not derived, because the bay also
holds the battery, Pi and amp; the run fails if it is narrower than the screen
module plus clearance. The LED bar sits inside the chamber height, as in Rev F;
only the control strip is above the chamber ceiling.

1. Screen pocket = screen module + 2 mm; window from the design file.
2. Chamber width = `target_volume_l` ÷ (chamber height × depth), rounded to the
   mm. This is the "maintains the speaker math" rule: change chamber height or
   depth and chamber width moves to hold volume.
3. Panels (sizes from internal dims + thicknesses), then cutouts placed on
   centrelines.
4. Checks that fail the run with a plain message: driver frame wider than its
   chamber, driver mount depth plus clearance exceeding chamber depth, cutouts
   overlapping or closer than 10 mm to a panel edge, any panel bigger than the
   sheet.

### Outputs

**3D model.** `model.glb` (per-part named meshes and materials, one file per
finish), plus `.dae` and `.stl` as today. `render-<finish>-front.png` and
`-back.png` for each finish.

**Finishes.** A finish is a material map plus cosmetic parts and their BOM lines:

| | Classic | Wood |
|---|---|---|
| Body | black | clear-finished birch / walnut veneer |
| Face | brushed silver | same wood |
| Speakers | chrome ring + black mesh grille | exposed driver, thin black ring |
| Controls | chrome caps, silver knob | black caps, wood or brass knob |
| Handle | chrome tube | leather strap |

Grilles and trim that need mounting holes add those holes to the baffle.

**Carpenter cut sheet** (`cut-sheet.html`, prints to letter paper). Replaces the
artifact. What the old one got wrong, and the fix:

| Old sheet | New sheet |
|---|---|
| mm only | fractional inches (nearest 1/32) first, mm in brackets |
| 5×5 ft Baltic birch | 4×4 or 4×8, chosen in the design file |
| hole positions in a separate document, in assembled-face coordinates ("subtract 12") | one drawing per panel, every feature dimensioned from that panel's own bottom-left corner, with the up face and grain arrow marked |

Contents: page 1 shopping list and "measure before you cut" box; one to-scale
diagram per sheet showing each part lying on it (the "layover"); numbered
rip-then-crosscut order for a table or track saw; then one page per panel.

```
 12 mm ply, 48 × 48 in                 grain →
 ┌───────────────────────────────────────────┐
 │ P6 back 28⅛ × 13¼ │ P3 side │ P4 side│░░░░│  rip 1
 ├───────────────────┴─────────┴────────┴────┤
 │ P7 │ P8 │ P9 door │ P11 ceil │ P12 ceil│░░│  rip 2
 ├────┴────┴─────────┴──────────┴─────────┴──┤
 │ P1 top 29 1/16 × 8¼              │░░░░░░░░│  rip 3
 ├──────────────────────────────────┴────────┤
 │ P2 bottom 29 1/16 × 8¼           │░░░░░░░░│  rip 4
 ├───────────────────────────────────────────┤
 │░░░░░░░░░░░░░░░░ offcut ░░░░░░░░░░░░░░░░░░░│
 └───────────────────────────────────────────┘
```

The nest uses straight edge-to-edge cuts only, keeps grain running one way on
every visible part, and reports sheets needed per thickness. (Rough check: Mk I's
12 mm parts fit one 4×4; the 18 mm baffle needs its own piece.)

**CNC files** (`cnc/`). One DXF per sheet, same nest as the cut sheet, true scale
in mm. Layers by operation: `CUT_THROUGH`, `POCKET_<depth>mm`, `DRILL_<dia>mm`.
Panels machined from both faces (baffle: screen pocket from the rear, LED channel
from the front; top: RFID pocket from the underside) get a second DXF for the
flip side, mirrored, with two registration holes common to both. No toolpaths or
G-code: the CNC operator's CAM software does that.

**Bill of materials** (`bom.md`). Sheet goods with quantities, then parts from the
design file, then per-finish hardware.

### Checking

- A test loads `designs/mk1-revf.json` (Rev F inputs, official Pi screen, 12/18 mm)
  and asserts the Rev F panel sizes, cutout centres and 12.18 L chamber volume.
- A test asserts every nested part lies inside its sheet and no two overlap.
- The renders are looked at by eye before stage 1 is called done.

## Decisions made on the owner's behalf (correct any of these)

1. "Layover on a sheet" = a to-scale diagram of the sheet with the parts on it,
   not full-size paper templates to glue to the wood.
2. CNC = DXF outlines by operation, not G-code.
3. Cut sheet is inches first.
4. Stage 1 is the Mk I layout only; "buttons on top / below the screen" come with
   the alternative designs.
5. Classic finish adds grilles and trim as real parts, not just colour.
6. `build_model.py` is replaced, not kept alongside.
7. The Rev F reproduction test passes from the inputs above with an empty
   `overrides` block; needing an override to match Rev F is a failing test.
8. A finish never changes cut geometry. The Classic silver face is paint, wrap or
   thin laminate on the baffle, not a separate face plate. There is one cut sheet;
   the shopping list has a per-finish section. Wood defaults to the same Baltic
   birch, clear-finished; veneer is a noted option.
9. Grille and driver screw holes are not drilled by the generator. The cut sheet
   says "mark from the part", as Rev F does for the Pioneer template.
10. The saw nest and the CNC nest are separate: the CNC nest spaces parts by
    cutter diameter + margin (default 6.35 mm bit, 4×4 ft bed), set in the design
    file. The saw cut sheet is the primary deliverable.

## Left to the builder

Package internals, the nesting algorithm (any guillotine packer that honours
grain), render method (offscreen GLB render or a headless-browser screenshot of a
local viewer page), DXF writer choice, exact inch rounding.

## Answered by the owner (2026-11-13)

1. Sheet diagram confirmed: his wife uses a tool that shows a plywood sheet with
   the part boxes outlined. A visualization, not a template.
2. Build one uses the standard encoder + Ø45 knob (Rev F C17). The CrowPanel knob
   is not in this box.
3. The transport row's "spare" becomes the power button (GPIO 27 + J2).
4. Work happens on a new branch off `main`, after `feat/rotary-knob` is merged.

## Still open

- Caliper the screen's visible picture area and where it sits in the glass, to
  replace the provisional window size before cutting.
