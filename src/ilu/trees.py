"""Seeded tree placement along roads and in woods, never on a building or road."""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable
from typing import Generic, TypeVar

from .geo import Point, poly_contains, seg_dist
from .mesh import Mesh, shade, srgb
from .opendata import TreeTop
from .osm import Area, Building, Path, Road
from .style import Style

Tree = tuple[float, float, float]  # x, z, scale
Segment = tuple[float, float, float, float, float]  # ax, az, bx, bz, clearance

T = TypeVar('T')


class _Grid(Generic[T]):
    """A spatial hash, so each placement only tests nearby shapes."""

    def __init__(self, cell: float = 40.0) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list[T]] = {}

    def add(self, minx: float, minz: float, maxx: float, maxz: float, item: T) -> None:
        c = self.cell
        for gx in range(math.floor(minx / c), math.floor(maxx / c) + 1):
            for gz in range(math.floor(minz / c), math.floor(maxz / c) + 1):
                self.cells.setdefault((gx, gz), []).append(item)

    def near(self, x: float, z: float) -> list[T]:
        return self.cells.get((math.floor(x / self.cell), math.floor(z / self.cell)), [])


def place(
    buildings: list[Building],
    roads: list[Road],
    areas: list[Area],
    seed: int = 0,
    spacing: tuple[float, float] = (11.0, 18.0),
) -> list[Tree]:
    """Decorative trees when there is no canopy data: avenues along roads, and planting in woods."""
    rng = random.Random(f'trees:{seed}')
    ok = _clear_spot(buildings, roads, areas)
    trees: list[Tree] = []

    def put(x: float, z: float, dense: bool = False) -> None:
        if ok(x, z):
            trees.append((round(x, 1), round(z, 1), round(rng.uniform(0.75, 1.5) * (1.15 if dense else 1.0), 2)))

    for r in roads:
        if r.cls in ('motorway', 'trunk'):
            continue
        half = r.half_width + 3.2
        acc = rng.uniform(0, spacing[1])
        for (ax, az), (bx, bz) in itertools.pairwise(r.points):
            ln = math.hypot(bx - ax, bz - az)
            if ln < 1:
                continue
            nx, nz = -(bz - az) / ln, (bx - ax) / ln
            t = acc
            while t < ln:
                f = t / ln
                x, z = ax + (bx - ax) * f, az + (bz - az) * f
                for side in (1, -1):
                    if rng.random() < 0.7:
                        off = half + rng.uniform(0.5, 3.0)
                        put(x + nx * off * side, z + nz * off * side)
                t += rng.uniform(*spacing)
            acc = t - ln
    for a in areas:
        if a.kind != 'wood':
            continue
        xs, zs = [p[0] for p in a.outline], [p[1] for p in a.outline]
        for _ in range(int((max(xs) - min(xs)) * (max(zs) - min(zs)) / 140)):
            x, z = rng.uniform(min(xs), max(xs)), rng.uniform(min(zs), max(zs))
            if poly_contains(a.outline, x, z):
                put(x, z, dense=True)
    return trees


def _clear_spot(buildings: list[Building], roads: list[Road], areas: list[Area]) -> Callable[[float, float], bool]:
    """A test for where a tree may stand: not on or right beside a building, not on a road, water or pitch."""
    bgrid: _Grid[list[Point]] = _Grid()
    rgrid: _Grid[Segment] = _Grid()
    for b in buildings:
        xs, zs = [p[0] for p in b.outline], [p[1] for p in b.outline]
        bgrid.add(min(xs) - 3, min(zs) - 3, max(xs) + 3, max(zs) + 3, b.outline)
    for r in roads:
        half = r.half_width + 2.6
        for (ax, az), (bx, bz) in itertools.pairwise(r.points):
            box = (min(ax, bx) - half, min(az, bz) - half, max(ax, bx) + half, max(az, bz) + half)
            rgrid.add(*box, (ax, az, bx, bz, half))
    blocked = [a.outline for a in areas if a.kind in ('water', 'pool', 'pitch', 'track', 'parking')]

    def ok(x: float, z: float) -> bool:
        for poly in bgrid.near(x, z):
            if poly_contains(poly, x, z) or any(math.hypot(x - p[0], z - p[1]) < 2.5 for p in poly):
                return False
        for ax, az, bx, bz, half in rgrid.near(x, z):
            if seg_dist(x, z, ax, az, bx, bz) < half:
                return False
        return not any(poly_contains(p, x, z) for p in blocked)

    return ok


