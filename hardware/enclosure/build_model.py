#!/usr/bin/env python3
"""Boombox Mk I enclosure — 3D model generator (Rev F geometry).

Coordinate system (mm): X = width (0 at viewer-left), Y = depth (0 at front
face, +Y toward the back), Z = height (0 at bottom). Matches the spec's
front-elevation coordinates with face-y -> Z.
"""
import numpy as np
import trimesh
from trimesh.creation import box as tm_box
from trimesh.creation import cylinder as tm_cyl

SEG = 64  # circle resolution


def box(p0, p1):
    p0, p1 = np.minimum(p0, p1), np.maximum(p0, p1)
    ext = np.array(p1) - np.array(p0)
    t = trimesh.transformations.translation_matrix(np.array(p0) + ext / 2)
    return tm_box(extents=ext, transform=t)


def cyl(axis, a, b, c0, c1, r):
    """Cylinder along `axis` ('x'|'y'|'z') from c0 to c1; (a,b) are the other
    two coords in x,y,z order skipping the axis."""
    h = abs(c1 - c0)
    m = tm_cyl(radius=r, height=h, sections=SEG)
    R = np.eye(4)
    if axis == 'x':
        R = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
        center = [(c0 + c1) / 2, a, b]
    elif axis == 'y':
        R = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
        center = [a, (c0 + c1) / 2, b]
    else:
        center = [a, b, (c0 + c1) / 2]
    m.apply_transform(R)
    m.apply_translation(np.array(center) - m.bounds.mean(axis=0))
    return m


def cut(base, cutters):
    return base.difference(cutters, engine='manifold')


BIRCH = [222, 195, 138, 255]
BIRCH_DK = [205, 175, 118, 255]
DARK = [40, 38, 34, 255]
ALU = [180, 182, 186, 255]
AMBER = [226, 106, 31, 255]
GLASS = [30, 34, 44, 255]
WHITE = [240, 238, 228, 200]

parts = {}  # name -> (mesh, color)

# ── panels ──────────────────────────────────────────────────────────
# P2 bottom
p2 = cut(box((0, 0, 0), (738, 210, 12)),
         [cyl('z', x, 105, -1, 13, 9.5) for x in (300, 346, 392, 438)])
parts['P2_bottom'] = (p2, BIRCH)

# P1 top: C16 handle bolt holes + C15 RFID pocket (underside)
p1 = cut(box((0, 0, 348), (738, 210, 360)),
         [cyl('z', 258, 108, 347, 361, 3.25), cyl('z', 480, 108, 347, 361, 3.25),
          box((316, 45, 347), (422, 125, 355))])
parts['P1_top'] = (p1, BIRCH)

# P3/P4 sides
parts['P3_side_L'] = (box((0, 0, 12), (12, 210, 348)), BIRCH)
parts['P4_side_R'] = (box((726, 0, 12), (738, 210, 348)), BIRCH)

# P5 baffle (18 mm) with all front cutouts
baffle = box((12, 0, 12), (726, 18, 348))
cutters = [
    cyl('y', 132, 140, -1, 19, 71.5),                    # C1 driver L
    cyl('y', 606, 140, -1, 19, 71.5),                    # C2 driver R
    box((276.5, -1, 89.5), (461.5, 19, 190.5)),          # C3 screen window
    box((270.5, 4, 83.5), (467.5, 19, 196.5)),           # C4 pocket (rear 14)
    box((73, -1, 245), (665, 10, 267)),                  # C13 LED channel (front 10)
    box((359, -1, 252), (379, 19, 260)),                 # C14 wire slot thru
    cyl('y', 666, 327, -1, 19, 5),                       # C17 encoder shaft
]
cutters += [cyl('y', x, 327, -1, 19, 8) for x in (301, 335, 369, 403, 437)]   # C5
cutters += [cyl('y', x, 327, -1, 19, 8) for x in (60, 90, 120, 150, 180, 210)]  # C18
parts['P5_baffle'] = (cut(baffle, cutters), BIRCH_DK)

# P6 back: vents + door opening
p6 = cut(box((12, 198, 12), (726, 210, 348)),
         [cyl('y', 132, 153, 197, 211, 25), cyl('y', 606, 153, 197, 211, 25),
          box((289, 197, 30), (449, 211, 300))])
parts['P6_back'] = (p6, BIRCH)

# P7/P8 dividers: C12 grommet + C19 channel pass (X-axis holes)
for name, x0 in (('P7_divider_L', 252), ('P8_divider_R', 474)):
    d = cut(box((x0, 18, 12), (x0 + 12, 198, 348)),
            [cyl('x', 148, 60, x0 - 1, x0 + 13, 4.5),    # C12: y=18+130, z=60
             cyl('x', 108, 315, x0 - 1, x0 + 13, 6.5)])  # C19: y=18+90, z=315
    parts[name] = (d, BIRCH)

# P11/P12 chamber ceilings
parts['P11_ceiling_L'] = (box((12, 18, 294), (252, 198, 306)), BIRCH)
parts['P12_ceiling_R'] = (box((486, 18, 294), (726, 198, 306)), BIRCH)

# P9 service door (overlay, proud of back): C9 USB-C + C10 exhaust
p9 = cut(box((269, 210, 10), (469, 222, 320)),
         [cyl('y', 414, 65, 209, 223, 12)] +
         [cyl('y', x, 285, 209, 223, 9.5) for x in (315, 351, 387, 423)])
parts['P9_door'] = (p9, BIRCH_DK)

