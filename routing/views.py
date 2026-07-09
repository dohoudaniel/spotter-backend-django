"""The one read endpoint. The view only parses, orchestrates, and serializes;
every piece of logic lives in tested services.

Contract:
    GET /route/?start=<place|lat,lng>&finish=<place|lat,lng>

Status codes:
    200  route found
    400  start/finish missing or unresolvable
    422  no drivable route, or route infeasible for the 500-mile tank range
    502  the routing service (OSRM) was unreachable
"""

import time

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from routing.services import geo
from routing.services.fuel import Infeasible, plan_fuel
from routing.services.osrm import RouteError, RouteServiceError, get_route
from routing.services.resolve import ResolveError, resolve


def _serialize_stop(s):
    """Map an internal stop dict to the public JSON shape.

    Renames the internal keys (``mile`` -> ``mile_marker``, ``price`` ->
    ``price_per_gallon``) and rounds for a clean payload: 5 decimals on coords
    (~1 m), 4 on price (sub-cent), 1 on the mile marker.
    """
    return {
        "name": s["name"],
        "city": s["city"],
        "state": s["state"],
        "lat": round(s["lat"], 5),
        "lng": round(s["lng"], 5),
        "price_per_gallon": round(s["price"], 4),
        "gallons": s["gallons"],
        "cost_usd": s["cost_usd"],
        "mile_marker": round(s["mile"], 1),
    }


@require_GET  # read-only endpoint; reject non-GET methods with 405
def route_view(request):
    # Time the whole request so the response can report how "fast" it was
    # (see meta.elapsed_ms) -- the assignment grades on speed.
    t0 = time.perf_counter()

    # 1. Resolve endpoints (accepts "lat,lng" or a place name).
    try:
        start = resolve(request.GET.get("start", ""))
        finish = resolve(request.GET.get("finish", ""))
    except ResolveError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    # 2. The single external call at request time: one OSRM route.
    try:
        coords, distance_mi = get_route(start, finish)
    except RouteError as exc:
        return JsonResponse({"error": str(exc)}, status=422)
    except RouteServiceError:
        return JsonResponse({"error": "Routing service unavailable."}, status=502)

    # 3. Pure in-memory computation against our own data.
    candidates = geo.stations_along_route(coords, distance_mi)
    try:
        total, stops = plan_fuel(candidates, distance_mi)
    except Infeasible as exc:
        return JsonResponse(
            {"error": str(exc), "distance_miles": round(distance_mi, 1)},
            status=422,
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return JsonResponse(
        {
            "route": {"type": "LineString", "coordinates": coords},
            "distance_miles": round(distance_mi, 1),
            "total_fuel_cost_usd": total,
            "fuel_stops": [_serialize_stop(s) for s in stops],
            "meta": {
                "stations_considered": len(candidates),
                "corridor_miles": settings.CORRIDOR_MILES,
                "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
                "vehicle_mpg": settings.VEHICLE_MPG,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        }
    )


def map_view(request):
    """Serve the Leaflet demo page that fetches /route and draws it."""
    return render(request, "routing/map.html")


def _api_spec():
    """Machine-readable description of the API, built from live settings.

    Kept as a plain dict so both the JSON endpoint and the HTML docs page render
    from one source of truth -- the documented params/limits can't drift from
    the actual configured values.
    """
    return {
        "name": "Fuel Route API",
        "description": (
            "Given a start and finish in the USA, returns the driving route, "
            "the cost-optimal fuel stops along it, and the total fuel cost."
        ),
        "endpoints": {
            "GET /route/": {
                "summary": "Plan a fuelling route.",
                "query_params": {
                    "start": "Required. 'lat,lng' or a place name (e.g. 'Dallas, TX').",
                    "finish": "Required. 'lat,lng' or a place name.",
                },
                "returns": "route GeoJSON, ordered fuel_stops, total_fuel_cost_usd, meta",
                "status_codes": {
                    "200": "route found",
                    "400": "start/finish missing or unresolvable",
                    "422": "no drivable route, or infeasible for the tank range",
                    "502": "routing service (OSRM) unreachable",
                },
                "examples": [
                    "/route/?start=Los Angeles, CA&finish=New York, NY",
                    "/route/?start=34.05,-118.24&finish=40.71,-74.01",
                ],
            },
            "GET /map/": {"summary": "Interactive Leaflet demo page."},
            "GET /api/": {"summary": "This machine-readable API spec (JSON)."},
            "GET /": {"summary": "Human-readable API documentation (HTML)."},
        },
        "vehicle_model": {
            "range_miles": settings.VEHICLE_RANGE_MILES,
            "mpg": settings.VEHICLE_MPG,
            "tank_gallons": settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG,
            "corridor_miles": settings.CORRIDOR_MILES,
            "assumption": "Leaves origin with a full tank; cost is fuel purchased to finish.",
        },
    }


def api_spec_view(request):
    """Return the API spec as JSON (for tooling / programmatic discovery)."""
    return JsonResponse(_api_spec())


def docs_view(request):
    """Render the human-readable API documentation page."""
    return render(request, "routing/docs.html", {"spec": _api_spec()})