def from_canopy(
    tops: list[TreeTop],
    buildings: list[Building],
    roads: list[Road],
    paths: list[Path],
    areas: list[Area],
    budget: int,
    near: float = 120.0,
) -> list[Tree]:
    """Real trees from the canopy height map, chosen to fit a budget.

    Every tree position and height is real. When there are more trees than
    the budget, trees within `near` metres of buildings, roads and paths,
    where people look, are kept first; the rest are thinned evenly by
    keeping the tallest tree in each square of a grid. Trees on buildings,
    roads, water and pitches are dropped.
    """
    busy: set[tuple[int, int]] = set()
    for poly in [b.outline for b in buildings] + [r.points for r in roads] + [p.points for p in paths]:
        for x, z in poly:
            busy.add((math.floor(x / near), math.floor(z / near)))

    def is_near(t: TreeTop) -> bool:
        cx, cz = math.floor(t.x / near), math.floor(t.z / near)
        return any((cx + dx, cz + dz) in busy for dx in (-1, 0, 1) for dz in (-1, 0, 1))

    close = [t for t in tops if is_near(t)]
    far = [t for t in tops if not is_near(t)]
    ok = _clear_spot(buildings, roads, areas)
    chosen = [t for t in _thin(close, budget) if ok(t.x, t.z)]
    if len(chosen) < budget:
        chosen += [t for t in _thin(far, budget - len(chosen)) if ok(t.x, t.z)]
    chosen.sort(key=lambda t: (t.z, t.x))
    # The tree model is 5.8 m tall at scale 1.
    return [(t.x, t.z, round(min(max(t.height / 5.8, 0.5), 6.5), 2)) for t in chosen[:budget]]


def _thin(tops: list[TreeTop], budget: int) -> list[TreeTop]:
    """At most `budget` trees, evenly spread: the tallest in each grid square, growing the squares until they fit."""
    if budget <= 0:
        return []
    cell = 8.0
    kept = tops
    while len(kept) > budget:
        best: dict[tuple[int, int], TreeTop] = {}
        for t in tops:
            k = (math.floor(t.x / cell), math.floor(t.z / cell))
            if k not in best or (t.height, -t.x, -t.z) > (best[k].height, -best[k].x, -best[k].z):
                best[k] = t
        kept = list(best.values())
        cell *= 1.3
    return kept


def build(trees: list[Tree], style: Style, ground: Callable[[float, float], float] | None = None) -> Mesh:
    """Low-poly trees (a square trunk and a two-tier crown), merged into one mesh, standing on `ground`."""
    m = Mesh('trees')
    trunk = srgb(style.trunk)
    for i, (x, z, s) in enumerate(trees):
        m.lift = ground(x, z) if ground else 0.0
        leaf = srgb(style.leaves[i % len(style.leaves)])
        ang = (i * 0.618) % 1.0 * math.pi
        m.box(x, z, ang, 0.35 * s, 0.35 * s, 0.0, 2.2 * s, trunk)
        _crown(m, x, z, ang, 2.0 * s, 4.6 * s, 1.6 * s, leaf)
        _crown(m, x, z, ang + 0.4, 3.6 * s, 5.8 * s, 1.1 * s, shade(leaf, 1.12))
    m.lift = 0.0
    return m


def _crown(
    m: Mesh,
    x: float,
    z: float,
    ang: float,
    y0: float,
    y1: float,
    r: float,
    col: tuple[float, float, float],
    seg: int = 6,
) -> None:
    ring: list[Point] = [
        (x + r * math.cos(ang + 2 * math.pi * k / seg), z + r * math.sin(ang + 2 * math.pi * k / seg))
        for k in range(seg)
    ]
    tip = (x, y1, z)
    for k in range(seg):
        a, b = ring[k], ring[(k + 1) % seg]
        mx, mz = (a[0] + b[0]) / 2 - x, (a[1] + b[1]) / 2 - z
        m.face([(a[0], y0, a[1]), (b[0], y0, b[1]), tip], col, (mx, r * 0.6, mz))
    m.face([(p[0], y0, p[1]) for p in ring], shade(col, 0.7), (0.0, -1.0, 0.0))