# ── hardware / cosmetics ────────────────────────────────────────────
# H1 handle: two posts + tube
post1 = cyl('z', 258, 108, 360, 400, 6)
post2 = cyl('z', 480, 108, 360, 400, 6)
tube = cyl('x', 108, 400, 219, 519, 12.5)
parts['H1_handle'] = (trimesh.util.concatenate([post1, post2, tube]), ALU)

# Drivers (cosmetic discs + surround ring)
for nm, x in (('DRV_L', 132), ('DRV_R', 606)):
    disc = cyl('y', x, 140, -6, 0, 80)
    cone = cyl('y', x, 140, -9, -5, 40)
    parts[nm] = (trimesh.util.concatenate([disc, cone]), DARK)

# Screen glass
parts['SCREEN'] = (box((276.5, 3, 89.5), (461.5, 4.5, 190.5)), GLASS)

# LED diffuser
parts['A1_diffuser'] = (box((74, 0.5, 246), (664, 3.5, 266)), WHITE)

# Volume knob
parts['KNOB'] = (cyl('y', 666, 327, -22, 0, 22.5), ALU)

# Buttons (proud caps)
btns = [cyl('y', x, 327, -4, 0, 9) for x in (301, 335, 369, 403, 437)]
btns += [cyl('y', x, 327, -4, 0, 9) for x in (60, 90, 120, 150, 180, 210)]
parts['BUTTONS'] = (trimesh.util.concatenate(btns), ALU)

# Feet
feet = [cyl('z', x, y, -10, 0, 19) for x, y in
        ((45, 45), (369, 45), (693, 45), (45, 165), (369, 165), (693, 165))]
parts['FEET'] = (trimesh.util.concatenate(feet), DARK)

# ── assemble scene ──────────────────────────────────────────────────
scene = trimesh.Scene()
for name, (mesh, color) in parts.items():
    mesh.visual.face_colors = color
    scene.add_geometry(mesh, node_name=name, geom_name=name)

# sanity report
print(f"{'part':16s} {'watertight':>10s} {'volume_cm3':>11s}  bounds(mm)")
for name, (mesh, _) in parts.items():
    b = mesh.bounds
    print(f"{name:16s} {str(mesh.is_watertight):>10s} {mesh.volume/1000:11.1f}  "
          f"x[{b[0][0]:.0f},{b[1][0]:.0f}] y[{b[0][1]:.0f},{b[1][1]:.0f}] z[{b[0][2]:.0f},{b[1][2]:.0f}]")

import os

out = os.path.expanduser('~/code/Boombox/hardware/enclosure')
os.makedirs(out, exist_ok=True)

# DAE via pycollada — named nodes + per-part materials, mm units
import collada as co

mesh_doc = co.Collada()
mesh_doc.assetInfo.unitname = 'millimeter'
mesh_doc.assetInfo.unitmeter = 0.001
mesh_doc.assetInfo.upaxis = 'Z_UP'
nodes = []
for name, (m, color) in parts.items():
    rgba = [c / 255 for c in color]
    eff = co.material.Effect(f'eff_{name}', [], 'lambert', diffuse=rgba[:3] + [1.0])
    mat = co.material.Material(f'mat_{name}', f'mat_{name}', eff)
    mesh_doc.effects.append(eff)
    mesh_doc.materials.append(mat)
    verts = m.vertices.flatten()
    vs = co.source.FloatSource(f'v_{name}', np.array(verts), ('X', 'Y', 'Z'))
    geom = co.geometry.Geometry(mesh_doc, f'geom_{name}', name, [vs])
    il = co.source.InputList()
    il.addInput(0, 'VERTEX', f'#v_{name}')
    tris = geom.createTriangleSet(m.faces.flatten(), il, f'mat_{name}')
    geom.primitives.append(tris)
    mesh_doc.geometries.append(geom)
    matnode = co.scene.MaterialNode(f'mat_{name}', mat, inputs=[])
    geomnode = co.scene.GeometryNode(geom, [matnode])
    nodes.append(co.scene.Node(name, children=[geomnode]))
myscene = co.scene.Scene('boombox_mk1', nodes)
mesh_doc.scenes.append(myscene)
mesh_doc.scene = myscene
mesh_doc.write(os.path.join(out, 'boombox-mk1.dae'))

scene.export(os.path.join(out, 'boombox-mk1.obj'))
merged = trimesh.util.concatenate([m for m, _ in parts.values()])
merged.export(os.path.join(out, 'boombox-mk1.stl'))
print('\nexported to', out)

# ── verification renders (matplotlib orthographic) ──────────────────
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

fig = plt.figure(figsize=(14, 6))
for i, (elev, azim, title) in enumerate(((12, -35, 'iso front-left'),
                                         (12, 215, 'iso back-right')), 1):
    ax = fig.add_subplot(1, 2, i, projection='3d')
    for name, (mesh, color) in parts.items():
        m = mesh.copy()
        pass
        pc = Poly3DCollection(m.vertices[m.faces], alpha=1.0)
        pc.set_facecolor(np.array(color[:3]) / 255)
        pc.set_edgecolor('none')
        ax.add_collection3d(pc)
    ax.set_xlim(0, 760); ax.set_ylim(-260, 500); ax.set_zlim(-40, 720)
    ax.set_box_aspect((760, 760, 760))
    ax.view_init(elev=elev, azim=azim)
    ax.axis('off'); ax.set_title(title)
plt.tight_layout()
plt.savefig('model-preview.png', dpi=90)
print('preview saved')
