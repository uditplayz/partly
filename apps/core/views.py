import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

# Static files the service worker precaches into the shell cache.
SHELL_ASSETS = [
    "vendor/bootstrap/bootstrap.min.css",
    "vendor/bootstrap/bootstrap.bundle.min.js",
    "css/tokens.css",
    "css/app.css",
    "js/app.js",
    "js/sw-register.js",
    "js/logout.js",
    "icons/icon.svg",
    "icons/icon-192.png",
    "icons/icon-512.png",
]

# Path prefixes the service worker must never cache (user-specific or side effects).
SW_NEVER_CACHE = ["/api/", "/payments/", "/accounts/", "/admin/", "/__debug__/"]

COMING_SOON = {
    "host": {
        "title": "Host something",
        "body": "Spin up a house party, a jam or a chai break. Event creation lands in the next build.",
    },
    "tickets": {
        "title": "My Tickets",
        "body": "Your RSVPs and QR passes will live here.",
    },
}


@require_GET
def home(request):
    return render(request, "core/home.html")


@require_GET
@login_required
def coming_soon(request, section):
    return render(request, "core/coming_soon.html", COMING_SOON[section])


@require_GET
def offline(request):
    return render(request, "core/offline.html")


@require_GET
@cache_control(max_age=3600)
def manifest(request):
    data = {
        "id": "/",
        "name": "Partly: hangouts near you",
        "short_name": "Partly",
        "description": "Find house parties, jams, workshops and chai breaks near you.",
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": settings.PWA_THEME_COLOR_LIGHT,
        "theme_color": settings.PWA_THEME_COLOR_LIGHT,
        "categories": ["social", "lifestyle", "events"],
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "My Tickets", "url": reverse("core:tickets")},
            {"name": "Host an event", "url": reverse("core:host")},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@require_GET
@cache_control(no_cache=True, max_age=0)
def serviceworker(request):
    response = render(
        request,
        "core/serviceworker.js",
        {
            # JSON literals are built here from trusted values (settings, static(), reverse()).
            "cache_version": mark_safe(json.dumps(settings.PWA_CACHE_VERSION)),
            "offline_url": mark_safe(json.dumps(reverse("core:offline"))),
            "shell_assets": mark_safe(json.dumps([static(p) for p in SHELL_ASSETS])),
            "never_cache": mark_safe(json.dumps(SW_NEVER_CACHE)),
        },
        content_type="application/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    return response
