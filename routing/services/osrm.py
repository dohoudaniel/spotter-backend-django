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

    ``coords`` is the FULL polyline as a list of [lon, lat] pairs (GeoJSON
    order); ``distance_miles`` is OSRM's authoritative total distance.

    We always fetch full geometry so corridor matching is accurate and the fuel
    result is stable. Trimming the geometry for a smaller client payload is a
    separate, display-only concern handled in the view -- it must never change
    the computed answer.
    """
    (slat, slng), (flat, flng) = start, finish
    # Round to ~11 m so trivially-different demo requests share a cache entry.
    return _get_route_cached(
        round(slat, 4), round(slng, 4), round(flat, 4), round(flng, 4)
    )


# OSRM status codes that mean "the request was understood but no route exists"
# (a client-side / geography problem, not a service outage). These map to 422.
_NO_ROUTE_CODES = {"NoRoute", "NoSegment", "NoTrips"}


@lru_cache(maxsize=256)
def _get_route_cached(slat, slng, flat, flng):
    url = f"{settings.OSRM_BASE_URL}/{slng},{slat};{flng},{flat}"  # lon,lat order
    # Note: OSRM returns HTTP 400 (not 200) for an unroutable pair, with a JSON
    # body like {"code": "NoRoute"}. So we do NOT raise_for_status blindly --
    # we parse the body and branch on OSRM's own status code, to tell "no route"
    # (422) apart from a genuine service failure (502).
    try:
        resp = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson"},
            timeout=settings.EXTERNAL_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RouteServiceError(str(exc)) from exc

    try:
        data = resp.json()
    except ValueError as exc:  # 5xx / HTML error page, not JSON
        raise RouteServiceError(
            f"Routing service returned non-JSON (HTTP {resp.status_code})."
        ) from exc

    code = data.get("code")
    if code == "Ok" and data.get("routes"):
        route = data["routes"][0]
        coords = route["geometry"]["coordinates"]      # [[lon, lat], ...]
        distance_miles = route["distance"] * M_TO_MI   # OSRM returns meters
        return coords, distance_miles

    if code in _NO_ROUTE_CODES:
        raise RouteError(
            data.get("message", "No route found between the given locations.")
        )

    # Anything else (server error, unexpected code) is a service-side problem.
    raise RouteServiceError(f"Routing service error (code={code!r}).")
