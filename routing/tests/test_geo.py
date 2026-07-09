"""Corridor filter + projection tests, using a synthetic straight-line route."""

import numpy as np
from django.test import SimpleTestCase

from routing.services import geo


def straight_route(lat, lon0, lon1, n=200):
    """An east-west polyline at constant latitude, as [[lon, lat], ...]."""
    lons = np.linspace(lon0, lon1, n)
    return [[float(x), float(lat)] for x in lons]


class CorridorTests(SimpleTestCase):
    def setUp(self):
        # Inject stations directly so no DB is needed.
        # On the line at lat 40: (40, -99), (40, -95). Off the line: (41, -97).
        geo._STATIONS = {
            "lat": np.array([40.0, 40.0, 41.0]),
            "lng": np.array([-99.0, -95.0, -97.0]),
            "price": np.array([3.0, 3.2, 2.9]),
            "meta": [
                {"name": "on-a", "city": "A", "state": "XX"},
                {"name": "on-b", "city": "B", "state": "XX"},
                {"name": "off", "city": "C", "state": "XX"},
            ],
        }

    def tearDown(self):
        geo.clear_cache()

    def test_keeps_on_route_drops_far(self):
        coords = straight_route(40.0, -100.0, -90.0)
        # ~530 miles across 10 degrees of longitude at lat 40.
        total = 530.0
        out = geo.stations_along_route(coords, total, corridor_mi=5.0)
        names = [s["name"] for s in out]
        self.assertIn("on-a", names)
        self.assertIn("on-b", names)
        self.assertNotIn("off", names)  # ~69 miles off the line

    def test_mile_markers_ordered_and_scaled(self):
        coords = straight_route(40.0, -100.0, -90.0)
        total = 530.0
        out = geo.stations_along_route(coords, total, corridor_mi=5.0)
        miles = [s["mile"] for s in out]
        self.assertEqual(miles, sorted(miles))
        # Station at -99 is ~1/10 of the way; at -95 is ~1/2.
        self.assertLess(out[0]["mile"], out[1]["mile"])
        self.assertTrue(0 <= miles[0] <= total)
        self.assertTrue(0 <= miles[-1] <= total)

    def test_empty_when_route_far_from_all(self):
        coords = straight_route(10.0, -100.0, -90.0)  # far south
        out = geo.stations_along_route(coords, 530.0, corridor_mi=5.0)
        self.assertEqual(out, [])
