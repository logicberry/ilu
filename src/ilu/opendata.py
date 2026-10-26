"""Open satellite datasets that make a model real where OpenStreetMap is thin.

- Copernicus DEM GLO-30: ground elevation, 30 m.
- ESA WorldCover 2021: land cover (trees, grass, crops, bare ground, ...), 10 m.
- Meta's Global Canopy Height Map v2: tree heights, about 1.2 m.

Each is a set of cloud-optimised GeoTIFFs on public cloud storage, read a
window at a time through `cog.Source`, with tiles cached on disk.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .cog import Source
from .geo import unprojector
from .terrain import GRID_STEP, Terrain

Bounds = tuple[float, float, float, float]  # local metres: min_x, max_x, min_z, max_z

COPERNICUS_URL = (
    'https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/'
    'Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif'
)
WORLDCOVER_URL = (
    'https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif'
)
CANOPY_URL = 'https://dataforgood-fb-data.s3.amazonaws.com/forests/v2/global/dinov3_global_chm_v2_ml3/chm/{quadkey}.tif'

CREDITS = {
    'copernicus': 'Elevation: Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH '
    '2014-2018, provided under COPERNICUS by the European Union and ESA',
    'worldcover': 'Land cover: ESA WorldCover 2021 (CC BY 4.0), contains modified Copernicus Sentinel data',
    'canopy': 'Tree heights: Meta Data for Good, Global Canopy Height Map v2 (DINOv3), CC BY 4.0',
}

# ESA WorldCover classes.
TREES, SHRUB, GRASS, CROPS, BUILT, BARE, SNOW, WATER, WETLAND, MANGROVE, MOSS = (
    10,
    20,
    30,
    40,
    50,
    60,
    70,
    80,
    90,
    95,
    100,
)
CLASS_NAMES = {
    TREES: 'trees',
    SHRUB: 'shrub',
    GRASS: 'grass',
    CROPS: 'crops',
    BUILT: 'built-up',
    BARE: 'bare',
    SNOW: 'snow',
    WATER: 'water',
    WETLAND: 'wetland',
    MANGROVE: 'mangrove',
    MOSS: 'moss',
}

_EARTH = 6378137.0  # Web Mercator sphere


def _lat_lon_box(origin: tuple[float, float], bounds: Bounds) -> tuple[float, float, float, float]:
    """(south, west, north, east) in degrees for a box in local metres."""
    unproject = unprojector(*origin)
    north, west = unproject(bounds[0], bounds[2])
    south, east = unproject(bounds[1], bounds[3])
    return south, west, north, east


def _hemi(value: int, pos: str, neg: str, width: int) -> str:
    return f'{pos if value >= 0 else neg}{abs(value):0{width}d}'


@dataclass
class _Window:
    """Pixels read from one file, with the transform from map units to pixels."""

    rows: list[list[float]]
    x0: int
    y0: int
    origin: tuple[float, float]
    scale: tuple[float, float]

    def value(self, mx: float, my: float, fill: float) -> float:
        col = (mx - self.origin[0]) / self.scale[0] - 0.5 - self.x0
        row = (self.origin[1] - my) / self.scale[1] - 0.5 - self.y0
        i, j = round(col), round(row)
        if 0 <= j < len(self.rows) and 0 <= i < len(self.rows[0]):
            return self.rows[j][i]
        return fill

    def bilinear(self, mx: float, my: float, fill: float) -> float:
        col = (mx - self.origin[0]) / self.scale[0] - 0.5 - self.x0
        row = (self.origin[1] - my) / self.scale[1] - 0.5 - self.y0
        i, j = math.floor(col), math.floor(row)
        if not (0 <= j < len(self.rows) - 1 and 0 <= i < len(self.rows[0]) - 1):
            return self.value(mx, my, fill)
        tx, ty = col - i, row - j
        r0, r1 = self.rows[j], self.rows[j + 1]
        top = r0[i] * (1 - tx) + r0[i + 1] * tx
        bottom = r1[i] * (1 - tx) + r1[i + 1] * tx
        return top * (1 - ty) + bottom * ty


def _read(source: Source, level: int, box: tuple[float, float, float, float], pad: int = 2) -> _Window:
    """The pixels of a level covering a box in the file's map units (x0, y0, x1, y1), y up."""
    sx, sy = source.level_scale(level)
    lv = source.levels[level]
    c0 = max(0, math.floor((box[0] - source.origin[0]) / sx) - pad)
    c1 = min(lv.width, math.ceil((box[2] - source.origin[0]) / sx) + pad)
    r0 = max(0, math.floor((source.origin[1] - box[3]) / sy) - pad)
    r1 = min(lv.height, math.ceil((source.origin[1] - box[1]) / sy) + pad)
    rows = source.window(level, c0, r0, max(1, c1 - c0), max(1, r1 - r0)) if c1 > c0 and r1 > r0 else [[0.0]]
    return _Window(rows, c0, r0, source.origin, (sx, sy))


