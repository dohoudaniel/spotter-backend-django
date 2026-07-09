"""The single external call in the request path: one OSRM route request.

OSRM's public server returns full geometry + total distance for one GET, no
API key. Three things that bite people, all handled here:
  - coordinates go in lon,lat order (not lat,lng);
  - distance comes back in meters;
  - the public box is rate-limited demo infra -> in production you self-host
    it via the official Docker image. We cache identical requests so repeated
    demo calls don't re-hit it.
"""

from functools import lru_cache

import requests
from django.conf import settings

M_TO_MI = 0.000621371


class RouteError(Exception):
    """OSRM could not return a route (no path, bad input)."""


class RouteServiceError(Exception):
    """OSRM was unreachable or misbehaved (network/5xx)."""


def get_route(start, finish):
    """Return (coords, distance_miles) for start/finish, each (lat, lng).

    ``coords`` is the polyline as a list of [lon, lat] pairs (GeoJSON order).
    ``distance_miles`` is OSRM's authoritative total distance.
    """
    (slat, slng), (flat, flng) = start, finish
    # Round to ~11 m so trivially-different demo requests share a cache entry.
    return _get_route_cached(
        round(slat, 4), round(slng, 4), round(flat, 4), round(flng, 4)
    )


@lru_cache(maxsize=256)
def _get_route_cached(slat, slng, flat, flng):
    url = f"{settings.OSRM_BASE_URL}/{slng},{slat};{flng},{flat}"  # lon,lat order
    try:
        resp = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson"},
            timeout=settings.EXTERNAL_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RouteServiceError(str(exc)) from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteError("No route found between the given locations.")

    route = data["routes"][0]
    coords = route["geometry"]["coordinates"]      # [[lon, lat], ...]
    distance_miles = route["distance"] * M_TO_MI   # OSRM returns meters
    return coords, distance_miles
