import itertools
import os
import pathlib
import struct
import tempfile
import unittest
import zlib
from unittest import mock

from ilu import lighting, opendata
from ilu.cog import Source


def _encode_tile(values: list[float], width: int, bits: int, predictor: int) -> bytes:
    """Encode one tile the way a GeoTIFF writer would, then DEFLATE it."""
    if bits == 8:
        rows = [bytes(int(v) for v in values[y * width : (y + 1) * width]) for y in range(len(values) // width)]
        if predictor == 2:
            rows = [bytes([r[0]] + [(r[i] - r[i - 1]) & 0xFF for i in range(1, len(r))]) for r in rows]
        return zlib.compress(b''.join(rows))
    out = b''
    for y in range(len(values) // width):
        row = values[y * width : (y + 1) * width]
        if predictor == 3:
            raw = struct.pack(f'>{width}f', *row)  # most significant byte first, as the planes expect
            planes = b''.join(raw[p::4] for p in range(4))
            out += bytes([planes[0]] + [(planes[i] - planes[i - 1]) & 0xFF for i in range(1, len(planes))])
        else:
            out += struct.pack(f'<{width}f', *row)
    return zlib.compress(out)


def write_tiff(
    path: str,
    values: list[float],
    width: int,
    height: int,
    tile: int,
    bits: int = 8,
    predictor: int = 1,
    big: bool = False,
    origin=(3.0, 9.0),
    scale=(0.5, 0.5),
) -> None:
    """A minimal tiled, DEFLATE-compressed GeoTIFF with one band."""
    across, down = -(-width // tile), -(-height // tile)
    tiles = []
    for ty, tx in itertools.product(range(down), range(across)):
        block = []
        for y in range(tile):
            for x in range(tile):
                gx, gy = tx * tile + x, ty * tile + y
                block.append(values[gy * width + gx] if gx < width and gy < height else 0)
        tiles.append(_encode_tile(block, tile, bits, predictor))
    o = '<'
    entries = [
        (256, 3, [width]),
        (257, 3, [height]),
        (258, 3, [bits]),
        (259, 3, [8]),
        (277, 3, [1]),
        (317, 3, [predictor]),
        (322, 3, [tile]),
        (323, 3, [tile]),
        (339, 3, [3 if bits == 32 else 1]),
        (324, 16 if big else 4, [0] * len(tiles)),
        (325, 16 if big else 4, [len(t) for t in tiles]),
        (33550, 12, [scale[0], scale[1], 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0]),
    ]
    fmt = {3: 'H', 4: 'I', 12: 'd', 16: 'Q'}
    size = {3: 2, 4: 4, 12: 8, 16: 8}
    header = 16 if big else 8
    entry_size, count_size, next_size = (20, 8, 8) if big else (12, 2, 4)
    ifd = header
    extra = ifd + count_size + entry_size * len(entries) + next_size
    blobs = b''
    pointers = {}
    for tag, typ, vals in entries:
        if size[typ] * len(vals) > (8 if big else 4):
            pointers[tag] = extra + len(blobs)
            blobs += struct.pack(f'{o}{len(vals)}{fmt[typ]}', *vals)
    data_start = extra + len(blobs)
    offsets, pos = [], data_start
    for t in tiles:
        offsets.append(pos)
        pos += len(t)
    blobs = b''
    for tag, typ, vals in entries:
        if tag == 324:
            vals[:] = offsets
        if size[typ] * len(vals) > (8 if big else 4):
            blobs += struct.pack(f'{o}{len(vals)}{fmt[typ]}', *vals)
    out = bytearray()
    out += b'II' + struct.pack(o + 'H', 43 if big else 42)
    out += struct.pack(o + 'HHQ', 8, 0, ifd) if big else struct.pack(o + 'I', ifd)
    out += struct.pack(o + ('Q' if big else 'H'), len(entries))
    for tag, typ, vals in entries:
        nbytes = size[typ] * len(vals)
        if nbytes <= (8 if big else 4):
            inline = struct.pack(f'{o}{len(vals)}{fmt[typ]}', *vals).ljust(8 if big else 4, b'\0')
        else:
            inline = struct.pack(o + ('Q' if big else 'I'), pointers[tag])
        out += struct.pack(o + 'HH', tag, typ) + struct.pack(o + ('Q' if big else 'I'), len(vals)) + inline
    out += b'\0' * next_size + blobs
    assert len(out) == data_start
    for t in tiles:
        out += t
    pathlib.Path(path).write_bytes(bytes(out))


class CogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'XDG_CACHE_HOME': os.path.join(self.tmp.name, 'cache')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def roundtrip(self, values, width, height, **kw):
        path = os.path.join(self.tmp.name, f'{len(os.listdir(self.tmp.name))}.tif')
        write_tiff(path, values, width, height, tile=16, **kw)
        src = Source(pathlib.Path(path).as_uri())
        rows = src.window(0, 0, 0, width, height)
        return src, [v for r in rows for v in r]

    def test_bytes_every_layout(self):
        values = [float((x * 7 + y * 13) % 251) for y in range(20) for x in range(37)]
        for big, predictor in itertools.product((False, True), (1, 2)):
            _, got = self.roundtrip(values, 37, 20, bits=8, predictor=predictor, big=big)
            self.assertEqual(got, values, f'big={big} predictor={predictor}')

    def test_floats_with_floating_point_predictor(self):
        values = [250.5 + 0.25 * x - 0.125 * y for y in range(18) for x in range(21)]
        for predictor in (1, 3):
            _, got = self.roundtrip(values, 21, 18, bits=32, predictor=predictor)
            for a, b in zip(got, values, strict=True):
                self.assertAlmostEqual(a, b, places=4)

    def test_georeference_and_partial_window(self):
        values = [float(x) for y in range(20) for x in range(40)]
        src, _ = self.roundtrip(values, 40, 20, origin=(3.0, 9.0), scale=(0.25, 0.25))
        self.assertEqual((src.origin, src.scale), ((3.0, 9.0), (0.25, 0.25)))
        rows = src.window(0, 30, 5, 15, 2, fill=-1)
        self.assertEqual(rows[0][:10], [float(x) for x in range(30, 40)])
        self.assertEqual(rows[0][10:], [-1.0] * 5)  # beyond the image

    def test_tiles_are_cached(self):
        values = [1.0] * 256
        src, _ = self.roundtrip(values, 16, 16)
        cached = os.listdir(src.folder)
        self.assertIn('0-0-0', cached)
        self.assertIn('header', cached)

    def test_not_a_tiff(self):
        path = os.path.join(self.tmp.name, 'x.tif')
        pathlib.Path(path).write_bytes(b'GIF89a' + bytes(100))
        with self.assertRaises(ValueError):
            Source(pathlib.Path(path).as_uri())


class OpenDataTest(unittest.TestCase):
    def test_quadkey(self):
        self.assertEqual(opendata._quadkey(7.52, 4.52, 10), '1222203120')

    def test_file_names(self):
        self.assertEqual(opendata._hemi(6, 'N', 'S', 2) + opendata._hemi(3, 'E', 'W', 3), 'N06E003')
        self.assertEqual(opendata._hemi(-3, 'N', 'S', 2) + opendata._hemi(-75, 'E', 'W', 3), 'S03W075')
        self.assertEqual(opendata._degree_files((6.5, 2.5, 9.5, 3.5), 3), [(6, 0), (6, 3), (9, 0), (9, 3)])

    def test_landcover_lookup_and_share(self):
        lc = opendata.LandCover(0.0, 0.0, 10.0, 2, 2, bytes([10, 10, 30, 50]))
        self.assertEqual(lc.at(5, 5), 10)
        self.assertEqual(lc.at(15, 15), 50)
        self.assertEqual(lc.at(-100, 100), 30)  # clamped to the edge
        self.assertEqual(lc.share(), {'trees': 0.5, 'grass': 0.25, 'built-up': 0.25})


class LightingTest(unittest.TestCase):
    def test_sun_overhead_at_equator_noon(self):
        _x, y, _z = lighting.sun_direction(0.0, 12.0)
        self.assertAlmostEqual(y, 1.0, places=2)

    def test_morning_sun_in_the_east(self):
        x, y, _ = lighting.sun_direction(7.5, 9.0)
        self.assertGreater(x, 0.3)
        self.assertGreater(y, 0.3)

    def test_flat_ground_in_sun_is_unchanged(self):
        sun = lighting.sun_direction(7.5, 10.0)
        self.assertAlmostEqual(lighting.light((0.0, 1.0, 0.0), sun), 1.0)
        self.assertLess(lighting.light((-sun[0], 0.0, -sun[2]), sun), 0.75)  # a wall facing away is darker


if __name__ == '__main__':
    unittest.main()
