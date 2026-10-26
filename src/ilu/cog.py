"""Read windows from cloud-optimised GeoTIFFs over HTTP, using only the standard library.

A cloud-optimised GeoTIFF (COG) stores its pixels in compressed square
tiles, often with smaller overview copies. Ìlú reads the file's directory
with one range request, then fetches only the tiles an area needs. Tiles
are cached on disk, so a second build of the same place needs no network.

Supported: classic TIFF and BigTIFF, tiled layout, DEFLATE or no
compression, horizontal and floating-point predictors, 8-bit unsigned
integers and 32-bit floats, one band.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from array import array
from dataclasses import dataclass

from . import __version__
from .overpass import cache_dir

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
_TYPE_FMT = {1: 'B', 3: 'H', 4: 'I', 6: 'b', 8: 'h', 9: 'i', 11: 'f', 12: 'd', 16: 'Q', 17: 'q', 18: 'Q'}
HEADER_BYTES = 1 << 16


@dataclass
class Level:
    """One resolution in the file: the full image or an overview."""

    width: int
    height: int
    tile_width: int
    tile_height: int
    offsets: list[int]
    counts: list[int]
    bits: int
    sample_format: int  # 1 unsigned integer, 3 float
    compression: int  # 1 none, 8 DEFLATE
    predictor: int  # 1 none, 2 horizontal, 3 floating point

    @property
    def tiles_across(self) -> int:
        return math.ceil(self.width / self.tile_width)


class Source:
    """A remote GeoTIFF, read in ranges, with tiles cached on disk."""

    def __init__(self, url: str, refresh: bool = False) -> None:
        self.url = url
        self.refresh = refresh
        self.folder = os.path.join(cache_dir(), 'cog', hashlib.sha256(url.encode()).hexdigest()[:16])
        head = self._cached('header', 0, HEADER_BYTES, allow_short=True)
        self._data = head
        self.levels, self.scale, self.origin = self._parse(head)

    # ------------------------------------------------------------ network

    def _get(self, start: int, length: int, allow_short: bool = False) -> bytes:
        req = urllib.request.Request(
            self.url,
            headers={'Range': f'bytes={start}-{start + length - 1}', 'User-Agent': f'ilu/{__version__}'},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    data: bytes = res.read()
                    whole = getattr(res, 'status', 200) != 206
                if whole and len(data) > length:
                    data = data[start : start + length]  # the server ignored the range and sent the whole file
                if len(data) < length and not allow_short:
                    raise OSError(f'short read: {len(data)} of {length} bytes')
                return data
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    raise FileNotFoundError(self.url) from err
                last: Exception = err
            except OSError as err:
                last = err
            print(f'  {self.url.rsplit("/", 1)[-1]}: {last}, retrying', file=sys.stderr)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f'could not download {self.url}: {last}')

    def _cached(self, name: str, start: int, length: int, allow_short: bool = False) -> bytes:
        path = os.path.join(self.folder, name)
        if os.path.exists(path) and not self.refresh:
            with open(path, 'rb') as f:
                return f.read()
        data = self._get(start, length, allow_short)
        os.makedirs(self.folder, exist_ok=True)
        with open(path + '.part', 'wb') as f:
            f.write(data)
        os.replace(path + '.part', path)
        return data

    def _bytes(self, start: int, length: int) -> bytes:
        """Bytes from the header region, fetching more of the file if a table lies beyond it."""
        if start + length <= len(self._data):
            return self._data[start : start + length]
        return self._cached(f'range-{start}-{length}', start, length)

    # ------------------------------------------------------------ directory

    def _parse(self, head: bytes) -> tuple[list[Level], tuple[float, float], tuple[float, float]]:
        bo = '<' if head[:2] == b'II' else '>'
        magic = struct.unpack(bo + 'H', head[2:4])[0]
        big = magic == 43
        if magic not in (42, 43):
            raise ValueError(f'{self.url} is not a TIFF file')
        offset = struct.unpack(bo + ('Q' if big else 'I'), head[8:16] if big else head[4:8])[0]
        levels: list[Level] = []
        scale = origin = (0.0, 0.0)
        while offset:
            n = struct.unpack(bo + ('Q' if big else 'H'), self._bytes(offset, 8 if big else 2))[0]
            size, base = (20, offset + 8) if big else (12, offset + 2)
            entries = self._bytes(base, size * n + (8 if big else 4))
            tags: dict[int, list[float]] = {}
            for i in range(n):
                e = entries[size * i : size * (i + 1)]
                tag, typ = struct.unpack(bo + 'HH', e[:4])
                count = struct.unpack(bo + ('Q' if big else 'I'), e[4:12] if big else e[4:8])[0]
                if typ not in _TYPE_FMT:
                    continue
                inline = e[12:20] if big else e[8:12]
                nbytes = _TYPE_SIZE[typ] * count
                if nbytes <= len(inline):
                    raw = inline[:nbytes]
                else:
                    pointer = struct.unpack(bo + ('Q' if big else 'I'), inline)[0]
                    raw = self._bytes(pointer, nbytes)
                tags[tag] = list(struct.unpack(f'{bo}{count}{_TYPE_FMT[typ]}', raw))
            offset = struct.unpack(bo + ('Q' if big else 'I'), entries[size * n :])[0]
            if 322 not in tags:
                continue  # stripped layout: not supported
            bits = int(tags.get(258, [8])[0])
            if bits == 1:
                continue  # a transparency mask, not data
            if not levels and 33550 in tags and 33922 in tags:
                scale = (tags[33550][0], tags[33550][1])
                origin = (tags[33922][3], tags[33922][4])
            levels.append(
                Level(
                    width=int(tags[256][0]),
                    height=int(tags[257][0]),
                    tile_width=int(tags[322][0]),
                    tile_height=int(tags[323][0]),
                    offsets=[int(v) for v in tags[324]],
                    counts=[int(v) for v in tags[325]],
                    bits=bits,
                    sample_format=int(tags.get(339, [1])[0]),
                    compression=int(tags.get(259, [1])[0]),
                    predictor=int(tags.get(317, [1])[0]),
                )
            )
        if not levels:
            raise ValueError(f'{self.url} has no tiled image Ìlú can read')
        for lv in levels:
            if lv.compression not in (1, 8) or (lv.bits, lv.sample_format) not in ((8, 1), (32, 3)):
                raise ValueError(f'{self.url}: unsupported TIFF encoding')
        return levels, scale, origin

    # ------------------------------------------------------------ pixels

    def tile(self, level: int, tx: int, ty: int) -> array[float] | None:
        """One decoded tile as a flat array, row by row, or None where the file has no data."""
        lv = self.levels[level]
        if tx < 0 or ty < 0 or tx >= lv.tiles_across or ty >= math.ceil(lv.height / lv.tile_height):
            return None
        i = ty * lv.tiles_across + tx
        if lv.counts[i] == 0:
            return None
        raw = self._cached(f'{level}-{tx}-{ty}', lv.offsets[i], lv.counts[i])
        return decode_tile(raw, lv)

    def window(self, level: int, x0: int, y0: int, width: int, height: int, fill: float = 0.0) -> list[list[float]]:
        """Pixels [y0, y0 + height) x [x0, x0 + width) at a level, as rows. Outside the image is `fill`."""
        lv = self.levels[level]
        tw, th = lv.tile_width, lv.tile_height
        rows = [[fill] * width for _ in range(height)]
        for ty in range(y0 // th, (y0 + height - 1) // th + 1):
            for tx in range(x0 // tw, (x0 + width - 1) // tw + 1):
                pixels = self.tile(level, tx, ty)
                if pixels is None:
                    continue
                # Edge tiles are padded past the image; that padding is not data.
                for py in range(max(y0, ty * th), min(y0 + height, (ty + 1) * th, lv.height)):
                    src = (py - ty * th) * tw
                    a, b = max(x0, tx * tw), min(x0 + width, (tx + 1) * tw, lv.width)
                    rows[py - y0][a - x0 : b - x0] = pixels[src + a - tx * tw : src + b - tx * tw]
        return rows

    def level_scale(self, level: int) -> tuple[float, float]:
        """Size of one pixel at a level, in the file's units."""
        full, lv = self.levels[0], self.levels[level]
        return self.scale[0] * full.width / lv.width, self.scale[1] * full.height / lv.height


