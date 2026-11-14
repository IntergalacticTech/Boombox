# Enclosure Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One design file (`designs/mk1.json`) in; 3D model in two finishes, carpenter cut sheet, BOM and CNC DXFs out.

**Architecture:** A small Python package under `hardware/enclosure/`. `derive` turns a design file into a `Cabinet` (panels with panel-local cutouts); every output module (`model`, `nest`, `cutsheet`, `dxf`, `bom`) reads only the `Cabinet`. The existing hand-written `build_model.py` is the reference the first tests are checked against, then deleted.

**Tech Stack:** Python ≥ 3.11, trimesh + manifold3d (solids, GLB/STL), pycollada (DAE), ezdxf (DXF), pytest. No web framework; the cut sheet is one self-contained HTML file with inline SVG.

**Spec:** `docs/superpowers/specs/2026-11-13-enclosure-generator-design.md`

## Global Constraints

- Work on branch `feat/enclosure-generator`, cut from `main` after PR #49 is merged.
- All paths below are relative to `hardware/enclosure/`. Tests run with `cd hardware/enclosure && .venv/bin/python -m pytest tests -q`.
- Venv: `python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt` (system python is 3.9; `.venv/` is already git-ignored).
- Repo CI runs `ruff check .` (py311, line length 120, rules E/F/W/I) over these files. Run `ruff check hardware/enclosure` before each commit.
- Units are mm everywhere in code. Inches exist only in `cutsheet.py` formatting.
- Internal dimensions are the invariants; sheet thicknesses are inputs.
- Every optional part (`rfid`, `led_bar`, `source_row`, `encoder`, `handle`) has `"enabled"`; when false it produces no cutouts, no 3D part, no BOM line, and every output still generates.
- A finish never changes cut geometry.
- With `designs/mk1-revf.json` and an empty `overrides` block the generator reproduces Rev F exactly (values in Task 1).
- The chamber volume target is a rule of thumb for an unmeasured driver. The cut sheet and BOM say "12.2 L sealed (rule of thumb, driver parameters unpublished)", never "tuned".
- Screen window default for `mk1.json` is provisional; the cut sheet's page-one box says "Caliper the screen's picture area before cutting the window".

## Review Focus

1. Sheet thickness that isn't nominal (11.5 instead of 12): chamber stays 240 × 282 × 180 and 12.18 L; outer size changes. (Task 1)
2. Screen window as large as or larger than the screen module (the Rev F window with the Hosyond screen): the run fails with a message naming window and module sizes. (Task 1)
3. An optional part disabled: no cutout with its id on any panel, no BOM line, all outputs still written. (Tasks 1, 4, 6)
4. A panel that cannot fit the chosen sheet in its allowed orientation: error naming the panel and sheet, not a silent extra sheet or an overlap. (Task 3)
5. A design file with a missing or misspelt key: error naming the key, not a `KeyError` traceback or a silently ignored value. (Task 1)

---

### Task 1: Design file → Cabinet

**Files:**
- Create: `requirements.txt`, `boombox_enclosure/__init__.py`, `boombox_enclosure/design.py`, `boombox_enclosure/derive.py`, `designs/mk1-revf.json`, `designs/mk1.json`, `tests/test_derive.py`

**Interfaces:**
- Produces:

```python
# design.py
class DesignError(ValueError): ...
def load_design(path: str | Path) -> dict   # validated; raises DesignError naming the bad/missing/unknown key

# derive.py
@dataclass
class Cutout:
    id: str                      # "C1"
    kind: str                    # "circle" | "rect"
    cx: float; cy: float         # panel-local, from the panel's bottom-left as seen from its show face
    d: float = 0                 # circle
    w: float = 0; h: float = 0; r: float = 0   # rect, corner radius
    depth: float | None = None   # None = through
    face: str = "front"          # "front" = show face, "back" = other face
    note: str = ""
    mark_only: bool = False      # "mark from the part" features: drawn on the cut sheet, never cut or drilled

@dataclass
class Panel:
    id: str; name: str           # "P5", "Front baffle"
    w: float; h: float; t: float
    cutouts: list[Cutout]
    grain: str                   # "w" = grain along w, may not rotate; "any" = may rotate in the nest
    show_face: str               # what the carpenter sees: "front", "rear", "top (from above)", "outside", "inside"
    origin: tuple[float, float, float]   # cabinet coords of the panel's min corner (X width, Y depth from front, Z up)
    plane: str                   # "xz" (baffle/back/door), "xy" (top/bottom/ceilings), "yz" (sides/dividers)

@dataclass
class Cabinet:
    name: str
    outer: tuple[float, float, float]      # w, h, d
    chamber: tuple[float, float, float]    # w, h, d
    chamber_volume_l: float
    panels: list[Panel]
    design: dict                            # the validated design, for bom/finishes

def derive(design: dict) -> Cabinet       # raises DesignError on a failed fit check
```

