# Contributing to Ìlú

Thank you for your interest in Ìlú. Bug reports, better building rules, new regional styles and documentation fixes are all welcome.

## Ways to contribute

- **Report a bug**, or a model that looks wrong, using the [issue templates](https://github.com/productreelabs/ilu/issues/new/choose).
- **Add a style** for your region (see below). This is a good first contribution.
- **Improve a rule**, with a fixture that shows the before and after.
- **Fix the map itself.** Many bad results come from missing data. Adding `building:levels` and `roof:shape` in [OpenStreetMap](https://www.openstreetmap.org) improves Ìlú and every other map.

For larger changes, open an issue first so we can agree on the approach before you write the code.

## Development setup

Ìlú needs Python 3.10 or newer.

```bash
git clone https://github.com/productreelabs/ilu.git
cd ilu
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Checks

Run all of these before opening a pull request. CI runs the same checks on Linux, macOS and Windows, with Python 3.10 to 3.13.

```bash
ruff check .                         # lint
ruff format .                        # format
mypy                                 # strict type check
python -m unittest discover -s tests # tests
```

## Project layout

| Path | Responsibility |
|---|---|
| `src/ilu/overpass.py` | Overpass query, download, mirror fallback, cache |
| `src/ilu/osm.py` | Raw OSM elements to `World` (buildings, roads, areas, places) |
| `src/ilu/geo.py` | Projection, polygons with holes, ring assembly, clipping, triangulation |
| `src/ilu/buildings.py` | Floor and roof guessing; walls and roofs |
| `src/ilu/ground.py` | Roads, sidewalks, paths, land, water and pools, ground plate |
| `src/ilu/markings.py` | Rule-book sport line markings, fitted to real pitch outlines |
| `src/ilu/terrain.py` | Elevation tiles, the terrain grid and its height lookup |
| `src/ilu/cog.py` | Reading cloud-optimised GeoTIFFs over HTTP, with a tile cache |
| `src/ilu/opendata.py` | The open data layers: Copernicus DEM, ESA WorldCover, Meta canopy height |
| `src/ilu/lighting.py` | Sun position and baked lighting |
| `src/ilu/furniture.py` | Walls, fences, hedges and street lamps |
| `src/ilu/viewer.py` | `ilu view`: the local browser viewer |
| `src/ilu/facade.py` | The generic window texture |
| `src/ilu/png.py` | Minimal PNG reading and writing |
| `src/ilu/trees.py` | Tree placement and tree meshes |
| `src/ilu/mesh.py` | The vertex-coloured mesh type |
| `src/ilu/glb.py` | glTF 2.0 binary writer |
| `src/ilu/style.py` | Colour palettes |
| `src/ilu/build.py` | Puts it together: `World` in, `Result` or tiles out |
| `src/ilu/cli.py` | The `ilu` command |
| `src/ilu/geocode.py` | Place search with Nominatim, for `ilu find` and `--near` |

## Engineering rules

- **No runtime dependencies.** Ìlú runs on the Python standard library alone. Development tools are fine.
- **Deterministic output.** All randomness goes through a seeded `random.Random`. The same input, style and seed must give identical bytes.
- **Offline tests.** Add a small saved Overpass response to `tests/fixtures/` instead of calling the network. For raster data, build a small GeoTIFF in the test (see `tests/test_opendata.py`).
- **Credit every dataset.** A new data layer needs its licence checked, a credit line written into the file and printed after the build, and a row in the README's licence section.
- **Tags before guesses.** Use OSM data when it exists. When a rule guesses, say in a comment what the guess is based on, and list it in the README's "What is real and what is guessed" table.
- **Leave out what the map does not describe.** Do not invent structures (stands, fences, lines on a court that does not fit).
- **Typed code.** New code passes `mypy --strict`.
- **Valid output.** Changes to the writer must keep the output passing the [Khronos glTF Validator](https://github.khronos.org/glTF-Validator/) with no errors.

## Adding a style

1. Add a `Style` to `src/ilu/style.py` and register it in `STYLES`.
2. Add a test that builds the fixture with it.
3. List it in the README's options table.
4. In the pull request, include a screenshot of a real area built with it.

## Pull requests

- Keep each pull request to one change, with a clear title ("Read roof:shape=skillion as a lean-to roof").
- Add a test for every behaviour change.
- Add a line to `CHANGELOG.md` under "Unreleased" for anything users will notice.
- Be ready for review comments; we aim to respond within a week.

## Code of conduct

This project follows our [code of conduct](CODE_OF_CONDUCT.md). By taking part, you agree to it.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
