"""Roads, paths, land and water: flat ribbons and polygons laid on the ground.

Layers sit a few centimetres apart so viewers without explicit depth
ordering do not flicker (z-fight) where they overlap. With terrain, every
layer is draped over the ground: lines are split every few metres and
polygons are subdivided so they follow the slope. Water stays level, at
the lowest point of its outline.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable

from . import markings
from .geo import Point, poly_contains, triangulate
from .mesh import Colour, Mesh, Vec3, srgb
from .opendata import LandCover
from .osm import Area, Building, Path, Road
from .style import LINE, SURFACE, Style
from .terrain import GRID_STEP, Terrain

Height = Callable[[float, float], float]

# Drawing order, bottom to top. Later kinds cover earlier ones where they overlap.
AREA_ORDER = ('wood', 'grass', 'cemetery', 'parking', 'track', 'pitch', 'pool', 'water')
# Woods can cover whole hillsides. On terrain they are painted into the
# ground grid's colours instead of being draped as separate polygons, which
# would cost far more triangles than the ground itself. Smaller areas are
# draped, which keeps their edges sharp.
NATURAL = ('wood',)
Y_AREA = {kind: 0.005 * i for i, kind in enumerate(AREA_ORDER)}
Y_MARKINGS = Y_AREA['water'] + 0.005
Y_PATH = Y_MARKINGS + 0.005
Y_WALK, Y_KERB, Y_ROAD = 0.07, 0.08, 0.09
# On terrain, lift every layer clear of the ground mesh, whose flat
# triangles can sit slightly above the true surface between grid points.
TERRAIN_CLEARANCE = 0.3
DRAPE_STEP = 8.0  # metres between draped points on lines and polygon edges
# Draped layers are cut into different triangles, so on a slope they can
# cross each other by a few centimetres. Spread the layers further apart.
TERRAIN_SPACING = 5.0
# Surface a path has when OSM gives none: paved for footways, bare for paths.
PATH_SURFACE = {'path': 'unpaved', 'track': 'unpaved'}
WALK_WIDTH = 2.2
KERB_WIDTH = 0.35
JOINT_SEGMENTS = 10


def _lift(ground: Height | None) -> Height:
    """Height of a layer's base: the terrain plus clearance, or zero on flat ground."""
    if ground is None:
        return lambda x, z: 0.0
    g = ground
    return lambda x, z: g(x, z) + TERRAIN_CLEARANCE


def _layer(y: float, ground: Height | None) -> float:
    """A layer's offset above the ground, spread further apart on terrain."""
    return y * TERRAIN_SPACING if ground else y


def _densify(pts: list[Point], step: float) -> list[Point]:
    """The polyline with extra points so no segment is longer than `step`."""
    out = [pts[0]]
    for (x0, z0), (x1, z1) in itertools.pairwise(pts):
        n = max(1, math.ceil(math.hypot(x1 - x0, z1 - z0) / step))
        out += [(x0 + (x1 - x0) * k / n, z0 + (z1 - z0) * k / n) for k in range(1, n + 1)]
    return out


def _subdivide(tri: tuple[Point, Point, Point], step: float) -> list[tuple[Point, Point, Point]]:
    """Split a triangle at the midpoint of its longest edge until every edge is at most `step`."""
    out, todo = [], [tri]
    while todo:
        a, b, c = todo.pop()
        longest, which = max((math.dist(a, b), 0), (math.dist(b, c), 1), (math.dist(c, a), 2))
        if longest <= step:
            out.append((a, b, c))
        elif which == 0:
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            todo += [(a, m, c), (m, b, c)]
        elif which == 1:
            m = ((b[0] + c[0]) / 2, (b[1] + c[1]) / 2)
            todo += [(a, b, m), (a, m, c)]
        else:
            m = ((c[0] + a[0]) / 2, (c[1] + a[1]) / 2)
            todo += [(a, b, m), (m, b, c)]
    return out


