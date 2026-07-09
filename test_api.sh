#!/usr/bin/env bash
#
# Smoke-test the Fuel Route API against a running server.
#
#   1. Start the server in one terminal:
#        source .venv/bin/activate
#        python manage.py runserver
#   2. Run this script in another:
#        ./test_api.sh                     # defaults to http://127.0.0.1:8000
#        ./test_api.sh http://host:port    # or point it elsewhere
#
# Each case prints the HTTP status, a PASS/FAIL against the expected status, and
# a short summary of the JSON. Exit code is non-zero if any case fails.

set -u
BASE="${1:-http://127.0.0.1:8000}"
PASS=0
FAIL=0

# req <label> <expected_status> <path-with-query>
req() {
  local label="$1" expected="$2" path="$3"
  local status tmp
  tmp="$(mktemp)"
  # Write the response body to a temp file; capture the HTTP status separately.
  # (Body goes to a file so the python summariser below can read it without
  # colliding with its own heredoc program on stdin.)
  status="$(curl -s -o "$tmp" -w '%{http_code}' "${BASE}${path}")"

  printf '\n=== %s ===\n' "$label"
  printf 'GET %s\n' "$path"
  if [ "$status" = "$expected" ]; then
    printf 'status %s  PASS\n' "$status"
    PASS=$((PASS + 1))
  else
    printf 'status %s  FAIL (expected %s)\n' "$status" "$expected"
    FAIL=$((FAIL + 1))
  fi

  # Pretty summary via python (no jq dependency). Body comes from the file.
  BODY_FILE="$tmp" python3 <<'PY'
import json, os
try:
    with open(os.environ["BODY_FILE"]) as f:
        d = json.load(f)
except Exception:
    print("  (non-JSON body)"); raise SystemExit
if "error" in d:
    print(f"  error: {d['error']}")
if "distance_miles" in d and "total_fuel_cost_usd" in d:
    print(f"  distance: {d['distance_miles']} mi")
    print(f"  total cost: ${d['total_fuel_cost_usd']}")
    print(f"  fuel stops: {len(d.get('fuel_stops', []))}")
    m = d.get("meta", {})
    if m:
        print(f"  considered: {m.get('stations_considered')} stations"
              f"  |  elapsed: {m.get('elapsed_ms')} ms")
    for i, s in enumerate(d.get("fuel_stops", [])[:3], 1):
        print(f"    #{i} mile {s['mile_marker']:>7} "
              f"${s['price_per_gallon']:.3f}/gal  {s['gallons']} gal  "
              f"${s['cost_usd']}  {s['name']} ({s['city']}, {s['state']})")
    if len(d.get("fuel_stops", [])) > 3:
        print(f"    ... {len(d['fuel_stops']) - 3} more")
PY
  rm -f "$tmp"
}

echo "Testing Fuel Route API at ${BASE}"

# 1. Long cross-country route by place name -> many fuel stops.
req "Los Angeles, CA -> New York, NY (place names)" 200 \
  "/route/?start=Los%20Angeles,%20CA&finish=New%20York,%20NY"

# 2. Same route by raw coordinates (lat,lng) -> no endpoint geocoding.
req "Coordinates: 34.05,-118.24 -> 40.71,-74.01" 200 \
  "/route/?start=34.05,-118.24&finish=40.71,-74.01"

# 3. Short route inside one tank -> zero fuel stops, $0.
req "Oklahoma City, OK -> Tulsa, OK (single tank)" 200 \
  "/route/?start=Oklahoma%20City,%20OK&finish=Tulsa,%20OK"

# 4. No drivable route (island to mainland) -> 422.
req "Honolulu, HI -> Los Angeles, CA (no road route)" 422 \
  "/route/?start=Honolulu,%20HI&finish=Los%20Angeles,%20CA"

# 5. Missing input -> 400.
req "Missing start/finish" 400 \
  "/route/?start=&finish=Tulsa,%20OK"

# 6. Unresolvable place name -> 400.
req "Gibberish location" 400 \
  "/route/?start=asdkjhaskdjh&finish=Tulsa,%20OK"

# 7. Machine-readable API spec -> 200 JSON.
req "API spec (JSON)" 200 "/api/"

# 8. HTML documentation page -> 200.
req "API docs (HTML)" 200 "/"

echo
echo "-----------------------------------------"
echo "PASS: ${PASS}   FAIL: ${FAIL}"
[ "$FAIL" -eq 0 ] || exit 1
