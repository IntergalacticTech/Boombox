import numpy as np
import trimesh
from boombox_enclosure.derive import derive
from boombox_enclosure.design import load_design
from boombox_enclosure.finishes import FINISHES
from boombox_enclosure.model import build_parts, export_model

# Printed by the hand-written build_model.py this generator replaced (square-cornered cutters).
REFERENCE_CM3 = {"P5_baffle": 3181.9, "P6_back": 2313.4, "P1_top": 1799.6, "P2_bottom": 1846.2,
                 "P7_divider_L": 723.4, "P9_door": 725.0, "P11_ceiling_L": 518.4, "P3_side_L": 846.7}


def parts():
    return build_parts(derive(load_design("designs/mk1-revf.json")), FINISHES["wood"])


def test_panels_are_watertight_solids():
    for name, (mesh, _) in parts().items():
        if name.startswith("P"):
            assert mesh.is_watertight, name


def test_revf_volumes_match_reference_script():
    p = parts()
    for name, cm3 in REFERENCE_CM3.items():
        # 2 cm3: this model rounds the corners of rectangular cutouts, the reference did not
        assert abs(p[name][0].volume / 1000 - cm3) < 2, name


def test_cabinet_bounds():
    shell = trimesh.util.concatenate([m for n, (m, _) in parts().items()
                                      if n.split("_")[0] in ("P1", "P2", "P3", "P4", "P5", "P6")])
    assert np.allclose(shell.bounds, [[0, 0, 0], [738, 210, 360]])


def test_panels_sit_where_the_reference_put_them():
    p = parts()
    assert np.allclose(p["P7_divider_L"][0].bounds, [[252, 18, 12], [264, 198, 348]])
    assert np.allclose(p["P9_door"][0].bounds, [[269, 210, 10], [469, 222, 320]])
    assert np.allclose(p["P12_ceiling_R"][0].bounds, [[486, 18, 294], [726, 198, 306]])


def test_finish_changes_materials_not_panels():
    cab = derive(load_design("designs/mk1.json"))
    a, b = build_parts(cab, FINISHES["classic"]), build_parts(cab, FINISHES["wood"])
    for n in a:
        if n.startswith("P"):
            assert a[n][0].volume == b[n][0].volume
    assert "GRILLE_L" in a and "GRILLE_L" not in b
    assert a["P5_baffle"][1].name != a["P3_side_L"][1].name  # classic: silver face, black body


def test_disabled_parts_have_no_cosmetic_part():
    d = load_design("designs/mk1.json")
    for k in ("rfid", "led_bar", "source_row", "encoder", "handle"):
        d["parts"][k]["enabled"] = False
    names = set(build_parts(derive(d), FINISHES["classic"]))
    assert names.isdisjoint({"KNOB", "HANDLE", "DIFFUSER"})


def test_export_writes_files(tmp_path):
    cab = derive(load_design("designs/mk1.json"))
    for f in FINISHES.values():
        export_model(cab, f, tmp_path)
    assert {p.name for p in tmp_path.iterdir()} >= {"model-classic.glb", "model-wood.glb", "model.dae", "model.stl"}
    scene = trimesh.load(tmp_path / "model-classic.glb")
    assert "P5_baffle" in scene.geometry
