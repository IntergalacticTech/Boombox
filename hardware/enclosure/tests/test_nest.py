import pytest
from boombox_enclosure.derive import derive
from boombox_enclosure.design import DesignError, load_design
from boombox_enclosure.nest import cnc_nest, saw_nest

CAB = derive(load_design("designs/mk1.json"))


def boxes(layout):
    return [(p.x, p.y, p.x + p.w, p.y + p.h) for b in layout.bands for p in b.placements]


@pytest.mark.parametrize("fn", [saw_nest, cnc_nest])
def test_every_part_placed_once_inside_sheet_without_overlap(fn):
    layouts = fn(CAB)
    placed = sorted(p.panel.id for lay in layouts for b in lay.bands for p in b.placements)
    assert placed == sorted(p.id for p in CAB.panels)
    for lay in layouts:
        W, H = lay.sheet
        bs = boxes(lay)
        for x0, y0, x1, y1 in bs:
            assert 10 <= x0 and 10 <= y0 and x1 <= W - 10 and y1 <= H - 10
        for i, a in enumerate(bs):
            for b in bs[i + 1:]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_mk1_needs_one_4x4_per_thickness():
    assert sorted((lay.t, lay.index) for lay in saw_nest(CAB)) == [(12, 0), (18, 0)]


def test_guillotine_bands_span_parts_of_equal_or_lesser_height():
    for lay in saw_nest(CAB):
        for b in lay.bands:
            assert all(p.y == b.y and p.h <= b.h for p in b.placements)


def test_parts_are_at_least_a_kerf_apart():
    for lay in saw_nest(CAB):
        for b in lay.bands:
            xs = sorted((p.x, p.x + p.w) for p in b.placements)
            assert all(nxt[0] - cur[1] >= 3.2 - 1e-9 for cur, nxt in zip(xs, xs[1:]))


def test_grain_w_panels_never_rotate():
    assert not any(p.rotated for lay in saw_nest(CAB) for b in lay.bands for p in b.placements
                   if p.panel.grain == "w")


def test_second_sheet_when_one_is_not_enough():
    d = load_design("designs/mk1.json")
    d["cabinet"]["chamber_h"] = 500
    d["parts"]["driver"]["target_volume_l"] = 22
    lays = [lay for lay in saw_nest(derive(d)) if lay.t == 12]
    assert [lay.index for lay in lays] == [0, 1]


def test_oversize_panel_is_an_error():  # Review Focus 4
    d = load_design("designs/mk1.json")
    d["cabinet"]["chamber_h"] = 1300
    d["parts"]["driver"]["target_volume_l"] = 60
    with pytest.raises(DesignError, match=r"P\d+.*4x4"):
        saw_nest(derive(d))