def _ribbon(
    m: Mesh, pts: list[Point], half: float, y: float, col: Colour, base: Height, joints: list[Point] | None = None
) -> None:
    """A strip `half` metres either side of the line, with round joints so bends have no gaps.

    `joints` are the points that get a round joint; by default every point.
    Draped lines pass their original points, since the extra points added
    for the slope lie on straight runs and need no joint.
    """

    def at(x: float, z: float) -> Vec3:
        return x, base(x, z) + y, z

    for (x0, z0), (x1, z1) in itertools.pairwise(pts):
        dx, dz = x1 - x0, z1 - z0
        ln = math.hypot(dx, dz) or 1.0
        nx, nz = -dz / ln * half, dx / ln * half
        a, b = at(x0 + nx, z0 + nz), at(x0 - nx, z0 - nz)
        c, d = at(x1 - nx, z1 - nz), at(x1 + nx, z1 + nz)
        m.tri_up([a, b, c], col)
        m.tri_up([a, c, d], col)
    for x, z in joints if joints is not None else pts:
        centre = at(x, z)
        for s in range(JOINT_SEGMENTS):
            t0 = 2 * math.pi * s / JOINT_SEGMENTS
            t1 = 2 * math.pi * (s + 1) / JOINT_SEGMENTS
            m.tri_up(
                [
                    centre,
                    at(x + half * math.cos(t0), z + half * math.sin(t0)),
                    at(x + half * math.cos(t1), z + half * math.sin(t1)),
                ],
                col,
            )


def build_roads(roads: list[Road], style: Style, ground: Height | None = None, walks: bool = True) -> list[Mesh]:
    """Asphalt ribbons, each with a kerb and (optionally) a sidewalk either side."""
    road_m, kerb_m, walk_m = Mesh('roads'), Mesh('kerbs'), Mesh('walks')
    kerb_c, walk_c = srgb(style.kerb), srgb(style.walk)
    base = _lift(ground)
    for r in roads:
        pts = _densify(r.points, DRAPE_STEP) if ground else r.points
        half = r.half_width
        # Asphalt unless the road is tagged with another surface (dirt, gravel, concrete...).
        surface = r.surface if r.surface in SURFACE and r.surface not in ('asphalt', 'paved') else None
        road_c = srgb(SURFACE[surface]) if surface else srgb(style.road)
        if walks and r.cls not in ('motorway', 'trunk', 'motorway_link', 'trunk_link'):
            _ribbon(walk_m, pts, half + WALK_WIDTH, _layer(Y_WALK, ground), walk_c, base, r.points)
        _ribbon(kerb_m, pts, half + KERB_WIDTH, _layer(Y_KERB, ground), kerb_c, base, r.points)
        _ribbon(road_m, pts, half, _layer(Y_ROAD, ground), road_c, base, r.points)
    return [walk_m, kerb_m, road_m]


def _covers(a: Area, x: float, z: float) -> bool:
    """True when (x, z) is inside the area and not in one of its holes."""
    return poly_contains(a.outline, x, z) and not any(poly_contains(h, x, z) for h in a.holes)


def water_level(a: Area, ground: Height | None) -> float:
    """The level of a water body or pool: the lowest ground on its outline (water is flat)."""
    base = _lift(ground)
    return min(base(x, z) for x, z in a.outline) + _layer(Y_AREA[a.kind], ground)


def area_colour(a: Area, style: Style) -> Colour:
    """A surface's colour: from its OSM `surface` tag when it has one, else the style's."""
    if a.kind in ('pitch', 'track', 'parking') and a.surface in SURFACE:
        return srgb(SURFACE[a.surface])
    return srgb(style.ground[a.kind])


def build_areas(areas: list[Area], style: Style, ground: Height | None = None, painted: bool = False) -> list[Mesh]:
    """Land, water, pools and sports surfaces as filled polygons, plus sport markings.

    When `painted`, woods are left out: the ground grid shows them instead.
    """
    land, water, lines = Mesh('land'), Mesh('water'), Mesh('markings')
    line_c = srgb(LINE)
    base = _lift(ground)
    for kind in AREA_ORDER:
        y = _layer(Y_AREA[kind], ground)
        if (ground or painted) and kind in NATURAL:
            continue  # painted into the ground grid by build_base
        for a in areas:
            if a.kind != kind:
                continue
            col = area_colour(a, style)
            pts, tris = triangulate(a.outline, a.holes)
            if kind in ('water', 'pool'):
                level = water_level(a, ground)
                for t in tris:
                    water.tri_up([(pts[i][0], level, pts[i][1]) for i in t], col)
                continue
            for t in tris:
                tri = (pts[t[0]], pts[t[1]], pts[t[2]])
                for p, q, r in _subdivide(tri, DRAPE_STEP) if ground else [tri]:
                    land.tri_up([(v[0], base(v[0], v[1]) + y, v[1]) for v in (p, q, r)], col)
            if kind == 'pitch':
                markings.draw(lines, a.outline, a.sport, _layer(Y_MARKINGS, ground), line_c, base)
    return [land, water, lines]


