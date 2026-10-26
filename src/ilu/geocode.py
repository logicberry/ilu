"""Find places by name with OpenStreetMap's Nominatim search, for `ilu find` and `ilu build --near`.

The public Nominatim service has a usage policy
(https://operations.osmfoundation.org/policies/nominatim/): searches must be
triggered by a person, at most one a second, with an identifying
User-Agent, and results cached. Ìlú searches once per command (twice if
the first finds nothing), caches every answer on disk and never searches
in loops. Point `ILU_NOMINATIM_URL`
at your own Nominatim server for heavier use.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import __version__
from .overpass import CERT_HELP, cache_dir

PUBLIC_URL = 'https://nominatim.openstreetmap.org/search'
CREDIT = 'Search: Nominatim, (c) OpenStreetMap contributors, ODbL'
_last_request = 0.0


@dataclass(frozen=True)
class Match:
    """One search result."""

    name: str
    lat: float
    lon: float
    kind: str  # OSM class and type, such as "amenity/place_of_worship"

    def bbox(self, radius: float) -> tuple[float, float, float, float]:
        """A box `radius` metres each way round the place: (south, west, north, east)."""
        dlat = radius / 111320
        dlon = radius / (111320 * max(math.cos(math.radians(self.lat)), 0.01))
        return (
            round(self.lat - dlat, 5),
            round(self.lon - dlon, 5),
            round(self.lat + dlat, 5),
            round(self.lon + dlon, 5),
        )


def endpoint() -> str:
    return os.environ.get('ILU_NOMINATIM_URL', '').strip() or PUBLIC_URL


def search(query: str, limit: int = 5, refresh: bool = False) -> list[Match]:
    """Places matching `query`, best first. Answers are cached on disk."""
    query = query.strip()
    if not query:
        raise ValueError('give a place to search for')
    url = endpoint() + '?' + urllib.parse.urlencode({'format': 'jsonv2', 'limit': limit, 'q': query})
    path = os.path.join(cache_dir(), 'search', hashlib.sha256(url.encode()).hexdigest()[:16] + '.json')
    if os.path.exists(path) and not refresh:
        with open(path, encoding='utf-8') as f:
            rows = json.load(f)
    else:
        rows = _get(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(rows, f)
    return [
        Match(
            name=str(r.get('display_name', '')),
            lat=float(r['lat']),
            lon=float(r['lon']),
            kind=f'{r.get("category") or r.get("class", "")}/{r.get("type", "")}',
        )
        for r in rows
        if 'lat' in r and 'lon' in r
    ]


def find(query: str, limit: int = 5, refresh: bool = False) -> list[Match]:
    """Like `search`, but if nothing matches, try once more without apostrophes.

    Names are often typed with a different apostrophe from the map, or a
    garbled one, so "St. Mary's Church" is retried as "St. Mary Church".
    """
    matches = search(query, limit, refresh)
    looser = re.sub(r'\s+', ' ', re.sub(r"['\u2019`]s?\b", '', query)).strip()
    if not matches and looser and looser != query.strip():
        matches = search(looser, limit, refresh)
    return matches


def _get(url: str) -> list[dict[str, Any]]:
    global _last_request
    wait = 1.0 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)  # at most one request a second, as the policy asks
    _last_request = time.monotonic()
    req = urllib.request.Request(url, headers={'User-Agent': f'ilu/{__version__} (OpenStreetMap to 3D; command line)'})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            rows = json.loads(res.read().decode('utf-8'))
    except urllib.error.HTTPError as err:
        err.close()
        raise RuntimeError(f'place search failed (HTTP {err.code}); try again in a minute') from err
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
        if isinstance(getattr(err, 'reason', None), ssl.SSLCertVerificationError):
            raise RuntimeError(CERT_HELP) from err
        raise RuntimeError(f'place search failed ({err}); check your connection') from err
    if not isinstance(rows, list):
        raise RuntimeError('place search returned an unexpected reply')
    return rows
