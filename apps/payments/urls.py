from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("events/<slug:slug>/publish/", views.start, name="start"),
    path("payments/checkout/<str:order_id>/", views.checkout, name="checkout"),
    path("payments/mock/<str:order_id>/pay/", views.mock_pay, name="mock_pay"),
    path("payments/return/<str:order_id>/", views.return_page, name="return"),
    path("payments/status/<str:order_id>/", views.status, name="status"),
    path("payments/webhook/<str:provider>/", views.webhook, name="webhook"),
]
