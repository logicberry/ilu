"""Plane geometry in local metres: projection, polygons and simplification.

Coordinates are (x, z) with x east and z south, so north is -z. That matches
glTF, where a viewer looking down -z faces north.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence

Point = tuple[float, float]

EARTH_RADIUS = 6_371_008.8
RAD = math.pi / 180


def round1(v: float) -> float:
    return round(v, 1)


def projector(lat0: float, lon0: float) -> Callable[[float, float], Point]:
    """Equirectangular projection to metres around (lat0, lon0).

    Accurate to well under 0.1% across a few kilometres, which is all a
    town or campus needs.
    """
    kx = EARTH_RADIUS * RAD * math.cos(lat0 * RAD)
    kz = EARTH_RADIUS * RAD

    def project(lat: float, lon: float) -> Point:
        return round1((lon - lon0) * kx), round1(-(lat - lat0) * kz)

    return project


def unprojector(lat0: float, lon0: float) -> Callable[[float, float], tuple[float, float]]:
    """The inverse of `projector`: local metres (x, z) back to (lat, lon)."""
    kx = EARTH_RADIUS * RAD * math.cos(lat0 * RAD)
    kz = EARTH_RADIUS * RAD

    def unproject(x: float, z: float) -> tuple[float, float]:
        return lat0 - z / kz, lon0 + x / kx

    return unproject


def signed_area(poly: Sequence[Point]) -> float:
    """Shoelace area; positive when the points run counter-clockwise in (x, z)."""
    n = len(poly)
    return sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)) / 2


def centroid(poly: Sequence[Point]) -> Point:
    a = signed_area(poly)
    n = len(poly)
    if abs(a) < 1e-6:
        return sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n
    cx = cz = 0.0
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        f = p[0] * q[1] - q[0] * p[1]
        cx += (p[0] + q[0]) * f
        cz += (p[1] + q[1]) * f
    return cx / (6 * a), cz / (6 * a)


def poly_contains(poly: Sequence[Point], x: float, z: float) -> bool:
    """Even-odd point-in-polygon test."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        ax, az = poly[i]
        bx, bz = poly[j]
        if (az > z) != (bz > z) and x < (bx - ax) * (z - az) / (bz - az) + ax:
            inside = not inside
        j = i
    return inside


def seg_dist(px: float, pz: float, ax: float, az: float, bx: float, bz: float) -> float:
    """Distance from a point to the segment a-b."""
    dx, dz = bx - ax, bz - az
    l2 = dx * dx + dz * dz or 1.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / l2))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def simplify(pts: Sequence[Point], tolerance: float) -> list[int]:
    """Douglas-Peucker. Returns the indices of the points kept."""
    if len(pts) <= 2:
        return list(range(len(pts)))
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        worst, worst_d = -1, tolerance
        for i in range(a + 1, b):
            d = seg_dist(pts[i][0], pts[i][1], pts[a][0], pts[a][1], pts[b][0], pts[b][1])
            if d > worst_d:
                worst, worst_d = i, d
        if worst >= 0:
            keep[worst] = True
            stack.append((a, worst))
            stack.append((worst, b))
    return [i for i, k in enumerate(keep) if k]


