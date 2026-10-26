"""Minimal 8-bit PNG decoding and encoding, using only the standard library."""

from __future__ import annotations

import struct
import zlib


def decode_png(data: bytes) -> tuple[int, int, int, bytes]:
    """Decode an 8-bit, non-interlaced greyscale, RGB or RGBA PNG. Returns (width, height, channels, pixels)."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG file')
    pos, idat = 8, bytearray()
    width = height = channels = 0
    while pos < len(data):
        length, kind = struct.unpack_from('>I4s', data, pos)
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b'IHDR':
            width, height, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', body)
            channels = {0: 1, 2: 3, 6: 4}.get(colour, 0)
            if depth != 8 or not channels or interlace:
                raise ValueError('unsupported PNG format')
        elif kind == b'IDAT':
            idat += body
        elif kind == b'IEND':
            break
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        filt = raw[src]
        line = bytearray(raw[src + 1 : src + 1 + stride])
        src += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = prev[i]
            if filt == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filt == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filt == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif filt == 4:
                ul = prev[i - channels] if i >= channels else 0
                p = left + up - ul
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else ul)) & 0xFF
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, channels, bytes(out)


def encode_png(width: int, height: int, channels: int, pixels: bytes) -> bytes:
    """Encode 8-bit pixels (greyscale, RGB or RGBA) as a PNG."""
    colour = {1: 0, 3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b''.join(b'\x00' + pixels[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')
