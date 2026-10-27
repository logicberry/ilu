# Ìlú

**Turn any OpenStreetMap area into a game-ready 3D model.**

[![CI](https://github.com/productreelabs/ilu/actions/workflows/ci.yml/badge.svg)](https://github.com/productreelabs/ilu/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/productreelabs/ilu/blob/main/LICENSE)

```bash
pip install ilu
ilu build "Obafemi Awolowo University" -o oau.glb --real
ilu view oau.glb
```

Not sure of the exact name? `ilu find "Oduduwa Hall"` lists matching places, and `ilu build --near "Oduduwa Hall, Ile-Ife" -o oduduwa.glb` builds the area round the best one.

Ìlú (Yoruba for "town") does three things:
1. It downloads the buildings, roads, footpaths, water, woods, car parks, pools and sports pitches of an area from OpenStreetMap.
2. With `--real`, it adds open satellite data: real ground elevation, real land cover (forest, grass, crops, bare earth) and real trees, where they stand and as tall as they are.
3. It raises every building into walls and a roof, bakes in sunlight and soft shadow, and writes one standard glTF 2.0 file, or a grid of tiles for large areas.

The file opens directly in Blender, three.js, Godot and Flutter Scene, and in Unity and Unreal through their glTF importers.

![Obafemi Awolowo University, Ile-Ife, built by Ìlú with --real](https://raw.githubusercontent.com/productreelabs/ilu/main/docs/oau-real.jpg)

<sub>Obafemi Awolowo University, Ile-Ife, built with `--real` and shown with `ilu view`. Every hill, forest, clearing and tree comes from data. Map data © OpenStreetMap contributors; elevation Copernicus DEM; land cover ESA WorldCover; tree heights Meta.</sub>

> **Status: early (0.1).** The command line and output format may change before 1.0.

## Contents

- [Why Ìlú](#why-ìlú)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Output format](#output-format)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Why Ìlú

In much of the world, OpenStreetMap has good building outlines but almost no heights. At Obafemi Awolowo University, 43 of 2,710 buildings have a height tag. Most map-to-3D tools then draw flat boxes everywhere, or nothing at all.

Ìlú handles this in three ways:
- **Tags first, then guesses.** It uses real tags where they exist and makes reasonable guesses where they don't, so a sparsely mapped town still looks like a town.
- **Open satellite data where the map is thin.** Free global datasets fill in what OpenStreetMap rarely records: the shape of the ground, what covers it, and where the trees are.
- **A local default style.** The default palette and rules are tuned for West African towns and campuses: painted walls, long-span metal roofs, concrete institutional blocks and rooftop water tanks. A neutral `plain` style is included for anywhere else.

Ìlú grew out of the map pipeline of Great Ife, a 3D campus game built with Flutter.

## Features

- **Any area.** Search by name with `ilu find` or `--near`, or use the exact OSM name of an area, a bounding box, or a saved Overpass file.
- **Real-world data, one flag.** `--real` adds three open datasets, read straight from public cloud storage with only the standard library:
  - **Elevation** from Copernicus DEM GLO-30: buildings, roads and land follow the real ground, and water stays level.
  - **Land cover** from ESA WorldCover at 10 m: forest, grass, crops, bare earth and built-up land, coloured as they really are.
  - **Trees** from Meta's 1.2 m canopy height map: trees where they really stand, as tall as they really are.
- **Baked light.** Sunlight for the area's latitude, soft contact shadows at the foot of every wall, and hill shading are baked into the colours, so the model looks right in any viewer and costs nothing to light on a phone.
- **Instant preview.** `ilu view` opens a model or a folder of tiles in your browser.
- **Detailed 3D buildings.** Where mappers have drawn [building parts](https://wiki.openstreetmap.org/wiki/Simple_3D_Buildings), Ìlú builds them as mapped: domes, onion domes, cones and pyramids, parts that start above the ground, and minarets and towers, including those mapped as a single point.
- **Courtyards, lakes and lagoons.** Multipolygon outlines, including inner rings, are read and built with their holes.
- **Windows.** Walls carry a window texture aligned to each building's floors.
- **Tiles for large areas.** `--tile-size` splits an area into a grid of small files that line up exactly, with an index for streaming.
- **Real detail where the map has it.**
  - Swimming pools, footpaths, car parks and cemeteries.
  - Pitch and court surfaces from their `surface` tag (clay, grass, sand, tartan and more).
  - Rule-book line markings for football, basketball, tennis, handball and volleyball.
  - Building and roof colours from `building:colour` and `roof:colour`.
- **Zero dependencies.** Pure Python standard library, so it runs wherever Python 3.10+ runs.
- **Game-ready.**
  - Static geometry is merged into about a dozen meshes, so a whole town draws in a few calls.
  - Colour lives in the vertices; the only texture is one small window image embedded in the file.
  - Real-world metres.
- **Deterministic.** The same input, style and seed always give byte-identical files.
- **Valid glTF.** Output passes the [Khronos glTF Validator](https://github.khronos.org/glTF-Validator/) with no errors or warnings.
- **Game data alongside.** An optional JSON file holds the road network, named places and tree positions, for navigation, labels or gameplay.
- **Cached downloads.** Each map query and each data tile is downloaded once; later builds of the same place work offline.

## Installation

```bash
pip install ilu
```

To install from source:

```bash
git clone https://github.com/productreelabs/ilu.git
cd ilu
pip install .
```

## Usage

### Command line

```bash
# Search by name: lists matches with their full address and a build command for each
ilu find "Obafemi Awolowo University"

# Build the area round the best match, 400 m each way (or --radius METRES)
ilu build --near "Oduduwa Hall, Ile-Ife" -o oduduwa.glb

# By the exact name of an area in OpenStreetMap
ilu build "Obafemi Awolowo University" -o oau.glb

# By bounding box: south,west,north,east in degrees
ilu build --bbox 7.5175,4.5195,7.5230,4.5262 -o oau-core.glb

# From a saved Overpass JSON response, with no network
ilu build --osm area.json -o area.glb

# Also write roads, places and trees as JSON
ilu build "Obafemi Awolowo University" -o oau.glb --json oau.json

# Real elevation, land cover and trees, split into 1 km tiles in the folder oau/
ilu build "Obafemi Awolowo University" -o oau --real --tile-size 1000

# Look at the result in your browser
ilu view oau
```

| Option | Default | Description |
|---|---|---|
| `--near PLACE` | none | Search for a place and build the area round the best match, instead of a name or box |
| `--radius METRES` | `400` | With `--near`: how far each way from the place to build |
| `-o`, `--out PATH` | required | Output `.glb` path, or a folder when `--tile-size` is set |
| `--json FILE` | none | Also write roads, places and trees as JSON |
| `--style NAME` | `west-africa` | Colour palette: `west-africa` or `plain` |
| `--seed N` | `0` | Seed for guessed details and tree placement |
| `--no-trees` | off | Leave trees out |
| `--max-trees N` | `4000` | Upper limit on the number of trees |
| `--real` | off | All three data layers below |
| `--terrain` | off | Real ground elevation (Copernicus DEM, with Terrain Tiles as a fallback) |
| `--landcover` | off | Real ground cover (ESA WorldCover) |
| `--canopy` | off | Real trees (Meta canopy height map) |
| `--tile-size METRES` | none | Split into square tiles of this size, written to the `--out` folder with a `tiles.json` index |
| `--plain-walls` | off | Painted walls without the window texture |
| `--no-bake` | off | Leave lighting to the engine: normal PBR materials, no baked sun or shadow |
| `--sun-hour HOUR` | `10` | Local solar time of the baked sun |
| `--refresh` | off | Download again, ignoring the cache |
| `--overpass-url URL` | public servers | Overpass server(s) to download map data from, comma-separated; also settable as `ILU_OVERPASS_URL` |

`ilu find QUERY` searches [Nominatim](https://nominatim.org), OpenStreetMap's own place search, and prints up to `--limit` matches (default 5) with a ready `ilu build --bbox` command each, sized by `--radius`. Many places share a name, so check the address before building. Searches follow the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/): one search per command (a second, without apostrophes, if the first finds nothing), at most one request a second, each answer cached. For heavier use, run your own Nominatim server and set `ILU_NOMINATIM_URL`.

Downloads and searches are cached in `~/.cache/ilu`, or in `$XDG_CACHE_HOME/ilu` when that is set.

`python -m ilu` works the same as `ilu`.

`ilu view PATH` serves a `.glb` file or a tile folder on your machine and opens it in your browser with [three.js](https://threejs.org). Options: `--port N`, `--no-open`. The page loads three.js from a CDN; your model never leaves your computer.

### Python

```python
import ilu

world = ilu.fetch(place='Obafemi Awolowo University')  # or bbox=(south, west, north, east)
result = ilu.build(
    world,
    terrain=ilu.fetch_terrain(world),  # each data layer is optional
    landcover=ilu.fetch_landcover(world),
    canopy=ilu.fetch_canopy(world),
)

with open('oau.glb', 'wb') as f:
    f.write(result.glb)

print(result.stats)  # buildings, courtyards, roads, paths, pitches, pools, trees, triangles, ...
```

Other entry points:
- `ilu.parse(elements)` builds a `World` from Overpass JSON you already have.
- `ilu.build_tiles(world, 1000)` returns a list of `Tile`s, each with its own `result.glb`; `ilu.tile_index(...)` describes them.
- `ilu.sidecar(world, result.trees)` returns the JSON game data as a dictionary.

## How it works

```
Overpass API  ->  osm.parse  ->  World (metres)  ->  build  ->  .glb (+ .json)
                                  buildings           walls, roofs, details
                                  roads               roads, kerbs, walks
                                  areas               land, water, base
                                  places              trees
```

### What is real and what is guessed

Ìlú draws what OpenStreetMap records, and only guesses where it must. The README's images show both.

| Real: from OpenStreetMap or open satellite data | Guessed by Ìlú |
|---|---|
| Position and outline of every building, road, path, pitch, pool, car park, wood and water | Building heights, when there is no `height` or `building:levels` tag |
| Heights and roof shapes, where tagged, including building parts, domes and minarets | Roof shapes, when there is no `roof:shape` tag |
| Pitch and path surfaces, where tagged | Wall and roof colours, when there is no colour tag |
| Building and roof colours, where tagged | Path widths, when there is no `width` tag (2 m for footways, 1.2 m for paths) |
| Sport of each pitch | Car park surface, when untagged (drawn as asphalt) |
| Ground elevation, with `--terrain` (Copernicus DEM) | Window layout: one window per 3 m bay per floor, a generic texture, since OSM does not record windows |
| Ground cover, with `--landcover` (ESA WorldCover): forest, grass, crops, bare earth | The exact colour of each kind of ground (one shade per class) |
| Tree positions and heights, with `--canopy` (Meta canopy height map) | Tree positions without `--canopy` (decoration along roads and in woods) |
| Trees, walls, fences, hedges and street lamps mapped in OSM | Heights of walls, fences, hedges and lamps without a `height` tag |
| Courtyards, islands and clearings (multipolygon inner rings) | The sun: a real position for the latitude, at the hour you choose |
| Place search results (Nominatim) | Minaret height (25 m) and width (3 m), and a cone top, when they are not tagged |
| | Dome and spire colour, when there is no `roof:colour` tag (plain metal grey) |

Things OSM does not describe are left out rather than invented: no stadium stands, no fences that are not mapped, no court lines on a court whose outline does not fit the sport.

### Buildings

Ìlú decides each building's floors and roof in order, stopping at the first rule that applies.

**Floors**

1. The OSM `height` or `building:levels` tag, when present. Parts that start above the ground use `min_height` or `building:min_level`.
2. Kiosks under 30 m²: one floor.
3. Institutional blocks: two to four floors by footprint. A block is a university, school, office, hospital or similar building, or any footprint over 1,500 m².
4. Houses and footprints under 220 m²: usually one floor, sometimes two.
5. Everything else: two or three floors by footprint.

**Roofs**

1. The OSM `roof:shape` tag: flat, gabled, hipped and skillion when the footprint is close enough to a rectangle; dome, onion, cone and pyramidal on any footprint without a courtyard, with `roof:height` when tagged.
2. Kiosks: a lean-to.
3. Small rectangular buildings: a hipped or gabled metal roof, chosen by proportion.
4. Institutional blocks and irregular footprints: a flat roof behind a parapet. In the `west-africa` style, some flat roofs carry a water tank.

**Building parts.** When a building is mapped as [parts](https://wiki.openstreetmap.org/wiki/Simple_3D_Buildings) (`building:part`), each part is built at its own height, from its own base, with its own roof, and the plain outline is left out once its parts cover at least half of it. A single dome mapped on a large roof keeps the building under it. Minarets and towers come from `man_made=minaret`, `man_made=tower` with a `tower:type` of minaret, bell tower or clock, or `tower:type=minaret`; masts and lattice towers are not drawn as solid towers.

Each building's random choices are seeded from its index and position, so a rebuild never changes the result.

### Real-world data

The three data layers are cloud-optimised GeoTIFFs on public cloud storage. Ìlú reads each file's directory, then downloads only the compressed tiles covering your area, and caches them.

| Layer | Dataset | Resolution | What Ìlú does with it |
|---|---|---|---|
| Elevation | [Copernicus DEM GLO-30](https://registry.opendata.aws/copernicus-dem/) | 30 m | The ground grid; everything is draped on it |
| Land cover | [ESA WorldCover 2021](https://esa-worldcover.org) | 10 m | Colours the ground by class, softened over 30 m so edges blend |
| Tree heights | [Meta Global Canopy Height Map v2](https://registry.opendata.aws/dataforgood-fb-forestsv2/) | 1.2 m (read at 4.8 m) | Finds each tree crown: the tallest point in every 7 m square |

**Trees and the budget.** A forested estate holds hundreds of thousands of real trees (the Obafemi Awolowo University estate: about 1.5 million crowns). `--max-trees` keeps the model light. Trees mapped individually in OSM are always kept. After them come the real trees within 120 m of buildings, roads and paths, where people look, and then the rest, thinned evenly by keeping the tallest tree in each square of a grid. Forests stay visible either way, because their ground is coloured from land cover.

A first `--real` build of a large area downloads a few tens of megabytes and takes a minute or two; later builds of the same place use the cache.

### Lighting and shadow

By default Ìlú bakes light into the vertex colours and marks every material `KHR_materials_unlit`, so engines show the colours as baked instead of lighting them again. This looks the same in every viewer and costs nothing on a phone.

- **Sun:** placed for the area's latitude on the March equinox at `--sun-hour` (10:00 by default); faces towards it are lit, faces away are in shade.
- **Sky light:** surfaces facing up get more sky than walls.
- **Contact shadow:** a soft dark band on the ground at the foot of every building, and walls that darken towards the ground: baked ambient occlusion.

Use `--no-bake` to keep ordinary materials and light the model in your engine instead.

### Terrain

With `--terrain` (or `--real`), Ìlú reads elevation from the Copernicus DEM. If that is unavailable, it falls back to [Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) on AWS Open Data (SRTM and other sources). Both are free and need no key.

- **Sampling.** Elevation is sampled every 30 m, the resolution of the source data. The ground is a grid on those samples.
- **Draping.** Roads, paths, pitches and other areas are draped onto exactly the same surface, so nothing sinks into the ground or floats above it.
- **Buildings** stand on the lowest point of their footprint, so on a slope the uphill side sits into the ground, as real buildings do.
- **Water** is flat, at the lowest point of its shoreline. The ground under mapped water is lowered below it, because elevation data over water measures vegetation and noise rather than the bed.
- **Heights** are relative: y = 0 is the lowest ground in the area. Its height above sea level is stored in the file's `extras`.

### Courtyards, lakes and lagoons

OpenStreetMap stores buildings with courtyards, and lakes with islands, as multipolygon relations: an outer ring with inner rings, each often split over several ways. Ìlú joins the pieces into rings and builds them with their holes. Courtyards get their own walls facing in, and islands stay dry land.

Very large areas, such as a lagoon or a forest reserve, are cut to the mapped buildings and roads plus a 150 m margin, so a campus by a lagoon does not become a model of the whole lagoon.

### Large areas and tiles

A whole university estate is hundreds of thousands of triangles. With `--tile-size`, Ìlú writes a grid of tiles instead of one file.

- **Shared frame.** Every tile uses the same origin, so tiles placed at the origin line up exactly.
- **What goes where.** Buildings go to the tile holding their centre; roads, paths and areas are cut at tile edges; trees are placed once for the whole area, so tiling never moves them.
- **Index.** `tiles.json` lists each tile's file, bounds, triangle count and size, so a game can load the tiles near the camera.

For example, the Obafemi Awolowo University estate with terrain (10 by 9 km, 2,710 buildings) becomes 69 tiles of 1 km, the largest about 3.6 MB.

### Sports pitches

Pitches are coloured by their `surface` tag. When the `sport` tag is football, basketball, tennis, handball or volleyball, Ìlú draws that sport's lines at their rule-book size: a football pitch is 90 to 120 m long, and a basketball court is 28 by 15 m. The lines are centred in the pitch's real outline and turned to match it, and are never stretched.

A pitch gets no lines when its outline:
- is not close to a rectangle;
- is smaller than the sport's playing area;
- is much bigger than the playing area plus its run-off, which usually means several courts mapped as one.

### Roads, land and trees

- **Roads** become ribbons sized by class and lane count, with kerbs and sidewalks (no sidewalks on motorways and trunk roads), and rounded joints at bends and junctions.
- **Footpaths**, cycleways and steps are thin ribbons, with their width and surface from OSM when tagged.
- **Areas:** water, pools, woods, grass, cemeteries, car parks and pitches are filled polygons, layered a few centimetres apart so they never flicker. On terrain, woods are painted into the ground's colours instead, since they can cover whole hillsides.
- **Trees** line both sides of each road and fill woods. They never stand on a building, a road, water, a pool, a pitch or a car park.

## Output format

### Model (`.glb`)

Coordinates are metres around the centre of the area: **x east, y up, z south**. A camera looking down -z faces north, as glTF expects. The latitude and longitude of the origin are stored in the file's `extras`.

| Node | Contents |
|---|---|
| `base` | The ground: a flat plate, or with terrain or land cover a 30 m grid (elevation, and ground colour by class) |
| `shadows` | Soft contact shadows at the foot of buildings |
| `land`, `water` | Woods, grass, cemeteries, car parks and pitches; water and pools |
| `markings` | Sport line markings |
| `paths` | Footpaths, cycleways and steps |
| `walks`, `kerbs`, `roads` | Sidewalks, kerbs and road surfaces |
| `walls`, `roofs`, `details` | Buildings (walls carry the window texture); floor slabs and water tanks |
| `barriers`, `lamps` | Walls, fences, hedges and street lamps mapped in OSM |
| `trees` | Low-poly trees |

Colour comes from the `COLOR_0` vertex attribute, with lighting baked in unless `--no-bake` is used. All nodes use one matte material, except `walls`, whose material multiplies in the window texture embedded in the file (`TEXCOORD_0`: u counts 3 m bays along a wall, v counts 3.2 m floors up it). Baked models mark both materials `KHR_materials_unlit`.

`extras` holds the origin's latitude and longitude, and with terrain the height of y = 0 above sea level. Tiles also record their column, row and bounds.

### Game data (`.json`)

| Key | Contents |
|---|---|
| `origin` | Latitude and longitude of the model origin |
| `roads` | Name, class, lanes, width, one-way flag and points of each road |
| `places` | Name, kind and position of each named feature |
| `trees` | `[x, z, scale]` for each tree |

## Limitations

- **No structures beyond buildings and mapped barriers.** Stadium stands and bridges are not generated, because OSM rarely describes their shape.
- **Round roofs follow the outline.** Domes, onions, cones and pyramids are made by shrinking the footprint towards its centre, so a dome on a long building is stretched like the building. Gambrel, mansard, round and other rarer roof shapes are drawn flat.
- **Terrain is about 30 m resolution.** Small banks, ditches and steps are smoothed out, and shorelines on terrain follow the 30 m grid. The Copernicus DEM measures the surface, so dense forest can raise the ground by a few metres.
- **Satellite data has dates.** Land cover is from 2021, and the tree map from imagery of recent years; newer buildings or felled trees may not match.
- **Ground cover is per class.** All grassland is one shade of green; real texture and colour variation is not captured.
- **Windows are generic.** The texture shows a regular pattern of windows, not the building's real ones.
- **Roads are simple:** no bridges, tunnels or lane markings, and dual carriageways are drawn as two separate roads. On terrain, roads follow the ground, including through cuttings and over embankments.
- **Guessed buildings are plausible, not exact.** Better tags give better models; see [contributing to the map](#contributing).

## Troubleshooting

**"HTTPS certificates could not be verified" on macOS**

Python from python.org needs its certificates installed once. Run `Install Certificates.command` in your `/Applications/Python 3.x/` folder.

**"no buildings or roads found"**

A place name given to `ilu build` must exactly match an area's `name` tag in OpenStreetMap. Use `ilu find` to search instead, then build with `--near` or the printed `--bbox` command.

**`--near` built the wrong place**

Many places share a name. Run `ilu find` with the same words to see every match and its address, add the town or state to the search, or copy the `--bbox` command printed under the right match.

**A data layer fails to download**

The data layers come from public buckets on `s3.amazonaws.com`. Check your connection, or build without that layer. Downloaded tiles are cached in `~/.cache/ilu`, so a build that succeeded once works offline.

**Overpass is busy or times out**

Map data comes from the public [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API), a free service run by volunteers on a few servers shared by everyone. At busy times a server may answer "too busy" (429), fail at its gateway (502, 504), or stop a heavy query before it finishes. Ìlú handles this for you:

- it tries the next server, up to six attempts, waiting as long as a busy server asks before trying again;
- it never caches a failed or incomplete reply;
- once an area has downloaded, it is cached, and the server is not needed again for that area.

If every attempt fails, wait a few minutes and run the command again. For very large areas, split them into smaller bounding boxes. Teams that build often can run their own Overpass server, or use a commercial one, and point Ìlú at it with `--overpass-url` or `ILU_OVERPASS_URL`.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](https://github.com/productreelabs/ilu/blob/main/CONTRIBUTING.md) for setup, checks and guidelines, and [CHANGELOG.md](https://github.com/productreelabs/ilu/blob/main/CHANGELOG.md) for release history.

The quickest way to improve every Ìlú model is to improve the map. Adding [`building:levels`](https://wiki.openstreetmap.org/wiki/Key:building:levels) and [`roof:shape`](https://wiki.openstreetmap.org/wiki/Key:roof:shape) to buildings you know in OpenStreetMap helps Ìlú and everyone else who uses the map.

To report a security issue, see [SECURITY.md](https://github.com/productreelabs/ilu/blob/main/SECURITY.md).

## License

- **Code:** [MIT](https://github.com/productreelabs/ilu/blob/main/LICENSE), © 2026 Productree Labs Limited.
- **Place search:** results come from [Nominatim](https://nominatim.org) and OpenStreetMap data (© OpenStreetMap contributors, ODbL).
- **Generated models and JSON:** these are derived from OpenStreetMap data and are licensed under the [Open Database License (ODbL) 1.0](https://www.openstreetmap.org/copyright). If you publish them, credit "© OpenStreetMap contributors".
- **Data layers:** models built with them include data under these terms. Ìlú prints the credits after each build and writes them into the file; keep them with anything you publish.
  - Elevation: Copernicus DEM GLO-30, © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA. Fallback: [Terrain Tiles](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) (Mapzen/Tilezen), from SRTM, GMTED, ETOPO1 and other sources.
  - Land cover: ESA WorldCover 2021, CC BY 4.0, containing modified Copernicus Sentinel data.
  - Tree heights: Meta Data for Good, Global Canopy Height Map v2, CC BY 4.0.
- **The preview image in `docs/`:** shows OpenStreetMap data (© OpenStreetMap contributors, ODbL) with the data layers credited above.

Ìlú is built and maintained by [Malik Rasaq](https://github.com/logicberry).