def ring(pts: Sequence[Point], tolerance: float) -> list[Point] | None:
    """A closed outline: simplified, counter-clockwise, no repeated end point."""
    pts = list(pts)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    closed = [*pts, pts[0]]
    kept = [closed[i] for i in simplify(closed, tolerance)][:-1]
    if len(kept) < 3:
        return None
    return kept[::-1] if signed_area(kept) < 0 else kept


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def ear_clip(poly: Sequence[Point]) -> tuple[list[Point], list[tuple[int, int, int]]]:
    """Triangulate a simple polygon (or one with holes bridged in). Returns the points and index triples.

    Only reflex points can block an ear, so those are kept in a spatial grid
    and only nearby ones are tested; large outlines stay fast. Points that
    coincide with an ear's corners, as bridge points do, do not block it.
    """
    pts = list(poly)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return pts, []
    sign = 1.0 if signed_area(pts) > 0 else -1.0
    prev = [(i - 1) % n for i in range(n)]
    nxt = [(i + 1) % n for i in range(n)]
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    cell = max(max(xs) - min(xs), max(zs) - min(zs), 1e-9) / max(1.0, math.sqrt(n))
    grid: dict[tuple[int, int], set[int]] = {}

    def key(p: Point) -> tuple[int, int]:
        return math.floor(p[0] / cell), math.floor(p[1] / cell)

    def is_reflex(i: int) -> bool:
        return _cross(pts[prev[i]], pts[i], pts[nxt[i]]) * sign <= 0

    reflex = {i for i in range(n) if is_reflex(i)}
    for i in reflex:
        grid.setdefault(key(pts[i]), set()).add(i)

    def blocked(i0: int, i1: int, i2: int) -> bool:
        a, b, c = pts[i0], pts[i1], pts[i2]
        (gx0, gz0), (gx1, gz1) = (
            key((min(a[0], b[0], c[0]), min(a[1], b[1], c[1]))),
            key((max(a[0], b[0], c[0]), max(a[1], b[1], c[1]))),
        )
        for gx in range(gx0, gx1 + 1):
            for gz in range(gz0, gz1 + 1):
                for j in grid.get((gx, gz), ()):
                    if j in (i0, i1, i2):
                        continue
                    p = pts[j]
                    if p in (a, b, c):
                        continue
                    d1, d2, d3 = _cross(p, a, b), _cross(p, b, c), _cross(p, c, a)
                    if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
                        return True
        return False

    tris: list[tuple[int, int, int]] = []
    remaining, i, misses = n, 0, 0
    while remaining > 3 and misses < remaining:
        i0, i2 = prev[i], nxt[i]
        if i not in reflex and not blocked(i0, i, i2):
            tris.append((i0, i, i2))
            nxt[i0], prev[i2] = i2, i0
            remaining -= 1
            for j in (i0, i2):  # neighbours may stop being reflex
                if j in reflex and not is_reflex(j):
                    reflex.discard(j)
                    grid[key(pts[j])].discard(j)
            i, misses = i2, 0
        else:
            i, misses = nxt[i], misses + 1
    rest = [i]
    j = nxt[i]
    while j != i and len(rest) <= remaining:
        rest.append(j)
        j = nxt[j]
    if len(rest) == 3:
        tris.append((rest[0], rest[1], rest[2]))
    elif len(rest) > 3:
        # No ear left (a self-touching outline): fan the rest rather than drop it.
        tris += [(rest[0], rest[k], rest[k + 1]) for k in range(1, len(rest) - 1)]
    return pts, tris


def _segments_cross(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """True when segments p1-p2 and q1-q2 cross at a point inside both."""
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def bridge_holes(outer: Sequence[Point], holes: Sequence[Sequence[Point]]) -> list[Point]:
    """One outline with each hole joined to it by a zero-width bridge, ready for ear_clip.

    The outer ring should be counter-clockwise and holes clockwise. Holes are
    joined from their right-most point to the nearest outline point it can see.
    """
    poly = list(outer)
    pending = sorted((list(h) for h in holes if len(h) >= 3), key=lambda h: -max(p[0] for p in h))
    for n, hole in enumerate(pending):
        j = max(range(len(hole)), key=lambda i: hole[i][0])
        m = hole[j]
        edges = [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]
        for other in pending[n:]:
            edges += [(other[i], other[(i + 1) % len(other)]) for i in range(len(other))]
        best = None
        for i in sorted(range(len(poly)), key=lambda i: (poly[i][0] - m[0]) ** 2 + (poly[i][1] - m[1]) ** 2):
            p = poly[i]
            if not any(_segments_cross(m, p, a, b) for a, b in edges if p not in (a, b) and m not in (a, b)):
                best = i
                break
        if best is None:
            continue  # cannot connect this hole; leave it out rather than break the outline
        ring = hole[j:] + hole[: j + 1]
        poly = poly[: best + 1] + ring + poly[best:]
    return poly


def triangulate(
    outer: Sequence[Point], holes: Sequence[Sequence[Point]] = ()
) -> tuple[list[Point], list[tuple[int, int, int]]]:
    """Triangulate a polygon with optional holes."""
    return ear_clip(bridge_holes(outer, holes) if holes else outer)


def assemble_rings(parts: Sequence[Sequence[Point]]) -> list[list[Point]]:
    """Join way segments that share end points into closed rings.

    Multipolygon outlines in OSM are often split over several ways. Pieces
    that never close into a ring are dropped.
    """
    pool = [list(p) for p in parts if len(p) >= 2]
    rings: list[list[Point]] = []
    while pool:
        ring = pool.pop()
        while ring[0] != ring[-1]:
            for i, part in enumerate(pool):
                if part[0] == ring[-1]:
                    ring += part[1:]
                elif part[-1] == ring[-1]:
                    ring += part[-2::-1]
                elif part[-1] == ring[0]:
                    ring = part[:-1] + ring
                elif part[0] == ring[0]:
                    ring = part[:0:-1] + ring
                else:
                    continue
                pool.pop(i)
                break
            else:
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def clip_line_to_box(points: Sequence[Point], x0: float, x1: float, z0: float, z1: float) -> list[list[Point]]:
    """The parts of a polyline inside an axis-aligned box, cut exactly at its edges (Liang-Barsky)."""
    runs: list[list[Point]] = []
    current: list[Point] = []
    for (ax, az), (bx, bz) in itertools.pairwise(points):
        dx, dz = bx - ax, bz - az
        t0, t1 = 0.0, 1.0
        inside = True
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dz, az - z0), (dz, z1 - az)):
            if p == 0:
                if q < 0:
                    inside = False
                    break
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                inside = False
                break
        if not inside:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        start = (ax + dx * t0, az + dz * t0)
        end = (ax + dx * t1, az + dz * t1)
        if not current or current[-1] != start:
            if len(current) >= 2:
                runs.append(current)
            current = [start]
        current.append(end)
        if t1 < 1.0:  # the line leaves the box here
            runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)
    return runs


