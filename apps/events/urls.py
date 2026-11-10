from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.FeedView.as_view(), name="feed"),
    path("host/", views.MyHostingView.as_view(), name="my_hosting"),
    path("events/new/", views.EventCreateView.as_view(), name="create"),
    path("events/<slug:slug>/", views.EventDetailView.as_view(), name="detail"),
    path("events/<slug:slug>/edit/", views.EventUpdateView.as_view(), name="edit"),
    path("events/<slug:slug>/delete/", views.EventDeleteView.as_view(), name="delete"),
]
