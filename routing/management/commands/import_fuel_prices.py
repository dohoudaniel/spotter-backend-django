"""
Import the fuel-price CSV into the FuelStation table.

Pipeline: parse -> dedup on OPIS id -> offline (city, state) geocode-join ->
bulk insert. Makes ZERO geocoding API calls. Run once; the request path
never geocodes.

    python manage.py import_fuel_prices fuel-prices-for-be-assessment.csv
"""

import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import FuelStation
from routing.services import cities


class Command(BaseCommand):
    help = "Load the fuel-price CSV into FuelStation (dedup + offline geocode)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument(
            "--keep-unmatched",
            action="store_true",
            help="Report unmatched (city, state) pairs at the end.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        seen = set()
        rows = []
        unmatched = 0
        unmatched_keys = set()
        total = 0

        # utf-8-sig strips the BOM; csv handles the quoted commas in Address.
        with open(opts["csv_path"], newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                total += 1
                oid = int(r["OPIS Truckstop ID"])
                if oid in seen:  # dedup: same stop, alternate branding
                    continue
                seen.add(oid)

                city, state = r["City"].strip(), r["State"].strip()
                coord = cities.lookup(city, state)
                if coord is None:  # residual miss (mostly Canadian towns) -> drop
                    unmatched += 1
                    unmatched_keys.add((city.upper(), state.upper()))
                    continue

                lat, lng = coord
                rows.append(
                    FuelStation(
                        opis_id=oid,
                        name=r["Truckstop Name"].strip(),
                        address=r["Address"].strip(),
                        city=city,
                        state=state,
                        price=float(r["Retail Price"]),
                        lat=lat,
                        lng=lng,
                    )
                )

        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(rows, batch_size=1000)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(rows)} stations from {total} rows "
                f"({len(seen)} unique OPIS ids); "
                f"{unmatched} dropped for missing (city, state) geocode."
            )
        )
        if opts["keep_unmatched"] and unmatched_keys:
            self.stdout.write("Unmatched (city, state):")
            for city, state in sorted(unmatched_keys):
                self.stdout.write(f"  {city}, {state}")