def clip_to_box(poly: Sequence[Point], x0: float, x1: float, z0: float, z1: float) -> list[Point]:
    """Sutherland-Hodgman clip of a polygon to an axis-aligned box."""

    def clip(pts: list[Point], inside: Callable[[Point], bool], cut: Callable[[Point, Point], Point]) -> list[Point]:
        out: list[Point] = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
        return out

    def at_x(x: float) -> Callable[[Point, Point], Point]:
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_z(z: float) -> Callable[[Point, Point], Point]:
        return lambda a, b: (a[0] + (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]), z)

    pts = list(poly)
    for inside, cut in (
        (lambda p: p[0] >= x0, at_x(x0)),
        (lambda p: p[0] <= x1, at_x(x1)),
        (lambda p: p[1] >= z0, at_z(z0)),
        (lambda p: p[1] <= z1, at_z(z1)),
    ):
        if not pts:
            break
        pts = clip(pts, inside, cut)
    return pts


def convex_hull(pts: Sequence[Point]) -> list[Point]:
    """Andrew's monotone chain."""
    ps = sorted({(float(x), float(z)) for x, z in pts})
    if len(ps) < 3:
        return ps

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    upper: list[Point] = []
    for p in ps:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(ps):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


Rect = tuple[float, float, float, float, float]


def min_rect(poly: Sequence[Point]) -> Rect | None:
    """Smallest oriented rectangle around a polygon: (cx, cz, angle, length, width).

    Length is always the longer side.
    """
    hull = convex_hull(poly)
    if len(hull) < 3:
        return None
    best = None
    for i in range(len(hull)):
        (ax, az), (bx, bz) = hull[i], hull[(i + 1) % len(hull)]
        ang = math.atan2(bz - az, bx - ax)
        ca, sa = math.cos(-ang), math.sin(-ang)
        xs = [x * ca - z * sa for x, z in hull]
        zs = [x * sa + z * ca for x, z in hull]
        area = (max(xs) - min(xs)) * (max(zs) - min(zs))
        if best is None or area < best[0]:
            mx, mz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
            cx = mx * math.cos(ang) - mz * math.sin(ang)
            cz = mx * math.sin(ang) + mz * math.cos(ang)
            best = (area, cx, cz, ang, max(xs) - min(xs), max(zs) - min(zs))
    assert best is not None
    _, cx, cz, ang, length, width = best
    if width > length:
        ang, length, width = ang + math.pi / 2, width, length
    return cx, cz, ang, length, width
