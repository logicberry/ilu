import json
import os
import unittest

from ilu import overpass
from ilu.geo import signed_area
from ilu.osm import parse, parse_colour, parse_number

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'small.json')


def load():
    with open(FIXTURE, encoding='utf-8') as f:
        return parse(json.load(f)['elements'])


class ParseTest(unittest.TestCase):
    def test_counts(self):
        w = load()
        self.assertEqual(len(w.buildings), 5)  # the multi-storey car park is a building
        self.assertEqual(len(w.roads), 2)  # footways, paths and tracks are not roads
        self.assertEqual(len(w.paths), 3)
        self.assertEqual(
            sorted(a.kind for a in w.areas), ['parking', 'pitch', 'pitch', 'pitch', 'pool', 'water', 'water', 'wood']
        )
        self.assertEqual(sorted(p.name for p in w.places), ['Main Gate', 'Science Block'])

    def test_heights(self):
        by_kind = {b.kind: b for b in load().buildings if not b.holes}
        self.assertFalse(by_kind[None].measured)
        self.assertEqual(by_kind[None].height, 6.0)
        self.assertTrue(by_kind['university'].measured)
        self.assertAlmostEqual(by_kind['university'].height, 9.6)
        self.assertEqual(by_kind['house'].height, 7.5)
        self.assertEqual(by_kind['house'].roof, 'gabled')

    def test_sport_tags_kept(self):
        courts = [a for a in load().areas if a.kind == 'pitch' and a.sport == 'basketball']
        self.assertEqual(len(courts), 2)
        self.assertTrue(all(a.surface == 'clay' for a in courts))

    def test_multipolygon_building_with_courtyard(self):
        b = next(b for b in load().buildings if b.holes)
        self.assertEqual(b.kind, 'university')
        self.assertAlmostEqual(abs(signed_area(b.outline)), 1600, delta=20)  # joined from two ways
        self.assertEqual(len(b.holes), 1)
        self.assertLess(signed_area(b.holes[0]), 0)  # holes run clockwise

    def test_big_areas_are_clipped_to_the_map(self):
        w = load()
        lake = max((a for a in w.areas if a.kind == 'water'), key=lambda a: abs(signed_area(a.outline)))
        self.assertEqual(len(lake.holes), 1)  # the island
        # Cut to the mapped area plus a 150 m margin, well short of its real east edge at 800 m.
        self.assertLessEqual(max(p[0] for p in lake.outline), 400)

    def test_paths(self):
        by_cls = {p.cls: p for p in load().paths}
        self.assertEqual(by_cls['footway'].width, 2.0)
        self.assertEqual(by_cls['path'].surface, 'gravel')

    def test_building_colours(self):
        b = next(b for b in load().buildings if b.kind is None and b.colour)
        self.assertEqual(b.colour, '#FFFFFF')
        self.assertEqual(b.roof_colour, '#8E5A3E')

    def test_parse_colour(self):
        self.assertEqual(parse_colour('#abc'), '#AABBCC')
        self.assertEqual(parse_colour('D8D0C0'), '#D8D0C0')
        self.assertEqual(parse_colour('Light Grey'), '#808080')
        self.assertIsNone(parse_colour('sparkly'))
        self.assertIsNone(parse_colour(None))

    def test_road(self):
        r = next(r for r in load().roads if r.cls == 'residential')
        self.assertEqual((r.cls, r.lanes, r.name, r.oneway), ('residential', 2, 'Road 1', False))
        self.assertEqual(len(r.points), 3)

    def test_parse_number(self):
        self.assertEqual(parse_number('12'), 12)
        self.assertEqual(parse_number('7.5 m'), 7.5)
        self.assertEqual(parse_number('3;4'), 3)
        self.assertIsNone(parse_number('tall'))
        self.assertIsNone(parse_number(None))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse([])


