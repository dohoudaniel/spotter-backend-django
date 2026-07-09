"""Endpoint resolution tests (no network: lat,lng parsing + offline city hit)."""

from unittest import mock

from django.test import SimpleTestCase

from routing.services import resolve


class ResolveTests(SimpleTestCase):
    def test_parses_lat_lng(self):
        self.assertEqual(resolve.resolve("36.12, -97.14"), (36.12, -97.14))

    def test_rejects_out_of_range(self):
        with self.assertRaises(resolve.ResolveError):
            resolve.resolve("999,999")

    def test_empty_raises(self):
        with self.assertRaises(resolve.ResolveError):
            resolve.resolve("")

    def test_city_state_uses_offline_table_no_network(self):
        # If the offline table resolves it, Nominatim must not be called.
        with mock.patch.object(resolve, "_nominatim") as nom:
            lat, lng = resolve.resolve("Chicago, IL")
            nom.assert_not_called()
        self.assertAlmostEqual(lat, 41.85, delta=0.5)
        self.assertAlmostEqual(lng, -87.65, delta=0.5)