- [ ] **Step 1: Write `designs/mk1-revf.json` and `designs/mk1.json`.**

Shape (values shown are Rev F; `mk1.json` differences listed after):

```json
{
  "name": "Boombox Mk I (Rev F reference)",
  "parts": {
    "driver": {"name": "Pioneer TS-A1671F", "cutout_d": 143, "frame_d": 166, "mount_depth": 59,
               "target_volume_l": 12.18, "vent_d": 50},
    "screen": {"name": "Raspberry Pi 7in Touch Display v1", "module": [194.7, 110.8, 20.7],
               "window": [185, 101], "window_offset": [0, 0], "pocket_clearance": 2.3, "pocket_depth": 14},
    "transport": {"count": 5, "d": 16, "pitch": 34,
                  "keys": ["prev", "play/pause", "stop", "next", "spare"]},
    "source_row": {"enabled": true, "count": 6, "d": 16, "pitch": 30, "x0": 60,
                   "keys": ["local", "bluetooth", "cast", "airplay", "spotify", "radio"]},
    "encoder": {"enabled": true, "shaft_d": 10, "knob_d": 45, "x_from_right": 72},
    "led_bar": {"enabled": true, "w": 592, "h": 22, "depth": 10, "gap_above_driver": 22, "slot": [20, 8]},
    "rfid": {"enabled": true, "reader": [102, 76], "pocket_clearance": 4, "web": 5, "cy": 85},
    "handle": {"enabled": true, "bolt_d": 6.5, "cy": 108, "tube_d": 25, "length": 300},
    "battery": {"name": "Anker Prime 26K (A110A)", "size": [127, 54, 50]},
    "door": {"opening": [160, 270], "opening_cy": 165, "leaf": [200, 310],
             "usb_c": {"d": 24, "cx": 55, "cy": 55},
             "exhaust": {"d": 19, "cy": 275, "cx_list": [46, 82, 118, 154]}},
    "intake": {"d": 19, "count": 4, "pitch": 46},
    "wire_pass": {"driver": {"d": 9, "from_baffle": 130, "cy": 60},
                  "channel": {"d": 13, "from_baffle": 90, "cy": 315}}
  },
  "cabinet": {
    "t_shell": 12, "t_baffle": 18,
    "chamber_h": 282, "chamber_d": 180, "bay_w": 210, "bay_clearance": 5,
    "centreline_y": 140, "control_strip_h": 42,
    "sheet": "4x4", "kerf": 3.2, "sheet_margin": 10,
    "cnc": {"bit_d": 6.35, "bed": "4x4"},
    "finishes": ["classic", "wood"]
  },
  "overrides": {}
}
```

`mk1.json` differs only in: `name` "Boombox Mk I"; `screen` = `{"name": "Hosyond 7in IPS DSI 800x480 (B0D3QB7X4Z)", "module": [164.89, 102.0, 12.25], "window": [155, 87], "window_offset": [0, 0], "pocket_clearance": 2, "pocket_depth": 14}`; last transport key `"power"`.

- [ ] **Step 2: Write the failing tests in `tests/test_derive.py`.**