def build_paths(paths: list[Path], ground: Height | None = None) -> Mesh:
    """Footways, paths, cycleways and steps as thin ribbons, coloured by surface."""
    m = Mesh('paths')
    base = _lift(ground)
    for p in paths:
        surface = p.surface if p.surface in SURFACE else PATH_SURFACE.get(p.cls, 'paving_stones')
        pts = _densify(p.points, DRAPE_STEP) if ground else p.points
        _ribbon(m, pts, p.width / 2, _layer(Y_PATH, ground), srgb(SURFACE[surface]), base, p.points)
    return m


def ground_colour(
    style: Style, landcover: LandCover | None = None, areas: list[Area] | None = None
) -> Callable[[float, float], Colour]:
    """The colour of bare ground at a point: from land cover when there is some, else plain grass.

    Land cover is averaged over the 10 m cells around the point, which
    softens the edges between classes the way real ground blends. Without
    land cover, mapped woods are painted in.
    """
    plain = srgb(style.ground['grass'])
    plain = (plain[0] * 0.85, plain[1] * 0.85, plain[2] * 0.85)
    if landcover is not None:
        lc = landcover
        palette = {k: srgb(v) for k, v in style.cover.items()}
        offsets = [(dx * lc.cell, dz * lc.cell) for dx in (-1, 0, 1) for dz in (-1, 0, 1)]

        def from_cover(x: float, z: float) -> Colour:
            r = g = b = 0.0
            for dx, dz in offsets:
                c = palette.get(lc.at(x + dx, z + dz), plain)
                r, g, b = r + c[0], g + c[1], b + c[2]
            n = len(offsets)
            return r / n, g / n, b / n

        return from_cover
    natural = [a for kind in NATURAL for a in (areas or []) if a.kind == kind]  # later kinds win

    def from_areas(x: float, z: float) -> Colour:
        found = plain
        for a in natural:
            if _covers(a, x, z):
                found = srgb(style.ground[a.kind])
        return found

    return from_areas


def build_base(
    bounds: tuple[float, float, float, float],
    style: Style,
    terrain: Terrain | None = None,
    areas: list[Area] | None = None,
    landcover: LandCover | None = None,
    margin: float = 20.0,
    tile: float = 250.0,
) -> Mesh:
    """The ground under everything, slightly below the other layers.

    Flat ground without land cover is a few large tiles, split so no single
    triangle spans kilometres (some renderers clip those badly near the
    camera). With terrain or land cover, the ground is a 30 m grid with
    shared vertices, coloured by `ground_colour` and, with terrain, shaped
    by the elevation with smooth normals.

    Under water the ground is lowered below the water level: elevation
    data over water measures vegetation and noise, not the bed, and would
    otherwise poke through the surface.
    """
    x0, x1, z0, z1 = bounds
    x0, x1, z0, z1 = x0 - margin, x1 + margin, z0 - margin, z1 + margin
    m = Mesh('base')
    colour = ground_colour(style, landcover, areas)
    if terrain is None and landcover is None:
        nx, nz = max(1, math.ceil((x1 - x0) / tile)), max(1, math.ceil((z1 - z0) / tile))
        for i in range(nx):
            for j in range(nz):
                ax, bx = x0 + (x1 - x0) * i / nx, x0 + (x1 - x0) * (i + 1) / nx
                az, bz = z0 + (z1 - z0) * j / nz, z0 + (z1 - z0) * (j + 1) / nz
                corners = [(ax, -0.02, az), (bx, -0.02, az), (bx, -0.02, bz), (ax, -0.02, bz)]
                m.face(corners, colour(ax, az), (0.0, 1.0, 0.0))
        return m
    if terrain is None:
        terrain = Terrain.from_function(lambda x, z: 0.0, (x0, x1, z0, z1), GRID_STEP)
    wet = [a for a in (areas or []) if a.kind in ('water', 'pool')]
    levels = [water_level(a, terrain.height) - TERRAIN_CLEARANCE - 0.5 for a in wet]
    t = terrain

    def height(i: int, j: int, x: float, z: float) -> float:
        y = t.at(i, j) - 0.02
        for a, level in zip(wet, levels, strict=True):
            if _covers(a, x, z):
                y = min(y, level)
        return y

    # Use the terrain's own grid nodes, so the ground is exactly the surface Terrain.height describes.
    first_i = max(0, math.floor((x0 - t.x0) / t.cell))
    last_i = min(t.cols - 1, math.ceil((x1 - t.x0) / t.cell))
    first_j = max(0, math.floor((z0 - t.z0) / t.cell))
    last_j = min(t.rows - 1, math.ceil((z1 - t.z0) / t.cell))
    nx, nz = last_i - first_i, last_j - first_j
    if nx < 1 or nz < 1:
        return m
    xs = [t.x0 + (first_i + i) * t.cell for i in range(nx + 1)]
    zs = [t.z0 + (first_j + j) * t.cell for j in range(nz + 1)]
    heights = [[height(first_i + i, first_j + j, x, z) for i, x in enumerate(xs)] for j, z in enumerate(zs)]
    index: list[list[int]] = []
    for j, z in enumerate(zs):
        row = []
        for i, x in enumerate(xs):
            # Smooth normal from the slope to the neighbours either side.
            left, right, up, down = max(i - 1, 0), min(i + 1, nx), max(j - 1, 0), min(j + 1, nz)
            dx = (heights[j][right] - heights[j][left]) / (xs[right] - xs[left])
            dz = (heights[down][i] - heights[up][i]) / (zs[down] - zs[up])
            ln = math.sqrt(dx * dx + 1 + dz * dz)
            row.append(m.vert((x, heights[j][i], z), (-dx / ln, 1 / ln, -dz / ln), colour(x, z)))
        index.append(row)
    for j in range(nz):
        for i in range(nx):
            a, b, c, d = index[j][i], index[j][i + 1], index[j + 1][i + 1], index[j + 1][i]
            m.idx.extend([a, c, b, a, d, c])  # counter-clockwise seen from above (+y)
    return m


