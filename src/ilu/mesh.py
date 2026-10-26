"""A vertex-coloured triangle mesh and the primitives buildings are made of."""

from __future__ import annotations

import math
from collections.abc import Sequence

Vec3 = tuple[float, float, float]
Colour = tuple[float, float, float]


def srgb(hex_colour: str) -> Colour:
    """'#RRGGBB' to linear RGB, as glTF vertex colours expect."""
    h = hex_colour.lstrip('#')
    out = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out[0], out[1], out[2]


def shade(c: Colour, k: float) -> Colour:
    return min(c[0] * k, 1.0), min(c[1] * k, 1.0), min(c[2] * k, 1.0)


class Mesh:
    """Vertex lists for one draw: positions, normals, colours, optional UVs and indices.

    `material` is glb.MATTE or glb.FACADE; facade meshes carry UVs. `lift`
    is added to the height of every vertex added, which is how a building
    is stood on sloping ground.
    """

    def __init__(self, name: str, uv: bool = False, material: int = 0) -> None:
        self.name = name
        self.material = material
        self.pos: list[Vec3] = []
        self.nor: list[Vec3] = []
        self.col: list[tuple[float, float, float, float]] = []
        self.uv: list[tuple[float, float]] | None = [] if uv else None
        self.idx: list[int] = []
        self.lift = 0.0

    @property
    def triangles(self) -> int:
        return len(self.idx) // 3

    def vert(self, p: Vec3, n: Vec3, c: Colour, uv: tuple[float, float] = (0.0, 0.0)) -> int:
        self.pos.append((p[0], p[1] + self.lift, p[2]) if self.lift else p)
        self.nor.append(n)
        self.col.append((c[0], c[1], c[2], 1.0))
        if self.uv is not None:
            self.uv.append(uv)
        return len(self.pos) - 1

    def tri_up(self, pts: Sequence[Vec3], col: Colour) -> None:
        """A triangle facing up (+y), whatever the input winding."""
        a, b, c = pts
        ny = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
        order = (0, 1, 2) if ny >= 0 else (0, 2, 1)
        for k in order:
            self.idx.append(self.vert(pts[k], (0.0, 1.0, 0.0), col))

    def face(self, pts: Sequence[Vec3], col: Colour, normal: Vec3) -> None:
        """A flat convex polygon facing `normal`, whatever the input winding."""
        a, b, c = pts[0], pts[1], pts[2]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        cr = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        if cr[0] * normal[0] + cr[1] * normal[1] + cr[2] * normal[2] < 0:
            pts = list(reversed(pts))
        ln = math.sqrt(sum(v * v for v in normal)) or 1.0
        n = (normal[0] / ln, normal[1] / ln, normal[2] / ln)
        ids = [self.vert(q, n, col) for q in pts]
        for k in range(1, len(ids) - 1):
            self.idx.extend([ids[0], ids[k], ids[k + 1]])

    def box(
        self,
        cx: float,
        cz: float,
        angle: float,
        length: float,
        width: float,
        y0: float,
        y1: float,
        col: Colour,
        top: Colour | None = None,
    ) -> None:
        """An oriented box: `length` along `angle`, `width` across it, no bottom."""
        ca, sa = math.cos(angle), math.sin(angle)
        hl, hw = length / 2, width / 2
        corners = [
            (cx + ca * x - sa * z, cz + sa * x + ca * z) for x, z in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw))
        ]
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            mx, mz = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cz
            self.face([(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1])], col, (mx, 0.0, mz))
        self.face([(c[0], y1, c[1]) for c in corners], top or col, (0.0, 1.0, 0.0))

    def wall(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
        y0: float,
        y1: float,
        col_bottom: Colour,
        col_top: Colour,
        outward: tuple[float, float],
        uv: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    ) -> None:
        """A vertical quad from ground point a to b, y0..y1, facing `outward`.

        `uv` is (u0, u1, v0, v1): u along the wall from a to b, v up it.
        """
        n = (outward[0], 0.0, outward[1])
        u0, u1, v0, v1 = uv
        i0 = self.vert((a[0], y0, a[1]), n, col_bottom, (u0, v0))
        i1 = self.vert((b[0], y0, b[1]), n, col_bottom, (u1, v0))
        i2 = self.vert((b[0], y1, b[1]), n, col_top, (u1, v1))
        i3 = self.vert((a[0], y1, a[1]), n, col_top, (u0, v1))
        ux, uz = b[0] - a[0], b[1] - a[1]
        if (-uz) * n[0] + ux * n[2] >= 0:
            self.idx.extend([i0, i1, i3, i1, i2, i3])
        else:
            self.idx.extend([i0, i3, i1, i1, i3, i2])
