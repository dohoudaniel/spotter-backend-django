from django.urls import path

from routing import views

urlpatterns = [
    path("route/", views.route_view, name="route"),  # the JSON API (the deliverable)
    path("map/", views.map_view, name="map"),         # Leaflet demo page (dev aid)
]
