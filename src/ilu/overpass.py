"""Download OpenStreetMap data from the public Overpass API, with a local cache."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import __version__
from .osm import DRIVABLE, PATH_WIDTH

MIRRORS = (
    'https://overpass-api.de/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
)

BBox = tuple[float, float, float, float]  # south, west, north, east


def _escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def query(place: str | None = None, bbox: BBox | None = None) -> str:
    """The Overpass QL for one place (by its exact OSM name) or one bounding box."""
    if (place is None) == (bbox is None):
        raise ValueError('give exactly one of place or bbox')
    if place is not None:
        head = f'area["name"="{_escape(place)}"]->.a;\n'
        scope = '(area.a)'
    else:
        s, w, n, e = bbox  # type: ignore[misc]
        if not (-90 <= s < n <= 90 and -180 <= w < e <= 180):
            raise ValueError('bbox must be south,west,north,east with south < north and west < east')
        head = ''
        scope = f'({s},{w},{n},{e})'
    roads = '|'.join(DRIVABLE)
    paths = '|'.join(PATH_WIDTH)
    return (
        '[out:json][timeout:180];\n' + head + '(\n'
        f'  way{scope}["highway"~"^({roads}|{paths})$"];\n'
        f'  way{scope}["building"];\n'
        f'  way{scope}["building:part"];\n'
        f'  nwr{scope}["man_made"~"^(minaret|tower)$"];\n'
        f'  nwr{scope}["name"];\n'
        f'  way{scope}["natural"~"^(water|wood)$"];\n'
        f'  way{scope}["landuse"~"^(forest|grass|meadow|reservoir|cemetery|recreation_ground|village_green)$"];\n'
        f'  way{scope}["leisure"~"^(pitch|track|swimming_pool|park|garden)$"];\n'
        f'  way{scope}["amenity"~"^(parking|grave_yard)$"];\n'
        f'  node{scope}["natural"="tree"];\n'
        f'  node{scope}["highway"="street_lamp"];\n'
        f'  way{scope}["barrier"~"^(wall|city_wall|retaining_wall|fence|hedge)$"];\n'
        f'  rel{scope}["type"="multipolygon"]["building"];\n'
        f'  rel{scope}["type"="multipolygon"]["building:part"];\n'
        f'  rel{scope}["type"="multipolygon"]["natural"~"^(water|wood)$"];\n'
        f'  rel{scope}["type"="multipolygon"]["water"];\n'
        f'  rel{scope}["type"="multipolygon"]["landuse"~"^(forest|grass|meadow|reservoir|cemetery)$"];\n'
        f'  rel{scope}["type"="multipolygon"]["leisure"~"^(pitch|park|garden)$"];\n'
        f'  rel{scope}["type"="multipolygon"]["amenity"="parking"];\n'
        ');\nout body geom;'
    )


def response_elements(doc: Any) -> list[dict[str, Any]]:
    """The `elements` list of an Overpass response, or a clear error."""
    items = doc.get('elements') if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise RuntimeError('unexpected Overpass response (no elements list)')
    if not items and isinstance(doc, dict) and doc.get('remark'):
        raise RuntimeError(f'Overpass: {doc["remark"]}')
    return items


CERT_HELP = (
    'HTTPS certificates could not be verified. On macOS with Python from python.org, run '
    '"Install Certificates.command" in your Python folder, or set SSL_CERT_FILE.'
)


def cache_dir() -> str:
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'ilu')


def servers() -> tuple[str, ...]:
    """The Overpass servers to use: `ILU_OVERPASS_URL` (comma-separated) if set, else the public ones."""
    custom = os.environ.get('ILU_OVERPASS_URL', '').strip()
    return tuple(u.strip() for u in custom.split(',') if u.strip()) if custom else MIRRORS


def _retry_after(err: urllib.error.HTTPError) -> float | None:
    value = err.headers.get('Retry-After') if err.headers else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def fetch(
    q: str,
    refresh: bool = False,
    cache: str | None = None,
    tries: int = 6,
    urls: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Run an Overpass query and return its elements. Results are cached by query.

    Public Overpass servers are shared and get busy. A busy server (429),
    a gateway error (502, 503, 504), a query that ran out of time, or a
    broken reply is retried on the next server, waiting as long as the
    server asks (`Retry-After`) or a little longer each time. A query the
    server rejects as malformed (400) is not retried.
    """
    folder = cache or cache_dir()
    path = os.path.join(folder, hashlib.sha256(q.encode()).hexdigest()[:16] + '.json')
    if os.path.exists(path) and not refresh:
        with open(path, encoding='utf-8') as f:
            return response_elements(json.load(f))
    pool = urls or servers()
    body = urllib.parse.urlencode({'data': q}).encode()
    reasons: list[str] = []
    for attempt in range(tries):
        url = pool[attempt % len(pool)]
        host = urllib.parse.urlparse(url).netloc
        print(f'Downloading from {host} (try {attempt + 1} of {tries})...', file=sys.stderr)
        wait = 4.0 * (attempt + 1)
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'User-Agent': f'ilu/{__version__} (OpenStreetMap to 3D)',
                },
            )
            with urllib.request.urlopen(req, timeout=240) as res:
                text = res.read().decode('utf-8')
            items = response_elements(json.loads(text))
        except urllib.error.HTTPError as err:
            err.close()
            if err.code == 400:
                raise RuntimeError(f'{host} rejected the query (400 Bad Request); check the place name') from err
            busy = {429: 'too busy', 502: 'gateway error', 503: 'unavailable', 504: 'timed out'}
            reasons.append(f'{host}: {busy.get(err.code, f"HTTP {err.code}")}')
            wait = _retry_after(err) or wait
        except (json.JSONDecodeError, UnicodeDecodeError):
            reasons.append(f'{host}: sent a reply that is not map data')
        except RuntimeError as err:  # a reply with no elements, such as a query that ran out of time
            reasons.append(f'{host}: {err}')
        except Exception as err:
            if isinstance(getattr(err, 'reason', err), ssl.SSLCertVerificationError):
                raise RuntimeError(CERT_HELP) from err
            reasons.append(f'{host}: {err}')
        else:
            os.makedirs(folder, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            return items
        print(f'  {reasons[-1]}', file=sys.stderr)
        if attempt < tries - 1:
            time.sleep(min(wait, 60.0))
    raise RuntimeError(
        f'every Overpass server was busy or unreachable after {tries} tries ({"; ".join(reasons[-3:])}). '
        'The public servers are shared by everyone; wait a few minutes and run again, '
        'or point ILU_OVERPASS_URL (or --overpass-url) at your own server.'
    )
