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

from django.conf import settings

_CACHE = None


def _normalize(name: str):
    """Return (canonical, spaceless) name variants for fuzzy matching.

    Collapses the small set of spelling differences between the fuel CSV and
    the cities dataset: "SAINT/STE X" -> "ST X", stripped punctuation, and a
    spaceless variant so "DE FOREST" matches "DEFOREST" and "MC CALLA"
    matches "MCCALLA".

    Plain string ops, not regex: this runs ~180k times at load, and the regex
    version was ~4x slower for identical output.
    """
    s = name.strip().upper()
    if "." in s or "'" in s:
        s = s.replace(".", "").replace("'", "")
    if s.startswith("SAINT "):
        s = "ST " + s[6:]
    elif s.startswith("STE "):
        s = "ST " + s[4:]
    if "  " in s or "\t" in s:
        s = " ".join(s.split())
    return s, s.replace(" ", "")


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = os.path.join(settings.BASE_DIR, "data", "uscities.csv")
    lut = {}
    # csv.reader with fixed column indices is meaningfully faster than
    # DictReader over ~180k rows. Columns: city, state_id, lat, lng.
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            city, state, lat, lng = row[0], row[1].upper(), row[2], row[3]
            coord = (float(lat), float(lng))
            canon, spaceless = _normalize(city)
            # First writer wins; the builder already kept the highest-population
            # city per (name, state), so earlier rows are the better centroid.
            k1 = (canon, state)
            if k1 not in lut:
                lut[k1] = coord
            k2 = (spaceless, state)
            if k2 not in lut:
                lut[k2] = coord
    _CACHE = lut
    return lut


def lookup(city: str, state: str):
    """Return (lat, lng) for a (city, state) pair, or None if unknown."""
    lut = _load()
    state = state.strip().upper()
    canon, spaceless = _normalize(city)
    return lut.get((canon, state)) or lut.get((spaceless, state))
