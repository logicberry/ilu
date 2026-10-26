"""Write meshes to a binary glTF 2.0 (.glb) file."""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from typing import Any

from . import __version__, facade
from .mesh import Mesh

CREDIT = 'Map data (c) OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)'

_FLOAT, _UBYTE, _UINT = 5126, 5121, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963
_LINEAR, _LINEAR_MIPMAP_LINEAR, _REPEAT = 9729, 9987, 10497

MATTE, FACADE = 0, 1  # material indices for Mesh.material
_PBR = {'metallicFactor': 0, 'roughnessFactor': 0.92}


def to_bytes(
    meshes: Sequence[Mesh], extras: dict[str, Any] | None = None, credit: str = CREDIT, unlit: bool = False
) -> bytes:
    """One node per non-empty mesh.

    Colour comes from vertex colours. Meshes with material FACADE also carry
    UVs and multiply in the facade texture, which is embedded in the file.
    With `unlit`, every material uses KHR_materials_unlit, for colours that
    already include baked lighting.
    """
    bin_ = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    gl_meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    def add(
        rows: Sequence[Any],
        fmt: str,
        comps: int,
        kind: str,
        target: int,
        minmax: bool = False,
        ctype: int = _FLOAT,
        normalized: bool = False,
    ) -> int:
        bin_.extend(b'\0' * (-len(bin_) % 4))
        start = len(bin_)
        flat = [v for row in rows for v in (row if isinstance(row, tuple) else (row,))]
        bin_.extend(struct.pack(f'<{len(flat)}{fmt}', *flat))
        views.append({'buffer': 0, 'byteOffset': start, 'byteLength': len(bin_) - start, 'target': target})
        acc: dict[str, Any] = {'bufferView': len(views) - 1, 'componentType': ctype, 'count': len(rows), 'type': kind}
        if normalized:
            acc['normalized'] = True
        if minmax:
            acc['min'] = [min(r[i] for r in rows) for i in range(comps)]
            acc['max'] = [max(r[i] for r in rows) for i in range(comps)]
        accessors.append(acc)
        return len(accessors) - 1

    used: set[int] = set()
    for m in meshes:
        if not m.idx:
            continue
        attrs = {
            'POSITION': add(m.pos, 'f', 3, 'VEC3', _ARRAY_BUFFER, minmax=True),
            'NORMAL': add(m.nor, 'f', 3, 'VEC3', _ARRAY_BUFFER),
            # Colours as normalised bytes: a quarter of the size of floats.
            'COLOR_0': add(
                [tuple(min(255, max(0, round(v * 255))) for v in c) for c in m.col],
                'B',
                4,
                'VEC4',
                _ARRAY_BUFFER,
                ctype=_UBYTE,
                normalized=True,
            ),
        }
        if m.uv is not None:
            attrs['TEXCOORD_0'] = add(m.uv, 'f', 2, 'VEC2', _ARRAY_BUFFER)
        material = FACADE if m.material == FACADE and m.uv is not None else MATTE
        used.add(material)
        indices = add(m.idx, 'I', 1, 'SCALAR', _ELEMENT_ARRAY_BUFFER, ctype=_UINT)
        gl_meshes.append(
            {'name': m.name, 'primitives': [{'attributes': attrs, 'indices': indices, 'material': material}]}
        )
        nodes.append({'name': m.name, 'mesh': len(gl_meshes) - 1})

    doc: dict[str, Any] = {
        'asset': {'version': '2.0', 'generator': f'ilu {__version__}', 'copyright': credit},
        'scene': 0,
        'scenes': [{'nodes': list(range(len(nodes)))}],
        'nodes': nodes,
        'meshes': gl_meshes,
        'materials': [{'name': 'matte', 'pbrMetallicRoughness': dict(_PBR)}],
        'accessors': accessors,
        'bufferViews': views,
        'buffers': [{'byteLength': len(bin_)}],
    }
    if FACADE in used:
        bin_.extend(b'\0' * (-len(bin_) % 4))
        image = facade.png()
        views.append({'buffer': 0, 'byteOffset': len(bin_), 'byteLength': len(image)})
        bin_.extend(image)
        doc['bufferViews'] = views
        doc['buffers'] = [{'byteLength': len(bin_)}]
        doc['images'] = [{'bufferView': len(views) - 1, 'mimeType': 'image/png'}]
        doc['samplers'] = [
            {'magFilter': _LINEAR, 'minFilter': _LINEAR_MIPMAP_LINEAR, 'wrapS': _REPEAT, 'wrapT': _REPEAT}
        ]
        doc['textures'] = [{'sampler': 0, 'source': 0}]
        doc['materials'].append({'name': 'facade', 'pbrMetallicRoughness': {**_PBR, 'baseColorTexture': {'index': 0}}})
    if unlit:
        # Lighting is baked into the vertex colours: ask engines not to light it again.
        for material in doc['materials']:
            material['extensions'] = {'KHR_materials_unlit': {}}
        doc['extensionsUsed'] = ['KHR_materials_unlit']
    if extras:
        doc['extras'] = extras
    j = json.dumps(doc, separators=(',', ':')).encode()
    j += b' ' * (-len(j) % 4)
    bin_.extend(b'\0' * (-len(bin_) % 4))
    return (
        struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(j) + 8 + len(bin_))
        + struct.pack('<I4s', len(j), b'JSON')
        + j
        + struct.pack('<I4s', len(bin_), b'BIN\x00')
        + bytes(bin_)
    )


def read_json(data: bytes) -> dict[str, Any]:
    """The JSON chunk of a .glb, for checks and tests."""
    magic, version, total = struct.unpack_from('<4sII', data, 0)
    if magic != b'glTF' or version != 2 or total != len(data):
        raise ValueError('not a glTF 2.0 binary')
    length, kind = struct.unpack_from('<I4s', data, 12)
    if kind != b'JSON':
        raise ValueError('first chunk is not JSON')
    doc = json.loads(data[20 : 20 + length])
    if not isinstance(doc, dict):
        raise ValueError('glTF JSON chunk is not an object')
    return doc
