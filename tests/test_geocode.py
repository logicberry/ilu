import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from ilu import cli, geocode

ROWS = [
    {
        'display_name': "Emir's Palace, Ilorin, Kwara, Nigeria",
        'lat': '8.4958',
        'lon': '4.5499',
        'category': 'historic',
        'type': 'palace',
    },
    {
        'display_name': 'Central Mosque, Omupo, Kwara, Nigeria',
        'lat': '8.3100',
        'lon': '4.7600',
        'category': 'amenity',
        'type': 'place_of_worship',
    },
]


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'XDG_CACHE_HOME': self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_parses_matches_and_caches_them(self):
        with mock.patch.object(geocode, '_get', return_value=ROWS) as get:
            first = geocode.search("Emir's Palace, Ilorin")
            again = geocode.search("Emir's Palace, Ilorin")
        self.assertEqual(get.call_count, 1)  # the second answer came from the cache
        self.assertEqual(first, again)
        self.assertEqual(first[0].name, "Emir's Palace, Ilorin, Kwara, Nigeria")
        self.assertEqual(first[0].kind, 'historic/palace')
        self.assertAlmostEqual(first[0].lat, 8.4958)

    def test_refresh_searches_again(self):
        with mock.patch.object(geocode, '_get', return_value=ROWS) as get:
            geocode.search('Ilorin')
            geocode.search('Ilorin', refresh=True)
        self.assertEqual(get.call_count, 2)

    def test_retries_without_apostrophes(self):
        with mock.patch.object(geocode, '_get', side_effect=[[], ROWS]) as get:
            matches = geocode.find("Emir of Ilorin's Palace")
        self.assertEqual(len(matches), 2)
        self.assertIn('Emir+of+Ilorin+Palace', get.call_args[0][0])

    def test_empty_query(self):
        with self.assertRaises(ValueError):
            geocode.search('  ')

    def test_box_round_a_match(self):
        s, w, n, e = geocode.Match('x', 8.5, 4.55, 'a/b').bbox(400)
        self.assertAlmostEqual((n - s) * 111320, 800, delta=2)
        self.assertGreater(e - w, n - s)  # a degree of longitude is shorter than one of latitude off the equator
        self.assertTrue(s < 8.5 < n and w < 4.55 < e)

    def test_own_server(self):
        with mock.patch.dict(os.environ, {'ILU_NOMINATIM_URL': 'http://localhost:8080/search'}):
            self.assertEqual(geocode.endpoint(), 'http://localhost:8080/search')
        self.assertEqual(geocode.endpoint(), geocode.PUBLIC_URL)


class FindCliTest(unittest.TestCase):
    def test_lists_every_match_with_a_build_command(self):
        matches = [geocode.Match(r['display_name'], float(r['lat']), float(r['lon']), 'a/b') for r in ROWS]
        out = io.StringIO()
        with mock.patch.object(geocode, 'find', return_value=matches), redirect_stdout(out):
            self.assertEqual(cli.main(['find', 'Central Mosque Kwara']), 0)
        text = out.getvalue()
        self.assertIn("1. Emir's Palace, Ilorin", text)
        self.assertIn('2. Central Mosque, Omupo', text)
        self.assertEqual(text.count('ilu build --bbox '), 2)
        self.assertIn('OpenStreetMap', text)

    def test_nothing_found(self):
        err = io.StringIO()
        with mock.patch.object(geocode, 'find', return_value=[]), redirect_stderr(err):
            self.assertEqual(cli.main(['find', 'Nowhere at all']), 1)
        self.assertIn('nothing found', err.getvalue())

    def test_near_builds_round_the_best_match_and_warns_of_others(self):
        matches = [geocode.Match('A', 8.4958, 4.5499, 'a/b'), geocode.Match('B', 8.31, 4.76, 'a/b')]
        err = io.StringIO()
        with (
            mock.patch.object(geocode, 'find', return_value=matches),
            mock.patch.object(cli.overpass, 'fetch', return_value=[]) as fetch,
            redirect_stderr(err),
        ):
            cli.main(['build', '--near', 'Emir', '--radius', '300', '-o', os.devnull])
        query = fetch.call_args[0][0]
        s, w, n, e = matches[0].bbox(300)
        self.assertIn(f'({s},{w},{n},{e})', query)
        self.assertIn('Found: A', err.getvalue())
        self.assertIn('ilu find "Emir"', err.getvalue())

    def test_near_rejects_a_silly_radius(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli.main(['build', '--near', 'Ilorin', '--radius', '0', '-o', os.devnull]), 1)
        self.assertIn('--radius', err.getvalue())


if __name__ == '__main__':
    unittest.main()
