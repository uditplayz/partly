from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("offline/", views.offline, name="offline"),
    path("terms/", views.legal, {"page": "terms"}, name="terms"),
    path("privacy/", views.legal, {"page": "privacy"}, name="privacy"),
    path("refunds/", views.legal, {"page": "refunds"}, name="refunds"),
    path("healthz/", views.healthz, name="healthz"),
    path("manifest.json", views.manifest, name="manifest"),
    path("serviceworker.js", views.serviceworker, name="serviceworker"),
]
