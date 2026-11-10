from django.urls import path

from . import views

app_name = "safety"

urlpatterns = [
    path("report/<str:kind>/<str:key>/", views.report, name="report"),
    path("block/<str:username>/", views.block, name="block"),
    path("unblock/<str:username>/", views.unblock, name="unblock"),
    path("blocked/", views.blocked, name="blocked"),
]
