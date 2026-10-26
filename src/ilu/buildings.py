"""Raise OSM building outlines into walls and roofs.

Where OSM records a height (`height`, `building:levels`, `min_height`) or a
roof shape (`roof:shape`, `roof:height`), that is used, including detailed
building parts (Simple 3D Buildings) such as a mosque's domes and
minarets. Most buildings carry none of it, so the rest is guessed from the
footprint's size and shape and the building's type. Courtyards (inner
rings) get their own walls facing in. On sloping ground a building stands
on the lowest point of its footprint.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from .facade import BAY, FLOOR
from .geo import Point, Rect, centroid, min_rect, poly_contains, signed_area, triangulate
from .glb import FACADE
from .mesh import Colour, Mesh, shade, srgb
from .osm import Building
from .style import Style

PARAPET = 0.5  # low wall around a flat roof
PLINTH = 0.9  # height of the darker base band
OCCLUSION = 0.75  # how dark a wall gets where it meets the ground
OCCLUSION_HEIGHT = 2.0  # metres over which that fades out

# Building types built as big institutional blocks (concrete, more floors).
BLOCK_KINDS = {
    'university',
    'college',
    'school',
    'office',
    'commercial',
    'hospital',
    'public',
    'government',
    'civic',
    'hotel',
    'apartments',
    'dormitory',
}
HOUSE_KINDS = {'house', 'residential', 'detached', 'bungalow', 'semidetached_house', 'terrace'}
BLOCK_AREA = 1500.0

# OSM roof:shape values drawn by shrinking the outline towards its centre as it rises.
ROUND_ROOFS = {'dome': 'dome', 'onion': 'onion', 'cone': 'cone', 'conical': 'cone', 'pyramidal': 'pyramid'}
# Each profile is (share of the outline's size, share of the roof's height), from the eave to the top.
PROFILES = {
    'dome': [(math.cos(math.pi / 2 * k / 6), math.sin(math.pi / 2 * k / 6)) for k in range(7)],
    'onion': [(1.0, 0.0), (1.22, 0.14), (1.28, 0.3), (1.1, 0.48), (0.62, 0.68), (0.22, 0.86), (0.0, 1.0)],
    'cone': [(1.0, 0.0), (0.0, 1.0)],
    'pyramid': [(1.0, 0.0), (0.0, 1.0)],
}
DOME = '#9BA1A6'
SPIRE_AREA = 30.0  # a pyramid roof on a smaller footprint is a spire, and gets the metal colour
# Guessed roof height, in multiples of the footprint's radius, when roof:height is not tagged.
ROUND_RISE = {'dome': 1.0, 'onion': 1.6, 'cone': 2.2, 'pyramid': 0.6}


@dataclass(frozen=True)
class Shape:
    floors: int
    roof: str  # flat, hip, gable, lean, or a round top: dome, onion, cone or pyramid
    block: bool  # an institutional block
    rectish: bool  # close enough to a rectangle for a pitched roof


def guess_shape(b: Building, pts: list[Point], rect: Rect | None, rng: random.Random) -> Shape:
    """Floors and roof for one footprint."""
    area = abs(signed_area(pts)) - sum(abs(signed_area(h)) for h in b.holes)
    block = b.kind in BLOCK_KINDS or area > BLOCK_AREA
    rectish = not b.holes and rect is not None and area / max(rect[3] * rect[4], 1e-6) > 0.82 and len(pts) <= 8
    aspect = rect[3] / max(rect[4], 0.1) if rect else 1.0
    if b.measured:
        floors = max(1, round((b.height - b.base - (b.roof_height or 0.0)) / FLOOR))
    elif area < 30:
        floors = 1
    elif block:
        floors = 4 if area > 1500 else (3 if area > 700 else 2)
    elif b.kind in HOUSE_KINDS or area < 220:
        floors = 1 if rng.random() < 0.8 else 2
    else:
        floors = 2 if area < 900 else 3
    tag = b.roof
    if tag == 'flat':
        roof = 'flat'
    elif tag in ROUND_ROOFS:
        roof = ROUND_ROOFS[tag] if not b.holes and poly_contains(pts, *centroid(pts)) else 'flat'
    elif tag in ('gabled', 'half-hipped'):
        roof = 'gable' if rectish else 'flat'
    elif tag == 'hipped':
        roof = 'hip' if rectish else 'flat'
    elif tag == 'skillion':
        roof = 'lean' if rectish else 'flat'
    elif b.part:
        roof = 'flat'  # a part without a roof:shape is flat-topped, as Simple 3D Buildings says
    elif area < 30 and rectish:
        roof = 'lean'
    elif rectish and not block and area < 450:
        roof = 'hip' if aspect < 2.2 else 'gable'
    elif rectish and not block and floors <= 2 and rng.random() < 0.5:
        roof = 'hip'
    else:
        roof = 'flat'
    return Shape(floors, roof, block, rectish)


def _at(rect: Rect, x: float, z: float, y: float) -> tuple[float, float, float]:
    cx, cz, ang, _, _ = rect
    ca, sa = math.cos(ang), math.sin(ang)
    return cx + ca * x - sa * z, y, cz + sa * x + ca * z


def hip_roof(m: Mesh, rect: Rect, eave: float, col: Colour, over: float = 0.6) -> None:
    """A hipped roof (a pyramid on a square) with overhanging eaves."""
    _, _, ang, length, width = rect
    hl, hw = length / 2 + over, width / 2 + over
    rise = min(3.2, 0.3 * hw * 2)
    ridge = max(0.0, hl - hw)
    ca, sa = math.cos(ang), math.sin(ang)
    e = eave - 0.2
    a, b, c, d = _at(rect, -hl, -hw, e), _at(rect, hl, -hw, e), _at(rect, hl, hw, e), _at(rect, -hl, hw, e)
    r0, r1 = _at(rect, -ridge, 0, eave + rise), _at(rect, ridge, 0, eave + rise)
    m.face([a, b, r1, r0], col, (sa * 0.6, 1.0, -ca * 0.6))
    m.face([d, c, r1, r0], col, (-sa * 0.6, 1.0, ca * 0.6))
    m.face([b, c, r1], col, (ca * 0.6, 1.0, sa * 0.6))
    m.face([a, d, r0], col, (-ca * 0.6, 1.0, -sa * 0.6))


def gable_roof(m: Mesh, rect: Rect, eave: float, col: Colour, wall: Colour, over: float = 0.5) -> None:
    """A pitched roof along the long axis, with wall-coloured gable ends."""
    cx, cz, ang, length, width = rect
    hl, hw = length / 2 + over, width / 2 + over
    ridge = eave + min(4.0, 0.36 * hw * 2)
    ca, sa = math.cos(ang), math.sin(ang)
    e = eave - 0.25
    a, b, c, d = _at(rect, -hl, -hw, e), _at(rect, hl, -hw, e), _at(rect, hl, hw, e), _at(rect, -hl, hw, e)
    r0, r1 = _at(rect, -hl, 0, ridge), _at(rect, hl, 0, ridge)
    m.face([a, b, r1, r0], col, (sa * 0.6, 1.0, -ca * 0.6))
    m.face([d, c, r1, r0], shade(col, 0.82), (-sa * 0.6, 1.0, ca * 0.6))
    for tri in ((a, d, r0), (b, c, r1)):
        mx = sum(q[0] for q in tri) / 3 - cx
        mz = sum(q[2] for q in tri) / 3 - cz
        m.face(list(tri), shade(wall, 0.9), (mx, 0.0, mz))


def lean_roof(m: Mesh, rect: Rect, eave: float, col: Colour, over: float = 0.4) -> None:
    """One sloping sheet: kiosks and sheds."""
    _, _, ang, length, width = rect
    hl, hw = length / 2 + over, width / 2 + over
    ca, sa = math.cos(ang), math.sin(ang)
    lo, hi = eave - 0.1, eave + 0.6
    m.face(
        [_at(rect, -hl, -hw, lo), _at(rect, hl, -hw, lo), _at(rect, hl, hw, hi), _at(rect, -hl, hw, hi)],
        col,
        (sa * 0.3, 1.0, -ca * 0.3),
    )


def round_roof(m: Mesh, ring: list[Point], eave: float, rise: float, profile: str, col: Colour) -> None:
    """A dome, onion, cone or pyramid: the outline shrunk towards its centre as it rises."""
    cx, cz = centroid(ring)
    steps = PROFILES[profile]
    levels = [[(cx + (x - cx) * r, eave + rise * h, cz + (z - cz) * r) for x, z in ring] for r, h in steps]
    mid = eave + rise * 0.3
    n = len(ring)
    for k in range(len(levels) - 1):
        lo, hi = levels[k], levels[k + 1]
        for i in range(n):
            j = (i + 1) % n
            quad = [lo[i], lo[j], hi[j]] if steps[k + 1][0] == 0 else [lo[i], lo[j], hi[j], hi[i]]
            a, b, c = quad[0], quad[1], quad[2] if len(quad) == 3 else quad[3]
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            px = sum(q[0] for q in quad) / len(quad) - cx
            py = sum(q[1] for q in quad) / len(quad) - mid
            pz = sum(q[2] for q in quad) / len(quad) - cz
            if nx * px + ny * py + nz * pz < 0:
                nx, ny, nz = -nx, -ny, -nz
            if nx or ny or nz:
                m.face(quad, col, (nx, ny, nz))


def round_rise(b: Building, pts: list[Point], profile: str) -> float:
    """The roof's height: roof:height if tagged, otherwise a guess from the footprint."""
    if b.roof_height:
        return b.roof_height
    radius = math.sqrt(abs(signed_area(pts)) / math.pi)
    rise = ROUND_RISE[profile] * radius
    return min(rise, 4.0) if profile == 'pyramid' else rise


