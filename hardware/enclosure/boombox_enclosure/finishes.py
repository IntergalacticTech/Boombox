"""Finishes: a material map plus cosmetic parts and their BOM lines. A finish never changes cut geometry."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    name: str
    rgba: tuple
    metallic: float
    roughness: float
    grain: bool = False  # draw wood grain along each panel's long horizontal axis


@dataclass(frozen=True)
class Finish:
    key: str
    label: str
    materials: dict  # body, face, trim, driver, glass, diffuser, handle, feet
    grille: bool  # chrome ring + mesh disc over each driver
    handle: str  # "tube" | "strap"
    bom: list  # (item, qty, note)


BLACK = Material("black", (22, 22, 24, 255), 0.0, 0.55)
RUBBER = Material("rubber", (30, 30, 30, 255), 0.0, 0.9)
GLASS = Material("glass", (12, 14, 20, 255), 0.0, 0.08)
DIFFUSER = Material("diffuser", (240, 238, 228, 255), 0.0, 0.6)
CHROME = Material("chrome", (225, 228, 232, 255), 1.0, 0.12)
SILVER = Material("brushed silver", (176, 180, 186, 255), 0.9, 0.42)
MESH = Material("grille mesh", (14, 14, 16, 255), 0.6, 0.7)
BIRCH = Material("birch", (214, 176, 116, 255), 0.0, 0.5, grain=True)
BIRCH_FACE = Material("birch face", (201, 160, 100, 255), 0.0, 0.5, grain=True)
LEATHER = Material("leather", (110, 68, 38, 255), 0.0, 0.8)
CONE = Material("driver cone", (34, 34, 36, 255), 0.0, 0.75)

FINISHES = {
    "classic": Finish(
        "classic", "Classic",
        {"body": BLACK, "face": SILVER, "trim": CHROME, "driver": MESH, "glass": GLASS,
         "diffuser": DIFFUSER, "handle": CHROME, "feet": RUBBER},
        grille=True, handle="tube",
        bom=[("Satin black paint or vinyl wrap (body)", 1, "all panels except the front"),
             ("Brushed-aluminium laminate or silver paint (front face)", 1,
              "on the baffle; apply before cutting holes"),
             ('6.5" chrome-ring mesh speaker grilles', 2, "mark screw holes from the part"),
             ("Chrome button caps, 16 mm", 0, "one per button"),
             ("Aluminium knob, polished", 1, "for the volume encoder"),
             ("Chrome or polished aluminium handle tube", 1, "on two M6 posts")],
    ),
    "wood": Finish(
        "wood", "Wood",
        {"body": BIRCH, "face": BIRCH_FACE, "trim": BLACK, "driver": CONE, "glass": GLASS,
         "diffuser": DIFFUSER, "handle": LEATHER, "feet": RUBBER},
        grille=False, handle="strap",
        bom=[("Clear satin polyurethane", 1, "three coats; Baltic birch as cut, or walnut veneer on the show faces"),
             ("Black trim rings for the drivers", 2, "or leave the driver frames exposed"),
             ("Black button caps, 16 mm", 0, "one per button"),
             ("Wood or brass knob", 1, "for the volume encoder"),
             ("Leather carry strap", 1, "on two M6 posts")],
    ),
}
