"""Corridor filter + projection, done in NumPy in memory.

Given the OSRM polyline, find the stations within ``CORRIDOR_MILES`` of it and
compute each one's distance-along-route ("mile marker") so the optimizer can
order them and measure leg gaps. A KD-tree over the route vertices narrows the
~6,600 stations to a small candidate set in O(log n) per station; the exact
point-to-segment test then runs only on those. All in memory -- no PostGIS, no
per-request DB spatial query.

All stations load into module-level arrays once (``_STATIONS``) and are reused
across requests, so the request path never queries the DB per call.
"""

import numpy as np
from django.conf import settings
from scipy.spatial import cKDTree

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

    # Project all stations into the same planar frame as the route.
    sxa, sya = _to_xy(S["lat"], S["lng"], lat0, lng0)

    # Spatial prefilter with a KD-tree over the route vertices. An axis-aligned
    # bounding box is nearly useless for a long diagonal route (its envelope
    # covers half the map), so most stations would survive it. The KD-tree
    # instead finds each station's nearest route vertex in O(log n) and lets us
    # keep only those that could possibly be within the corridor.
    #
    # Threshold: a station within `corridor_mi` of a segment's interior can be
    # up to one segment-length farther from the nearest vertex, so we pad by the
    # longest segment. This is a superset; the exact test below trims it.
    ax, ay = px[:-1], py[:-1]              # segment starts
    abx, aby = np.diff(px), np.diff(py)    # segment vectors
    l2 = abx * abx + aby * aby
    safe_l2 = np.where(l2 == 0.0, 1.0, l2)  # avoid /0 on zero-length segments

    tree = cKDTree(np.column_stack([px, py]))
    vert_dist, _ = tree.query(np.column_stack([sxa, sya]))
    prefilter = corridor_mi + (seg_len.max() if seg_len.size else 0.0)
    cand = np.where(vert_dist <= prefilter)[0]
    if cand.size == 0:
        return []

    # Exact point-to-segment distance for the narrowed candidate set against
    # every segment (small matrix now), tracking the closest segment and the
    # along-route mileage at the projection point.
    cx, cy = sxa[cand], sya[cand]
    dx0 = cx[:, None] - ax[None, :]        # (ncand, nseg)
    dy0 = cy[:, None] - ay[None, :]
    t = np.clip((dx0 * abx + dy0 * aby) / safe_l2, 0.0, 1.0)
    dist = np.hypot(dx0 - t * abx, dy0 - t * aby)
    dist[:, l2 == 0.0] = np.inf            # ignore degenerate segments

    nearest = np.argmin(dist, axis=1)      # closest segment per candidate
    rows = np.arange(cand.size)
    best_d = dist[rows, nearest]
    best_mile = cum[nearest] + t[rows, nearest] * seg_len[nearest]

    keep = np.where(best_d <= corridor_mi)[0]
    out = [
        {
            "mile": float(best_mile[j]),
            "price": float(S["price"][cand[j]]),
            "lat": float(S["lat"][cand[j]]),
            "lng": float(S["lng"][cand[j]]),
            **S["meta"][cand[j]],
        }
        for j in keep
    ]
    out.sort(key=lambda s: s["mile"])
    return out