def water_tank(
    m: Mesh, x: float, y: float, z: float, col: Colour, r: float = 0.7, h: float = 1.4, seg: int = 8
) -> None:
    """An overhead plastic tank on a small block."""
    m.box(x, z, 0.0, r * 2.1, r * 2.1, y, y + 0.3, srgb('#A9A39A'))
    top = y + 0.3 + h
    ring = [(x + r * math.cos(2 * math.pi * i / seg), z + r * math.sin(2 * math.pi * i / seg)) for i in range(seg)]
    for i in range(seg):
        a, b = ring[i], ring[(i + 1) % seg]
        mx, mz = (a[0] + b[0]) / 2 - x, (a[1] + b[1]) / 2 - z
        m.face([(a[0], y + 0.3, a[1]), (b[0], y + 0.3, b[1]), (b[0], top, b[1]), (a[0], top, a[1])], col, (mx, 0.0, mz))
    m.face([(q[0], top, q[1]) for q in ring], shade(col, 1.15), (0.0, 1.0, 0.0))


@dataclass
class BuildingMeshes:
    walls: Mesh
    roofs: Mesh
    details: Mesh

    @classmethod
    def empty(cls, facades: bool = True) -> BuildingMeshes:
        walls = Mesh('walls', uv=True, material=FACADE) if facades else Mesh('walls')
        return cls(walls, Mesh('roofs'), Mesh('details'))

    def underside(self, tri: list[tuple[float, float, float]], col: Colour) -> None:
        self.roofs.face(tri, col, (0.0, -1.0, 0.0))

    def lift(self, y: float) -> None:
        self.walls.lift = self.roofs.lift = self.details.lift = y


