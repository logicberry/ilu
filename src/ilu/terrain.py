"""Ground elevation from the public Terrain Tiles dataset on AWS (no key needed).

Tiles are Terrarium-encoded PNGs: elevation in metres is
(R * 256 + G + B / 256) - 32768. The dataset combines SRTM, GMTED, ETOPO1
and other open sources; see TERRAIN_CREDIT.
"""

from __future__ import annotations

import math
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import __version__
from .geo import unprojector
from .overpass import cache_dir
from .png import decode_png

TILE_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
TERRAIN_CREDIT = (
    'Elevation: Terrain Tiles on AWS Open Data (Mapzen/Tilezen), from SRTM, GMTED, ETOPO1 and other sources; '
    'see https://github.com/tilezen/joerd/blob/master/docs/attribution.md'
)
MAX_ZOOM = 13  # about 19 m per pixel at the equator
MAX_TILES = 36
GRID_STEP = 30.0  # metres between terrain samples


def _tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Fractional Web Mercator tile coordinates."""
    n = 2**z
    lat = max(min(lat, 85.0511), -85.0511)
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def _fetch_tile(z: int, x: int, y: int, refresh: bool) -> bytes:
    path = os.path.join(cache_dir(), 'terrarium', str(z), str(x), f'{y}.png')
    if os.path.exists(path) and not refresh:
        with open(path, 'rb') as f:
            return f.read()
    url = TILE_URL.format(z=z, x=x, y=y)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': f'ilu/{__version__} (OpenStreetMap to 3D)'})
            with urllib.request.urlopen(req, timeout=60) as res:
                data: bytes = res.read()
            break
        except Exception as err:
            print(f'  elevation tile {z}/{x}/{y}: {err}', file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError('elevation tiles are unavailable; try again later or build without --terrain')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return data


@dataclass
class Terrain:
    """Heights on a regular grid in local metres.

    `height(x, z)` is relative to `base`, the lowest point of the grid, so
    the model's ground never goes below y = 0.
    """

    x0: float
    z0: float
    cell: float
    cols: int
    rows: int
    heights: list[float]
    base: float
    credit: str = TERRAIN_CREDIT

    def height(self, x: float, z: float) -> float:
        """Height on the grid's triangles: each cell is split along its (i, j)-(i+1, j+1) diagonal.

        This is exactly the surface build_base draws, so anything draped
        with this height lies on the ground mesh rather than above or under it.
        """
        fx = min(max((x - self.x0) / self.cell, 0.0), self.cols - 1.0)
        fz = min(max((z - self.z0) / self.cell, 0.0), self.rows - 1.0)
        i, j = min(int(fx), self.cols - 2), min(int(fz), self.rows - 2)
        tx, tz = fx - i, fz - j
        a, b, c, d = self.at(i, j), self.at(i + 1, j), self.at(i + 1, j + 1), self.at(i, j + 1)
        if tx >= tz:
            return a + tx * (b - a) + tz * (c - b)
        return a + tz * (d - a) + tx * (c - d)

    def at(self, i: int, j: int) -> float:
        """The height at grid node (i, j)."""
        return self.heights[j * self.cols + i]

    @classmethod
    def from_function(
        cls,
        f: Callable[[float, float], float],
        bounds: tuple[float, float, float, float],
        cell: float,
        credit: str = TERRAIN_CREDIT,
    ) -> Terrain:
        """Sample f(x, z) in metres on a grid covering bounds (min_x, max_x, min_z, max_z)."""
        x0, x1, z0, z1 = bounds
        cols = max(2, math.ceil((x1 - x0) / cell) + 1)
        rows = max(2, math.ceil((z1 - z0) / cell) + 1)
        raw = [f(x0 + i * cell, z0 + j * cell) for j in range(rows) for i in range(cols)]
        base = min(raw)
        return cls(x0, z0, cell, cols, rows, [round(v - base, 2) for v in raw], round(base, 2), credit)


def fetch(
    origin: tuple[float, float], bounds: tuple[float, float, float, float], refresh: bool = False, margin: float = 50.0
) -> Terrain:
    """Download elevation for an area (local metres around origin) and sample it onto a grid."""
    unproject = unprojector(*origin)
    x0, x1, z0, z1 = bounds[0] - margin, bounds[1] + margin, bounds[2] - margin, bounds[3] + margin
    north, west = unproject(x0, z0)
    south, east = unproject(x1, z1)
    z = MAX_ZOOM
    while z > 0:
        ax, ay = _tile_xy(north, west, z)
        bx, by = _tile_xy(south, east, z)
        if (int(bx) - int(ax) + 1) * (int(by) - int(ay) + 1) <= MAX_TILES:
            break
        z -= 1
    tiles: dict[tuple[int, int], tuple[int, int, bytes]] = {}
    for tx in range(int(ax), int(bx) + 1):
        for ty in range(int(ay), int(by) + 1):
            w, _, ch, px = decode_png(_fetch_tile(z, tx, ty, refresh))
            tiles[(tx, ty)] = (w, ch, px)

    def pixel(gx: int, gy: int) -> float:
        tx, px_x = divmod(gx, 256)
        ty, px_y = divmod(gy, 256)
        tile = tiles.get((tx, ty))
        if tile is None:
            tile = tiles[min(tiles, key=lambda k: abs(k[0] - tx) + abs(k[1] - ty))]
            px_x, px_y = min(max(px_x, 0), 255), min(max(px_y, 0), 255)
        w, ch, data = tile
        o = (px_y * w + px_x) * ch
        return data[o] * 256 + data[o + 1] + data[o + 2] / 256 - 32768

    def elevation(x: float, zz: float) -> float:
        lat, lon = unproject(x, zz)
        fx, fy = _tile_xy(lat, lon, z)
        gx, gy = fx * 256 - 0.5, fy * 256 - 0.5
        ix, iy = math.floor(gx), math.floor(gy)
        tx, ty = gx - ix, gy - iy
        top = pixel(ix, iy) * (1 - tx) + pixel(ix + 1, iy) * tx
        bottom = pixel(ix, iy + 1) * (1 - tx) + pixel(ix + 1, iy + 1) * tx
        return top * (1 - ty) + bottom * ty

    # The tiles' finest source data (SRTM) is about 30 m apart; sampling finer adds triangles, not detail.
    metres_per_pixel = 40075016.7 * math.cos(math.radians(origin[0])) / (256 * 2**z)
    cell = max(GRID_STEP, round(metres_per_pixel))
    return Terrain.from_function(elevation, (x0, x1, z0, z1), cell)


def flat() -> Callable[[float, float], float]:
    """A height function for flat ground."""
    return lambda x, z: 0.0
