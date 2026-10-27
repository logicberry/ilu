# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-10-27

### Changed

- Ìlú moved to [github.com/productreelabs/ilu](https://github.com/productreelabs/ilu). Old links redirect. No changes to the code or output.

## [0.1.0] - 2026-10-27

First release.

### Added

- `ilu build`: build a `.glb` from an OSM area name, a bounding box, or a saved Overpass file.
- Buildings: walls with a base band and a window texture aligned to floors (`--plain-walls` to turn it off); flat roofs with parapets; hipped, gabled and lean-to roofs; floor slabs and rooftop water tanks.
- Height and roof guessing from footprint size, shape and building type, using OSM `height`, `building:levels` and `roof:shape` tags where present. Wall and roof colours from `building:colour` and `roof:colour`.
- Multipolygon relations: buildings with courtyards, and lakes and lagoons with islands. Very large areas are cut to the mapped area plus a margin.
- `--real`, `--terrain`, `--landcover`, `--canopy`: open data layers read from cloud-optimised GeoTIFFs with only the standard library. Copernicus DEM GLO-30 elevation (Terrain Tiles as a fallback): buildings stand on the ground, roads and areas are draped over it, and water stays level. ESA WorldCover 2021 land cover colours the ground. Meta's canopy height map v2 places real trees at real heights, chosen to fit `--max-trees`.
- Baked lighting: sun for the area's latitude at `--sun-hour`, sky light, contact shadows round buildings and darkening at the foot of walls, with `KHR_materials_unlit` materials. `--no-bake` turns it off.
- `ilu view`: open a model or a folder of tiles in the browser.
- `ilu find`: search for a place by name with Nominatim and print a build command for each match. `ilu build --near PLACE --radius METRES` builds the area round the best match and warns when others exist. Searches are cached and rate-limited, and `ILU_NOMINATIM_URL` points at your own server. A search that finds nothing is retried once without apostrophes.
- Simple 3D Buildings: `building:part`, `min_height`, `building:min_level`, `roof:height` and `roof:levels`, with the outline left out where parts cover it. Dome, onion, cone and pyramidal roofs, and skillion roofs as lean-tos. Minarets and towers from `man_made=minaret`, `man_made=tower` and `tower:type`, including ones mapped as a single point.
- `--bbox` and `ilu.fetch(bbox=...)` cut the model to the box: roads, paths and barriers are clipped at its edges, and buildings are kept whole when their centre is inside.
- `python -m ilu`.
- Walls, fences, hedges, street lamps and individually mapped trees from OSM; road colours from their `surface` tag.
- `--tile-size`: split an area into tiles that line up exactly, with a `tiles.json` index.
- Roads with kerbs and sidewalks; footpaths, cycleways and steps; water, pools, woods, grass, cemeteries, car parks and pitches; a ground plate; seeded trees.
- Pitch and court colours from the `surface` tag, and rule-book line markings for football, basketball, tennis, handball and volleyball, drawn at real size only where the outline fits the sport.
- `west-africa` and `plain` styles.
- `--json` sidecar with roads, named places and trees.
- Python API: `ilu.fetch`, `ilu.fetch_terrain`, `ilu.fetch_landcover`, `ilu.fetch_canopy`, `ilu.parse`, `ilu.build`, `ilu.build_tiles`, `ilu.tile_index`, `ilu.sidecar`.
- Overpass download with mirror fallback, `Retry-After` handling, no caching of failed or incomplete replies, an on-disk cache, and `--overpass-url` / `ILU_OVERPASS_URL` for your own server.

[Unreleased]: https://github.com/productreelabs/ilu/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/productreelabs/ilu/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/productreelabs/ilu/releases/tag/v0.1.0
