"""Corridor filter + projection, done in NumPy in memory.

Given the OSRM polyline, find the stations within ``CORRIDOR_MILES`` of it and
compute each one's distance-along-route ("mile marker") so the optimizer can
order them and measure leg gaps. This is pure in-memory computation over a few
thousand stations and a few hundred segments -> a few million float ops,
sub-millisecond. No PostGIS, no per-request DB spatial query.

All stations load into module-level arrays once (``_STATIONS``) and are reused
across requests, so the request path never queries the DB per call.
"""

import numpy as np
from django.conf import settings

from routing.models import FuelStation

_STATIONS = None

# Cap on polyline vertices used for corridor matching (see stations_along_route).
MAX_MATCH_VERTICES = 2000


def load_stations(force=False):
    """Load all stations into NumPy arrays once; reuse across requests."""
    global _STATIONS
    if _STATIONS is not None and not force:
        return _STATIONS
    qs = FuelStation.objects.all().values_list(
        "lat", "lng", "price", "name", "city", "state"
    )
    rows = list(qs)
    _STATIONS = {
        "lat": np.array([r[0] for r in rows], dtype=float),
        "lng": np.array([r[1] for r in rows], dtype=float),
        "price": np.array([r[2] for r in rows], dtype=float),
        "meta": [{"name": r[3], "city": r[4], "state": r[5]} for r in rows],
    }
    return _STATIONS


def clear_cache():
    """Drop the in-memory station cache (used by tests after loading data)."""
    global _STATIONS
    _STATIONS = None


def _to_xy(lat, lng, lat0, lng0):
    """Equirectangular projection to miles around (lat0, lng0).

    Accurate at these scales and far cheaper than great-circle math for the
    point-to-segment distances.
    """
    x = (lng - lng0) * np.cos(np.radians(lat0)) * 69.172
    y = (lat - lat0) * 69.0
    return x, y


def stations_along_route(coords, total_distance_mi, corridor_mi=None):
    """Return stations within the corridor, ordered by mile marker.

    ``coords`` is the OSRM polyline as [[lon, lat], ...]. Each returned dict has
    name/city/state/lat/lng/price plus ``mile`` (distance from start along the
    route). ``total_distance_mi`` is OSRM's authoritative distance; the
    polyline's cumulative length is scaled to match it so leg checks are exact.
    """
    if corridor_mi is None:
        corridor_mi = settings.CORRIDOR_MILES

    poly = np.asarray(coords, dtype=float)
    if poly.shape[0] < 2:
        return []
    plng, plat = poly[:, 0], poly[:, 1]
    lat0, lng0 = plat.mean(), plng.mean()

    # Polyline vertices in local planar miles, and cumulative distance scaled
    # so the last value equals OSRM's reported total distance.
    px, py = _to_xy(plat, plng, lat0, lng0)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(px), np.diff(py)))])
    if cum[-1] > 0:
        cum *= total_distance_mi / cum[-1]

    # overview=full can return tens of thousands of vertices. For corridor
    # matching that resolution is wasted against a miles-wide corridor, and it
    # dominates runtime. Downsample to at most MAX_MATCH_VERTICES (keeping the
    # endpoints); retained vertices keep their true along-route mileage, so
    # mile markers stay accurate to roughly one vertex spacing (~1 mi).
    if px.size > MAX_MATCH_VERTICES:
        keep_v = np.linspace(0, px.size - 1, MAX_MATCH_VERTICES).round().astype(int)
        keep_v = np.unique(keep_v)
        px, py, cum = px[keep_v], py[keep_v], cum[keep_v]
    seg_len = np.diff(cum)  # segment lengths consistent with scaled cum

    S = load_stations()
    if S["lat"].size == 0:
        return []

    # Bounding-box prefilter: pad the route envelope by the corridor width
    # (deg latitude ~ 69 mi) and drop everything outside it instantly.
    pad = corridor_mi / 69.0
    m = (
        (S["lat"] >= plat.min() - pad)
        & (S["lat"] <= plat.max() + pad)
        & (S["lng"] >= plng.min() - pad)
        & (S["lng"] <= plng.max() + pad)
    )
    idx = np.where(m)[0]
    if idx.size == 0:
        return []

    sx, sy = _to_xy(S["lat"][idx], S["lng"][idx], lat0, lng0)

    # Point-to-segment distance from every candidate to the closest segment,
    # plus the along-route mileage at that projection point.
    #
    # We loop over CANDIDATES (a few hundred) and vectorize across all segments
    # at once. With overview=full the polyline can have tens of thousands of
    # segments, so looping segments in Python would be the bottleneck; looping
    # the smaller dimension keeps this in the millisecond range.
    ax, ay = px[:-1], py[:-1]  # segment starts
    abx, aby = np.diff(px), np.diff(py)
    l2 = abx * abx + aby * aby
    safe_l2 = np.where(l2 == 0.0, 1.0, l2)  # avoid /0 on zero-length segments

    best_d = np.empty(idx.size)
    best_mile = np.empty(idx.size)
    for i in range(idx.size):
        t = np.clip(((sx[i] - ax) * abx + (sy[i] - ay) * aby) / safe_l2, 0.0, 1.0)
        dx = sx[i] - (ax + t * abx)
        dy = sy[i] - (ay + t * aby)
        d = np.hypot(dx, dy)
        d[l2 == 0.0] = np.inf  # ignore degenerate segments
        k = int(np.argmin(d))
        best_d[i] = d[k]
        best_mile[i] = cum[k] + t[k] * seg_len[k]

    keep = np.where(best_d <= corridor_mi)[0]
    out = [
        {
            "mile": float(best_mile[j]),
            "price": float(S["price"][idx[j]]),
            "lat": float(S["lat"][idx[j]]),
            "lng": float(S["lng"][idx[j]]),
            **S["meta"][idx[j]],
        }
        for j in keep
    ]
    out.sort(key=lambda s: s["mile"])
    return out
