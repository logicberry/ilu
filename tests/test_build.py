import json
import math
import os
import random
import struct
import tempfile
import unittest

import ilu
from ilu import cli, markings
from ilu.buildings import guess_shape
from ilu.geo import min_rect
from ilu.glb import read_json
from ilu.mesh import Mesh
from ilu.osm import Building

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'small.json')


def world():
    with open(FIXTURE, encoding='utf-8') as f:
        return ilu.parse(json.load(f)['elements'])


class ShapeTest(unittest.TestCase):
    def shape(self, outline, **kw):
        b = Building(outline=outline, height=kw.pop('height', 6.0), **kw)
        return guess_shape(b, outline, min_rect(outline), random.Random(1))

    def test_measured_height_sets_floors(self):
        sq = [(0, 0), (20, 0), (20, 20), (0, 20)]
        self.assertEqual(self.shape(sq, height=9.6, measured=True).floors, 3)

    def test_roof_tag_wins(self):
        sq = [(0, 0), (20, 0), (20, 10), (0, 10)]
        self.assertEqual(self.shape(sq, roof='flat').roof, 'flat')
        self.assertEqual(self.shape(sq, roof='gabled').roof, 'gable')

    def test_big_or_institutional_is_a_block(self):
        big = [(0, 0), (60, 0), (60, 40), (0, 40)]
        self.assertTrue(self.shape(big).block)
        self.assertEqual(self.shape(big).floors, 4)
        small = [(0, 0), (10, 0), (10, 8), (0, 8)]
        self.assertTrue(self.shape(small, kind='school').block)
        self.assertFalse(self.shape(small).block)

    def test_kiosk_gets_lean_to(self):
        kiosk = [(0, 0), (5, 0), (5, 4), (0, 4)]
        self.assertEqual(self.shape(kiosk).roof, 'lean')


class MarkingsTest(unittest.TestCase):
    def court(self, length, width):
        return [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]

    def test_fits_standard_court(self):
        self.assertIsNotNone(markings.fit(self.court(28, 15), 'basketball'))
        self.assertIsNotNone(markings.fit(self.court(23.77, 10.97), 'tennis'))
        self.assertIsNotNone(markings.fit(self.court(100, 64), 'soccer'))
        self.assertIsNotNone(markings.fit(self.court(40, 20), 'handball;volleyball'))

    def test_skips_what_does_not_match(self):
        self.assertIsNone(markings.fit(self.court(14, 14), 'basketball'))  # smaller than a court
        self.assertIsNone(markings.fit(self.court(74, 36), 'basketball'))  # several courts in one outline
        self.assertIsNone(markings.fit(self.court(60, 40), 'soccer'))  # smaller than a legal pitch
        self.assertIsNone(markings.fit(self.court(100, 64), 'baseball'))  # no layout
        self.assertIsNone(markings.fit(self.court(100, 64), None))
        ell = [(0.0, 0.0), (28.0, 0.0), (28.0, 7.0), (14.0, 7.0), (14.0, 15.0), (0.0, 15.0)]
        self.assertIsNone(markings.fit(ell, 'basketball'))  # not rectangular

    def test_lines_are_never_stretched(self):
        # A pitch inside a running track: lines at the largest legal size, centred.
        fitted = markings.fit(self.court(156, 75), 'soccer')
        self.assertIsNotNone(fitted)
        _, length, width = fitted
        self.assertEqual((length, width), (120.0, 75))
        _, length, width = markings.fit(self.court(32, 18), 'basketball')
        self.assertEqual((length, width), (28.0, 15.0))

    def test_lines_stay_inside_the_court(self):
        m = Mesh('t')
        self.assertTrue(markings.draw(m, self.court(28, 15), 'basketball', 0.0, (1.0, 1.0, 1.0)))
        xs, zs = [p[0] for p in m.pos], [p[2] for p in m.pos]
        self.assertGreaterEqual(min(xs), -0.1)
        self.assertLessEqual(max(xs), 28.1)
        self.assertGreaterEqual(min(zs), -0.1)
        self.assertLessEqual(max(zs), 15.1)


