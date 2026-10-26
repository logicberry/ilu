"""Command line: `ilu find "Place"`, `ilu build --near "Place" -o out.glb`, `ilu view out.glb`."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__, geocode, opendata, overpass, terrain, viewer
from .build import build, build_tiles, crop_to_bbox, sidecar, tile_index
from .osm import World, parse
from .style import STYLES
from .trees import Tree


def _bbox(text: str) -> tuple[float, float, float, float]:
    try:
        s, w, n, e = (float(v) for v in text.split(','))
    except ValueError:
        raise argparse.ArgumentTypeError('expected four numbers: south,west,north,east') from None
    return s, w, n, e


def _count(n: int, noun: str) -> str:
    return f'{n:,} {noun}' + ('' if n == 1 else 's')


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='ilu', description='Turn an OpenStreetMap area into a 3D model (.glb).')
    p.add_argument('--version', action='version', version=f'ilu {__version__}')
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='download an area and build a .glb')
    where = b.add_mutually_exclusive_group(required=True)
    where.add_argument('place', nargs='?', help='exact OSM name of an area, e.g. "Obafemi Awolowo University"')
    where.add_argument('--bbox', type=_bbox, metavar='S,W,N,E', help='bounding box in degrees')
    where.add_argument('--near', metavar='PLACE', help='search for a place and build the area round it')
    where.add_argument('--osm', metavar='FILE', help='use a saved Overpass JSON file instead of downloading')
    b.add_argument(
        '--radius', type=float, default=400.0, metavar='METRES', help='with --near: metres each way (default: 400)'
    )
    b.add_argument('-o', '--out', required=True, help='output .glb path, or a folder with --tile-size')
    b.add_argument('--json', metavar='FILE', help='also write roads, places and trees as JSON')
    b.add_argument(
        '--style', choices=sorted(STYLES), default='west-africa', help='colour palette (default: west-africa)'
    )
    b.add_argument('--seed', type=int, default=0, help='seed for the guesses and trees (default: 0)')
    b.add_argument('--no-trees', action='store_true', help='leave trees out')
    b.add_argument('--max-trees', type=int, default=4000, help='cap on trees (default: 4000)')
    real = b.add_argument_group('real-world data (downloaded and cached; see the README for credits)')
    real.add_argument('--real', action='store_true', help='all of the data layers below')
    real.add_argument('--terrain', action='store_true', help='real ground elevation (Copernicus DEM)')
    real.add_argument(
        '--landcover', action='store_true', help='real ground cover: trees, grass, crops, bare earth (ESA WorldCover)'
    )
    real.add_argument(
        '--canopy', action='store_true', help='real trees where and as tall as they are (Meta canopy height map)'
    )
    look = b.add_argument_group('look')
    look.add_argument('--no-bake', action='store_true', help='leave lighting to the engine instead of baking it in')
    look.add_argument(
        '--sun-hour', type=float, default=10.0, metavar='HOUR', help='local solar time of the baked sun (default: 10)'
    )
    b.add_argument(
        '--tile-size', type=float, metavar='METRES', help='split into square tiles of this size, written to a folder'
    )
    look.add_argument('--plain-walls', action='store_true', help='plain painted walls, without the window texture')
    b.add_argument('--refresh', action='store_true', help='download again even if cached')
    b.add_argument(
        '--overpass-url',
        metavar='URL',
        help='Overpass server to download from (default: public servers, or ILU_OVERPASS_URL)',
    )
    f = sub.add_parser('find', help='search for a place by name and print a build command for each match')
    f.add_argument('query', help='what to search for, e.g. "Oduduwa Hall"')
    f.add_argument('--radius', type=float, default=400.0, metavar='METRES', help='box size for the printed commands')
    f.add_argument('--limit', type=int, default=5, help='how many matches to list (default: 5)')
    f.add_argument('--refresh', action='store_true', help='search again even if cached')
    v = sub.add_parser('view', help='look at a model or a folder of tiles in the browser')
    v.add_argument('path', help='a .glb file, or a folder written with --tile-size')
    v.add_argument('--port', type=int, default=0, help='port to serve on (default: any free port)')
    v.add_argument('--no-open', action='store_true', help='do not open a browser')
    return p


Written = tuple[list[Tree], dict[str, int], str]


def _write_one(world: World, args: argparse.Namespace, options: dict[str, Any]) -> Written:
    """Build one model and write it to args.out. Returns the trees, stats and a summary."""
    result = build(world, **options)
    with open(args.out, 'wb') as f:
        f.write(result.glb)
    return (
        result.trees,
        result.stats,
        f'{result.stats["meshes"]} meshes -> {args.out} ({len(result.glb) / 1024:.0f} KB)',
    )


def _write_tiles(world: World, args: argparse.Namespace, options: dict[str, Any]) -> Written:
    """Build tiles and write them, with tiles.json, to the folder args.out."""
    if os.path.exists(args.out) and not os.path.isdir(args.out):
        raise NotADirectoryError(f'{args.out} is a file; with --tile-size, -o names a folder')
    tiles = build_tiles(world, args.tile_size, **options)
    os.makedirs(args.out, exist_ok=True)
    names = [f'tile_{t.col}_{t.row}.glb' for t in tiles]
    for t, name in zip(tiles, names, strict=True):
        with open(os.path.join(args.out, name), 'wb') as f:
            f.write(t.result.glb)
    with open(os.path.join(args.out, 'tiles.json'), 'w', encoding='utf-8') as f:
        json.dump(tile_index(world, tiles, names, args.tile_size), f, indent=1)
    total = sum(len(t.result.glb) for t in tiles)
    largest = max((len(t.result.glb) for t in tiles), default=0)
    stats = {k: sum(t.result.stats[k] for t in tiles) for k in ('buildings', 'measured_heights', 'triangles')}
    summary = (
        f'{_count(len(tiles), "tile")} -> {args.out}/ ({total / 1024:.0f} KB in all, largest {largest / 1024:.0f} KB)'
    )
    return [tree for t in tiles for tree in t.result.trees], stats, summary


def _layers(world: World, args: argparse.Namespace) -> dict[str, Any]:
    """Download the data layers asked for. Returns build() keyword arguments."""
    out: dict[str, Any] = {}
    if args.terrain or args.real:
        print('Fetching elevation...', file=sys.stderr)
        try:
            out['terrain'] = opendata.copernicus(world.origin, world.bounds(), refresh=args.refresh)
        except (OSError, ValueError, RuntimeError) as err:
            print(f'  Copernicus DEM unavailable ({err}); using Terrain Tiles', file=sys.stderr)
            out['terrain'] = terrain.fetch(world.origin, world.bounds(), refresh=args.refresh)
    if args.landcover or args.real:
        print('Fetching land cover...', file=sys.stderr)
        out['landcover'] = opendata.worldcover(world.origin, world.bounds(), refresh=args.refresh)
    if args.canopy or args.real:
        print('Fetching tree heights...', file=sys.stderr)
        out['canopy'] = opendata.canopy(world.origin, world.bounds(), refresh=args.refresh)
    return out


def _bbox_text(bbox: tuple[float, float, float, float]) -> str:
    return ','.join(f'{v:g}' for v in bbox)


def _find(args: argparse.Namespace) -> int:
    try:
        matches = geocode.find(args.query, limit=max(1, min(args.limit, 20)), refresh=args.refresh)
    except (OSError, ValueError, RuntimeError) as err:
        print(f'ilu: {err}', file=sys.stderr)
        return 1
    if not matches:
        print(f'ilu: nothing found for "{args.query}"; try adding the town or country', file=sys.stderr)
        return 1
    for i, m in enumerate(matches, 1):
        print(f'{i}. {m.name}')
        print(f'   {m.lat:.5f}, {m.lon:.5f}  ({m.kind})')
        print(f'   ilu build --bbox {_bbox_text(m.bbox(args.radius))} -o out.glb')
    print(geocode.CREDIT)
    return 0


def _near(args: argparse.Namespace) -> tuple[float, float, float, float]:
    """Search for args.near and return the box round the best match."""
    if not 0 < args.radius <= 5000:
        raise ValueError('--radius must be between 0 and 5000 metres')
    matches = geocode.find(args.near, refresh=args.refresh)
    if not matches:
        raise ValueError(f'nothing found for "{args.near}"; try adding the town or country')
    best = matches[0]
    print(f'Found: {best.name} ({best.lat:.5f}, {best.lon:.5f})', file=sys.stderr)
    if len(matches) > 1:
        print(
            f'  {len(matches) - 1} other match(es); if this is the wrong place, run: ilu find "{args.near}"',
            file=sys.stderr,
        )
    return best.bbox(args.radius)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Place names such as "Ìlọrin" must not crash a console or pipe that cannot show them.
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors='replace')
    args = _parser().parse_args(argv)
    if args.command == 'find':
        return _find(args)
    if args.command == 'view':
        try:
            viewer.serve(args.path, args.port, open_browser=not args.no_open)
        except FileNotFoundError:
            print(f'ilu: no such file: {args.path} (build it first: ilu build ... -o {args.path})', file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as err:
            print(f'ilu: {err}', file=sys.stderr)
            return 1
        return 0
    try:
        if args.near:
            args.bbox = _near(args)
        if args.osm:
            with open(args.osm, encoding='utf-8') as f:
                elements = overpass.response_elements(json.load(f))
        else:
            q = overpass.query(place=args.place, bbox=args.bbox)
            urls = tuple(u.strip() for u in args.overpass_url.split(',')) if args.overpass_url else None
            elements = overpass.fetch(q, refresh=args.refresh, urls=urls)
        world = parse(elements)
        if args.bbox:
            world = crop_to_bbox(world, args.bbox)
    except (OSError, ValueError, RuntimeError, KeyError) as err:
        print(f'ilu: {err}', file=sys.stderr)
        return 1
    if not world.buildings and not world.roads:
        hint = f' (ilu find "{args.place}" lists places by that name)' if args.place else ''
        print(f'ilu: no buildings or roads found; check the name or box{hint}', file=sys.stderr)
        return 1
    if args.tile_size is not None and args.tile_size <= 0:
        print('ilu: --tile-size must be positive', file=sys.stderr)
        return 1
    if not 0 <= args.sun_hour <= 24:
        print('ilu: --sun-hour must be between 0 and 24', file=sys.stderr)
        return 1
    try:
        layers = _layers(world, args)
    except (OSError, ValueError, RuntimeError) as err:
        print(f'ilu: {err}', file=sys.stderr)
        return 1
    options: dict[str, Any] = {
        'style': args.style,
        'seed': args.seed,
        'with_trees': not args.no_trees,
        'max_trees': args.max_trees,
        'facades': not args.plain_walls,
        'bake': not args.no_bake,
        'sun_hour': args.sun_hour,
        **layers,
    }
    try:
        if args.tile_size:
            planted, stats, summary = _write_tiles(world, args, options)
        else:
            planted, stats, summary = _write_one(world, args, options)
        if args.json:
            with open(args.json, 'w', encoding='utf-8') as f:
                json.dump(sidecar(world, planted), f, separators=(',', ':'))
    except OSError as err:
        print(f'ilu: cannot write output: {err}', file=sys.stderr)
        return 1
    print(
        f'{_count(stats["buildings"], "building")} ({stats["measured_heights"]} with a height tag), '
        f'{_count(len(world.roads), "road")}, {_count(len(planted), "tree")}, '
        f'{stats["triangles"]:,} triangles in {summary}'
    )
    if stats['buildings'] == 0:
        print(
            'Note: OpenStreetMap has no buildings mapped here yet, so the model shows only the ground, '
            'roads and trees. Check the place is the one you meant; buildings can be added at openstreetmap.org.'
        )
    ground = layers.get('terrain')
    if ground:
        level = f'{abs(ground.base):.0f} m {"above" if ground.base >= 0 else "below"} sea level'
        print(f'Terrain: y = 0 is {level}; ground sampled every {ground.cell:.0f} m.')
    if 'landcover' in layers:
        share = ', '.join(f'{k} {v:.0%}' for k, v in list(layers['landcover'].share().items())[:4])
        print(f'Land cover: {share}.')
    if 'canopy' in layers:
        print(f'Trees: {len(planted):,} of {len(layers["canopy"]):,} found in the canopy map.')
    print('Credits (keep these with the output):')
    print('  Map data (c) OpenStreetMap contributors, ODbL.')
    if args.near:
        print(f'  {geocode.CREDIT}')
    if ground:
        print(f'  {ground.credit}')
    if 'landcover' in layers:
        print(f'  {opendata.CREDITS["worldcover"]}')
    if 'canopy' in layers:
        print(f'  {opendata.CREDITS["canopy"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