def _undo_differencing(row: bytes) -> bytes:
    """Running sum of a row of bytes, modulo 256."""
    return bytes(v & 0xFF for v in itertools.accumulate(row))


def decode_tile(raw: bytes, lv: Level) -> array[float]:
    """Decompress one tile and undo its predictor."""
    data = zlib.decompress(raw) if lv.compression == 8 else raw
    tw, th = lv.tile_width, lv.tile_height
    if lv.bits == 8:
        if lv.predictor == 2:
            data = b''.join(_undo_differencing(data[y * tw : (y + 1) * tw]) for y in range(th))
        return array('f', list(data))  # array('f', bytes) would read the bytes as raw floats
    stride = tw * 4
    if lv.predictor == 3:
        # Floating-point predictor: each row's bytes were split into four planes,
        # most significant byte first, then differenced along the row.
        out = bytearray(len(data))
        for y in range(th):
            row = _undo_differencing(data[y * stride : (y + 1) * stride])
            dest = memoryview(out)[y * stride : (y + 1) * stride]
            for plane in range(4):  # little-endian floats: least significant byte first
                dest[plane::4] = row[(3 - plane) * tw : (4 - plane) * tw]
        data = bytes(out)
    values = array('f')
    values.frombytes(data)
    if sys.byteorder == 'big':
        values.byteswap()
    if lv.predictor == 2:
        values = array('f', (v for y in range(th) for v in itertools.accumulate(values[y * tw : (y + 1) * tw])))
    return values