class BuildTest(unittest.TestCase):
    def test_glb_is_valid(self):
        r = ilu.build(world())
        doc = read_json(r.glb)
        self.assertEqual(doc['asset']['version'], '2.0')
        self.assertIn('OpenStreetMap', doc['asset']['copyright'])
        names = {m['name'] for m in doc['meshes']}
        self.assertTrue({'walls', 'roofs', 'roads', 'land', 'water', 'markings', 'paths', 'base', 'trees'} <= names)
        # Every index is in range for its mesh.
        bin_off = 20 + struct.unpack_from('<I', r.glb, 12)[0] + 8
        for mesh in doc['meshes']:
            prim = mesh['primitives'][0]
            n = doc['accessors'][prim['attributes']['POSITION']]['count']
            acc = doc['accessors'][prim['indices']]
            view = doc['bufferViews'][acc['bufferView']]
            idx = struct.unpack_from(f'<{acc["count"]}I', r.glb, bin_off + view['byteOffset'])
            self.assertLess(max(idx), n)
            self.assertEqual(acc['count'] % 3, 0)

    def test_stats(self):
        s = ilu.build(world()).stats
        self.assertEqual(s['buildings'], 5)
        self.assertEqual(s['measured_heights'], 3)
        self.assertEqual(s['courtyards'], 1)
        self.assertEqual(s['roof_tags'], 1)
        self.assertEqual(s['colour_tags'], 1)
        self.assertEqual(s['pools'], 1)
        self.assertEqual(s['pitches'], 3)
        self.assertEqual(s['marked_pitches'], 2)  # the 14 x 14 m square court gets no lines
        self.assertEqual(s['paths'], 3)
        self.assertGreater(s['triangles'], 100)

    def test_deterministic(self):
        self.assertEqual(ilu.build(world(), seed=3).glb, ilu.build(world(), seed=3).glb)

    def test_style_changes_output(self):
        base = ilu.build(world()).glb
        self.assertNotEqual(base, ilu.build(world(), style='plain').glb)

    def test_no_trees(self):
        r = ilu.build(world(), with_trees=False)
        self.assertEqual(r.trees, [])
        self.assertNotIn('trees', {m['name'] for m in read_json(r.glb)['meshes']})

    def test_unknown_style(self):
        with self.assertRaises(ValueError):
            ilu.build(world(), style='nope')

    def test_sidecar(self):
        w = world()
        side = ilu.sidecar(w, ilu.build(w).trees)
        self.assertEqual(side['roads'][0]['name'], 'Road 1')
        self.assertIn('Main Gate', [p['name'] for p in side['places']])
        self.assertIn('OpenStreetMap', side['$credit'])


def _positions(glb: bytes, mesh_name: str) -> list[tuple[float, float, float]]:
    doc = read_json(glb)
    bin_off = 20 + struct.unpack_from('<I', glb, 12)[0] + 8
    mesh = next(m for m in doc['meshes'] if m['name'] == mesh_name)
    acc = doc['accessors'][mesh['primitives'][0]['attributes']['POSITION']]
    view = doc['bufferViews'][acc['bufferView']]
    flat = struct.unpack_from(f'<{acc["count"] * 3}f', glb, bin_off + view['byteOffset'])
    return [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3)]


class FacadeTest(unittest.TestCase):
    def test_walls_carry_the_window_texture(self):
        doc = read_json(ilu.build(world()).glb)
        walls = next(m for m in doc['meshes'] if m['name'] == 'walls')['primitives'][0]
        self.assertIn('TEXCOORD_0', walls['attributes'])
        material = doc['materials'][walls['material']]
        self.assertEqual(material['pbrMetallicRoughness']['baseColorTexture'], {'index': 0})
        self.assertEqual(doc['images'][0]['mimeType'], 'image/png')

    def test_texture_is_a_valid_png(self):
        from ilu import facade
        from ilu.png import decode_png

        width, height, channels, _ = decode_png(facade.png())
        self.assertEqual((width, height, channels), (facade.WIDTH, facade.HEIGHT, 3))

    def test_plain_walls(self):
        doc = read_json(ilu.build(world(), facades=False).glb)
        self.assertNotIn('images', doc)
        self.assertEqual(len(doc['materials']), 1)


