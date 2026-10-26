"""The generic facade texture: one window per bay per floor.

This is a stylised facade, not the real one: OpenStreetMap does not record
where windows are. Walls map it with u counting bays along the wall and v
counting floors up it, so windows line up with the building's floors.
"""

from __future__ import annotations

from functools import cache

from .png import encode_png

WIDTH, HEIGHT = 64, 128  # one bay (3 m) by one floor (3.2 m)
# Window, in metres within one bay and one floor.
WINDOW_LEFT, WINDOW_RIGHT = 0.75, 2.25
WINDOW_SILL, WINDOW_HEAD = 0.9, 2.3
BAY = 3.0  # metres per window bay along a wall
FLOOR = 3.2  # metres per storey


@cache
def png() -> bytes:
    """The texture as PNG bytes. White wall (tinted by vertex colour), dark glazing, a pale sill."""
    rows = []
    for row in range(HEIGHT):
        # glTF's v runs down the image, and walls set v = height / FLOOR,
        # so image row r shows the wall at height r / HEIGHT * FLOOR.
        y = (row + 0.5) / HEIGHT * FLOOR
        line = bytearray()
        for col in range(WIDTH):
            x = (col + 0.5) / WIDTH * BAY
            inside = WINDOW_LEFT <= x <= WINDOW_RIGHT
            if inside and WINDOW_SILL <= y <= WINDOW_HEAD:
                frame = min(x - WINDOW_LEFT, WINDOW_RIGHT - x, y - WINDOW_SILL, WINDOW_HEAD - y) < 0.06
                line += bytes((205, 205, 200) if frame else (58, 70, 84))
            elif inside and WINDOW_SILL - 0.08 <= y < WINDOW_SILL:
                line += bytes((228, 226, 220))
            else:
                line += bytes((255, 255, 255))
        rows.append(bytes(line))
    return encode_png(WIDTH, HEIGHT, 3, b''.join(rows))
