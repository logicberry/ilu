import unittest
import zlib

from ilu.png import decode_png, encode_png
from ilu.terrain import Terrain


def _png_with_filter(filter_type: int) -> bytes:
    """A 3 x 2 RGB PNG whose rows all use one filter type, built by hand."""
    import struct

    rows = [bytes([10, 20, 30, 40, 50, 60, 70, 80, 90]), bytes([15, 25, 35, 45, 55, 65, 75, 85, 95])]
    raw = b''
    prev = bytes(9)
    for row in rows:
        out = bytearray()
        for i, v in enumerate(row):
            left = row[i - 3] if i >= 3 else 0
            up = prev[i]
            ul = prev[i - 3] if i >= 3 else 0
            if filter_type == 0:
                pred = 0
            elif filter_type == 1:
                pred = left
            elif filter_type == 2:
                pred = up
            elif filter_type == 3:
                pred = (left + up) >> 1
            else:
                p = left + up - ul
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else ul
            out.append((v - pred) & 0xFF)
        raw += bytes([filter_type]) + bytes(out)
        prev = row

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))

    ihdr = struct.pack('>IIBBBBB', 3, 2, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


class PngTest(unittest.TestCase):
    def test_every_filter_type(self):
        expected = bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 15, 25, 35, 45, 55, 65, 75, 85, 95])
        for f in range(5):
            self.assertEqual(decode_png(_png_with_filter(f)), (3, 2, 3, expected), f'filter {f}')

    def test_roundtrip(self):
        pixels = bytes(range(48))
        self.assertEqual(decode_png(encode_png(4, 3, 4, pixels)), (4, 3, 4, pixels))

    def test_rejects_other_files(self):
        with self.assertRaises(ValueError):
            decode_png(b'GIF89a')


class TerrainTest(unittest.TestCase):
    def test_grid_is_relative_to_lowest_point(self):
        t = Terrain.from_function(lambda x, z: 300 + x * 0.1, (0, 100, 0, 50), cell=10)
        self.assertEqual(t.base, 300)
        self.assertAlmostEqual(t.height(0, 0), 0)
        self.assertAlmostEqual(t.height(100, 25), 10)

    def test_bilinear_between_samples(self):
        t = Terrain.from_function(lambda x, z: x + 2 * z, (0, 20, 0, 20), cell=10)
        self.assertAlmostEqual(t.height(5, 5), 15)
        self.assertAlmostEqual(t.height(-50, 0), 0)  # clamped at the edge


if __name__ == '__main__':
    unittest.main()
