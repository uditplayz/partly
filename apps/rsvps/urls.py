from django.urls import path

from . import api, views

app_name = "rsvps"

urlpatterns = [
    path("tickets/", views.my_plans, name="tickets"),
    path("tickets/<uuid:token>/qr.svg", views.qr_image, {"fmt": "svg"}, name="qr_svg"),
    path("tickets/<uuid:token>/qr.png", views.qr_image, {"fmt": "png"}, name="qr_png"),
    path("events/<slug:slug>/scanner/", views.scanner, name="scanner"),
    path("api/events/<slug:slug>/checkin/", api.checkin_scan, name="api_checkin"),
    path("api/events/<slug:slug>/checkin-stats/", api.checkin_stats, name="api_checkin_stats"),
    path("rsvps/<int:pk>/checkin/", views.manual_checkin, name="manual_checkin"),
    path("events/<slug:slug>/rsvp/", views.rsvp_create, name="create"),
    path("events/<slug:slug>/rsvp/cancel/", views.rsvp_cancel, name="cancel"),
    path("events/<slug:slug>/manage/", views.manage, name="manage"),
    path("events/<slug:slug>/invite/", views.invite, name="invite"),
    path("events/<slug:slug>/cancel/", views.cancel_event, name="cancel_event"),
    path("rsvps/<int:pk>/approve/", views.approve, name="approve"),
    path("rsvps/<int:pk>/decline/", views.decline, name="decline"),
    path("invite/<uuid:token>/", views.invitation, name="invitation"),
]