```python
REVF = load_design("designs/mk1-revf.json")

def panel(cab, pid): return next(p for p in cab.panels if p.id == pid)
def cut(p, cid): return [c for c in p.cutouts if c.id == cid]

def test_revf_envelope_and_volume():
    cab = derive(REVF)
    assert cab.outer == (738, 360, 210)
    assert cab.chamber == (240, 282, 180)
    assert round(cab.chamber_volume_l, 2) == 12.18

def test_revf_panel_sizes():
    cab = derive(REVF)
    want = {"P1": (738, 210, 12), "P2": (738, 210, 12), "P3": (210, 336, 12), "P4": (210, 336, 12),
            "P5": (714, 336, 18), "P6": (714, 336, 12), "P7": (180, 336, 12), "P8": (180, 336, 12),
            "P9": (200, 310, 12), "P11": (240, 180, 12), "P12": (240, 180, 12)}
    assert {p.id: (p.w, p.h, p.t) for p in cab.panels} == want

def test_revf_baffle_cutouts():
    p5 = panel(derive(REVF), "P5")          # panel-local = face coordinate - 12
    c = {x.id: x for x in p5.cutouts if x.id not in ("C5", "C18")}
    assert (c["C1"].cx, c["C1"].cy, c["C1"].d) == (120, 128, 143)
    assert (c["C2"].cx, c["C2"].cy) == (594, 128)
    assert (c["C3"].cx, c["C3"].cy, c["C3"].w, c["C3"].h, c["C3"].depth) == (357, 128, 185, 101, None)
    assert (c["C4"].w, c["C4"].h, c["C4"].depth, c["C4"].face) == (197, 113, 14, "back")
    assert (c["C13"].cx, c["C13"].cy, c["C13"].w, c["C13"].h, c["C13"].depth) == (357, 244, 592, 22, 10)
    assert (c["C14"].w, c["C14"].h, c["C14"].depth) == (20, 8, None)
    assert (c["C17"].cx, c["C17"].cy, c["C17"].d) == (654, 315, 10)
    assert [x.cx for x in cut(p5, "C5")] == [289, 323, 357, 391, 425]
    assert [x.cx for x in cut(p5, "C18")] == [48, 78, 108, 138, 168, 198]
    assert {x.cy for x in cut(p5, "C5") + cut(p5, "C18")} == {315}

def test_revf_other_cutouts():
    cab = derive(REVF)
    p6 = panel(cab, "P6")                    # viewed from the rear
    assert sorted((x.cx, x.cy, x.d) for x in p6.cutouts if x.kind == "circle") == [(120, 141, 50), (594, 141, 50)]
    c8 = cut(p6, "C8")[0]; assert (c8.cx, c8.cy, c8.w, c8.h) == (357, 153, 160, 270)
    p1 = panel(cab, "P1")
    c15 = cut(p1, "C15")[0]; assert (c15.cx, c15.cy, c15.w, c15.h, c15.depth, c15.face) == (369, 85, 106, 80, 7, "back")
    assert [x.cx for x in cut(p1, "C16")] == [258, 480]
    assert [x.cx for x in cut(panel(cab, "P2"), "C11")] == [300, 346, 392, 438]

def test_thickness_change_keeps_internal_dims():        # Review Focus 1
    d = copy.deepcopy(REVF); d["cabinet"]["t_shell"] = 11.5
    cab = derive(d)
    assert cab.chamber == (240, 282, 180) and round(cab.chamber_volume_l, 2) == 12.18
    assert cab.outer[0] == 736                          # four 11.5 mm walls instead of four 12s

def test_chamber_width_holds_volume():
    d = copy.deepcopy(REVF); d["cabinet"]["chamber_h"] = 300
    cab = derive(d)
    assert abs(cab.chamber_volume_l - 12.18) < 0.03 and cab.chamber[0] < 240

def test_window_must_be_smaller_than_module():           # Review Focus 2
    d = copy.deepcopy(REVF); d["parts"]["screen"]["module"] = [164.89, 102.0, 12.25]
    with pytest.raises(DesignError, match="window.*185.*164.89"): derive(d)

def test_disabled_parts_leave_no_cutouts():              # Review Focus 3
    d = copy.deepcopy(REVF)
    for k in ("rfid", "led_bar", "source_row", "encoder", "handle"): d["parts"][k]["enabled"] = False
    ids = {c.id for p in derive(d).panels for c in p.cutouts}
    assert ids.isdisjoint({"C13", "C14", "C15", "C16", "C17", "C18", "C19"})

def test_bad_keys_are_named(tmp_path):                   # Review Focus 5
    for mutate, key in ((lambda d: d["cabinet"].pop("chamber_h"), "cabinet.chamber_h"),
                        (lambda d: d["cabinet"].update(chamber_hieght=1), "cabinet.chamber_hieght")):
        d = copy.deepcopy(REVF); mutate(d)
        f = tmp_path / "d.json"; f.write_text(json.dumps(d))
        with pytest.raises(DesignError, match=key): load_design(f)

def test_mk1_derives():
    cab = derive(load_design("designs/mk1.json"))
    c4 = cut(panel(cab, "P5"), "C4")[0]
    assert (round(c4.w, 2), round(c4.h, 2)) == (168.89, 106.0)     # module + 2 * 2 mm
```

