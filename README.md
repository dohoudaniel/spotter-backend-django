# Fuel Route API

A single Django read endpoint that, given a start and finish in the USA,
returns the driving route, the cost-optimal set of fuel stops along it, and the
total fuel cost — using one external routing call and no per-station API calls.

```
GET /route/?start=<place|lat,lng>&finish=<place|lat,lng>
```

Built for the Spotter Backend Django Engineer assessment. Django 6.0.7, Python
3.12+, SQLite. Dependencies: `django`, `numpy`, `requests`.

---

## The one idea that matters

The fuel CSV has **no coordinates** — only `City, State` and highway-exit
addresses like `I-44, EXIT 283 & US-69` that no geocoder can resolve. To know
which stations lie along a route you need coordinates, so the naive design
geocodes stations at request time: thousands of API calls per request, which
blows both the "fast" and "one routing call" constraints.

Instead:

- **Geocode once, offline, at import.** Every station is resolved to a
  city-centroid `(lat, lng)` by joining `(City, State)` against a bundled static
  dataset (`data/uscities.csv`, derived from the free GeoNames US dump). The
  import makes **zero** geocoding API calls.
- **At request time: exactly one external call**, to OSRM, for the route
  geometry and total distance.
- **Corridor matching and fuel optimization are pure in-memory NumPy/Python
  computation** over a few hundred stations — sub-second, no per-request DB
  spatial query, no PostGIS.

Total gallons burned is fixed by distance (`distance / mpg`). The optimization
is not *how much* you burn — it's *where you buy*, because prices differ per
station. That is the whole problem.

---

## Setup (one command per step)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py import_fuel_prices fuel-prices-for-be-assessment.csv
python manage.py runserver
```

Then hit the endpoint or open the map:

```bash
# Coast to coast — multiple fuel-ups
curl "http://127.0.0.1:8000/route/?start=Los%20Angeles,%20CA&finish=New%20York,%20NY"

# Raw coordinates also work (lat,lng)
curl "http://127.0.0.1:8000/route/?start=34.05,-118.24&finish=40.71,-74.01"
```

Visual demo (Leaflet + OSM, fetches the endpoint and draws the route + stops):
<http://127.0.0.1:8000/map/>

Run the tests:

```bash
python manage.py test routing
```

---

## Assumptions (decided and documented, per the deadline)

- **Starting tank.** You leave the origin with a **full tank** (500 mi of
  range). The reported cost is the fuel you *purchase* to complete the trip. A
  "pay for every mile" variant is a one-line change (charge the first
  `min(500, distance)` miles at the origin-nearest price).
- **Vehicle physics.** Range 500 mi, 10 mpg ⇒ 50-gallon tank. Every leg
  (origin→first stop, stop→stop, last stop→finish) must be ≤ 500 mi or the route
  is reported **infeasible** (HTTP 422), never silently wrong.
- **Geocoding granularity.** City/state centroid, not street address — the
  addresses are highway-exit strings and the route corridor is miles wide, so
  street precision is both impossible and unnecessary.
- **Corridor width.** A station counts as "on the route" if it lies within
  **5 miles** of the polyline (`CORRIDOR_MILES` in settings).
- **Fuel price.** The CSV `Retail Price` column is USD per gallon
  ($2.69–$6.04 in this dataset).
- **Endpoint input.** `start`/`finish` accept either `lat,lng` or a place name.
  Place names resolve against the offline city table first, falling back to
  Nominatim (free, no key) only on a miss. Two endpoint geocodes + one route
  call = at most three external calls, cached.

All tunables live in `config/settings.py` under the "Fuel-routing domain
settings" block.

---

## Architecture

```
Import time (run once):
  CSV → dedup on OPIS id → offline (city,state) geocode-join → FuelStation rows

Request time (GET /route/):
  1. resolve start & finish → coords        (offline city table, else Nominatim)
  2. ONE OSRM call → polyline + total distance   ← the only external call
  3. in memory, own DB/NumPy:
       a. bbox + corridor filter of stations near the polyline
       b. project each onto the route → mile marker
       c. greedy gas-station optimizer over the ordered list
  4. return route GeoJSON + ordered fuel stops + total cost