def build_shadows(
    buildings: list[Building],
    colour: Callable[[float, float], Colour],
    ground: Height | None = None,
    width: float = 1.6,
    darkness: float = 0.55,
) -> Mesh:
    """Soft contact shadow round the foot of each building: ambient occlusion, baked.

    A strip on the ground that is darkest against the wall and fades to the
    ground colour `width` metres out. It sits just above the ground grid
    and below every mapped surface, so roads and pitches still draw on top.
    """
    m = Mesh('shadows')
    y = 0.15 if ground else 0.002

    def at(x: float, z: float) -> Vec3:
        return x, (ground(x, z) if ground else 0.0) + y, z

    for b in buildings:
        ring = b.outline
        ccw = (
            sum(
                ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
                for i in range(len(ring))
            )
            > 0
        )
        normals = []
        for i in range(len(ring)):
            (ax, az), (bx, bz) = ring[i], ring[(i + 1) % len(ring)]
            ln = math.hypot(bx - ax, bz - az) or 1.0
            nx, nz = ((bz - az) / ln, -(bx - ax) / ln) if ccw else (-(bz - az) / ln, (bx - ax) / ln)
            normals.append((nx, nz))
        for i in range(len(ring)):
            a, c = ring[i], ring[(i + 1) % len(ring)]
            nx, nz = normals[i]
            pts = _densify([a, c], DRAPE_STEP) if ground else [a, c]
            for (px, pz), (qx, qz) in itertools.pairwise(pts):
                inner_p, inner_q = at(px, pz), at(qx, qz)
                outer_p, outer_q = at(px + nx * width, pz + nz * width), at(qx + nx * width, qz + nz * width)
                dark_p, dark_q = _dim(colour(px, pz), darkness), _dim(colour(qx, qz), darkness)
                light_p, light_q = colour(outer_p[0], outer_p[2]), colour(outer_q[0], outer_q[2])
                _quad(m, (inner_p, inner_q, outer_q, outer_p), (dark_p, dark_q, light_q, light_p))
            # Fill the wedge at the corner between this edge and the previous one.
            pnx, pnz = normals[i - 1]
            corner = at(*a)
            _quad(
                m,
                (corner, at(a[0] + pnx * width, a[1] + pnz * width), at(a[0] + nx * width, a[1] + nz * width), corner),
                (_dim(colour(*a), darkness), colour(*a), colour(*a), _dim(colour(*a), darkness)),
            )
    return m


def _dim(c: Colour, k: float) -> Colour:
    return c[0] * k, c[1] * k, c[2] * k


def _quad(m: Mesh, pts: tuple[Vec3, Vec3, Vec3, Vec3], cols: tuple[Colour, Colour, Colour, Colour]) -> None:
    """Two triangles facing up, with a colour per corner."""
    ids = [m.vert(p, (0.0, 1.0, 0.0), c) for p, c in zip(pts, cols, strict=True)]
    for a, b, c in ((0, 1, 2), (0, 2, 3)):
        pa, pb, pc = pts[a], pts[b], pts[c]
        ny = (pb[2] - pa[2]) * (pc[0] - pa[0]) - (pb[0] - pa[0]) * (pc[2] - pa[2])
        if abs(ny) < 1e-12:
            continue  # degenerate (the corner wedge's repeated point)
        m.idx.extend([ids[a], ids[b], ids[c]] if ny > 0 else [ids[a], ids[c], ids[b]])
