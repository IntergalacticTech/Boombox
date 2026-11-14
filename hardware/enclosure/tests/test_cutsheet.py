from boombox_enclosure.bom import render_bom
from boombox_enclosure.cutsheet import dim, fmt_in, render_cut_sheet
from boombox_enclosure.derive import derive
from boombox_enclosure.design import load_design
from boombox_enclosure.nest import saw_nest

CAB = derive(load_design("designs/mk1.json"))
HTML = render_cut_sheet(CAB, saw_nest(CAB))


def test_fmt_in():
    assert fmt_in(714) == '28 1/8"' and fmt_in(738) == '29 1/16"' and fmt_in(210) == '8 9/32"'
    assert fmt_in(12) == '15/32"' and fmt_in(25.4) == '1"' and fmt_in(1219.2) == '48"'
    assert dim(714) == '28 1/8" [714]' and dim(168.89) == '6 21/32" [168.9]'


def test_page_one_warnings():
    assert "Caliper the screen" in HTML and "Measure your actual plywood thickness" in HTML
    assert "rule of thumb" in HTML and "tuned" not in HTML.lower()


def test_one_sheet_diagram_per_layout_and_one_drawing_per_panel():
    assert HTML.count('class="sheet-diagram"') == len(saw_nest(CAB))
    assert HTML.count('class="panel-drawing"') == len(CAB.panels)


def test_panel_features_are_dimensioned_from_the_panel_corner():
    assert '4 23/32" [120]' in HTML and '5 1/32" [128]' in HTML  # P5 driver L centre, panel-local
    assert "subtract" not in HTML.lower()


def test_back_face_features_are_called_out():
    assert HTML.count("from the back face") >= 2  # C4 screen pocket, C15 RFID pocket


def test_cut_order_lists_every_rip_and_crosscut():
    lays = saw_nest(CAB)
    assert HTML.count('class="cut-step rip"') == sum(len(lay.bands) for lay in lays)
    assert HTML.count('class="cut-step cross"') == len(CAB.panels)


def test_mark_only_features_say_do_not_cut():
    assert "mark only, do not cut" in HTML


def test_bom_sheets_and_finish_sections():
    md = render_bom(CAB, saw_nest(CAB))
    assert "12 mm" in md and "18 mm" in md and "4 × 4 ft" in md
    assert "## Classic finish" in md and "## Wood finish" in md and "Hosyond" in md
    assert "rule of thumb" in md and "tuned" not in md.lower()


def test_disabled_rfid_drops_its_bom_line():  # Review Focus 3
    d = load_design("designs/mk1.json")
    d["parts"]["rfid"]["enabled"] = False
    cab = derive(d)
    assert "RFID" not in render_bom(cab, saw_nest(cab)) and "C15" not in render_cut_sheet(cab, saw_nest(cab))
