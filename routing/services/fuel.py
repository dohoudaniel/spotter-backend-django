"""The fuel optimizer: the classic gas-station problem.

Total gallons burned is fixed by distance (D / mpg); the only thing to
optimize is WHERE you buy, because prices differ per station. Given stations
ordered by mile marker with a max tank range, minimize total dollars.

Assumption (stated in the README): you leave the origin with a full tank
(``tank_range`` miles) and the reported cost is the fuel you purchase to
complete the trip.

Greedy rule (provably optimal for uniform consumption + fixed tank):
  at each station, if a cheaper station is reachable within range, buy just
  enough to reach it; otherwise fill the tank (capped at what finishing needs).

Verified against a brute-force optimum in the test suite.
"""

_EPS = 1e-9


class Infeasible(Exception):
    """A leg longer than the tank range has no station in it."""


def plan_fuel(stations, distance_mi, tank_range=None, mpg=None):
    """Return (total_cost_usd, stops).

    ``stations`` is the ordered corridor list from ``stations_along_route``.
    Each stop dict carries the station fields plus ``gallons`` and ``cost_usd``.
    Raises ``Infeasible`` if any leg (origin->first, station->station,
    last->finish) exceeds ``tank_range``.
    """
    from django.conf import settings

    if tank_range is None:
        tank_range = settings.VEHICLE_RANGE_MILES
    if mpg is None:
        mpg = settings.VEHICLE_MPG

    # Feasibility: every gap between consecutive fill opportunities must fit
    # in one tank. Origin and finish bracket the station mile markers.
    marks = [0.0] + [s["mile"] for s in stations] + [distance_mi]
    for a, b in zip(marks, marks[1:]):
        if b - a > tank_range + _EPS:
            raise Infeasible(
                f"A {b - a:.0f}-mile stretch has no fuel station within the "
                f"{tank_range:.0f}-mile range."
            )

    # Fuel is tracked in MILES OF RANGE (not gallons) because consumption is
    # linear; we convert to gallons only when recording a purchase. Start full.
    fuel = tank_range
    pos = 0.0
    stops = []

    for i, s in enumerate(stations):
        # Drive from the previous position to this station, burning fuel.
        fuel -= s["mile"] - pos
        pos = s["mile"]
        remaining = distance_mi - pos

        # If the fuel already on board reaches the finish, stop buying.
        if fuel >= remaining - _EPS:
            break

        # Look ahead for the NEAREST cheaper station within one tank. Nearest,
        # not cheapest: we only commit enough fuel to reach it, then re-decide
        # there -- deferring purchases toward ever-cheaper prices. Stations are
        # ordered by mile, so the first one past tank range ends the search.
        cheaper = None
        for t in stations[i + 1:]:
            if t["mile"] - pos > tank_range + _EPS:
                break
            if t["price"] < s["price"]:
                cheaper = t
                break

        if cheaper is not None:
            target = cheaper["mile"] - pos          # just enough to reach it
        else:
            # Nothing cheaper reachable: this is the cheapest fuel around, so
            # fill up -- but never buy more range than finishing the trip needs.
            target = min(tank_range, remaining)

        buy = target - fuel
        if buy > _EPS:  # skip zero/negative buys (already have enough on board)
            gallons = buy / mpg
            stops.append(
                {
                    **s,
                    "gallons": round(gallons, 2),
                    "cost_usd": round(gallons * s["price"], 2),
                }
            )
            fuel += buy

    total = round(sum(x["cost_usd"] for x in stops), 2)
    return total, stops
