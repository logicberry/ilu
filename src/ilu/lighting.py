"""Bake sunlight and sky light into vertex colours.

A baked model looks the same in every viewer and costs nothing to light,
which suits phones. The sun is placed where it really is for the area's
latitude at a chosen hour on the March equinox. Baked models use the
KHR_materials_unlit material, so engines show the colours as baked
instead of lighting them a second time.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .mesh import Mesh, Vec3

SKY = 0.62  # light from the sky on any surface
SKY_UP = 0.16  # extra sky light on surfaces that face up
SUN = 0.6  # direct sunlight on a surface facing the sun


def sun_direction(lat: float, hour: float = 10.0, day: int = 80) -> Vec3:
    """Unit vector towards the sun in model axes (x east, y up, z south).

    `hour` is local solar time and `day` the day of the year (80 is the
    March equinox). The sun is kept at least 10 degrees up so morning and
    evening models stay readable.
    """
    decl = math.radians(23.44 * math.sin(2 * math.pi * (284 + day) / 365))
    phi = math.radians(lat)
    h = math.radians(15 * (hour - 12))
    sin_el = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(h)
    el = max(math.asin(max(-1.0, min(1.0, sin_el))), math.radians(10))
    cos_az = (math.sin(decl) - math.sin(el) * math.sin(phi)) / max(math.cos(el) * math.cos(phi), 1e-9)
    az = math.acos(max(-1.0, min(1.0, cos_az)))  # from north, towards east
    if h > 0:
        az = 2 * math.pi - az  # afternoon: the sun is in the west
    east, north, up = math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)
    return east, up, -north


def light(normal: Vec3, sun: Vec3) -> float:
    """How bright a surface with this normal is, 1.0 for flat ground in the sun."""
    flat = SKY + SKY_UP + SUN * max(sun[1], 0.0)
    nx, ny, nz = normal
    direct = max(0.0, nx * sun[0] + ny * sun[1] + nz * sun[2])
    return (SKY + SKY_UP * max(ny, 0.0) + SUN * direct) / flat


def bake(meshes: Iterable[Mesh], sun: Vec3) -> None:
    """Multiply every vertex colour by its light, in place."""
    for m in meshes:
        for i, (n, c) in enumerate(zip(m.nor, m.col, strict=True)):
            k = light(n, sun)
            m.col[i] = (min(c[0] * k, 1.0), min(c[1] * k, 1.0), min(c[2] * k, 1.0), c[3])
