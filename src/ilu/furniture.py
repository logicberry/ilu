"""Walls, fences, hedges and street lamps, where OpenStreetMap maps them."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable

from .geo import Point
from .mesh import Mesh, shade, srgb
from .osm import Barrier, Feature

Height = Callable[[float, float], float]

# Thickness in metres and colour, by barrier kind.
BARRIER_LOOK = {
    'wall': (0.25, '#BDB4A3'),
    'city_wall': (0.8, '#9C8E78'),
    'retaining_wall': (0.4, '#A39886'),
    'fence': (0.08, '#4A4E52'),
    'hedge': (0.8, '#3F6B35'),
}
LAMP_HEIGHT = 7.0  # metres, when a street lamp has no `height` tag
STEP = 4.0  # metres between posts when following sloping ground


def build_barriers(barriers: list[Barrier], ground: Height | None = None) -> Mesh:
    """Each barrier as a run of thin boxes, standing on the ground."""
    m = Mesh('barriers')
    for b in barriers:
        thickness, colour = BARRIER_LOOK[b.kind]
        col = srgb(colour)
        pts: list[Point] = b.points
        if ground:
            dense: list[Point] = [pts[0]]
            for (x0, z0), (x1, z1) in itertools.pairwise(pts):
                n = max(1, math.ceil(math.hypot(x1 - x0, z1 - z0) / STEP))
                dense += [(x0 + (x1 - x0) * k / n, z0 + (z1 - z0) * k / n) for k in range(1, n + 1)]
            pts = dense
        for (x0, z0), (x1, z1) in itertools.pairwise(pts):
            ln = math.hypot(x1 - x0, z1 - z0)
            if ln < 0.05:
                continue
            base = min(ground(x0, z0), ground(x1, z1)) if ground else 0.0
            top = max(ground(x0, z0), ground(x1, z1)) + b.height if ground else b.height
            m.box((x0 + x1) / 2, (z0 + z1) / 2, math.atan2(z1 - z0, x1 - x0), ln, thickness, base - 0.2, top, col)
    return m


def build_lamps(features: list[Feature], ground: Height | None = None) -> Mesh:
    """Street lamps: a pole with a lamp head."""
    m = Mesh('lamps')
    pole, head = srgb('#5B6066'), srgb('#E9E4D2')
    for f in features:
        if f.kind != 'lamp':
            continue
        h = f.height or LAMP_HEIGHT
        y = ground(f.x, f.z) if ground else 0.0
        m.box(f.x, f.z, 0.0, 0.16, 0.16, y, y + h, pole)
        m.box(f.x, f.z, 0.0, 0.55, 0.3, y + h - 0.2, y + h, shade(pole, 0.9), top=head)
    return m