Height = Callable[[float, float], float]


def build(
    buildings: list[Building],
    style: Style,
    seed: int = 0,
    ground: Height | None = None,
    facades: bool = True,
) -> tuple[BuildingMeshes, list[Shape]]:
    """Every building into three merged meshes. Deterministic for a given seed.

    `ground(x, z)` gives the terrain height; without it the ground is flat.
    Each building's random choices are seeded from its position, so a
    building looks the same however the area is split into tiles.
    """
    out = BuildingMeshes.empty(facades)
    shapes: list[Shape] = []
    for b in buildings:
        pts = b.outline
        if len(pts) < 3:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[1] for p in pts) / len(pts)
        rng = random.Random(f'{seed}:{cx:.1f}:{cz:.1f}')
        rect = min_rect(pts) if len(pts) >= 4 else None
        shape = guess_shape(b, pts, rect, rng)
        shapes.append(shape)
        out.lift(min(ground(x, z) for x, z in pts) if ground else 0.0)
        _one(out, b, rect, shape, style, rng)
    out.lift(0.0)
    return out, shapes


def _walls(
    out: BuildingMeshes,
    ring: list[Point],
    facing: float,
    top: float,
    wall: Colour,
    plinth: Colour,
    shape: Shape,
    flat: bool,
    eave: float,
    base: float = 0.0,
) -> None:
    """Walls round one ring, from `base` up. `facing` is +1 for an outer ring and -1 for a courtyard."""
    ccw = signed_area(ring) > 0
    foot = shade(wall, 0.72)
    for i in range(len(ring)):
        a, c = ring[i], ring[(i + 1) % len(ring)]
        dx, dz = c[0] - a[0], c[1] - a[1]
        ln = math.hypot(dx, dz) or 1.0
        sx, sz = (dz / ln, -dx / ln) if ccw else (-dz / ln, dx / ln)
        outward = (sx * facing, sz * facing)
        # A whole number of window bays per wall, so windows never get cut at corners.
        bays = max(1, round(ln / BAY)) if ln >= 2.0 else 0
        if base > 0:
            # A part standing on another: no plinth or ground shadow, windows lined up with the floors below.
            out.walls.wall(a, c, base, top, wall, wall, outward, (0.0, float(bays), base / FLOOR, top / FLOOR))
        else:
            out.walls.wall(a, c, 0.0, PLINTH, shade(plinth, OCCLUSION), plinth, outward, (0.02, 0.02, 0.02, 0.02))
            # Ambient occlusion: the wall darkens towards the ground over its lowest few metres.
            fade = min(top, PLINTH + OCCLUSION_HEIGHT)
            uv_fade = PLINTH / FLOOR, fade / FLOOR
            out.walls.wall(a, c, PLINTH, fade, foot, wall, outward, (0.0, float(bays), *uv_fade))
            if top > fade:
                out.walls.wall(a, c, fade, top, wall, wall, outward, (0.0, float(bays), fade / FLOOR, top / FLOOR))
        if shape.block and shape.floors >= 2 and ln >= 5:
            ang = math.atan2(dz, dx)
            mx, mz = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
            for f in range(1, shape.floors):
                y = base + f * FLOOR
                out.details.box(mx, mz, ang, ln + 0.3, 0.5, y - 0.13, y + 0.13, shade(wall, 1.12))
        if flat:
            # Inside face of the parapet, so the roof reads as sunk behind it.
            out.roofs.wall(c, a, eave, top, shade(wall, 0.62), shade(wall, 0.8), (-outward[0], -outward[1]))