def _degree_files(box: tuple[float, float, float, float], step: int) -> list[tuple[int, int]]:
    """South-west corners (lat, lon) of the step-degree cells a box touches."""
    south, west, north, east = box
    lats = range(math.floor(south / step) * step, math.floor(north / step) * step + 1, step)
    lons = range(math.floor(west / step) * step, math.floor(east / step) * step + 1, step)
    return [(lat, lon) for lat in lats for lon in lons]


# ---------------------------------------------------------------- elevation


def copernicus(origin: tuple[float, float], bounds: Bounds, refresh: bool = False, margin: float = 50.0) -> Terrain:
    """Ground elevation from Copernicus GLO-30 on a 30 m grid. Sea and missing tiles are 0 m."""
    grown = (bounds[0] - margin, bounds[1] + margin, bounds[2] - margin, bounds[3] + margin)
    box = _lat_lon_box(origin, grown)
    windows: list[_Window] = []
    for south, west in _degree_files(box, 1):
        url = COPERNICUS_URL.format(lat=_hemi(south, 'N', 'S', 2), lon=_hemi(west, 'E', 'W', 3))
        try:
            src = Source(url, refresh)
        except FileNotFoundError:
            continue  # open sea: no tile
        windows.append(_read(src, 0, (box[1], box[0], box[3], box[2])))
    unproject = unprojector(*origin)

    def elevation(x: float, z: float) -> float:
        lat, lon = unproject(x, z)
        for w in windows:
            col = (lon - w.origin[0]) / w.scale[0]
            row = (w.origin[1] - lat) / w.scale[1]
            if w.x0 <= col < w.x0 + len(w.rows[0]) and w.y0 <= row < w.y0 + len(w.rows):
                return w.bilinear(lon, lat, 0.0)
        return 0.0

    return Terrain.from_function(elevation, grown, GRID_STEP, CREDITS['copernicus'])


# ---------------------------------------------------------------- land cover


@dataclass
class LandCover:
    """ESA WorldCover classes on a 10 m grid in local metres."""

    x0: float
    z0: float
    cell: float
    cols: int
    rows: int
    classes: bytes

    def at(self, x: float, z: float) -> int:
        i = min(max(int((x - self.x0) / self.cell), 0), self.cols - 1)
        j = min(max(int((z - self.z0) / self.cell), 0), self.rows - 1)
        return self.classes[j * self.cols + i]

    def share(self) -> dict[str, float]:
        """Fraction of the area in each class."""
        total = len(self.classes) or 1
        counts: dict[str, float] = {}
        for c in self.classes:
            name = CLASS_NAMES.get(c, 'unknown')
            counts[name] = counts.get(name, 0) + 1 / total
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def worldcover(origin: tuple[float, float], bounds: Bounds, refresh: bool = False, cell: float = 10.0) -> LandCover:
    """Land cover for an area, sampled every `cell` metres."""
    box = _lat_lon_box(origin, bounds)
    windows: list[_Window] = []
    for south, west in _degree_files(box, 3):
        tile = _hemi(south, 'N', 'S', 2) + _hemi(west, 'E', 'W', 3)
        try:
            src = Source(WORLDCOVER_URL.format(tile=tile), refresh)
        except FileNotFoundError:
            continue
        windows.append(_read(src, 0, (box[1], box[0], box[3], box[2])))
    unproject = unprojector(*origin)
    cols = max(1, math.ceil((bounds[1] - bounds[0]) / cell))
    rows = max(1, math.ceil((bounds[3] - bounds[2]) / cell))
    out = bytearray(cols * rows)
    for j in range(rows):
        for i in range(cols):
            lat, lon = unproject(bounds[0] + (i + 0.5) * cell, bounds[2] + (j + 0.5) * cell)
            for w in windows:
                v = w.value(lon, lat, -1.0)
                if v >= 0:
                    out[j * cols + i] = int(v)
                    break
    return LandCover(bounds[0], bounds[2], cell, cols, rows, bytes(out))


