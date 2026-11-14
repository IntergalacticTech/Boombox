# Boombox Mk I — enclosure 3D model

Generated from the BBX-ENC-01 **Rev F** spec (the claude.ai artifact "Boombox Mk I ·
Enclosure Spec") — same coordinate numbers as the spec's §9 JSON. Units are **mm**,
Z-up, origin at the front-bottom-left corner of the cabinet.

| File | Use |
|---|---|
| `boombox-mk1.dae` | **SketchUp: import this one** (File → Import, set units to mm if asked). Every panel is a named component (`P5_baffle`, `P7_divider_L`, …) with its own material, so you can hide/edit parts independently. |
| `boombox-mk1.obj` | Alternate for SketchUp Pro or other tools. |
| `boombox-mk1.stl` | Universal fallback (SketchUp Web imports STL). Single merged mesh — no part separation, and not manifold as a whole (parts butt against each other); fine for viewing, not for 3D printing as-is. |

What's modeled:

- All 12 structural panels with real boolean cutouts: drivers, screen window + rear
  pocket, LED visualizer channel (10 mm deep, non-through), all 11 button holes,
  encoder shaft, aperiodic vents, door opening, RFID pocket, handle bolt holes,
  vent holes, divider wire passes.
- Hardware/cosmetics as separate parts you can hide: handle (H1), door (P9, drawn
  closed and proud of the back), drivers, screen glass, LED diffuser, volume knob,
  button caps, feet.

Not modeled: fasteners, hinge, gaskets, electronics, the Pioneer drivers' true
profile (represented as flat discs), roundovers on the outer edges.

Regenerate: `build_model.py` (this folder) builds everything with
trimesh + manifold3d; geometry constants at the top of the script mirror the
spec's cutout schedule — change the spec, change the numbers, rerun.
