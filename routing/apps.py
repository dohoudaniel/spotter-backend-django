import sys
import threading

from django.apps import AppConfig

# Management commands that don't serve requests -- no point warming caches (and
# some, like migrate, run before the stations table even exists).
_NO_WARMUP = {
    "migrate", "makemigrations", "test", "import_fuel_prices",
    "collectstatic", "shell", "createsuperuser", "check",
}


class RoutingConfig(AppConfig):
    name = "routing"

    def ready(self):
        # Warm the offline city table and the station arrays at startup, in a
        # background thread so server boot isn't blocked. This moves the ~700 ms
        # + 30 ms one-time load off the first real request's critical path.
        argv1 = sys.argv[1] if len(sys.argv) > 1 else ""
        if argv1 in _NO_WARMUP:
            return

        def _warm():
            try:
                from routing.services import cities, geo
                cities._load()
                geo.load_stations()
            except Exception:
                # Warmup is best-effort; the lazy load in each service still
                # runs on first use if this fails (e.g. empty/unmigrated DB).
                pass

        threading.Thread(target=_warm, name="cache-warmup", daemon=True).start()