class TerrainBuildTest(unittest.TestCase):
    def slope(self):
        from ilu.terrain import Terrain

        w = world()
        x0, x1, z0, z1 = w.bounds()
        return w, Terrain.from_function(lambda x, z: 100 + 0.05 * x, (x0 - 60, x1 + 60, z0 - 60, z1 + 60), 30)

    def test_buildings_stand_on_the_ground(self):
        w, t = self.slope()
        r = ilu.build(w, terrain=t)
        for x, y, z in _positions(r.glb, 'walls'):
            self.assertGreaterEqual(y, t.height(x, z) - 0.05 * 60 - 0.01)  # at most the footprint's fall below

    def test_water_is_level(self):
        w, t = self.slope()
        heights = {round(y, 3) for _, y, _ in _positions(ilu.build(w, terrain=t).glb, 'water')}
        self.assertEqual(len(heights), 3)  # the pool, the pond and the clipped lake, each flat

    def test_records_the_elevation(self):
        w, t = self.slope()
        doc = read_json(ilu.build(w, terrain=t).glb)
        self.assertEqual(doc['extras']['elevation']['base_m'], t.base)
        self.assertIn('Terrain Tiles', doc['asset']['copyright'])


class TileTest(unittest.TestCase):
    def test_tiles_cover_everything_once(self):
        w = world()
        tiles = ilu.build_tiles(w, 100)
        self.assertGreater(len(tiles), 1)
        self.assertEqual(sum(t.result.stats['buildings'] for t in tiles), len(w.buildings))
        planted = sorted(tree for t in tiles for tree in t.result.trees)
        self.assertEqual(planted, sorted(ilu.build(w).trees))
        for t in tiles:
            read_json(t.result.glb)

    def test_index(self):
        w = world()
        tiles = ilu.build_tiles(w, 100)
        names = [f'{t.col}_{t.row}.glb' for t in tiles]
        index = ilu.tile_index(w, tiles, names, 100)
        self.assertEqual([t['file'] for t in index['tiles']], names)
        self.assertEqual(index['tile_size'], 100)

    def test_rejects_bad_size(self):
        with self.assertRaises(ValueError):
            ilu.build_tiles(world(), 0)


class CliTest(unittest.TestCase):
    def test_tiles_to_a_folder(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'tiles')
            self.assertEqual(cli.main(['build', '--osm', FIXTURE, '-o', out, '--tile-size', '150', '--plain-walls']), 0)
            with open(os.path.join(out, 'tiles.json'), encoding='utf-8') as f:
                index = json.load(f)
            self.assertTrue(index['tiles'])
            for t in index['tiles']:
                self.assertTrue(os.path.exists(os.path.join(out, t['file'])))

    def test_tiles_onto_an_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'model.glb')
            open(path, 'wb').close()
            self.assertEqual(cli.main(['build', '--osm', FIXTURE, '-o', path, '--tile-size', '100']), 1)

    def test_unwritable_output(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cli.main(['build', '--osm', FIXTURE, '-o', os.path.join(d, 'missing', 'x.glb')]), 1)

    def test_bad_tile_size(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cli.main(['build', '--osm', FIXTURE, '-o', d, '--tile-size', '-5']), 1)

    def test_build_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            out, side = os.path.join(d, 'x.glb'), os.path.join(d, 'x.json')
            self.assertEqual(cli.main(['build', '--osm', FIXTURE, '-o', out, '--json', side, '--no-trees']), 0)
            with open(out, 'rb') as f:
                read_json(f.read())
            with open(side, encoding='utf-8') as f:
                self.assertEqual(json.load(f)['trees'], [])

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                cli.main(['build', '--osm', os.path.join(d, 'none.json'), '-o', os.path.join(d, 'x.glb')]), 1
            )


if __name__ == '__main__':
    unittest.main()


