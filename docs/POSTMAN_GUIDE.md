# Testing the Fuel Route API with Postman

A step-by-step guide to exercising every endpoint from Postman, with the exact
requests, expected responses, and what to look for.

---

## 0. Prerequisites

Start the server first (in a terminal):

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py import_fuel_prices fuel-prices-for-be-assessment.csv
python manage.py runserver
```

Server runs at `http://127.0.0.1:8000`. Leave it running.

---

## 1. One-time Postman setup

### Create an environment (so you don't retype the host)

1. Postman → **Environments** (left sidebar) → **+** → name it `Fuel Route (local)`.
2. Add a variable:
   - **Variable:** `base_url`
   - **Initial / Current value:** `http://127.0.0.1:8000`
3. **Save**, then select this environment in the top-right dropdown.

Now every request can use `{{base_url}}` instead of the literal host.

### Create a collection

1. **Collections** → **+** → name it `Fuel Route API`.
2. Add the requests below into it (each: **Add request**).

> Tip: all requests are **GET**. The API is read-only.

---

## 2. The requests

For each, set the method to **GET**, paste the URL, and hit **Send**.

Where a request takes `start` / `finish`, use the **Params** tab so Postman
handles URL-encoding for you (spaces, commas). Enter the key and value in the
table; Postman builds the query string.

---

### 2.1 API docs (HTML)

- **URL:** `{{base_url}}/`
- **Expect:** `200 OK`, HTML body. Click **Preview** in the response pane to see
  the rendered documentation page.

### 2.2 Machine-readable spec (JSON)

- **URL:** `{{base_url}}/api/`
- **Expect:** `200 OK`, JSON describing endpoints, params, status codes, and the
  vehicle model.

### 2.3 Long route by place name — the main demo

- **URL:** `{{base_url}}/route/`
- **Params:**
  | Key | Value |
  |--------|------------------|
  | start | `Los Angeles, CA` |
  | finish | `New York, NY` |
- **Full URL becomes:**
  `{{base_url}}/route/?start=Los Angeles, CA&finish=New York, NY`
- **Expect:** `200 OK`. In the body:
  - `distance_miles` ≈ `2793.7`
  - `total_fuel_cost_usd` ≈ `699`
  - `fuel_stops` — an ordered array (~15 stops), each with `price_per_gallon`,
    `gallons`, `cost_usd`, `mile_marker`.
  - `meta.stations_considered` — how many stations were in the corridor.
  - `meta.elapsed_ms` — server compute time.
- **What to check:** the `mile_marker` values increase in order, and no gap
  between consecutive markers (or origin/finish) exceeds 500.

### 2.4 Same route by raw coordinates

- **URL:** `{{base_url}}/route/`
- **Params:**
  | Key | Value |
  |--------|-------------------|
  | start | `34.05,-118.24` |
  | finish | `40.71,-74.01` |
- **Expect:** `200 OK`, essentially the same result as 2.3. This path does **no**
  endpoint geocoding — coordinates are parsed directly.

### 2.5 Short route within one tank

- **URL:** `{{base_url}}/route/`
- **Params:** `start = Oklahoma City, OK`, `finish = Tulsa, OK`
- **Expect:** `200 OK`, `distance_miles` ≈ `106`, `fuel_stops` = `[]`,
  `total_fuel_cost_usd` = `0`. You start with a full tank (500 mi range), so a
  106-mile trip needs no purchase.

### 2.6 No drivable route → 422

- **URL:** `{{base_url}}/route/`
- **Params:** `start = Honolulu, HI`, `finish = Los Angeles, CA`
- **Expect:** `422 Unprocessable Entity`, body `{"error": "Impossible route
  between points"}`. There is no road route across the ocean; the API says so
  cleanly instead of crashing.

### 2.7 Missing input → 400

- **URL:** `{{base_url}}/route/`
- **Params:** `start =` (empty), `finish = Tulsa, OK`
- **Expect:** `400 Bad Request`, `{"error": "Missing start/finish value."}`

### 2.8 Unresolvable location → 400

- **URL:** `{{base_url}}/route/`
- **Params:** `start = asdkjhaskdjh`, `finish = Tulsa, OK`
- **Expect:** `400 Bad Request`, `{"error": "Could not geocode location: ..."}`

---

## 3. Optional: automated checks (Postman Tests tab)

Paste into the **Tests** tab of request 2.3 to assert the response
programmatically. Postman runs this after each **Send**.

```javascript
pm.test("status is 200", () => pm.response.to.have.status(200));

const body = pm.response.json();

pm.test("has route, distance, cost, stops", () => {
  pm.expect(body).to.have.property("route");
  pm.expect(body).to.have.property("distance_miles");
  pm.expect(body).to.have.property("total_fuel_cost_usd");
  pm.expect(body.fuel_stops).to.be.an("array");
});

pm.test("stops are ordered and legs <= 500 mi", () => {
  const marks = [0, ...body.fuel_stops.map(s => s.mile_marker), body.distance_miles];
  for (let i = 1; i < marks.length; i++) {
    pm.expect(marks[i]).to.be.at.least(marks[i - 1]);   // ordered
    pm.expect(marks[i] - marks[i - 1]).to.be.at.most(500 + 1e-6);  // reachable
  }
});
```

For request 2.6 (no route):

```javascript
pm.test("status is 422", () => pm.response.to.have.status(422));
pm.test("has an error message", () => pm.expect(pm.response.json()).to.have.property("error"));
```

---

## 4. Run the whole collection at once

1. Hover the collection → **Run** (or **⋯ → Run collection**).
2. Select all requests → **Run Fuel Route API**.
3. The **Collection Runner** shows pass/fail per request and per test assertion.

That's a full regression pass in one click.

---

## 5. Notes

- The first request to a new route is slower (~1–3 s) because of the one live
  OSRM call; identical repeat requests are cached and near-instant.
- **Response size / "Couldn't generate table view":** by default the route
  geometry is thinned to ~600 points (~18 KB), so the JSON stays small and
  Postman renders it fine. If you add `&geometry=full`, the body jumps to
  ~800 KB (the full 33k-point polyline) and Postman may refuse its table view —
  that's a Postman limit, not an error; use the **Pretty / JSON** tab. The fuel
  result is identical either way.
- All endpoints are **GET**. Sending **POST** to `/route/` returns `405 Method
  Not Allowed`.
- The API talks to OSRM's public demo server. If it's rate-limited or down,
  `/route/` returns `502` — retry, or self-host OSRM (see the README).
