# Loom Walkthrough Script — Fuel Route API

A spoken script for a < 5-minute demo. **Bold** = what you say. _Italic_ = what
you do on screen. Timings are targets, not rules.

Before recording: server running, Postman open with the collection, editor open
with the `routing/services/` folder. Pick a route > 500 mi so multiple fuel-ups
appear.

---

## 0. Intro — 20 sec

> **Hi, I'm [name]. This is my submission for the fuel-route assessment. The task
> is one endpoint: given a start and finish in the US, return the driving route,
> the cheapest set of fuel stops along it, and the total fuel cost — for a truck
> with a 500-mile range at 10 miles per gallon.**

> **Before the code, the one design decision that everything hinges on.**

---

## 1. The constraint — 40 sec

> **The fuel data has about 8,000 stations, but no coordinates — just city,
> state, and highway-exit addresses that no geocoder can resolve. To know which
> stations are on a route, I need their coordinates.**

> **The trap is geocoding stations at request time — that's thousands of API
> calls per request, and it kills both "fast" and "few external calls." So I
> geocode once, offline, at import, against a bundled US-cities dataset. Zero
> geocoding API calls, ever. At request time I make exactly one external call —
> to the routing API — and everything else is in-memory computation.**

> **That's the whole thing. Let me show it working.**

---

## 2. Live demo in Postman — 90 sec

_Select the "Los Angeles, CA → New York, NY" request. Click Send._

> **Here's a coast-to-coast route, Los Angeles to New York, by place name.**

_Response comes back. Scroll the JSON._

> **Two-thousand-eight-hundred miles. Total fuel cost about seven hundred
> dollars. And here's the ordered list of fuel stops — each one has the station
> name, its price per gallon, how many gallons I buy there, the cost, and its
> mile-marker along the route.**

_Point at `meta`._

> **In the meta block: how many stations were in the route corridor, and the
> server compute time. The heavy part — matching stations to the route and
> optimizing the fuel — is milliseconds. The only real latency is the single
> routing call.**

_Send the "no route" request (Honolulu → LA)._

> **And it fails cleanly when it should. Honolulu to LA — there's no road across
> the ocean — returns a 422 with a clear message, not a crash or a wrong number.**

_Optional: open `/map/` in the browser._

> **There's also a Leaflet page that draws the route and drops a marker at each
> fuel stop, if you want to see it on a map.**

---

## 3. Code tour — 3 talking points — 100 sec

_Open `routing/` in the editor. Keep it fast._

### Point 1 — geocode once, one call at request time

_Open `routing/management/commands/import_fuel_prices.py`._

> **The import: dedup the stations on their OPIS id — the same stop is listed
> under several brand names — then join city and state against the bundled
> cities dataset to get coordinates. In-memory join, no API calls.**

_Open `routing/views.py`._

> **The request path resolves the two endpoints, makes one call to OSRM for the
> route geometry and distance, and then does everything else against my own
> data. One external call.**

### Point 2 — the corridor match is pure computation

_Open `routing/services/geo.py`._

> **Given the route polyline, I find stations within five miles of it and project
> each one to a mile-marker along the route — all in NumPy. A KD-tree over the
> route vertices narrows six-and-a-half thousand stations to a few hundred
> candidates, then an exact point-to-segment test keeps the ones actually on the
> way. No PostGIS, no per-request database query — the stations load into memory
> once and are reused.**

### Point 3 — the fuel choice is the gas-station problem

_Open `routing/services/fuel.py`._

> **Total gallons burned is fixed by the distance — I can't change that. What I
> optimize is where I buy. This is the classic gas-station problem: at each
> station, if a cheaper one is reachable within a tank, buy just enough to reach
> it; otherwise fill up and drive to the cheapest reachable one.**

_Open `routing/tests/test_fuel.py`._

> **It's a greedy, and it's provably optimal — but I didn't just trust that. I
> verified it against a brute-force optimum on a couple hundred randomized cases.
> They match.**

---

## 4. Close — 20 sec

> **So: one endpoint, one external call per request, station geocoding done once
> offline, corridor matching and fuel optimization as in-memory computation
> that's verified for correctness. Stack is Django 6, plain views, SQLite,
> NumPy — deliberately minimal so it clones and runs in one command.**

> **The README has the assumptions, the setup, and the measured timings. Thanks
> for watching.**

---

## One-sentence version (if you only say one thing)

> **"I geocode the stations once at import, so the request path makes exactly one
> external call; the corridor match and the fuel optimization are pure in-memory
> computation, so the endpoint is fast and never hammers the routing API."**

---

## Cheat-sheet — numbers to have ready

| Thing | Value |
|---|---|
| Stations imported | 6,598 (from 8,151 rows, deduped to 6,738, 97.9% geocoded) |
| Vehicle | 500-mile range, 10 mpg → 50-gallon tank |
| Corridor width | 5 miles |
| LA → NY demo | ~2,794 mi, ~15 stops, ~$699 |
| External calls / request | 1 (route), + up to 2 endpoint geocodes, all cached |
| Compute time | corridor ≈ 130 ms (KD-tree), optimizer < 1 ms; warm request ≈ 130 ms |
| Stack | Django 6.0.7, plain views, SQLite, NumPy, SciPy, requests |

## Things a sharp reviewer may ask — have an answer

- **"Why SQLite?"** Read-mostly single table; spatial work is in NumPy, not the
  DB. Reviewer runs it with zero setup. Postgres swap is two lines.
- **"Why not DRF?"** One read endpoint doesn't justify it; fewer deps, faster
  clone-and-run.
- **"City-centroid geocoding — isn't that imprecise?"** The corridor is 5 miles
  wide and the real addresses are highway exits, so street precision is both
  impossible and unnecessary.
- **"OSRM public server in production?"** No — self-host via the official Docker
  image. The base URL is one setting.
- **"What about the dropped stations?"** 140 of 6,738, mostly Canadian-province
  stops that a US cities file can't contain; thousands still cover every US
  corridor.
