"""Cabinet -> solids. Cabinet coordinates (mm): X width, Y depth from the front, Z up."""
from pathlib import Path

import numpy as np
import trimesh
from trimesh.creation import box as tm_box
from trimesh.creation import cylinder as tm_cyl

from .derive import Cabinet, Panel
from .finishes import FINISHES, Finish

SEG = 64
PART_NAMES = {"P1": "P1_top", "P2": "P2_bottom", "P3": "P3_side_L", "P4": "P4_side_R", "P5": "P5_baffle",
              "P6": "P6_back", "P7": "P7_divider_L", "P8": "P8_divider_R", "P9": "P9_door",
              "P11": "P11_ceiling_L", "P12": "P12_ceiling_R"}


def box(p0, p1):
    p0, p1 = np.minimum(p0, p1), np.maximum(p0, p1)
    return tm_box(extents=p1 - p0, transform=trimesh.transformations.translation_matrix((p0 + p1) / 2))


def cyl(axis, a, b, c0, c1, r):
    """Cylinder along `axis` from c0 to c1; (a, b) are the other two coordinates in x, y, z order."""
    m = tm_cyl(radius=r, height=abs(c1 - c0), sections=SEG)
    mid = (c0 + c1) / 2
    if axis == "x":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
        m.apply_translation([mid, a, b])
    elif axis == "y":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        m.apply_translation([a, mid, b])
    else:
        m.apply_translation([a, b, mid])
    return m


def _to_cabinet(p: Panel) -> np.ndarray:
    """Panel-local (x right, y up, z into the panel from its show face) -> cabinet coordinates."""
    ox, oy, oz = p.origin
    if p.plane == "xz":
        cols, t = (((-1, 0, 0), (0, 0, 1), (0, -1, 0)), (ox + p.w, oy + p.t, oz)) if p.mirror else \
                  (((1, 0, 0), (0, 0, 1), (0, 1, 0)), (ox, oy, oz))
    elif p.plane == "xy":
        cols, t = ((1, 0, 0), (0, 1, 0), (0, 0, -1)), (ox, oy, oz + p.t)
    else:
        cols, t = ((0, 1, 0), (0, 0, 1), (1, 0, 0)), (ox, oy, oz)
    m = np.eye(4)
    m[:3, :3] = np.array(cols).T
    m[:3, 3] = t
    return m


def panel_solid(p: Panel) -> trimesh.Trimesh:
    cutters = []
    for c in p.cutouts:
        if c.mark_only:
            continue
        if c.depth is None:
            z0, z1 = -1, p.t + 1
        elif c.face == "front":
            z0, z1 = -1, c.depth
        else:
            z0, z1 = p.t - c.depth, p.t + 1
        if c.kind == "circle":
            cutters.append(cyl("z", c.cx, c.cy, z0, z1, c.d / 2))
        else:
            hw, hh, r = c.w / 2, c.h / 2, c.r
            if r:  # rounded rectangle = two boxes + four corner cylinders
                cutters += [box((c.cx - hw + r, c.cy - hh, z0), (c.cx + hw - r, c.cy + hh, z1)),
                            box((c.cx - hw, c.cy - hh + r, z0), (c.cx + hw, c.cy + hh - r, z1))]
                cutters += [cyl("z", c.cx + sx * (hw - r), c.cy + sy * (hh - r), z0, z1, r)
                            for sx in (-1, 1) for sy in (-1, 1)]
            else:
                cutters.append(box((c.cx - hw, c.cy - hh, z0), (c.cx + hw, c.cy + hh, z1)))
    mesh = box((0, 0, 0), (p.w, p.h, p.t))
    if cutters:
        mesh = mesh.difference(cutters, engine="manifold")
    mesh.apply_transform(_to_cabinet(p))
    if mesh.volume < 0:  # the local->cabinet map can be a reflection
        mesh.invert()
    return mesh


def _join(meshes):
    return trimesh.util.concatenate(meshes)