```

```
config/                Django project (settings, urls)
routing/
  models.py            FuelStation(opis_id, name, address, city, state, price, lat, lng)
  management/commands/
    import_fuel_prices.py   CSV → dedup → offline geocode-join → bulk insert
  services/
    cities.py          offline (city,state) → lat/lng lookup + name normalization
    resolve.py         endpoint resolution (lat,lng | offline city | Nominatim)
    osrm.py            the single route call (lru-cached)
    geo.py             corridor filter + projection (NumPy)
    fuel.py            the greedy optimizer
  views.py             thin orchestrator: parse → services → serialize
  urls.py
  templates/routing/map.html   Leaflet demo page
  tests/               greedy-vs-brute-force + geometry + resolver + view
data/uscities.csv      bundled geocode source (GeoNames US, offline)
```

Splitting `services/` from the view keeps the view thin and every piece
independently testable.

---

## The fuel optimizer

The classic **gas-station problem**. Stations are ordered by mile marker, each
with a price; the tank holds 500 mi of range. Greedy rule:

> At the current station, if a cheaper station is reachable within one tank, buy
> *just enough* to reach it. Otherwise fill the tank (capped at what finishing
> needs) and drive on.

This is provably optimal for uniform consumption with a fixed tank. It is
**verified against a brute-force optimum** (a fine-grid DP) on 200+ randomized
cases in `routing/tests/test_fuel.py` — so the claim isn't just "provably," it's
checked.

---

## Performance

Measured on a coast-to-coast route (Los Angeles → New York, ~2,794 mi, 33k
polyline points, 363 stations in the corridor):

| Stage                          | Time      |
|--------------------------------|-----------|
| OSRM call (cold)               | ~1.2 s    |
| OSRM call (cached)             | ~0 ms     |
| Corridor filter + projection   | ~0.35 s   |
| Fuel optimizer                 | < 1 ms    |
| **Total request (cold / warm)**| ~1.8 s / ~0.4 s |

The request path touches the DB **once** — stations load into module-level NumPy
arrays on first use and are reused across requests. There is exactly one
external call per uncached request. `overview=full` returns tens of thousands of
polyline points; the corridor match downsamples to ≤ 2,000 vertices (accuracy
stays well inside the 5-mile corridor) so runtime doesn't scale with route
length. Identical requests are `lru_cache`d.

---

## Response schema

```json
{
  "route": { "type": "LineString", "coordinates": [[lon, lat], ...] },
  "distance_miles": 2793.7,
  "total_fuel_cost_usd": 699.15,
  "fuel_stops": [
    {
      "name": "Maverik #674", "city": "North Las Vegas", "state": "NV",
      "lat": 36.19881, "lng": -115.12281,
      "price_per_gallon": 3.282, "gallons": 26.09,
      "cost_usd": 85.64, "mile_marker": 260.9
    }
  ],
  "meta": {
    "stations_considered": 365, "corridor_miles": 5.0,
    "vehicle_range_miles": 500.0, "vehicle_mpg": 10.0, "elapsed_ms": 374.0
  }
}
```

Error responses: `400` (bad start/finish), `422` (no route, or infeasible for
the 500-mile range), `502` (routing service unavailable).

---

## Data notes

- Source CSV: 8,151 rows → **6,738 unique** stations after dedup on `OPIS
  Truckstop ID` (the same physical stop is listed under several brand names,
  e.g. `PILOT TRAVEL CENTER #1243` vs `PILOT #1243`).
- Geocoded: **6,598 / 6,738 (97.9%)**. The 140 dropped are mostly Canadian-
  province truck stops (`ON`, `AB`, `BC` — absent from a US cities dataset) plus
  a handful of tiny US hamlets; thousands of stations still cover every US
  corridor.

---

## Production notes

- **OSRM public server** is rate-limited demo infrastructure. In production you
  self-host it via the official Docker image; the base URL is a single setting.
- **SQLite** is deliberate: this is a read-mostly single-table store and the
  spatial work happens in NumPy, so a reviewer can clone, migrate, load, and run
  with zero DB setup. Swapping to Postgres is a two-line `DATABASES` change; if
  PostGIS were already stood up, the corridor filter could become an
  `ST_DWithin` query.
- **Plain Django views, not DRF** — one read endpoint doesn't justify DRF's
  machinery, and fewer dependencies means faster clone-and-run.
