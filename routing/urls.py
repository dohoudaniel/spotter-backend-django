from django.urls import path

from routing import views

urlpatterns = [
    path("", views.docs_view, name="docs"),           # HTML API documentation
    path("route/", views.route_view, name="route"),   # the JSON API (the deliverable)
    path("map/", views.map_view, name="map"),          # Leaflet demo page (dev aid)
    path("api/", views.api_spec_view, name="api-spec"),  # machine-readable spec (JSON)
]
