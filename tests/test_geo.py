import math
import unittest

from ilu.geo import (
    assemble_rings,
    centroid,
    clip_line_to_box,
    clip_to_box,
    ear_clip,
    min_rect,
    poly_contains,
    projector,
    ring,
    signed_area,
    simplify,
    triangulate,
    unprojector,
)


class GeoTest(unittest.TestCase):
    def test_projector_axes(self):
        project = projector(7.5, 4.5)
        self.assertEqual(project(7.5, 4.5), (0.0, 0.0))
        x, z = project(7.5, 4.501)  # east
        self.assertGreater(x, 100)
        self.assertEqual(z, 0.0)
        x, z = project(7.501, 4.5)  # north is -z
        self.assertLess(z, -100)
        self.assertAlmostEqual(-z, 111.2, delta=0.2)

    def test_area_and_centroid(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertEqual(signed_area(sq), 100)
        self.assertEqual(signed_area(sq[::-1]), -100)
        self.assertEqual(centroid(sq), (5, 5))

    def test_contains(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(poly_contains(sq, 5, 5))
        self.assertFalse(poly_contains(sq, 15, 5))

    def test_simplify_drops_collinear(self):
        line = [(0, 0), (1, 0.01), (2, 0), (3, 5)]
        self.assertEqual(simplify(line, 0.1), [0, 2, 3])

    def test_ring_is_counter_clockwise_and_open(self):
        clockwise = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]
        r = ring(clockwise, 0.1)
        self.assertEqual(len(r), 4)
        self.assertGreater(signed_area(r), 0)
        self.assertIsNone(ring([(0, 0), (1, 0), (0, 0)], 0.1))

    def test_ear_clip_concave(self):
        ell = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
        pts, tris = ear_clip(ell)
        self.assertEqual(len(tris), len(pts) - 2)
        total = sum(abs(signed_area([pts[a], pts[b], pts[c]])) for a, b, c in tris)
        self.assertAlmostEqual(total, abs(signed_area(ell)))

    def test_triangulate_with_holes(self):
        outer = [(0, 0), (30, 0), (30, 20), (0, 20)]
        holes = [[(5, 5), (5, 15), (12, 15), (12, 5)], [(18, 5), (18, 15), (25, 15), (25, 5)]]
        pts, tris = triangulate(outer, holes)
        total = sum(abs(signed_area([pts[a], pts[b], pts[c]])) for a, b, c in tris)
        self.assertAlmostEqual(total, 600 - 70 - 70)
        for a, b, c in tris:  # no triangle covers a hole
            cx, cz = (pts[a][0] + pts[b][0] + pts[c][0]) / 3, (pts[a][1] + pts[b][1] + pts[c][1]) / 3
            self.assertFalse(any(poly_contains(h, cx, cz) for h in holes))

    def test_ear_clip_is_fast_on_large_outlines(self):
        import time

        n = 3000
        wavy = [
            (
                1000 * math.cos(2 * math.pi * i / n) * (1 + 0.3 * math.sin(i / 7)),
                1000 * math.sin(2 * math.pi * i / n) * (1 + 0.3 * math.sin(i / 7)),
            )
            for i in range(n)
        ]
        start = time.perf_counter()
        pts, tris = ear_clip(wavy)
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertEqual(len(tris), n - 2)
        self.assertAlmostEqual(sum(abs(signed_area([pts[a], pts[b], pts[c]])) for a, b, c in tris), signed_area(wavy))

    def test_assemble_rings(self):
        parts = [[(0, 0), (1, 0)], [(1, 1), (1, 0)], [(1, 1), (0, 1), (0, 0)], [(5, 5), (6, 5)]]
        rings = assemble_rings(parts)
        self.assertEqual(len(rings), 1)  # the open piece is dropped
        self.assertEqual(len(rings[0]), 5)
        self.assertEqual(rings[0][0], rings[0][-1])

    def test_clip_to_box(self):
        clipped = clip_to_box([(-5, -5), (5, -5), (5, 5), (-5, 5)], 0, 10, 0, 10)
        self.assertAlmostEqual(abs(signed_area(clipped)), 25)

    def test_clip_line_to_box(self):
        # A road crossing the whole box is cut exactly at its edges.
        self.assertEqual(clip_line_to_box([(-10, 5), (20, 5)], 0, 10, 0, 10), [[(0, 5), (10, 5)]])
        # Leaving and coming back in gives two pieces.
        runs = clip_line_to_box([(2, 2), (2, 20), (8, 20), (8, 2)], 0, 10, 0, 10)
        self.assertEqual(runs, [[(2, 2), (2, 10)], [(8, 10), (8, 2)]])
        # Entirely outside gives nothing; entirely inside is unchanged.
        self.assertEqual(clip_line_to_box([(20, 20), (30, 30)], 0, 10, 0, 10), [])
        self.assertEqual(clip_line_to_box([(1, 1), (5, 5), (9, 1)], 0, 10, 0, 10), [[(1, 1), (5, 5), (9, 1)]])

    def test_unprojector_inverts_projector(self):
        project, unproject = projector(7.5, 4.5), unprojector(7.5, 4.5)
        lat, lon = unproject(*project(7.51, 4.52))
        self.assertAlmostEqual(lat, 7.51, places=5)
        self.assertAlmostEqual(lon, 4.52, places=5)

    def test_min_rect_of_rotated_rectangle(self):
        a = math.radians(30)
        corners = [
            (x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a))
            for x, z in [(-10, -4), (10, -4), (10, 4), (-10, 4)]
        ]
        cx, cz, _ang, length, width = min_rect(corners)
        self.assertAlmostEqual(length, 20, places=6)
        self.assertAlmostEqual(width, 8, places=6)
        self.assertAlmostEqual(cx, 0, places=6)
        self.assertAlmostEqual(cz, 0, places=6)


if __name__ == '__main__':
    unittest.main()
