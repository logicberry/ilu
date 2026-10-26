"""Line markings for sports pitches tagged with a known `sport`.

Lines are drawn at the sport's real, rule-book size, centred in the pitch's
outline from OpenStreetMap and turned to match it. Nothing is stretched:

- The playing area is the outline's size, clamped to the range the rules
  allow (a football pitch may be 90 to 120 m long; a basketball court is
  28 by 15 m). Goal areas, keys and circles keep their fixed sizes.
- A pitch gets no markings when its outline is not close to a rectangle, is
  smaller than the smallest legal playing area, or is larger than a legal
  playing area plus its run-off. Then the outline is probably something
  else (several courts in one, a whole stadium), and lines would be wrong.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass

from .geo import Point, Rect, min_rect, signed_area
from .mesh import Colour, Mesh

LINE_WIDTH = 0.1  # metres
MIN_FILL = 0.85  # outline area / its bounding rectangle

Polyline = list[Point]
Layout = Callable[[float, float], list[Polyline]]


@dataclass(frozen=True)
class Rules:
    """Playing-area limits in metres, and the largest outline accepted (area plus run-off)."""

    length: tuple[float, float]
    width: tuple[float, float]
    outline: tuple[float, float]
    layout: Layout


def _rect(hl: float, hw: float) -> Polyline:
    return [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw), (-hl, -hw)]


def _arc(cu: float, cv: float, r: float, a0: float, a1: float) -> Polyline:
    steps = max(8, int(abs(a1 - a0) * r * 2))
    return [
        (cu + r * math.cos(a0 + (a1 - a0) * i / steps), cv + r * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def _mirror(line: Polyline) -> Polyline:
    return [(-u, v) for u, v in line]


def soccer(length: float, width: float) -> list[Polyline]:
    """Laws of the Game: penalty area 16.5 m, goal area 5.5 m, circles 9.15 m."""
    hl, hw = length / 2, width / 2
    box, goal, spot = hl - 16.5, hl - 5.5, hl - 11.0
    end = [
        [(hl, -20.16), (box, -20.16), (box, 20.16), (hl, 20.16)],
        [(hl, -9.16), (goal, -9.16), (goal, 9.16), (hl, 9.16)],
        # The penalty arc: the part of the 9.15 m circle round the spot outside the box.
        [p for p in _arc(spot, 0, 9.15, 0, 2 * math.pi) if p[0] < box],
    ]
    return [_rect(hl, hw), [(0.0, -hw), (0.0, hw)], _arc(0, 0, 9.15, 0, 2 * math.pi), *end, *map(_mirror, end)]


def basketball(length: float, width: float) -> list[Polyline]:
    """FIBA: key 5.8 by 4.9 m, three-point line 6.75 m, circles 1.8 m."""
    hl, hw = length / 2, width / 2
    key, basket, corner = hl - 5.8, hl - 1.575, hl - 2.99
    end = [
        [(hl, -2.45), (key, -2.45), (key, 2.45), (hl, 2.45)],
        _arc(key, 0, 1.8, 0, 2 * math.pi),
        [(hl, -6.6), (corner, -6.6)],
        [(hl, 6.6), (corner, 6.6)],
        [p for p in _arc(basket, 0, 6.75, 0, 2 * math.pi) if p[0] <= corner],
    ]
    return [_rect(hl, hw), [(0.0, -hw), (0.0, hw)], _arc(0, 0, 1.8, 0, 2 * math.pi), *end, *map(_mirror, end)]


def tennis(length: float, width: float) -> list[Polyline]:
    """ITF: singles sidelines 8.23 m apart, service lines 6.40 m from the net."""
    hl, hw, singles, service = length / 2, width / 2, 8.23 / 2, 6.40
    return [
        _rect(hl, hw),
        [(-hl, -singles), (hl, -singles)],
        [(-hl, singles), (hl, singles)],
        [(0.0, -hw), (0.0, hw)],
        [(-service, -singles), (-service, singles)],
        [(service, -singles), (service, singles)],
        [(-service, 0.0), (service, 0.0)],
    ]


def handball(length: float, width: float) -> list[Polyline]:
    """IHF: the 6 m goal-area line, quarter circles round each post joined by a straight."""
    hl, hw = length / 2, width / 2
    area = [
        *_arc(hl, -1.5, 6.0, -math.pi / 2, -math.pi),
        (hl - 6.0, -1.5),
        (hl - 6.0, 1.5),
        *_arc(hl, 1.5, 6.0, math.pi, math.pi / 2),
    ]
    return [_rect(hl, hw), [(0.0, -hw), (0.0, hw)], area, _mirror(area)]


def volleyball(length: float, width: float) -> list[Polyline]:
    """FIVB: attack lines 3 m from the centre line."""
    hl, hw = length / 2, width / 2
    return [_rect(hl, hw), [(0.0, -hw), (0.0, hw)], [(-3.0, -hw), (-3.0, hw)], [(3.0, -hw), (3.0, hw)]]


RULES: dict[str, Rules] = {
    # A football outline may include a running track round the pitch (up to about 165 m).
    'soccer': Rules(length=(90.0, 120.0), width=(45.0, 90.0), outline=(165.0, 100.0), layout=soccer),
    'basketball': Rules(length=(28.0, 28.0), width=(15.0, 15.0), outline=(36.0, 21.0), layout=basketball),
    'tennis': Rules(length=(23.77, 23.77), width=(10.97, 10.97), outline=(40.0, 20.0), layout=tennis),
    'handball': Rules(length=(40.0, 40.0), width=(20.0, 20.0), outline=(46.0, 26.0), layout=handball),
    'volleyball': Rules(length=(18.0, 18.0), width=(9.0, 9.0), outline=(32.0, 22.0), layout=volleyball),
}


def _sport(tag: str | None) -> str | None:
    """The first sport in a tag like 'basketball;volleyball' that has a layout."""
    for s in (tag or '').split(';'):
        if s.strip() in RULES:
            return s.strip()
    return None


def fit(outline: list[Point], sport: str | None) -> tuple[Rect, float, float] | None:
    """(rectangle, playing length, playing width) when the sport's lines fit the outline, else None."""
    name = _sport(sport)
    if name is None:
        return None
    rect = min_rect(outline)
    if rect is None or rect[3] * rect[4] <= 0:
        return None
    if abs(signed_area(outline)) / (rect[3] * rect[4]) < MIN_FILL:
        return None
    rules = RULES[name]
    real_l, real_w = rect[3], rect[4]
    if real_l < rules.length[0] - 0.5 or real_w < rules.width[0] - 0.5:
        return None  # too small for this sport's playing area
    if real_l > rules.outline[0] or real_w > rules.outline[1]:
        return None  # much bigger than the playing area plus run-off
    length = min(max(real_l, rules.length[0]), rules.length[1])
    width = min(max(real_w, rules.width[0]), rules.width[1])
    return rect, length, width