class QueryTest(unittest.TestCase):
    def test_place(self):
        q = overpass.query(place='Obafemi "Awolowo" University')
        self.assertIn('area["name"="Obafemi \\"Awolowo\\" University"]->.a;', q)
        self.assertIn('way(area.a)["building"];', q)

    def test_bbox(self):
        q = overpass.query(bbox=(7.5, 4.5, 7.6, 4.6))
        self.assertIn('way(7.5,4.5,7.6,4.6)["building"];', q)
        self.assertNotIn('area', q)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            overpass.query()
        with self.assertRaises(ValueError):
            overpass.query(place='x', bbox=(0, 0, 1, 1))
        with self.assertRaises(ValueError):
            overpass.query(bbox=(8, 4, 7, 5))

    def test_response_errors(self):
        with self.assertRaises(RuntimeError):
            overpass.response_elements({'version': 0.6})
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            overpass.response_elements({'elements': [], 'remark': 'runtime error: Query timed out'})
        self.assertEqual(overpass.response_elements({'elements': []}), [])

    def test_cache_is_used(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            q = overpass.query(bbox=(0, 0, 1, 1))
            import hashlib

            path = os.path.join(d, hashlib.sha256(q.encode()).hexdigest()[:16] + '.json')
            with open(path, 'w') as f:
                json.dump({'elements': [{'type': 'node', 'id': 1}]}, f)
            self.assertEqual(overpass.fetch(q, cache=d), [{'type': 'node', 'id': 1}])


class RetryTest(unittest.TestCase):
    """Busy public servers, simulated: no network is used."""

    def run_fetch(self, replies, tries=4):
        import io
        import tempfile
        import urllib.error
        from email.message import Message
        from unittest import mock

        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            reply = replies[len(calls) - 1]
            if isinstance(reply, int):
                headers = Message()
                if reply == 429:
                    headers['Retry-After'] = '7'
                raise urllib.error.HTTPError(req.full_url, reply, 'error', headers, io.BytesIO())
            return io.BytesIO(reply.encode())

        sleeps = []
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch('urllib.request.urlopen', fake_urlopen),
            mock.patch('time.sleep', sleeps.append),
        ):
            try:
                return overpass.fetch('q', cache=d, tries=tries, urls=('https://a/api', 'https://b/api')), calls, sleeps
            except RuntimeError as err:
                return err, calls, sleeps

    def test_busy_server_then_success(self):
        good = json.dumps({'elements': [{'type': 'node', 'id': 1}]})
        result, calls, sleeps = self.run_fetch([429, good])
        self.assertEqual(result, [{'type': 'node', 'id': 1}])
        self.assertEqual(calls, ['https://a/api', 'https://b/api'])  # moved to the next server
        self.assertEqual(sleeps, [7.0])  # waited as long as the server asked

    def test_timed_out_query_is_retried_not_cached(self):
        timeout = json.dumps({'elements': [], 'remark': 'runtime error: Query timed out'})
        good = json.dumps({'elements': [{'type': 'way', 'id': 2}]})
        result, calls, _ = self.run_fetch([timeout, 502, good])
        self.assertEqual(result, [{'type': 'way', 'id': 2}])
        self.assertEqual(len(calls), 3)

    def test_bad_query_is_not_retried(self):
        result, calls, _ = self.run_fetch([400])
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(len(calls), 1)

    def test_gives_a_clear_error_when_all_are_busy(self):
        result, calls, sleeps = self.run_fetch([504, 429, 503, '<html>busy</html>'])
        self.assertIsInstance(result, RuntimeError)
        self.assertIn('ILU_OVERPASS_URL', str(result))
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(sleeps), 3)  # no wait after the last try

    def test_custom_server_from_the_environment(self):
        from unittest import mock

        with mock.patch.dict(os.environ, {'ILU_OVERPASS_URL': 'https://mine/api, https://backup/api'}):
            self.assertEqual(overpass.servers(), ('https://mine/api', 'https://backup/api'))
        with mock.patch.dict(os.environ, {'ILU_OVERPASS_URL': ''}):
            self.assertEqual(overpass.servers(), overpass.MIRRORS)


if __name__ == '__main__':
    unittest.main()


def _way(i, tags, lat, lon, size=0.0002):
    corners = [(lat, lon), (lat, lon + size), (lat + size, lon + size), (lat + size, lon), (lat, lon)]
    return {'type': 'way', 'id': i, 'tags': tags, 'geometry': [{'lat': a, 'lon': b} for a, b in corners]}


class BuildingPartTest(unittest.TestCase):
    def test_parts_replace_the_outline(self):
        w = parse(
            [
                _way(1, {'building': 'mosque', 'height': '12'}, 8.0, 4.0, 0.0004),
                _way(2, {'building:part': 'yes', 'height': '10'}, 8.0, 4.0, 0.0004),
                _way(
                    3,
                    {'building:part': 'yes', 'min_height': '10', 'height': '22', 'roof:shape': 'dome'},
                    8.0001,
                    4.0001,
                ),
            ]
        )
        self.assertEqual(len(w.buildings), 2)
        self.assertTrue(all(b.part for b in w.buildings))
        dome = next(b for b in w.buildings if b.roof == 'dome')
        self.assertEqual((dome.base, dome.height), (10.0, 22.0))

    def test_a_lone_small_part_keeps_the_outline(self):
        w = parse(
            [
                _way(1, {'building': 'yes', 'height': '9'}, 8.0, 4.0, 0.001),
                _way(
                    2,
                    {'building:part': 'yes', 'min_height': '9', 'height': '15', 'roof:shape': 'onion'},
                    8.0004,
                    4.0004,
                ),
            ]
        )
        self.assertEqual(len(w.buildings), 2)  # one dome on a big roof does not replace the building

    def test_levels_above_a_min_level(self):
        (b,) = parse(
            [_way(1, {'building:part': 'yes', 'building:min_level': '2', 'building:levels': '3'}, 8.0, 4.0)]
        ).buildings
        self.assertAlmostEqual(b.base, 6.4)
        self.assertAlmostEqual(b.height, 16.0)
        self.assertTrue(b.measured)

    def test_minaret_node_becomes_a_round_tower(self):
        w = parse(
            [
                _way(1, {'building': 'mosque'}, 8.0, 4.0),
                {
                    'type': 'node',
                    'id': 9,
                    'lat': 8.0003,
                    'lon': 4.0003,
                    'tags': {'man_made': 'minaret', 'height': '30'},
                },
                {
                    'type': 'node',
                    'id': 10,
                    'lat': 8.0003,
                    'lon': 4.0,
                    'tags': {'man_made': 'tower', 'tower:type': 'communication'},
                },
            ]
        )
        towers = [b for b in w.buildings if b.kind == 'minaret']
        self.assertEqual(len(towers), 1)  # the telecom mast is not drawn as a solid tower
        self.assertEqual(towers[0].height, 30.0)
        self.assertEqual(towers[0].roof, 'cone')
        self.assertAlmostEqual(abs(signed_area(towers[0].outline)), 7.0, delta=0.6)  # 3 m across

    def test_overpass_query_asks_for_parts_and_towers(self):
        q = overpass.query(bbox=(8.49, 4.54, 8.50, 4.55))
        self.assertIn('["building:part"]', q)
        self.assertIn('minaret', q)