- [ ] **Step 3: Run tests; expect FAIL (module not found).**

- [ ] **Step 4: Implement `design.py` and `derive.py`.**

`load_design`: validate against a nested dict of required keys (the Step 1 shape is the schema; `enabled` defaults to true; unknown keys are errors; error text uses dotted paths).

Derivation rules (face coordinates; subtract the panel's own origin for panel-local). `t` = `t_shell`, `tb` = `t_baffle`:

| Quantity | Rule |
|---|---|
| chamber w | `round(target_volume_l * 1e6 / (chamber_h * chamber_d))` |
| outer w | `4*t + 2*chamber_w + bay_w` |
| outer h | `2*t + chamber_h + t + control_strip_h` |
| outer d | `tb + chamber_d + t` |
| driver centre x (L, R) | `t + chamber_w/2`, mirrored |
| screen centre | `(outer_w/2 + window_offset[0], centreline_y + window_offset[1])`; pocket centred on the module, i.e. without the offset |
| C4 pocket | `module + 2*pocket_clearance`, r 8, depth `pocket_depth`, back face. C3 window r 6 |
| LED bar centre y | `centreline_y + frame_d/2 + gap_above_driver + h/2`, r 4; C14 slot at its centre |
| control strip centre y | `t + chamber_h + t + control_strip_h/2` |
| transport row | centred on `outer_w/2`; source row from `x0`; encoder at `outer_w - x_from_right` |
| rear vents C6/C7 | driver x (as seen from the rear), `t + chamber_h/2` |
| door opening C8 | centred x, `opening_cy`, r 6; P9 leaf local cutouts from `door` |
| intake C11 | bottom panel, centred x, `outer_d/2` |
| RFID C15 | top panel underside, centred x, `cy`, `reader + pocket_clearance`, depth `t - web`, r 6 |
| handle C16 | top panel, x = divider centres, `cy` |
| divider C12 / C19 | from `wire_pass`, local x = `from_baffle` |
| grain | `"any"` for P7, P8, P11, P12; `"w"` for the rest |
| mark-only | driver screw circle on P5 (Ø = `frame_d`, `mark_only=True`, note "mark screw holes from the Pioneer template") |

P3/P4 are w = outer d (210), h = 336, show face "outside". P11/P12 are 240 × 180.

Fit checks, each a `DesignError` with both numbers in the message: window ≥ module in either axis; `frame_d + 10 > chamber_w`; `mount_depth + 15 > chamber_d`; `bay_w < module_w + 2*bay_clearance`; any two cut features on one panel overlapping; any cut feature closer than 10 mm to its panel edge; LED bar top above the chamber ceiling. `overrides` is `{"<cutout id>": {"cx": .., "cy": ..}}` applied last, in panel-local coordinates.

- [ ] **Step 5: Run tests; expect PASS. `ruff check hardware/enclosure`.**

- [ ] **Step 6: Commit** `feat(enclosure): design file and cabinet derivation (Rev F reproduced)`

---

### Task 2: 3D model, finishes, exports

**Files:**
- Create: `boombox_enclosure/model.py`, `boombox_enclosure/finishes.py`, `tests/test_model.py`
- Delete: `build_model.py` (after the reference numbers below are confirmed by running it once in the venv)

**Interfaces:**
- Consumes: `Cabinet`, `Panel`, `Cutout` from Task 1.
- Produces:

```python
# finishes.py
@dataclass
class Material: name: str; rgba: tuple[int, int, int, int]; metallic: float; roughness: float
@dataclass
class Finish:
    key: str; label: str
    materials: dict[str, Material]     # keys: "body", "face", "trim", "driver", "glass", "diffuser", "handle", "feet"
    grille: bool                       # chrome ring + mesh disc over each driver
    handle: str                        # "tube" | "strap"
    bom: list[tuple[str, int, str]]    # (item, qty, note)
FINISHES: dict[str, Finish]            # "classic", "wood"

# model.py
def build_parts(cab: Cabinet, finish: Finish) -> dict[str, tuple[trimesh.Trimesh, Material]]
def export_model(cab: Cabinet, finish: Finish, out_dir: Path) -> None
    # writes model-<finish.key>.glb; and once per cabinet (finish-independent names): model.dae, model.stl
```

- [ ] **Step 1: Confirm reference numbers.** In the venv run the existing `build_model.py` once (it prints a part table) and record the printed `volume_cm3` of `P5_baffle`, `P6_back`, `P1_top`. Put those three numbers in the test below. If they differ from the placeholders, the script's output wins.

- [ ] **Step 2: Write failing tests in `tests/test_model.py`.**

```python
def parts(): return build_parts(derive(load_design("designs/mk1-revf.json")), FINISHES["wood"])

def test_panels_are_watertight_solids():
    for name, (mesh, _) in parts().items():
        if name.startswith("P"): assert mesh.is_watertight, name

def test_revf_volumes_match_reference_script():
    p = parts()
    for name, cm3 in REFERENCE_CM3.items():          # the three numbers from Step 1
        assert abs(p[name][0].volume / 1000 - cm3) < 0.5, name

def test_cabinet_bounds():
    shell = trimesh.util.concatenate([m for n, (m, _) in parts().items() if n[:2] in ("P1", "P2", "P3", "P4", "P5", "P6")])
    assert np.allclose(shell.bounds, [[0, 0, 0], [738, 210, 360]])

def test_finish_changes_materials_not_panels():
    cab = derive(load_design("designs/mk1.json"))
    a, b = build_parts(cab, FINISHES["classic"]), build_parts(cab, FINISHES["wood"])
    for n in a:
        if n.startswith("P"): assert a[n][0].volume == b[n][0].volume
    assert "GRILLE_L" in a and "GRILLE_L" not in b
    assert a["P5_baffle"][1].name != a["P3_side_L"][1].name          # classic: silver face, black body

def test_export_writes_files(tmp_path):
    cab = derive(load_design("designs/mk1.json"))
    for f in FINISHES.values(): export_model(cab, f, tmp_path)
    assert {p.name for p in tmp_path.iterdir()} >= {"model-classic.glb", "model-wood.glb", "model.dae", "model.stl"}
```

- [ ] **Step 3: Run; expect FAIL.**

- [ ] **Step 4: Implement.** Port the `box` / `cyl` / `cut` helpers from `build_model.py`. One generic function turns any `Panel` into a solid: box at `origin` in `plane`, minus each non-`mark_only` cutout extruded through or to `depth` from its `face` (rounded-rect cutter for `r > 0`; the reference script uses square corners, so pass `r=0` when computing the Step 1 comparison or widen the tolerance to 2 cm³ and say so in the test). Part names keep the reference script's (`P5_baffle`, `P3_side_L`, …). Cosmetic parts (drivers, screen glass, diffuser, knob, button caps, feet, handle, door proud of the back) port over from the script, each skipped when its part is disabled. Finishes per the spec's table: Classic = black body, brushed-silver face, chrome trim, `grille=True`, tube handle; Wood = birch body and face, black trim, `grille=False`, strap handle. GLB uses `trimesh.visual.material.PBRMaterial`; DAE keeps the script's pycollada block; STL is the merged mesh.

- [ ] **Step 5: Run tests; expect PASS. Delete `build_model.py`. Ruff.**

- [ ] **Step 6: Commit** `feat(enclosure): parametric 3D model with classic and wood finishes`

---

### Task 3: Sheet nesting

**Files:**
- Create: `boombox_enclosure/nest.py`, `tests/test_nest.py`

**Interfaces:**
- Consumes: `Cabinet`, `Panel`, `DesignError`.
- Produces:

```python
SHEETS = {"4x4": (1219.2, 1219.2), "4x8": (2438.4, 1219.2)}     # w (along grain), h

@dataclass
class Placement: panel: Panel; x: float; y: float; w: float; h: float; rotated: bool   # sheet coords, bottom-left
@dataclass
class Band: y: float; h: float; placements: list[Placement]      # one rip
@dataclass
class SheetLayout: t: float; sheet: tuple[float, float]; index: int; bands: list[Band]

def nest(cab: Cabinet, *, sheet: str, gap: float, margin: float) -> list[SheetLayout]
def saw_nest(cab: Cabinet) -> list[SheetLayout]     # gap = kerf, sheet = cabinet.sheet
def cnc_nest(cab: Cabinet) -> list[SheetLayout]     # gap = cnc.bit_d + 6, sheet = cnc.bed
```

- [ ] **Step 1: Write failing tests.**

```python
CAB = derive(load_design("designs/mk1.json"))

def boxes(layout): return [(p.x, p.y, p.x + p.w, p.y + p.h) for b in layout.bands for p in b.placements]

@pytest.mark.parametrize("fn", [saw_nest, cnc_nest])
def test_every_part_placed_once_inside_sheet_without_overlap(fn):
    layouts = fn(CAB)
    placed = sorted(p.panel.id for l in layouts for b in l.bands for p in b.placements)
    assert placed == sorted(p.id for p in CAB.panels)
    for l in layouts:
        W, H = l.sheet; bs = boxes(l)
        for x0, y0, x1, y1 in bs: assert 10 <= x0 and 10 <= y0 and x1 <= W - 10 and y1 <= H - 10
        for i, a in enumerate(bs):
            for b in bs[i + 1:]: assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]

def test_mk1_needs_one_4x4_per_thickness():
    assert sorted((l.t, l.index) for l in saw_nest(CAB)) == [(12, 0), (18, 0)]

def test_guillotine_bands_span_parts_of_equal_or_lesser_height():
    for l in saw_nest(CAB):
        for b in l.bands:
            assert all(p.y == b.y and p.h <= b.h for p in b.placements)

def test_grain_w_panels_never_rotate():
    assert not any(p.rotated for l in saw_nest(CAB) for b in l.bands for p in b.placements if p.panel.grain == "w")

def test_oversize_panel_is_an_error():                    # Review Focus 4
    d = load_design("designs/mk1.json"); d["cabinet"]["chamber_h"] = 1300
    d["parts"]["driver"]["target_volume_l"] = 60
    with pytest.raises(DesignError, match=r"P\d+.*4x4"): saw_nest(derive(d))
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement.** Per thickness: shelf packing. Sort panels by height descending (a `grain == "any"` panel may rotate if that lets it join an open band); each band is a full-width rip whose height is its tallest part; parts sit left to right separated by `gap`; bands stack bottom-up separated by `gap`; start a new sheet when the next band does not fit. Sheet `w` is the grain direction.

- [ ] **Step 4: Run; expect PASS. Ruff.**

- [ ] **Step 5: Commit** `feat(enclosure): guillotine sheet nesting for saw and CNC`

---

### Task 4: Carpenter cut sheet and BOM

**Files:**
- Create: `boombox_enclosure/cutsheet.py`, `boombox_enclosure/bom.py`, `tests/test_cutsheet.py`

**Interfaces:**
- Consumes: `Cabinet`, `saw_nest`, `SheetLayout`, `FINISHES`.
- Produces:

```python
# cutsheet.py
def fmt_in(mm: float) -> str                 # nearest 1/32 in, reduced: 714 -> '28 1/8"', 12 -> '15/32"'
def dim(mm: float) -> str                    # '28 1/8" [714]'
def render_cut_sheet(cab: Cabinet, layouts: list[SheetLayout]) -> str     # complete HTML document
# bom.py
def render_bom(cab: Cabinet, layouts: list[SheetLayout]) -> str           # Markdown
```

- [ ] **Step 1: Write failing tests.**

```python
def test_fmt_in():
    assert fmt_in(714) == '28 1/8"' and fmt_in(738) == '29 1/16"' and fmt_in(210) == '8 9/32"'
    assert fmt_in(12) == '15/32"' and fmt_in(25.4) == '1"' and fmt_in(1219.2) == '48"'

HTML = render_cut_sheet(CAB, saw_nest(CAB))

def test_page_one_warnings():
    assert "Caliper the screen" in HTML and "Measure your actual plywood thickness" in HTML
    assert "rule of thumb" in HTML and "tuned" not in HTML.lower()

def test_one_sheet_diagram_per_layout_and_one_drawing_per_panel():
    assert HTML.count('class="sheet-diagram"') == len(saw_nest(CAB))
    assert HTML.count('class="panel-drawing"') == len(CAB.panels)

def test_panel_features_are_dimensioned_from_the_panel_corner():
    assert '4 23/32" [120]' in HTML and '5 1/32" [128]' in HTML      # P5 driver L centre, panel-local
    assert "subtract" not in HTML.lower()

def test_back_face_features_are_called_out():
    assert HTML.count("from the back face") >= 2                     # C4 screen pocket, C15 RFID pocket

def test_cut_order_lists_every_rip_and_crosscut():
    n_bands = sum(len(l.bands) for l in saw_nest(CAB))
    assert HTML.count('class="cut-step rip"') == n_bands

def test_bom_sheets_and_finish_sections():
    md = render_bom(CAB, saw_nest(CAB))
    assert "12 mm" in md and "18 mm" in md and "4 × 4 ft" in md
    assert "## Classic finish" in md and "## Wood finish" in md and "Hosyond" in md

def test_disabled_rfid_drops_its_bom_line():                         # Review Focus 3
    d = load_design("designs/mk1.json"); d["parts"]["rfid"]["enabled"] = False
    cab = derive(d)
    assert "RFID" not in render_bom(cab, saw_nest(cab)) and "C15" not in render_cut_sheet(cab, saw_nest(cab))
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement.** One self-contained HTML string, inline CSS and SVG, no scripts, no external assets; `@media print` gives each sheet diagram and each panel drawing its own letter page. Sections in order:
  1. Title, cabinet outer size, "12.2 L sealed per speaker (rule of thumb, driver parameters unpublished)".
  2. Shopping list (sheets per thickness from the layouts).
  3. "Before the first cut" box with the two warning sentences from the tests, verbatim: "Measure your actual plywood thickness." and "Caliper the screen's picture area before cutting the window."
  4. One sheet diagram per layout: sheet outline, each part a labelled box (id, name, `dim(w) × dim(h)`), offcut hatched, grain arrow, band numbers.
  5. Cut order table: step 0 "trim two factory edges square", then per band one rip (`class="cut-step rip"`) "rip N: `dim(band.h)`", then its crosscuts left to right, then any trim-to-height for parts shorter than their band.
  6. One drawing per panel seen from `show_face`: outline with overall dims, grain arrow, "UP" arrow, each feature drawn and tabulated with id, what it is, centre X and Y via `dim()` from the bottom-left corner, size, depth ("through" or `dim(depth)` + "from the back face" when `face == "back"`). Back-face features dashed. `mark_only` features dotted with their note.

  BOM: sheet goods; parts from `design["parts"]` (enabled ones); one `## <label> finish` section per finish from `Finish.bom`.

- [ ] **Step 4: Run; expect PASS. Ruff.**

- [ ] **Step 5: Commit** `feat(enclosure): carpenter cut sheet (inches first, per-panel drawings) and BOM`

---

### Task 5: CNC DXF

**Files:**
- Create: `boombox_enclosure/dxf.py`, `tests/test_dxf.py`

**Interfaces:**
- Consumes: `cnc_nest`, `SheetLayout`, `Placement`.
- Produces: `write_dxfs(layouts: list[SheetLayout], out_dir: Path) -> list[Path]` — `sheet-<t>mm-<index+1>-front.dxf`, plus `...-back.dxf` for any sheet carrying a back-face feature.

- [ ] **Step 1: Write failing tests** (read back with `ezdxf.readfile`).

```python
def test_files_and_layers(tmp_path):
    paths = write_dxfs(cnc_nest(CAB), tmp_path)
    names = {p.name for p in paths}
    assert names == {"sheet-12mm-1-front.dxf", "sheet-12mm-1-back.dxf", "sheet-18mm-1-front.dxf", "sheet-18mm-1-back.dxf"}
    front18 = ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf")
    layers = {e.dxf.layer for e in front18.modelspace()}
    assert {"CUT_THROUGH", "POCKET_10mm", "DRILL_16mm", "REGISTRATION", "SHEET"} <= layers
    assert front18.units == ezdxf.units.MM

def test_back_file_is_mirrored_and_has_only_back_pockets(tmp_path):
    write_dxfs(cnc_nest(CAB), tmp_path)
    back = ezdxf.readfile(tmp_path / "sheet-18mm-1-back.dxf")
    layers = {e.dxf.layer for e in back.modelspace()}
    assert layers == {"POCKET_14mm", "REGISTRATION", "SHEET"}
    reg = lambda doc: sorted((round(e.dxf.center.x, 2), round(e.dxf.center.y, 2)) for e in doc.modelspace() if e.dxf.layer == "REGISTRATION")
    assert reg(back) == reg(ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf"))

def test_mark_only_features_are_not_cut(tmp_path):
    write_dxfs(cnc_nest(CAB), tmp_path)
    doc = ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf")
    assert not any(e.dxftype() == "CIRCLE" and abs(e.dxf.radius - 83) < 0.01 for e in doc.modelspace())
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement.** Sheet outline on `SHEET`. Panel outlines and through rects/circles wider than `bit_d` on `CUT_THROUGH` (rects as closed LWPOLYLINE with arc corners); through circles ≤ 20 mm on `DRILL_<d>mm`; blind features on `POCKET_<depth>mm`. A rotated placement rotates its cutouts with it. Two Ø4 circles on `REGISTRATION` at `(W/2, margin/2)` and `(W/2, H - margin/2)`, which map to themselves when the sheet is flipped left-to-right. Back file: x → `W - x`, only `face == "back"` features plus `SHEET` and `REGISTRATION`. Layer names format depth and diameter with `:g`.

- [ ] **Step 4: Run; expect PASS. Ruff.**

- [ ] **Step 5: Commit** `feat(enclosure): CNC DXF export with flip-side files`

---

### Task 6: CLI, viewer, renders, generated Mk I

**Files:**
- Create: `boombox_enclosure/__main__.py`, `boombox_enclosure/viewer.py`, `tests/test_cli.py`, `out/mk1/*` (generated)
- Modify: `README.md` (this folder)
- Delete: `boombox-mk1.dae`, `boombox-mk1.obj`, `boombox-mk1.stl` (superseded by `out/mk1/`)

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m boombox_enclosure <design.json> [--out DIR] [--render]`; default out dir `out/<design file stem>/`. Exit code 2 and a one-line message on `DesignError`.

- [ ] **Step 1: Write failing tests.**

```python
def run(*args): return subprocess.run([sys.executable, "-m", "boombox_enclosure", *args], capture_output=True, text=True)

def test_generates_everything(tmp_path):
    r = run("designs/mk1.json", "--out", str(tmp_path)); assert r.returncode == 0, r.stderr
    names = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}
    assert names >= {"model-classic.glb", "model-wood.glb", "model.dae", "model.stl", "viewer.html",
                     "cut-sheet.html", "bom.md", "cnc/sheet-12mm-1-front.dxf", "cnc/sheet-18mm-1-back.dxf"}

def test_all_optional_parts_off_still_generates(tmp_path):            # Review Focus 3
    d = json.loads(Path("designs/mk1.json").read_text())
    for k in ("rfid", "led_bar", "source_row", "encoder", "handle"): d["parts"][k]["enabled"] = False
    f = tmp_path / "bare.json"; f.write_text(json.dumps(d))
    assert run(str(f), "--out", str(tmp_path / "o")).returncode == 0

def test_design_error_is_one_line(tmp_path):
    d = json.loads(Path("designs/mk1.json").read_text()); d["parts"]["screen"]["window"] = [185, 101]
    f = tmp_path / "bad.json"; f.write_text(json.dumps(d))
    r = run(str(f), "--out", str(tmp_path / "o"))
    assert r.returncode == 2 and "Traceback" not in r.stderr and "window" in r.stderr
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Implement.** `viewer.py::render_viewer(cab, finishes) -> str`: one HTML page using `<model-viewer>` 4.0.0 from `https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js`, a button per finish that swaps `src` between `model-<key>.glb`, camera-controls on, neutral background. `--render`: start `http.server` on a free port serving the out dir, and for each finish and each of front (`camera-orbit="-30deg 75deg"`) and back (`"150deg 75deg"`) open `viewer.html?finish=<key>&orbit=<...>` with the `agent-browser` CLI, wait for model-viewer's `load` event, screenshot to `render-<key>-front.png` / `-back.png`. If `agent-browser` is not on PATH, print "renders skipped: agent-browser not found" and continue (exit 0).

- [ ] **Step 4: Run tests; expect PASS. Ruff.**

- [ ] **Step 5: Generate and look.** `python -m boombox_enclosure designs/mk1.json --render`. Read all four PNGs and `cut-sheet.html` (screenshot it too). Check by eye: classic reads as silver-face/black-body with grilles; wood reads as wood; screen window is smaller than in Rev F; no part floats or intersects; sheet diagram is legible at letter size. Fix what is wrong before committing.

- [ ] **Step 6: Rewrite `README.md`:** what the generator is, the one command, what each output is for (carpenter: `cut-sheet.html`; CNC shop: `cnc/`; SketchUp: `model.dae`), how to make a variant (copy a design file, edit, run), the rule-of-thumb caveat on chamber volume, and the caliper-the-screen warning.

- [ ] **Step 7: Commit** `feat(enclosure): CLI, 3D viewer, renders; generated Mk I outputs`
