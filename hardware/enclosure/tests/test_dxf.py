import ezdxf
from boombox_enclosure.derive import Cutout, derive
from boombox_enclosure.design import load_design
from boombox_enclosure.dxf import on_sheet, write_dxfs
from boombox_enclosure.nest import Placement, cnc_nest

CAB = derive(load_design("designs/mk1.json"))


def layers(doc):
    return {e.dxf.layer for e in doc.modelspace()}


def test_files_and_layers(tmp_path):
    paths = write_dxfs(cnc_nest(CAB), tmp_path)
    assert {p.name for p in paths} == {"sheet-12mm-1-front.dxf", "sheet-12mm-1-back.dxf",
                                       "sheet-18mm-1-front.dxf", "sheet-18mm-1-back.dxf"}
    front18 = ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf")
    assert {"CUT_THROUGH", "POCKET_10mm", "DRILL_16mm", "REGISTRATION", "SHEET"} <= layers(front18)
    assert front18.units == ezdxf.units.MM


def test_back_file_is_mirrored_and_has_only_back_pockets(tmp_path):
    write_dxfs(cnc_nest(CAB), tmp_path)
    back = ezdxf.readfile(tmp_path / "sheet-18mm-1-back.dxf")
    front = ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf")
    assert layers(back) == {"POCKET_14mm", "REGISTRATION", "SHEET"}

    def reg(doc):
        return sorted((round(e.dxf.center.x, 2), round(e.dxf.center.y, 2))
                      for e in doc.modelspace() if e.dxf.layer == "REGISTRATION")

    assert reg(back) == reg(front) and len(reg(back)) == 2
    # the pocket sits behind the screen window: mirrored about the sheet's vertical centre line
    win = next(e for e in front.modelspace() if e.dxf.layer == "CUT_THROUGH" and e.dxftype() == "LWPOLYLINE"
               and abs(max(p[0] for p in e) - min(p[0] for p in e) - 155) < 0.01)
    pocket = next(e for e in back.modelspace() if e.dxf.layer == "POCKET_14mm")
    mid = lambda e: (max(p[0] for p in e) + min(p[0] for p in e)) / 2  # noqa: E731
    assert abs(mid(win) + mid(pocket) - 1219.2) < 0.01


def test_mark_only_features_are_not_cut(tmp_path):
    write_dxfs(cnc_nest(CAB), tmp_path)
    doc = ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf")
    assert not any(e.dxftype() == "CIRCLE" and abs(e.dxf.radius - 83) < 0.01 for e in doc.modelspace())


def test_driver_hole_lands_inside_its_panel(tmp_path):
    write_dxfs(cnc_nest(CAB), tmp_path)
    doc = ezdxf.readfile(tmp_path / "sheet-18mm-1-front.dxf")
    pl = next(p for lay in cnc_nest(CAB) if lay.t == 18 for b in lay.bands for p in b.placements)
    big = sorted((e.dxf.center.x, e.dxf.center.y) for e in doc.modelspace()
                 if e.dxftype() == "CIRCLE" and abs(e.dxf.radius - 71.5) < 0.01)
    assert [(round(x - pl.x, 2), round(y - pl.y, 2)) for x, y in big] == [(120, 128), (594, 128)]


def test_rotated_placement_turns_the_cutout_with_the_panel():
    panel = next(p for p in CAB.panels if p.id == "P7")  # 180 x 336
    pl = Placement(panel, 100, 50, panel.h, panel.w, True)
    x, y, w, h = on_sheet(Cutout("X", "rect", 30, 300, w=20, h=10), pl)
    assert (x, y, w, h) == (100 + 336 - 300, 50 + 30, 10, 20)
