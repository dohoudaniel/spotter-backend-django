"""Offline city -> (lat, lng) lookup.

The fuel CSV has no coordinates and its ``Address`` column is 96%
highway-exit strings ("I-44, EXIT 283 & US-69"), which no geocoder can
resolve. The only geocodable signal is (City, State). We resolve that
against a bundled static dataset (``data/uscities.csv``, derived from the
free GeoNames US dump) so the import makes ZERO geocoding API calls.

City-centroid precision is exactly right here: the route corridor is miles
wide and the real stations are highway exits, so street precision is both
impossible and unnecessary.
"""

import csv
import os
import re

from django.conf import settings

_CACHE = None


def _normalize(name: str):
    """Return (canonical, spaceless) name variants for fuzzy matching.

    Collapses the small set of spelling differences between the fuel CSV and
    the cities dataset: "SAINT/STE X" -> "ST X", stripped punctuation, and a
    spaceless variant so "DE FOREST" matches "DEFOREST" and "MC CALLA"
    matches "MCCALLA".
    """
    s = name.strip().upper()
    s = re.sub(r"[.']", "", s)
    s = re.sub(r"^(SAINT|STE)\s+", "ST ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s, s.replace(" ", "")


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = os.path.join(settings.BASE_DIR, "data", "uscities.csv")
    lut = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            state = r["state_id"].strip().upper()
            lat, lng = float(r["lat"]), float(r["lng"])
            canon, spaceless = _normalize(r["city"])
            # First writer wins; the builder already kept the highest-population
            # city per (name, state), so earlier rows are the better centroid.
            lut.setdefault((canon, state), (lat, lng))
            lut.setdefault((spaceless, state), (lat, lng))
    _CACHE = lut
    return lut


def lookup(city: str, state: str):
    """Return (lat, lng) for a (city, state) pair, or None if unknown."""
    lut = _load()
    state = state.strip().upper()
    canon, spaceless = _normalize(city)
    return lut.get((canon, state)) or lut.get((spaceless, state))
