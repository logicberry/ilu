"""Put the pieces together: a World in, one .glb or a grid of tiles out."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from . import buildings, furniture, ground, lighting, markings, trees
from .geo import Point, clip_line_to_box, clip_to_box, signed_area
from .glb import CREDIT, to_bytes
from .mesh import Mesh
from .opendata import CREDITS, LandCover, TreeTop
from .osm import Area, Barrier, Path, Road, World
from .style import STYLES, Style
from .terrain import Terrain

Bounds = tuple[float, float, float, float]  # min_x, max_x, min_z, max_z


@dataclass
class Result:
    glb: bytes
    meshes: list[Mesh]
    trees: list[trees.Tree]
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class Tile:
    """One square of a tiled build. Tiles share one coordinate frame, so they line up when loaded together."""

    col: int
    row: int
    bounds: Bounds
    result: Result


def _style(name: str) -> Style:
    if name not in STYLES:
        raise ValueError(f'unknown style {name!r}; choose from {", ".join(sorted(STYLES))}')
    return STYLES[name]


@dataclass(frozen=True)
class Settings:
    """How to build: everything except the map and the data layers."""

    style: Style
    seed: int
    with_trees: bool
    max_trees: int
    facades: bool
    bake: bool
    sun_hour: float


@dataclass(frozen=True)
class Layers:
    """Optional real-world data laid over the map."""

    terrain: Terrain | None = None
    landcover: LandCover | None = None
    canopy: list[TreeTop] | None = None


def _plant(world: World, settings: Settings, layers: Layers) -> list[trees.Tree]:
    """Trees mapped in OSM first, then real canopy trees or decorative ones, up to the budget."""
    if not settings.with_trees:
        return []
    mapped = [
        (round(f.x, 1), round(f.z, 1), round((f.height or 5.8) / 5.8, 2)) for f in world.features if f.kind == 'tree'
    ]
    room = max(0, settings.max_trees - len(mapped))
    if layers.canopy is not None:
        more = trees.from_canopy(layers.canopy, world.buildings, world.roads, world.paths, world.areas, room)
    else:
        more = trees.place(world.buildings, world.roads, world.areas, seed=settings.seed)[:room]
    return mapped[: settings.max_trees] + more


def _credit(layers: Layers) -> str:
    parts = [CREDIT]
    if layers.terrain:
        parts.append(layers.terrain.credit)
    if layers.landcover:
        parts.append(CREDITS['worldcover'])
    if layers.canopy is not None:
        parts.append(CREDITS['canopy'])
    return '; '.join(parts)


def _assemble(
    world: World,
    settings: Settings,
    layers: Layers,
    planted: list[trees.Tree],
    base: Bounds | None,
    extras: dict[str, Any],
) -> Result:
    st = settings.style
    terrain = layers.terrain
    height = terrain.height if terrain else None
    painted = layers.landcover is not None
    meshes: list[Mesh] = []
    if base:
        meshes.append(ground.build_base(base, st, terrain, world.areas, layers.landcover))
    meshes.append(
        ground.build_shadows(world.buildings, ground.ground_colour(st, layers.landcover, world.areas), height)
    )
    meshes += ground.build_areas(world.areas, st, height, painted=painted)
    meshes.append(ground.build_paths(world.paths, height))
    meshes += ground.build_roads(world.roads, st, height)
    bm, _ = buildings.build(world.buildings, st, seed=settings.seed, ground=height, facades=settings.facades)
    meshes += [bm.walls, bm.roofs, bm.details]
    meshes += [furniture.build_barriers(world.barriers, height), furniture.build_lamps(world.features, height)]
    if planted:
        meshes.append(trees.build(planted, st, height))
    if settings.bake:
        lighting.bake(meshes, lighting.sun_direction(world.origin[0], settings.sun_hour))
    stats = {
        'buildings': len(world.buildings),
        'measured_heights': sum(1 for b in world.buildings if b.measured),
        'roof_tags': sum(1 for b in world.buildings if b.roof),
        'colour_tags': sum(1 for b in world.buildings if b.colour or b.roof_colour),
        'courtyards': sum(len(b.holes) for b in world.buildings),
        'roads': len(world.roads),
        'paths': len(world.paths),
        'areas': len(world.areas),
        'pitches': sum(1 for a in world.areas if a.kind == 'pitch'),
        'marked_pitches': sum(1 for a in world.areas if a.kind == 'pitch' and markings.fit(a.outline, a.sport)),
        'pools': sum(1 for a in world.areas if a.kind == 'pool'),
        'barriers': len(world.barriers),
        'lamps': sum(1 for f in world.features if f.kind == 'lamp'),
        'mapped_trees': sum(1 for f in world.features if f.kind == 'tree'),
        'trees': len(planted),
        'triangles': sum(m.triangles for m in meshes),
        'meshes': sum(1 for m in meshes if m.idx),
    }
    glb = to_bytes(meshes, extras=extras, credit=_credit(layers), unlit=settings.bake)
    return Result(glb, meshes, planted, stats)


def _extras(world: World, settings: Settings, layers: Layers) -> dict[str, Any]:
    extras: dict[str, Any] = {
        'origin': {'lat': world.origin[0], 'lon': world.origin[1]},
        'axes': 'x east, y up, z south; metres',
    }
    if layers.terrain:
        extras['elevation'] = {'base_m': layers.terrain.base, 'note': 'y = 0 is this many metres above sea level'}
    if settings.bake:
        extras['lighting'] = {'baked': True, 'sun_hour': settings.sun_hour}
    return extras


def _settings(
    style: str, seed: int, with_trees: bool, max_trees: int, facades: bool, bake: bool, sun_hour: float
) -> Settings:
    if not 0 <= sun_hour <= 24:
        raise ValueError('sun_hour must be between 0 and 24')
    return Settings(_style(style), seed, with_trees, max_trees, facades, bake, sun_hour)


def build(
    world: World,
    style: str = 'west-africa',
    seed: int = 0,
    with_trees: bool = True,
    max_trees: int = 4000,
    base: bool = True,
    terrain: Terrain | None = None,
    facades: bool = True,
    landcover: LandCover | None = None,
    canopy: list[TreeTop] | None = None,
    bake: bool = True,
    sun_hour: float = 10.0,
) -> Result:
    """Build the whole area as one model. The same inputs always give the same bytes.

    `terrain`, `landcover` and `canopy` are the optional real-data layers
    (see `ilu.fetch_terrain`, `ilu.fetch_landcover`, `ilu.fetch_canopy`).
    With `bake`, sunlight for `sun_hour` (local solar time) and soft
    shadows are baked into the colours and the materials are unlit.
    """
    settings = _settings(style, seed, with_trees, max_trees, facades, bake, sun_hour)
    layers = Layers(terrain, landcover, canopy)
    planted = _plant(world, settings, layers)
    bounds = world.bounds() if base else None
    return _assemble(world, settings, layers, planted, bounds, _extras(world, settings, layers))


def _split_lines(points: list[Point], box: Bounds) -> list[list[Point]]:
    """Runs of consecutive segments whose midpoints fall inside the box."""
    runs: list[list[Point]] = []
    current: list[Point] = []
    for a, b in itertools.pairwise(points):
        if _inside((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, box):
            if not current:
                current = [a]
            current.append(b)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _inside(x: float, z: float, box: Bounds) -> bool:
    return box[0] <= x < box[1] and box[2] <= z < box[3]


def _part(world: World, box: Bounds) -> World:
    """The part of the world inside one tile. Buildings go by centre; lines and areas are cut at the edges."""
    part = World(origin=world.origin)
    for b in world.buildings:
        cx = sum(p[0] for p in b.outline) / len(b.outline)
        cz = sum(p[1] for p in b.outline) / len(b.outline)
        if _inside(cx, cz, box):
            part.buildings.append(b)
    for r in world.roads:
        part.roads += [Road(run, r.cls, r.lanes, r.lane_width, r.name, r.oneway) for run in _split_lines(r.points, box)]
    for p in world.paths:
        part.paths += [Path(run, p.cls, p.width, p.surface) for run in _split_lines(p.points, box)]
    for a in world.areas:
        outline = clip_to_box(a.outline, *box)
        if len(outline) >= 3 and abs(signed_area(outline)) > 1:
            holes = [h for h in (clip_to_box(h, *box) for h in a.holes) if len(h) >= 3]
            part.areas.append(Area(a.kind, outline, a.sport, a.surface, holes))
    part.places = [p for p in world.places if _inside(p.x, p.z, box)]
    part.features = [f for f in world.features if _inside(f.x, f.z, box)]
    for bar in world.barriers:
        part.barriers += [Barrier(run, bar.kind, bar.height, bar.measured) for run in _split_lines(bar.points, box)]
    return part


def crop(world: World, box: Bounds) -> World:
    """The world cut to a box in local metres: buildings whose centre is inside, and lines and areas cut at the edges.

    OpenStreetMap returns every road and area that touches a bounding box, whole,
    so without this a `--bbox` model would reach far past the box asked for.
    """
    x0, x1, z0, z1 = box
    out = World(origin=world.origin)
    for b in world.buildings:
        cx = sum(p[0] for p in b.outline) / len(b.outline)
        cz = sum(p[1] for p in b.outline) / len(b.outline)
        if x0 <= cx <= x1 and z0 <= cz <= z1:
            out.buildings.append(b)
    for r in world.roads:
        out.roads += [
            Road(run, r.cls, r.lanes, r.lane_width, r.name, r.oneway, r.surface)
            for run in clip_line_to_box(r.points, *box)
        ]
    for p in world.paths:
        out.paths += [Path(run, p.cls, p.width, p.surface) for run in clip_line_to_box(p.points, *box)]
    for bar in world.barriers:
        out.barriers += [Barrier(run, bar.kind, bar.height, bar.measured) for run in clip_line_to_box(bar.points, *box)]
    for a in world.areas:
        outline = clip_to_box(a.outline, *box)
        if len(outline) >= 3 and abs(signed_area(outline)) > 1:
            holes = [h for h in (clip_to_box(h, *box) for h in a.holes) if len(h) >= 3]
            out.areas.append(Area(a.kind, outline, a.sport, a.surface, holes))
    out.places = [p for p in world.places if x0 <= p.x <= x1 and z0 <= p.z <= z1]
    out.features = [f for f in world.features if x0 <= f.x <= x1 and z0 <= f.z <= z1]
    return out


def crop_to_bbox(world: World, bbox: tuple[float, float, float, float]) -> World:
    """Crop a world to a bounding box given in degrees (south, west, north, east)."""
    from .geo import projector

    south, west, north, east = bbox
    project = projector(*world.origin)
    x0, z_north = project(north, west)
    x1, z_south = project(south, east)
    return crop(world, (x0, x1, z_north, z_south))


def build_tiles(
    world: World,
    tile_size: float,
    style: str = 'west-africa',
    seed: int = 0,
    with_trees: bool = True,
    max_trees: int = 4000,
    terrain: Terrain | None = None,
    facades: bool = True,
    landcover: LandCover | None = None,
    canopy: list[TreeTop] | None = None,
    bake: bool = True,
    sun_hour: float = 10.0,
) -> list[Tile]:
    """Split the area into square tiles and build each as its own model.

    Every tile uses the same origin and axes, so tiles placed at (0, 0, 0)
    line up exactly. Trees are chosen once for the whole area, so tiling
    never changes where they stand. Empty tiles are left out.
    """
    if tile_size <= 0:
        raise ValueError('tile size must be positive')
    settings = _settings(style, seed, with_trees, max_trees, facades, bake, sun_hour)
    layers = Layers(terrain, landcover, canopy)
    planted = _plant(world, settings, layers)
    x0, x1, z0, z1 = world.bounds()
    cols, rows = max(1, math.ceil((x1 - x0) / tile_size)), max(1, math.ceil((z1 - z0) / tile_size))
    tiles: list[Tile] = []
    for row in range(rows):
        for col in range(cols):
            box = (
                x0 + col * tile_size,
                x1 + 1e-6 if col == cols - 1 else x0 + (col + 1) * tile_size,
                z0 + row * tile_size,
                z1 + 1e-6 if row == rows - 1 else z0 + (row + 1) * tile_size,
            )
            part = _part(world, box)
            if not (part.buildings or part.roads or part.paths or part.areas):
                continue
            here = [t for t in planted if _inside(t[0], t[1], box)]
            extras = _extras(world, settings, layers) | {'tile': {'col': col, 'row': row, 'bounds': list(box)}}
            tiles.append(Tile(col, row, box, _assemble(part, settings, layers, here, box, extras)))
    return tiles


def tile_index(world: World, tiles: list[Tile], names: list[str], tile_size: float) -> dict[str, Any]:
    """An index of a tiled build, for loading tiles as the camera moves."""
    return {
        '$credit': CREDIT,
        'origin': {'lat': world.origin[0], 'lon': world.origin[1]},
        'axes': 'x east, y up, z south; metres',
        'tile_size': tile_size,
        'tiles': [
            {
                'file': name,
                'col': t.col,
                'row': t.row,
                'bounds': [round(v, 2) for v in t.bounds],
                'triangles': t.result.stats['triangles'],
                'bytes': len(t.result.glb),
            }
            for t, name in zip(tiles, names, strict=True)
        ],
    }


def sidecar(world: World, planted: list[trees.Tree]) -> dict[str, Any]:
    """Roads, places and trees as plain data for game logic (navigation, labels).

    Pass `result.trees`, or for a tiled build, the trees of all tiles.
    """
    return {
        '$credit': CREDIT,
        'origin': {'lat': world.origin[0], 'lon': world.origin[1]},
        'axes': 'x east, z south; metres',
        'roads': [
            {
                'name': r.name,
                'class': r.cls,
                'lanes': r.lanes,
                'width': round(r.half_width * 2, 2),
                'oneway': r.oneway,
                'points': [list(p) for p in r.points],
            }
            for r in world.roads
        ],
        'places': [{'name': p.name, 'kind': p.kind, 'x': p.x, 'z': p.z} for p in world.places],
        'trees': [list(t) for t in planted],
    }
