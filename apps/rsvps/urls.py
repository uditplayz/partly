from django.urls import path

from . import views

app_name = "rsvps"

urlpatterns = [
    path("tickets/", views.my_plans, name="tickets"),
    path("events/<slug:slug>/rsvp/", views.rsvp_create, name="create"),
    path("events/<slug:slug>/rsvp/cancel/", views.rsvp_cancel, name="cancel"),
    path("events/<slug:slug>/manage/", views.manage, name="manage"),
    path("events/<slug:slug>/invite/", views.invite, name="invite"),
    path("events/<slug:slug>/cancel/", views.cancel_event, name="cancel_event"),
    path("rsvps/<int:pk>/approve/", views.approve, name="approve"),
    path("rsvps/<int:pk>/decline/", views.decline, name="decline"),
    path("invite/<uuid:token>/", views.invitation, name="invitation"),
]
