from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("host/", views.coming_soon, {"section": "host"}, name="host"),
    path("tickets/", views.coming_soon, {"section": "tickets"}, name="tickets"),
    path("offline/", views.offline, name="offline"),
    path("manifest.json", views.manifest, name="manifest"),
    path("serviceworker.js", views.serviceworker, name="serviceworker"),
]