# ---------------------------------------------------------------- trees


def _mercator(lat: float, lon: float) -> tuple[float, float]:
    return math.radians(lon) * _EARTH, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _EARTH


def _quadkey(lat: float, lon: float, zoom: int) -> str:
    n = 2**zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return ''.join(str(((x >> (i - 1)) & 1) + 2 * ((y >> (i - 1)) & 1)) for i in range(zoom, 0, -1))


@dataclass(frozen=True)
class TreeTop:
    """A tree found in the canopy height map: position in local metres and height in metres."""

    x: float
    z: float
    height: float


def canopy(
    origin: tuple[float, float],
    bounds: Bounds,
    refresh: bool = False,
    min_height: float = 4.0,
    spacing: float = 7.0,
) -> list[TreeTop]:
    """Tree tops: the tallest point of the canopy in each `spacing`-metre square, where it is at least `min_height`.

    Reads the 4.8 m overview of the 1.2 m map: fine enough to place crowns
    of real trees, and small enough to download quickly for a whole town.
    """
    box = _lat_lon_box(origin, bounds)
    corners = [(box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3])]
    quadkeys = sorted({_quadkey(lat, lon, 10) for lat, lon in corners})
    mx0, my0 = _mercator(box[0], box[1])
    mx1, my1 = _mercator(box[2], box[3])
    to_local = _local_from_mercator(origin)
    found: list[TreeTop] = []
    for qk in quadkeys:
        try:
            src = Source(CANOPY_URL.format(quadkey=qk), refresh)
        except FileNotFoundError:
            continue
        level = min(2, len(src.levels) - 1)
        w = _read(src, level, (mx0, my0, mx1, my1), pad=0)
        step = max(1, round(spacing / w.scale[0]))
        rows = w.rows
        width = len(rows[0])
        for j in range(0, len(rows), step):
            block = rows[j : j + step]
            for i in range(0, width, step):
                end = min(i + step, width)
                best = max(max(r[i:end]) for r in block)
                if best < min_height:
                    continue
                bj = next(jj for jj, r in enumerate(block) if best in r[i:end])
                bi = block[bj].index(best, i, end)
                mx = w.origin[0] + (w.x0 + bi + 0.5) * w.scale[0]
                my = w.origin[1] - (w.y0 + j + bj + 0.5) * w.scale[1]
                x, z = to_local(mx, my)
                if bounds[0] <= x <= bounds[1] and bounds[2] <= z <= bounds[3]:
                    found.append(TreeTop(round(x, 1), round(z, 1), float(best)))
    return found


def _local_from_mercator(origin: tuple[float, float]) -> Callable[[float, float], tuple[float, float]]:
    from .geo import projector

    project = projector(*origin)

    def back(mx: float, my: float) -> tuple[float, float]:
        lon = math.degrees(mx / _EARTH)
        lat = math.degrees(2 * math.atan(math.exp(my / _EARTH)) - math.pi / 2)
        return project(lat, lon)

    return back
