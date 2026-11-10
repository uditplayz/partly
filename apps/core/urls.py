from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("offline/", views.offline, name="offline"),
    path("manifest.json", views.manifest, name="manifest"),
    path("serviceworker.js", views.serviceworker, name="serviceworker"),
]
