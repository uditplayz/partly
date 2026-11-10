from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import PublicProfileView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("u/<str:username>/", PublicProfileView.as_view(), name="public_profile"),
    path("", include("apps.core.urls")),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
