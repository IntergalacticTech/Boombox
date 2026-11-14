import copy
import json

import pytest
from boombox_enclosure.derive import derive
from boombox_enclosure.design import DesignError, load_design

REVF = load_design("designs/mk1-revf.json")


def panel(cab, pid):
    return next(p for p in cab.panels if p.id == pid)


def cut(p, cid):
    return [c for c in p.cutouts if c.id == cid]


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
    p5 = panel(derive(REVF), "P5")  # panel-local = face coordinate - 12
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
    p6 = panel(cab, "P6")  # viewed from the rear
    assert sorted((x.cx, x.cy, x.d) for x in p6.cutouts if x.kind == "circle") == [(120, 141, 50), (594, 141, 50)]
    c8 = cut(p6, "C8")[0]
    assert (c8.cx, c8.cy, c8.w, c8.h) == (357, 153, 160, 270)
    p1 = panel(cab, "P1")
    c15 = cut(p1, "C15")[0]
    assert (c15.cx, c15.cy, c15.w, c15.h, c15.depth, c15.face) == (369, 85, 106, 80, 7, "back")
    assert [x.cx for x in cut(p1, "C16")] == [258, 480]
    assert [x.cx for x in cut(panel(cab, "P2"), "C11")] == [300, 346, 392, 438]


def test_thickness_change_keeps_internal_dims():  # Review Focus 1
    d = copy.deepcopy(REVF)
    d["cabinet"]["t_shell"] = 11.5
    cab = derive(d)
    assert cab.chamber == (240, 282, 180) and round(cab.chamber_volume_l, 2) == 12.18
    assert cab.outer[0] == 736  # four 11.5 mm walls instead of four 12s


def test_chamber_width_holds_volume():
    d = copy.deepcopy(REVF)
    d["cabinet"]["chamber_h"] = 300
    d["parts"]["wire_pass"]["channel"]["cy"] += 18  # the control channel moves up with the ceiling
    cab = derive(d)
    assert abs(cab.chamber_volume_l - 12.18) < 0.03 and cab.chamber[0] < 240


def test_window_must_be_smaller_than_module():  # Review Focus 2
    d = copy.deepcopy(REVF)
    d["parts"]["screen"]["module"] = [164.89, 102.0, 12.25]
    with pytest.raises(DesignError, match="window.*185.*164.89"):
        derive(d)


def test_disabled_parts_leave_no_cutouts():  # Review Focus 3
    d = copy.deepcopy(REVF)
    for k in ("rfid", "led_bar", "source_row", "encoder", "handle"):
        d["parts"][k]["enabled"] = False
    ids = {c.id for p in derive(d).panels for c in p.cutouts}
    assert ids.isdisjoint({"C13", "C14", "C15", "C16", "C17", "C18", "C19"})


def test_bad_keys_are_named(tmp_path):  # Review Focus 5
    for mutate, key in ((lambda d: d["cabinet"].pop("chamber_h"), "cabinet.chamber_h"),
                        (lambda d: d["cabinet"].update(chamber_hieght=1), "cabinet.chamber_hieght")):
        d = copy.deepcopy(REVF)
        mutate(d)
        f = tmp_path / "d.json"
        f.write_text(json.dumps(d))
        with pytest.raises(DesignError, match=key):
            load_design(f)


def test_driver_too_big_for_chamber_is_an_error():
    d = copy.deepcopy(REVF)
    d["parts"]["driver"]["frame_d"] = 260
    with pytest.raises(DesignError, match="driver frame"):
        derive(d)


def test_override_moves_a_cutout():
    d = copy.deepcopy(REVF)
    d["overrides"] = {"C17": {"cx": 640}}
    assert cut(panel(derive(d), "P5"), "C17")[0].cx == 640


def test_mk1_derives():
    cab = derive(load_design("designs/mk1.json"))
    c4 = cut(panel(cab, "P5"), "C4")[0]
    assert (round(c4.w, 2), round(c4.h, 2)) == (168.89, 106.0)  # module + 2 * 2 mm


# ── final review findings ───────────────────────────────────────────
MK1 = load_design("designs/mk1.json")


def changed(base=None, **paths):
    d = copy.deepcopy(base or MK1)
    for path, v in paths.items():
        *keys, last = path.split("__")
        node = d
        for k in keys:
            node = node[k]
        node[last] = v
    return d


def test_screen_pocket_corners_clear_a_square_module_corner():
    for d in (MK1, REVF):
        clr = d["parts"]["screen"]["pocket_clearance"]
        c4 = cut(panel(derive(d), "P5"), "C4")[0]
        assert c4.r * (2 ** 0.5 - 1) <= min(clr if isinstance(clr, list) else [clr]) * 2 ** 0.5


@pytest.mark.parametrize("bad", [{"C9": {"x": 5}}, {"C9": {"cx": "100"}}])
def test_override_with_unknown_field_or_non_number_is_refused(bad):
    with pytest.raises(DesignError, match="overrides.C9"):
        derive(changed(overrides=bad))


def test_enabled_must_be_true_or_false():
    with pytest.raises(DesignError, match="led_bar.enabled"):
        derive(changed(parts__led_bar__enabled="false"))


@pytest.mark.parametrize("offset", [[0, 8], [20, 0]])
def test_window_offset_past_the_glass_is_refused(offset):
    with pytest.raises(DesignError, match="falls through"):
        derive(changed(parts__screen__window_offset=offset))


@pytest.mark.parametrize("path,value", [
    ("parts__screen__pocket_depth", 20), ("parts__led_bar__depth", 20), ("parts__rfid__web", 14)])
def test_pocket_deeper_than_the_panel_allows_is_refused(path, value):
    with pytest.raises(DesignError, match="pocket"):
        derive(changed(**{path: value}))


@pytest.mark.parametrize("paths", [
    {"parts__source_row__pitch": 40},
    {"parts__transport__count": 7, "parts__transport__keys": ["a"] * 7},
    {"parts__intake__count": 6},
    {"parts__led_bar__enabled": False, "cabinet__centreline_y": 225},
    {"parts__wire_pass__channel__cy": 300},
    {"cabinet__bay_w": 175, "parts__screen__pocket_clearance": [6, 2]},
])
def test_cut_into_a_divider_ceiling_or_chamber_is_refused(paths):
    with pytest.raises(DesignError, match="divider|ceiling|chamber"):
        derive(changed(**paths))


@pytest.mark.parametrize("paths", [{"parts__door__opening_cy": 200}, {"parts__door__opening": [220, 270]}])
def test_door_that_does_not_cover_its_opening_is_refused(paths):
    with pytest.raises(DesignError, match="door"):
        derive(changed(**paths))
