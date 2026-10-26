"""Ìlú: turn any OpenStreetMap area into a game-ready 3D model.

    >>> import ilu
    >>> world = ilu.fetch(place='Obafemi Awolowo University')  # doctest: +SKIP
    >>> result = ilu.build(world)  # doctest: +SKIP
    >>> open('oau.glb', 'wb').write(result.glb)  # doctest: +SKIP

Output is derived from OpenStreetMap and stays under the ODbL 1.0.
"""

from __future__ import annotations

__version__ = '0.1.0'

from .build import Result, Tile, build, build_tiles, crop, crop_to_bbox, sidecar, tile_index
from .opendata import LandCover, TreeTop
from .osm import World, parse
from .terrain import Terrain


def fetch(
    place: str | None = None, bbox: tuple[float, float, float, float] | None = None, refresh: bool = False
) -> World:
    """Download one place (exact OSM name) or bbox (south, west, north, east) and parse it."""
    from . import overpass

    world = parse(overpass.fetch(overpass.query(place=place, bbox=bbox), refresh=refresh))
    return crop_to_bbox(world, bbox) if bbox else world


def fetch_terrain(world: World, refresh: bool = False) -> Terrain:
    """Ground elevation for a world, for `build(..., terrain=...)`.

    Copernicus DEM GLO-30 when it can be read, otherwise Terrain Tiles.
    """
    from . import opendata, terrain

    try:
        return opendata.copernicus(world.origin, world.bounds(), refresh=refresh)
    except (OSError, ValueError, RuntimeError):
        return terrain.fetch(world.origin, world.bounds(), refresh=refresh)


def fetch_landcover(world: World, refresh: bool = False) -> LandCover:
    """ESA WorldCover land cover for a world, for `build(..., landcover=...)`."""
    from . import opendata

    return opendata.worldcover(world.origin, world.bounds(), refresh=refresh)


def fetch_canopy(world: World, refresh: bool = False) -> list[TreeTop]:
    """Real tree tops from Meta's canopy height map, for `build(..., canopy=...)`."""
    from . import opendata

    return opendata.canopy(world.origin, world.bounds(), refresh=refresh)


__all__ = [
    'Result',
    'Tile',
    'World',
    '__version__',
    'build',
    'build_tiles',
    'crop',
    'crop_to_bbox',
    'fetch',
    'fetch_canopy',
    'fetch_landcover',
    'fetch_terrain',
    'parse',
    'sidecar',
    'tile_index',
]