def draw(
    m: Mesh,
    outline: list[Point],
    sport: str | None,
    y: float,
    col: Colour,
    ground: Callable[[float, float], float] | None = None,
) -> bool:
    """Add the sport's markings to `m`, `y` above the ground. Returns False when they do not fit."""
    fitted = fit(outline, sport)
    name = _sport(sport)
    if fitted is None or name is None:
        return False
    (cx, cz, ang, _, _), length, width = fitted
    ca, sa = math.cos(ang), math.sin(ang)
    half = LINE_WIDTH / 2
    for line in RULES[name].layout(length, width):
        pts = [(cx + ca * u - sa * v, cz + sa * u + ca * v) for u, v in line]
        for (x0, z0), (x1, z1) in itertools.pairwise(pts):
            dx, dz = x1 - x0, z1 - z0
            ln = math.hypot(dx, dz)
            if ln < 1e-6:
                continue
            nx, nz = -dz / ln * half, dx / ln * half
            corners = [
                (x0 + nx, z0 + nz),
                (x0 - nx, z0 - nz),
                (x1 - nx, z1 - nz),
                (x1 + nx, z1 + nz),
            ]
            a, b, c, d = [(x, y + (ground(x, z) if ground else 0.0), z) for x, z in corners]
            m.tri_up([a, b, c], col)
            m.tri_up([a, c, d], col)
    return True