def _one(out: BuildingMeshes, b: Building, rect: Rect | None, shape: Shape, style: Style, rng: random.Random) -> None:
    pts = b.outline
    rounded = shape.roof in PROFILES
    rise = round_rise(b, pts, shape.roof) if rounded else 0.0
    if b.part or b.base > 0 or b.kind in ('minaret', 'tower') or (rounded and b.measured):
        # Parts must meet the parts above and below them, and towers are not built in floors,
        # so these keep their exact heights.
        eave = max(b.height - (rise if rounded else (b.roof_height or 0.0)), b.base + 0.5)
    else:
        eave = shape.floors * FLOOR
    flat = shape.roof == 'flat' or (rect is None and not rounded)
    top = eave + (PARAPET if flat and not b.part else 0.0)
    if shape.block:
        wall = srgb(style.concrete[rng.randrange(len(style.concrete))])
        plinth = shade(wall, 0.8)
    else:
        wall = srgb(style.house[rng.randrange(len(style.house))])
        plinth = srgb(style.plinth[rng.randrange(len(style.plinth))])
    if b.colour:  # a real colour from OSM beats the palette
        wall = srgb(b.colour)
        plinth = shade(wall, 0.8)
    _walls(out, pts, 1.0, top, wall, plinth, shape, flat and not b.part, eave, b.base)
    for hole in b.holes:
        _walls(out, hole, -1.0, top, wall, plinth, shape, flat and not b.part, eave, b.base)
    if b.base > 0:  # the underside, seen from below where a part overhangs
        tri_pts, tris = triangulate(pts, b.holes)
        for t in tris:
            out.underside([(tri_pts[i][0], b.base, tri_pts[i][1]) for i in t], shade(wall, 0.55))
    if rounded:
        if b.roof_colour:
            cover = srgb(b.roof_colour)
        elif shape.roof == 'pyramid' and abs(signed_area(pts)) >= SPIRE_AREA:
            cover = srgb(style.sheet[rng.randrange(len(style.sheet))])
        else:
            cover = srgb(DOME)  # domes and spires untagged for colour get plain metal, not a guessed paint
        round_roof(out.roofs, pts, eave, rise, shape.roof, cover)
        return
    if flat:
        slab = srgb(b.roof_colour) if b.roof_colour else srgb(style.slab[rng.randrange(len(style.slab))])
        tri_pts, tris = triangulate(pts, b.holes)
        for t in tris:
            out.roofs.tri_up([(tri_pts[i][0], eave, tri_pts[i][1]) for i in t], slab)
        if style.tank_chance and abs(signed_area(pts)) > 60 and rng.random() < style.tank_chance:
            tx, tz = _tank_spot(pts, rect, rng)
            if poly_contains(pts, tx, tz) and not any(poly_contains(h, tx, tz) for h in b.holes):
                water_tank(out.details, tx, eave, tz, srgb(style.tanks[rng.randrange(len(style.tanks))]))
        return
    assert rect is not None
    sheet = srgb(style.sheet[rng.randrange(len(style.sheet))])
    if b.roof_colour:
        sheet = srgb(b.roof_colour)
    if shape.roof == 'hip':
        hip_roof(out.roofs, rect, eave, sheet)
    elif shape.roof == 'gable':
        gable_roof(out.roofs, rect, eave, sheet, wall)
    else:
        lean_roof(out.roofs, rect, eave, sheet)


def _tank_spot(pts: list[Point], rect: Rect | None, rng: random.Random) -> tuple[float, float]:
    if rect is None:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    cx, cz, ang, length, width = rect
    ox = (rng.random() - 0.5) * length * 0.4
    oz = (rng.random() - 0.5) * width * 0.4
    return cx + math.cos(ang) * ox - math.sin(ang) * oz, cz + math.sin(ang) * ox + math.cos(ang) * oz