def build_parts(cab: Cabinet, finish: Finish) -> dict:
    """name -> (mesh, Material). Panels first, then cosmetic hardware (skipped when its part is disabled)."""
    parts, mat = cab.design["parts"], finish.materials
    W, H, D = cab.outer
    out = {PART_NAMES[p.id]: (panel_solid(p), mat["face"] if p.id == "P5" else mat["body"]) for p in cab.panels}
    baffle = next(p for p in cab.panels if p.id == "P5")
    ox, oz = baffle.origin[0], baffle.origin[2]
    cuts = {}
    for c in baffle.cutouts:
        cuts.setdefault(c.id, []).append(c)

    def at(c):
        return c.cx + ox, c.cy + oz

    drv = parts["driver"]
    fr = drv["frame_d"] / 2
    for side, cid in (("L", "C1"), ("R", "C2")):
        x, z = at(cuts[cid][0])
        if finish.grille:
            ring = cyl("y", x, z, -9, 0, fr + 5).difference([cyl("y", x, z, -10, 1, fr - 7)], engine="manifold")
            out[f"GRILLE_{side}"] = (ring, mat["trim"])
            out[f"MESH_{side}"] = (cyl("y", x, z, -6, 0, fr - 6.5), mat["driver"])
        else:
            ring = cyl("y", x, z, -4, 0, fr).difference([cyl("y", x, z, -5, 1, fr - 9)], engine="manifold")
            out[f"RING_{side}"] = (ring, mat["trim"])
            out[f"DRV_{side}"] = (_join([cyl("y", x, z, -2.5, 0, fr - 8.5), cyl("y", x, z, -7, -2, fr * 0.42)]),
                                  mat["driver"])

    win = cuts["C3"][0]
    x, z = at(win)
    web = baffle.t - parts["screen"]["pocket_depth"]
    out["SCREEN"] = (box((x - win.w / 2, web - 1, z - win.h / 2), (x + win.w / 2, web + 0.5, z + win.h / 2)),
                     mat["glass"])

    if parts["led_bar"]["enabled"]:
        c = cuts["C13"][0]
        x, z = at(c)
        out["DIFFUSER"] = (box((x - c.w / 2 + 1, 0.5, z - c.h / 2 + 1), (x + c.w / 2 - 1, 3.5, z + c.h / 2 - 1)),
                           mat["diffuser"])
    if parts["encoder"]["enabled"]:
        x, z = at(cuts["C17"][0])
        out["KNOB"] = (cyl("y", x, z, -22, 0, parts["encoder"]["knob_d"] / 2), mat["trim"])
    buttons = cuts.get("C5", []) + cuts.get("C18", [])
    out["BUTTONS"] = (_join([cyl("y", *at(c), -4, 0, c.d / 2 + 1) for c in buttons]), mat["trim"])

    out["FEET"] = (_join([cyl("z", x, y, -10, 0, 19) for x in (45, W / 2, W - 45) for y in (45, D - 45)]),
                   mat["feet"])

    if parts["handle"]["enabled"]:
        hd = parts["handle"]
        xs = [c.cx for p in cab.panels if p.id == "P1" for c in p.cutouts if c.id == "C16"]
        posts = [cyl("z", x, hd["cy"], H, H + 40, 6) for x in xs]
        if finish.handle == "tube":
            grip = cyl("x", hd["cy"], H + 40, W / 2 - hd["length"] / 2, W / 2 + hd["length"] / 2, hd["tube_d"] / 2)
        else:
            grip = box((min(xs) - 14, hd["cy"] - 14, H + 36), (max(xs) + 14, hd["cy"] + 14, H + 41))
        out["HANDLE"] = (_join(posts + [grip]), mat["handle"])
    return out


def _write_dae(parts: dict, path: Path) -> None:
    """SketchUp-friendly: every part a named node with its own material, mm, Z up."""
    import collada as co

    doc = co.Collada()
    doc.assetInfo.unitname, doc.assetInfo.unitmeter, doc.assetInfo.upaxis = "millimeter", 0.001, "Z_UP"
    nodes = []
    for name, (m, material) in parts.items():
        rgb = [c / 255 for c in material.rgba[:3]]
        eff = co.material.Effect(f"eff_{name}", [], "lambert", diffuse=rgb + [1.0])
        cmat = co.material.Material(f"mat_{name}", f"mat_{name}", eff)
        doc.effects.append(eff)
        doc.materials.append(cmat)
        vs = co.source.FloatSource(f"v_{name}", np.array(m.vertices.flatten()), ("X", "Y", "Z"))
        geom = co.geometry.Geometry(doc, f"geom_{name}", name, [vs])
        il = co.source.InputList()
        il.addInput(0, "VERTEX", f"#v_{name}")
        geom.primitives.append(geom.createTriangleSet(m.faces.flatten(), il, f"mat_{name}"))
        doc.geometries.append(geom)
        nodes.append(co.scene.Node(name, children=[
            co.scene.GeometryNode(geom, [co.scene.MaterialNode(f"mat_{name}", cmat, inputs=[])])]))
    scene = co.scene.Scene("boombox", nodes)
    doc.scenes.append(scene)
    doc.scene = scene
    doc.write(str(path))


# glTF is metres, Y up, and viewers face +Z: (x, y, z) mm -> (x, z, -y) m
_TO_GLTF = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1000]]) / 1000


def export_model(cab: Cabinet, finish: Finish, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    for name, (mesh, m) in build_parts(cab, finish).items():
        mesh = mesh.copy()
        mesh.apply_transform(_TO_GLTF)
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=m.name, baseColorFactor=list(m.rgba), metallicFactor=m.metallic, roughnessFactor=m.roughness))
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.export(str(out_dir / f"model-{finish.key}.glb"))

    wood = build_parts(cab, FINISHES["wood"])  # the CAD exports don't depend on the finish asked for
    _write_dae(wood, out_dir / "model.dae")
    _join([m for m, _ in wood.values()]).export(str(out_dir / "model.stl"))
