"""Resolve the two endpoints (start/finish) to coordinates.

Accepts either:
  - "lat,lng" -> parsed directly, zero external calls; or
  - a place name -> resolved once, cached. We try the bundled offline city
    table first ("City, ST"); only if that misses do we fall back to
    Nominatim (free, no key).

Endpoint geocoding is a separate concern from station geocoding: it's at most
two calls per request (usually zero, thanks to the cache), which sits inside
the "two or three external calls is acceptable" ceiling. Stations are never
geocoded at request time.
"""

import re
from functools import lru_cache

import requests
from django.conf import settings

from routing.services import cities


class ResolveError(Exception):
    """The start/finish value could not be turned into coordinates."""


_LATLNG_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$"
)


def resolve(value: str):
    """Return (lat, lng) for a start/finish string."""
    if not value or not value.strip():
        raise ResolveError("Missing start/finish value.")
    value = value.strip()

    m = _LATLNG_RE.match(value)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ResolveError(f"Coordinates out of range: {value!r}")
        return lat, lng

    # "City, ST" -> try the offline table before any network call.
    if "," in value:
        city, _, tail = value.rpartition(",")
        state = tail.strip()
        if len(state) == 2 and state.isalpha():
            coord = cities.lookup(city.strip(), state)
            if coord is not None:
                return coord

    return _nominatim(value)


@lru_cache(maxsize=256)
def _nominatim(query: str):
    try:
        resp = requests.get(
            settings.NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us,ca"},
            headers={"User-Agent": settings.GEOCODER_USER_AGENT},
            timeout=settings.EXTERNAL_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as exc:
        raise ResolveError(f"Geocoding service unavailable: {exc}") from exc

    if not results:
        raise ResolveError(f"Could not geocode location: {query!r}")
    return float(results[0]["lat"]), float(results[0]["lon"])