class RealLayersTest(unittest.TestCase):
    def test_baked_models_are_unlit(self):
        doc = read_json(ilu.build(world()).glb)
        self.assertIn('KHR_materials_unlit', doc['extensionsUsed'])
        self.assertTrue(all('KHR_materials_unlit' in m['extensions'] for m in doc['materials']))
        self.assertTrue(doc['extras']['lighting']['baked'])

    def test_no_bake_leaves_lighting_to_the_engine(self):
        doc = read_json(ilu.build(world(), bake=False).glb)
        self.assertNotIn('extensionsUsed', doc)

    def test_contact_shadows_darken_towards_the_wall(self):
        r = ilu.build(world(), bake=False)
        shadows = next(m for m in r.meshes if m.name == 'shadows')
        self.assertTrue(shadows.idx)
        colours = sorted({round(c[1], 4) for c in shadows.col})
        self.assertLess(colours[0], colours[-1] * 0.7)

    def test_landcover_colours_the_ground(self):
        from ilu.opendata import LandCover

        w = world()
        x0, x1, z0, z1 = w.bounds()
        cols, rows = int((x1 - x0) // 10) + 1, int((z1 - z0) // 10) + 1
        # Bare earth on the west half, trees on the east half.
        classes = bytes(60 if i < cols // 2 else 10 for _ in range(rows) for i in range(cols))
        lc = LandCover(x0, z0, 10.0, cols, rows, classes)
        base = next(m for m in ilu.build(w, landcover=lc, bake=False).meshes if m.name == 'base')
        west = [c for p, c in zip(base.pos, base.col, strict=True) if p[0] < x0 + (x1 - x0) * 0.25]
        east = [c for p, c in zip(base.pos, base.col, strict=True) if p[0] > x0 + (x1 - x0) * 0.75]
        self.assertGreater(sum(c[0] for c in west) / len(west), sum(c[0] for c in east) / len(east))  # redder

    def test_canopy_trees_are_real_and_within_budget(self):
        from ilu.opendata import TreeTop

        w = world()
        tops = [TreeTop(float(x), float(z), 10.0 + (x % 7)) for x in range(-200, 300, 6) for z in range(-200, 300, 6)]
        r = ilu.build(w, canopy=tops, max_trees=60)
        self.assertLessEqual(len(r.trees), 60)
        real = {(t.x, t.z) for t in tops} | {(f.x, f.z) for f in w.features if f.kind == 'tree'}
        mapped = [t for t in r.trees if t[2] == round(12 / 5.8, 2)]
        self.assertEqual(len(mapped), 1)  # the tree mapped in OSM is always kept
        for x, z, _ in r.trees:
            self.assertIn((round(x), round(z)), {(round(a), round(b)) for a, b in real})

    def test_osm_details(self):
        w = world()
        self.assertEqual(sorted(b.kind for b in w.barriers), ['fence', 'wall'])
        fence = next(b for b in w.barriers if b.kind == 'fence')
        self.assertEqual((fence.height, fence.measured), (2.4, True))
        self.assertEqual(sorted(f.kind for f in w.features), ['lamp', 'tree'])
        stats = ilu.build(w).stats
        self.assertEqual((stats['barriers'], stats['lamps'], stats['mapped_trees']), (2, 1, 1))
        names = {m['name'] for m in read_json(ilu.build(w).glb)['meshes']}
        self.assertTrue({'barriers', 'lamps', 'shadows'} <= names)

    def test_unpaved_roads_are_not_asphalt(self):
        w = world()
        service = next(r for r in w.roads if r.cls == 'service')
        self.assertEqual(service.surface, 'unpaved')


class CropTest(unittest.TestCase):
    def test_nothing_reaches_past_the_box(self):
        w = world()
        box = (-30.0, 90.0, -40.0, 60.0)
        cropped = ilu.crop(w, box)
        for r in cropped.roads + cropped.paths:
            for x, z in r.points:
                self.assertTrue(box[0] - 1e-9 <= x <= box[1] + 1e-9 and box[2] - 1e-9 <= z <= box[3] + 1e-9)
        for a in cropped.areas:
            for x, z in a.outline:
                self.assertTrue(box[0] - 1e-9 <= x <= box[1] + 1e-9 and box[2] - 1e-9 <= z <= box[3] + 1e-9)
        self.assertLess(len(cropped.buildings), len(w.buildings))
        # Buildings are kept whole, never cut in half: one whose centre is inside may reach past the edge.
        for b in cropped.buildings:
            cx = sum(p[0] for p in b.outline) / len(b.outline)
            cz = sum(p[1] for p in b.outline) / len(b.outline)
            self.assertTrue(box[0] <= cx <= box[1] and box[2] <= cz <= box[3])
            self.assertIn(b, w.buildings)

    def test_crop_to_bbox_in_degrees(self):
        w = world()
        # The fixture's origin is near 7.52 N, 4.52 E; a tiny box round it keeps little.
        small = ilu.crop_to_bbox(
            w, (w.origin[0] - 0.0002, w.origin[1] - 0.0002, w.origin[0] + 0.0002, w.origin[1] + 0.0002)
        )
        self.assertLessEqual(len(small.buildings), 1)
        big = ilu.crop_to_bbox(w, (w.origin[0] - 1, w.origin[1] - 1, w.origin[0] + 1, w.origin[1] + 1))
        self.assertEqual(len(big.buildings), len(w.buildings))


class ViewerTest(unittest.TestCase):
    def test_files_for_a_model_and_a_tile_folder(self):
        from ilu import viewer

        with tempfile.TemporaryDirectory() as d:
            model = os.path.join(d, 'a.glb')
            open(model, 'wb').close()
            self.assertEqual(viewer.files_for(model), (d, ['a.glb']))
            out = os.path.join(d, 'tiles')
            cli.main(['build', '--osm', FIXTURE, '-o', out, '--tile-size', '150'])
            folder, files = viewer.files_for(out)
            self.assertEqual(folder, out)
            self.assertTrue(files and all(f.endswith('.glb') for f in files))
            with self.assertRaises(FileNotFoundError):
                viewer.files_for(os.path.join(d, 'missing.glb'))

    def test_page_lists_the_files(self):
        from ilu import viewer

        html = viewer.page(['tile_0_0.glb'])
        self.assertIn('["tile_0_0.glb"]', html)
        self.assertIn('three@0.160.0', html)
        self.assertNotIn('THREE/', html)


class CliOptionsTest(unittest.TestCase):
    def test_view_a_missing_file(self):
        import contextlib
        import io

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(['view', 'nowhere.glb', '--no-open']), 1)
        self.assertIn('build it first', err.getvalue())

    def test_bad_sun_hour(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                cli.main(['build', '--osm', FIXTURE, '-o', os.path.join(d, 'x.glb'), '--sun-hour', '30']), 1
            )

    def test_no_bake(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'x.glb')
            self.assertEqual(cli.main(['build', '--osm', FIXTURE, '-o', out, '--no-bake']), 0)
            with open(out, 'rb') as f:
                self.assertNotIn('extensionsUsed', read_json(f.read()))


class RoundRoofTest(unittest.TestCase):
    def _square(self, size=10.0):
        return [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]

    def _build(self, b):
        from ilu import buildings
        from ilu.style import STYLES

        meshes, shapes = buildings.build([b], STYLES['west-africa'], facades=False)
        return meshes, shapes[0]

    def test_dome_rises_over_the_walls(self):
        b = Building(self._square(), 14.0, roof='dome', measured=True, roof_height=5.0)
        meshes, shape = self._build(b)
        self.assertEqual(shape.roof, 'dome')
        ys = [p[1] for p in meshes.roofs.pos]
        self.assertAlmostEqual(min(ys), 9.0)
        self.assertAlmostEqual(max(ys), 14.0)
        self.assertAlmostEqual(max(p[1] for p in meshes.walls.pos), 9.0)

    def test_round_roof_normals_point_outwards(self):
        for roof in ('dome', 'onion', 'cone', 'pyramidal'):
            meshes, _ = self._build(Building(self._square(), 10.0, roof=roof))
            for (x, _y, z), (nx, ny, nz) in zip(meshes.roofs.pos, meshes.roofs.nor, strict=True):
                self.assertGreaterEqual((x - 5) * nx + (z - 5) * nz + ny * 0.5, -1e-6, roof)

    def test_part_walls_start_at_its_base(self):
        meshes, _ = self._build(Building(self._square(), 20.0, base=12.0, part=True, measured=True))
        self.assertAlmostEqual(min(p[1] for p in meshes.walls.pos), 12.0)
        self.assertAlmostEqual(max(p[1] for p in meshes.walls.pos), 20.0)
        self.assertTrue(any(n == (0.0, -1.0, 0.0) for n in meshes.roofs.nor))  # its underside is closed

    def test_unmeasured_minaret_keeps_its_guessed_height(self):
        ring = [(1.5 * math.cos(i * math.pi / 6), 1.5 * math.sin(i * math.pi / 6)) for i in range(12)]
        meshes, _ = self._build(Building(ring, 25.0, kind='minaret', roof='cone'))
        self.assertAlmostEqual(max(p[1] for p in meshes.roofs.pos), 25.0)

    def test_round_roof_on_a_courtyard_falls_back_to_flat(self):
        holes = [[(3.0, 3.0), (3.0, 7.0), (7.0, 7.0), (7.0, 3.0)]]
        _, shape = self._build(Building(self._square(), 10.0, roof='dome', holes=holes))
        self.assertEqual(shape.roof, 'flat')
