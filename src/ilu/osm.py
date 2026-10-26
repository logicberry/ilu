"""Turn raw Overpass JSON into buildings, roads, areas and places in metres."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .geo import (
    Point,
    assemble_rings,
    centroid,
    clip_to_box,
    poly_contains,
    projector,
    ring,
    round1,
    signed_area,
    simplify,
)

# Heights by OSM building kind (metres), used when a building has no
# `height` or `building:levels` tag.
KIND_HEIGHT = {
    'university': 9,
    'college': 9,
    'school': 7,
    'dormitory': 10,
    'residential': 6,
    'house': 5,
    'apartments': 9,
    'church': 10,
    'mosque': 10,
    'commercial': 7,
    'retail': 5,
    'office': 9,
    'hospital': 9,
    'public': 8,
    'hotel': 9,
    'roof': 4,
    'garage': 3.5,
    'shed': 3,
    'hut': 3,
    'kiosk': 3,
    'minaret': 25,  # a guess: minarets are rarely tagged with a height
    'tower': 15,
}
DEFAULT_HEIGHT = 6.0
LEVEL = 3.2  # metres per storey

DRIVABLE = (
    'motorway',
    'trunk',
    'primary',
    'secondary',
    'tertiary',
    'motorway_link',
    'trunk_link',
    'primary_link',
    'secondary_link',
    'tertiary_link',
    'unclassified',
    'residential',
    'service',
    'living_street',
    'road',
)

LANE_WIDTH = {
    'motorway': 3.7,
    'trunk': 3.6,
    'primary': 3.6,
    'secondary': 3.5,
    'tertiary': 3.5,
    'unclassified': 3.3,
    'residential': 3.1,
    'living_street': 3.0,
    'road': 3.1,
    'service': 2.9,
}

# Paths people walk on, and their usual width in metres when OSM has no `width` tag.
PATH_WIDTH = {
    'pedestrian': 4.0,
    'footway': 2.0,
    'cycleway': 2.0,
    'steps': 2.0,
    'path': 1.2,
    'track': 3.0,
}

PLACE_KIND_KEYS = (
    'amenity',
    'building',
    'leisure',
    'landuse',
    'office',
    'shop',
    'tourism',
    'natural',
    'place',
    'healthcare',
)

_NUMBER = re.compile(r'^\s*([+-]?(?:\d+\.?\d*|\.\d+))')


def parse_number(s: str | None) -> float | None:
    """The leading number of an OSM value ('12', '12.5 m', '3;4'), or None."""
    if not s:
        return None
    m = _NUMBER.match(s)
    return float(m.group(1)) if m else None


@dataclass
class Building:
    outline: list[Point]
    height: float
    kind: str | None = None
    roof: str | None = None
    measured: bool = False  # height came from an OSM tag, not a guess
    colour: str | None = None  # '#RRGGBB' from building:colour
    roof_colour: str | None = None  # '#RRGGBB' from roof:colour
    holes: list[list[Point]] = field(default_factory=list)  # courtyards, clockwise
    base: float = 0.0  # height of the bottom (min_height), for parts that start above the ground
    roof_height: float | None = None  # from roof:height or roof:levels
    part: bool = False  # a building:part (Simple 3D Buildings), drawn instead of its outline


@dataclass
class Road:
    points: list[Point]
    cls: str
    lanes: int
    lane_width: float
    name: str | None = None
    oneway: bool = False
    surface: str | None = None

    @property
    def half_width(self) -> float:
        return self.lanes * self.lane_width / 2 + 0.6


@dataclass
class Area:
    """A filled ground surface.

    kind is one of: water, wood, grass, cemetery, parking, pitch,
    track, pool. For pitches, `sport` and `surface` carry the OSM tags.
    """

    kind: str
    outline: list[Point]
    sport: str | None = None
    surface: str | None = None
    holes: list[list[Point]] = field(default_factory=list)  # islands and clearings, clockwise


@dataclass
class Path:
    """A footway, path, cycleway or steps, drawn as a thin ribbon."""

    points: list[Point]
    cls: str
    width: float
    surface: str | None = None


# Usual heights in metres, used when a wall, fence or hedge has no `height` tag.
BARRIER_HEIGHT = {'wall': 2.0, 'city_wall': 4.0, 'retaining_wall': 1.0, 'fence': 1.5, 'hedge': 1.2}


@dataclass
class Barrier:
    """A wall, fence or hedge mapped as a line."""

    points: list[Point]
    kind: str
    height: float
    measured: bool = False


@dataclass
class Feature:
    """A small thing mapped as a point: a tree or a street lamp."""

    kind: str  # 'tree' or 'lamp'
    x: float
    z: float
    height: float | None = None  # from the `height` tag


@dataclass
class Place:
    name: str
    kind: str
    x: float
    z: float


@dataclass
class World:
    """Everything Ìlú builds from, in metres around `origin` (lat, lon)."""

    origin: tuple[float, float]
    buildings: list[Building] = field(default_factory=list)
    roads: list[Road] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    places: list[Place] = field(default_factory=list)
    barriers: list[Barrier] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)

    def bounds(self) -> tuple[float, float, float, float]:
        """(min_x, max_x, min_z, max_z) over all geometry."""
        xs: list[float] = []
        zs: list[float] = []
        for poly in (
            [b.outline for b in self.buildings]
            + [a.outline for a in self.areas]
            + [r.points for r in self.roads]
            + [p.points for p in self.paths]
        ):
            xs += [p[0] for p in poly]
            zs += [p[1] for p in poly]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return min(xs), max(xs), min(zs), max(zs)


def _geometry(e: dict[str, Any]) -> list[tuple[float, float]]:
    return [(g['lat'], g['lon']) for g in e.get('geometry') or [] if g]


def _origin(elements: Iterable[dict[str, Any]]) -> tuple[float, float]:
    lats: list[float] = []
    lons: list[float] = []
    for e in elements:
        for lat, lon in _geometry(e):
            lats.append(lat)
            lons.append(lon)
        if e.get('type') == 'node' and 'lat' in e:
            lats.append(e['lat'])
            lons.append(e['lon'])
    if not lats:
        raise ValueError('no map data in this area')
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2


def _kind(tags: dict[str, str]) -> str:
    for k in PLACE_KIND_KEYS:
        v = tags.get(k)
        if v and v != 'yes':
            return v
    return 'building' if tags.get('building') else 'place'


# CSS colour names that appear in OSM colour tags.
_NAMED_COLOURS = {
    'white': '#FFFFFF',
    'black': '#202020',
    'grey': '#808080',
    'gray': '#808080',
    'silver': '#C0C0C0',
    'red': '#B03A2E',
    'maroon': '#800000',
    'brown': '#8B5A2B',
    'orange': '#E07B39',
    'yellow': '#E8C547',
    'beige': '#E8DCC0',
    'cream': '#F3E9D2',
    'tan': '#D2B48C',
    'green': '#3E7D4A',
    'olive': '#808000',
    'blue': '#2F5C8F',
    'navy': '#1F2F5A',
    'teal': '#2A7F7F',
    'pink': '#E3A5B5',
    'purple': '#6B4A8A',
}
_HEX = re.compile(r'^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$')


def parse_colour(s: str | None) -> str | None:
    """An OSM colour value ('#d8d0c0', 'fff', 'white', 'light grey') as '#RRGGBB', or None."""
    if not s:
        return None
    s = s.strip().lower()
    m = _HEX.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        return '#' + h.upper()
    base = s.removeprefix('light ').removeprefix('dark ').replace('_', ' ').strip()
    return _NAMED_COLOURS.get(base)


TOWER_TYPES = {'minaret', 'bell_tower', 'clock'}  # man_made=tower nodes drawn as a slender round tower
TOWER_DIAMETER = {'minaret': 3.0, 'tower': 4.0}  # guesses, when there is no `diameter` tag
MIN_BUILDING_AREA = 12.0
MIN_PART_AREA = 2.0
PART_COVER = 0.5  # parts covering this share of an outline replace it


def building_kind(tags: dict[str, str]) -> str | None:
    """'building', 'part' or 'tower' for a way or relation drawn as a building, else None."""
    if tags.get('building', 'no') != 'no':
        return 'building'
    if tags.get('building:part', 'no') != 'no':
        return 'part'
    if tags.get('man_made') in ('minaret', 'tower') or tags.get('tower:type') == 'minaret':
        return 'tower'
    return None


def _tower_kind(tags: dict[str, str]) -> str:
    return 'minaret' if 'minaret' in (tags.get('man_made'), tags.get('tower:type')) else 'tower'


def _building(tags: dict[str, str], outline: list[Point], holes: list[list[Point]] | None = None) -> Building:
    what = building_kind(tags)
    if what == 'tower':
        kind: str | None = _tower_kind(tags)
    else:
        value = tags.get('building:part' if what == 'part' else 'building', 'yes')
        kind = None if value == 'yes' else value
    levels = parse_number(tags.get('building:levels'))
    min_level = parse_number(tags.get('building:min_level'))
    height = parse_number(tags.get('height'))
    min_height = parse_number(tags.get('min_height'))
    if min_height is not None:
        base = max(min_height, 0.0)
    elif min_level is not None:
        base = max(min_level, 0.0) * LEVEL
    else:
        base = 0.0
    roof_height = parse_number(tags.get('roof:height'))
    roof_levels = parse_number(tags.get('roof:levels'))
    if roof_height is None and roof_levels is not None:
        roof_height = roof_levels * LEVEL
    if height is not None:
        h = height
    elif levels is not None:
        # building:levels counts floors above building:min_level, not counting the roof.
        h = (max(min_level or 0.0, 0.0) + max(levels, 1)) * LEVEL + (roof_height or 0.0)
    else:
        h = base + KIND_HEIGHT.get(kind or '', DEFAULT_HEIGHT)
    if h <= base:
        h = base + LEVEL
    roof = tags.get('roof:shape')
    if roof is None and kind == 'minaret':
        roof = 'cone'  # a guess; tag roof:shape to get the real top
    return Building(
        outline=outline,
        height=round1(h),
        kind=kind,
        roof=roof,
        measured=height is not None or levels is not None,
        colour=parse_colour(tags.get('building:colour')),
        roof_colour=parse_colour(tags.get('roof:colour')),
        holes=holes or [],
        base=round1(base),
        roof_height=round1(roof_height) if roof_height is not None and roof_height > 0 else None,
        part=what == 'part',
    )


def _tower_node(tags: dict[str, str], x: float, z: float, sides: int = 12) -> Building | None:
    """A round footprint for a minaret or tower mapped as a single point."""
    kind = _tower_kind(tags)
    if kind == 'tower' and tags.get('tower:type') not in TOWER_TYPES:
        return None  # masts and lattice towers are not solid buildings
    diameter = parse_number(tags.get('diameter'))
    r = (diameter if diameter is not None and 0.5 <= diameter <= 30 else TOWER_DIAMETER[kind]) / 2
    outline = [
        (round1(x + r * math.cos(2 * math.pi * i / sides)), round1(z + r * math.sin(2 * math.pi * i / sides)))
        for i in range(sides)
    ]
    return _building({**tags, 'man_made': kind}, outline)


def _replace_outlines(buildings: list[Building]) -> list[Building]:
    """Drop building outlines whose parts cover most of them: the parts are the 3D model."""
    parts = [(centroid(b.outline), abs(signed_area(b.outline))) for b in buildings if b.part]
    if not parts:
        return buildings
    kept = []
    for b in buildings:
        if not b.part and b.kind not in ('minaret', 'tower'):
            area = abs(signed_area(b.outline))
            x0, x1 = min(p[0] for p in b.outline), max(p[0] for p in b.outline)
            z0, z1 = min(p[1] for p in b.outline), max(p[1] for p in b.outline)
            covered = sum(
                a for (x, z), a in parts if x0 <= x <= x1 and z0 <= z <= z1 and poly_contains(b.outline, x, z)
            )
            if area > 0 and covered >= PART_COVER * area:
                continue
        kept.append(b)
    return kept


def _area_kind(tags: dict[str, str]) -> str | None:
    leisure, landuse = tags.get('leisure'), tags.get('landuse')
    if leisure == 'swimming_pool':
        return 'pool'
    if tags.get('natural') == 'water' or tags.get('water') or landuse == 'reservoir':
        return 'water'
    if leisure == 'pitch':
        return 'pitch'
    if leisure == 'track':
        return 'track'
    if tags.get('amenity') == 'parking' and tags.get('parking', 'surface') == 'surface':
        return 'parking'
    if tags.get('natural') == 'wood' or landuse == 'forest':
        return 'wood'
    if landuse == 'cemetery' or tags.get('amenity') == 'grave_yard':
        return 'cemetery'
    if landuse in ('grass', 'meadow', 'recreation_ground', 'village_green') or leisure in ('park', 'garden'):
        return 'grass'
    return None


# Smallest area kept, in square metres, per kind: courts and pools are small.
_MIN_AREA = {'pool': 8.0, 'pitch': 20.0, 'track': 20.0, 'parking': 20.0}


def _path(tags: dict[str, str], pts: list[Point]) -> Path | None:
    cls = tags['highway']
    kept = [pts[i] for i in simplify(pts, 0.5)]
    if len(kept) < 2:
        return None
    width = parse_number(tags.get('width'))
    if width is None or not 0.3 <= width <= 30:
        width = PATH_WIDTH[cls]
    return Path(points=kept, cls=cls, width=width, surface=tags.get('surface'))


def _road(tags: dict[str, str], pts: list[Point]) -> Road | None:
    cls = tags['highway']
    base = cls.removesuffix('_link')
    oneway = tags.get('oneway') in ('yes', '1', 'true', '-1', 'reverse') or tags.get('junction') == 'roundabout'
    lanes_tag = parse_number(tags.get('lanes'))
    lanes = int(lanes_tag) if lanes_tag and lanes_tag >= 1 else (1 if oneway else 2)
    kept = [pts[i] for i in simplify(pts, 1.5)]
    if len(kept) < 2:
        return None
    return Road(
        points=kept,
        cls=cls,
        lanes=lanes,
        lane_width=LANE_WIDTH.get(base, 3.1),
        name=tags.get('name'),
        oneway=oneway,
        surface=tags.get('surface'),
    )


def _polygons(
    e: dict[str, Any], project: Callable[[float, float], Point], tolerance: float
) -> list[tuple[list[Point], list[list[Point]]]]:
    """The (outer ring, holes) polygons of a multipolygon relation.

    Outer and inner rings may each be split over several member ways; they
    are joined first. Each inner ring goes to the outer ring that contains it.
    """
    parts: dict[str, list[list[Point]]] = {'outer': [], 'inner': []}
    for m in e.get('members') or []:
        if m.get('type') == 'way' and m.get('geometry') and m.get('role') in parts:
            parts[m['role']].append([project(g['lat'], g['lon']) for g in m['geometry'] if g])
    outers = [r for r in (ring(x, tolerance) for x in assemble_rings(parts['outer'])) if r]
    inners = [r for r in (ring(x, tolerance) for x in assemble_rings(parts['inner'])) if r]
    out: list[tuple[list[Point], list[list[Point]]]] = [(o, []) for o in outers]
    for hole in inners:
        for outer, holes in out:
            if poly_contains(outer, hole[0][0], hole[0][1]):
                holes.append(hole[::-1])  # ring() returns counter-clockwise; holes run clockwise
                break
    return out


def _clip_areas(world: World, margin: float = 150.0) -> None:
    """Cut areas down to the mapped buildings, roads and paths, plus a margin.

    A lagoon or forest relation can stretch for kilometres beyond the place
    asked for; this keeps the model to the place.
    """
    pts = [p for b in world.buildings for p in b.outline] + [p for r in world.roads for p in r.points]
    pts += [p for path in world.paths for p in path.points]
    if not pts:
        return
    x0, x1 = min(p[0] for p in pts) - margin, max(p[0] for p in pts) + margin
    z0, z1 = min(p[1] for p in pts) - margin, max(p[1] for p in pts) + margin
    kept: list[Area] = []
    for a in world.areas:
        xs, zs = [p[0] for p in a.outline], [p[1] for p in a.outline]
        if min(xs) >= x0 and max(xs) <= x1 and min(zs) >= z0 and max(zs) <= z1:
            kept.append(a)
            continue
        outline = clip_to_box(a.outline, x0, x1, z0, z1)
        if len(outline) < 3 or abs(signed_area(outline)) < 1:
            continue
        holes = [h for h in (clip_to_box(h, x0, x1, z0, z1) for h in a.holes) if len(h) >= 3]
        kept.append(Area(a.kind, outline, sport=a.sport, surface=a.surface, holes=holes))
    world.areas = kept


def parse(elements: list[dict[str, Any]]) -> World:
    """Build a World from Overpass `out body geom` elements."""
    lat0, lon0 = _origin(elements)
    project = projector(lat0, lon0)
    world = World(origin=(lat0, lon0))
    for e in elements:
        tags = e.get('tags') or {}
        kind = e.get('type')
        if kind == 'way' and e.get('geometry'):
            pts = [project(lat, lon) for lat, lon in _geometry(e)]
            highway = tags.get('highway')
            if highway in DRIVABLE:
                r = _road(tags, pts)
                if r:
                    world.roads.append(r)
                continue
            barrier = tags.get('barrier')
            if barrier in BARRIER_HEIGHT and not building_kind(tags):
                height = parse_number(tags.get('height'))
                kept = [pts[i] for i in simplify(pts, 0.3)]
                if len(kept) >= 2:
                    h = height if height is not None and 0 < height < 30 else BARRIER_HEIGHT[barrier]
                    world.barriers.append(Barrier(kept, barrier, h, measured=height is not None))
                continue
            if highway in PATH_WIDTH and tags.get('area') != 'yes':
                path = _path(tags, pts)
                if path:
                    world.paths.append(path)
                continue
            what = building_kind(tags)
            if what:
                outline = ring(pts, 0.3 if what != 'building' else 0.5)
                least = MIN_BUILDING_AREA if what == 'building' else MIN_PART_AREA
                if outline and abs(signed_area(outline)) >= least:
                    world.buildings.append(_building(tags, outline))
            else:
                ak = _area_kind(tags)
                closed = len(pts) > 3 and pts[0] == pts[-1]
                outline = ring(pts, 0.3 if ak in _MIN_AREA else 1.5) if ak and closed else None
                if ak and outline and abs(signed_area(outline)) > _MIN_AREA.get(ak, 50.0):
                    world.areas.append(Area(ak, outline, sport=tags.get('sport'), surface=tags.get('surface')))
        elif kind == 'relation' and tags.get('type') == 'multipolygon':
            what = building_kind(tags)
            if what:
                least = MIN_BUILDING_AREA if what == 'building' else MIN_PART_AREA
                for outer, holes in _polygons(e, project, 0.5 if what == 'building' else 0.3):
                    if abs(signed_area(outer)) >= least:
                        world.buildings.append(_building(tags, outer, holes))
            else:
                ak = _area_kind(tags)
                for outer, holes in _polygons(e, project, 0.3 if ak in _MIN_AREA else 1.5) if ak else []:
                    if abs(signed_area(outer)) > _MIN_AREA.get(ak or '', 50.0):
                        world.areas.append(Area(ak or '', outer, tags.get('sport'), tags.get('surface'), holes))
        if kind == 'node' and 'lat' in e and building_kind(tags) == 'tower':
            tower = _tower_node(tags, *project(e['lat'], e['lon']))
            if tower:
                world.buildings.append(tower)
        if kind == 'node' and 'lat' in e and (tags.get('natural') == 'tree' or tags.get('highway') == 'street_lamp'):
            x, z = project(e['lat'], e['lon'])
            height = parse_number(tags.get('height'))
            what = 'tree' if tags.get('natural') == 'tree' else 'lamp'
            world.features.append(Feature(what, x, z, height if height is not None and 0 < height < 80 else None))
        name = tags.get('name')
        if name and not tags.get('highway'):
            if kind == 'node' and 'lat' in e:
                x, z = project(e['lat'], e['lon'])
            elif kind == 'way' and e.get('geometry'):
                x, z = centroid([project(lat, lon) for lat, lon in _geometry(e)])
            else:
                continue
            if math.isfinite(x) and math.isfinite(z):
                world.places.append(Place(name, _kind(tags), round1(x), round1(z)))
    world.buildings = _replace_outlines(world.buildings)
    _clip_areas(world)
    return world
