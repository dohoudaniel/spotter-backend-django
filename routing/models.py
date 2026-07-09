from django.db import models


class FuelStation(models.Model):
    """
    One truck stop, geocoded to a city/state centroid at import time.

    Coordinates are resolved once (offline, city-level) by the
    ``import_fuel_prices`` management command, so the request path never
    geocodes. ``opis_id`` is unique because the source CSV lists the same
    physical stop under several brand names; the importer collapses those.
    """

    opis_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=8)
    price = models.FloatField(help_text="Retail price, USD per gallon")
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=["lat", "lng"])]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.price:.2f}"
