"""Verify the greedy fuel optimizer against a brute-force optimum.

The greedy in ``fuel.plan_fuel`` is provably optimal, but "provably" is worth
nothing without a check. Here we build a small DP that computes the true
minimum cost over the same inputs and assert the greedy matches on many
randomized cases. This is the claim we make on camera: "I verified the greedy
against a brute-force optimum."
"""

import random

from django.test import SimpleTestCase

from routing.services.fuel import Infeasible, plan_fuel

TANK = 500.0
MPG = 10.0


def brute_force_min_cost(stations, distance_mi, tank_range=TANK, mpg=MPG):
    """True minimum fuel cost via DP over a fine fuel grid.

    State: at each station, for each achievable fuel level (miles of range),
    the minimum cost to arrive there. Fuel is discretized; prices are chosen so
    the greedy's continuous optimum lands on grid points, letting us compare
    exactly. Returns None if infeasible.
    """
    # Feasibility check mirrors plan_fuel.
    marks = [0.0] + [s["mile"] for s in stations] + [distance_mi]
    for a, b in zip(marks, marks[1:]):
        if b - a > tank_range + 1e-9:
            return None

    step = 10.0  # miles of range per grid unit
    max_units = int(round(tank_range / step))
    gpm = 1.0 / mpg

    # cost[u] = min cost to be at current position with u*step miles of range.
    # Start: full tank at origin, zero cost.
    INF = float("inf")
    cost = [INF] * (max_units + 1)
    cost[max_units] = 0.0
    pos = 0.0

    for s in stations:
        drive = s["mile"] - pos
        drive_units = int(round(drive / step))
        pos = s["mile"]
        # Drive to this station: every state loses drive_units of fuel.
        arrived = [INF] * (max_units + 1)
        for u in range(max_units + 1):
            if cost[u] == INF:
                continue
            nu = u - drive_units
            if nu < 0:
                continue
            arrived[nu] = min(arrived[nu], cost[u])
        # Buy every possible amount (0..fill) at this station's price. Trying
        # all purchase amounts at all stations is what makes this an exhaustive
        # optimum -- no greedy assumption -- so it's a trustworthy oracle to
        # check plan_fuel against. `after` starts as `arrived` (the buy-nothing
        # case); each nonzero purchase relaxes a higher fuel level.
        price = s["price"]
        after = list(arrived)
        for u in range(max_units + 1):
            if arrived[u] == INF:
                continue
            for add in range(1, max_units - u + 1):
                nu = u + add
                c = arrived[u] + add * step * gpm * price
                if c < after[nu]:
                    after[nu] = c
        cost = after

    # Drive final leg to the finish.
    final_units = int(round((distance_mi - pos) / step))
    best = INF
    for u in range(max_units + 1):
        if cost[u] == INF:
            continue
        if u - final_units >= 0:
            best = min(best, cost[u])
    return None if best == INF else round(best, 2)


def make_stations(rng, n, distance_mi):
    # Snap positions to 10-mile multiples so the grid DP (step=10) is exact and
    # the continuous greedy's purchase amounts land on the same grid.
    miles = sorted(
        {rng.randrange(1, int(distance_mi // 10)) * 10 for _ in range(n)}
    )
    return [
        {
            "mile": float(m),
            # Prices on a coarse set so grid DP is exact.
            "price": rng.choice([2.5, 3.0, 3.5, 4.0, 4.5]),
            "name": f"S{i}",
            "city": "X",
            "state": "XX",
            "lat": 0.0,
            "lng": 0.0,
        }
        for i, m in enumerate(miles)
    ]


class GreedyMatchesBruteForceTests(SimpleTestCase):
    def test_random_cases(self):
        rng = random.Random(1234)
        checked = 0
        for _ in range(400):
            distance = rng.choice([300, 600, 900, 1200])
            # Guarantee feasibility: enough stations, spaced under a tank.
            n = rng.randint(3, 12)
            stations = make_stations(rng, n, distance)
            # Ensure no leg exceeds the tank so both solvers run.
            marks = [0.0] + [s["mile"] for s in stations] + [float(distance)]
            if any(b - a > TANK for a, b in zip(marks, marks[1:])):
                continue
            greedy_total, _ = plan_fuel(stations, distance)
            bf = brute_force_min_cost(stations, distance)
            self.assertIsNotNone(bf)
            self.assertAlmostEqual(
                greedy_total, bf, places=2,
                msg=f"greedy={greedy_total} bf={bf} n={n} d={distance}",
            )
            checked += 1
        self.assertGreater(checked, 200)

    def test_no_stations_but_reachable(self):
        # Distance within one tank, no stations: cost is zero (start full).
        total, stops = plan_fuel([], 400.0)
        self.assertEqual(total, 0.0)
        self.assertEqual(stops, [])

    def test_infeasible_gap(self):
        # 700-mile trip, single station at mile 50 -> final leg 650 > 500.
        stations = [
            {"mile": 50.0, "price": 3.0, "name": "A", "city": "X",
             "state": "XX", "lat": 0.0, "lng": 0.0}
        ]
        with self.assertRaises(Infeasible):
            plan_fuel(stations, 700.0)

    def test_buys_at_cheaper_station(self):
        # Cheap station early, expensive later: should tank up at the cheap one.
        stations = [
            {"mile": 100.0, "price": 2.5, "name": "cheap", "city": "X",
             "state": "XX", "lat": 0.0, "lng": 0.0},
            {"mile": 550.0, "price": 5.0, "name": "pricey", "city": "X",
             "state": "XX", "lat": 0.0, "lng": 0.0},
        ]
        total, stops = plan_fuel(stations, 900.0)
        bf = brute_force_min_cost(stations, 900.0)
        self.assertAlmostEqual(total, bf, places=2)
