import json

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.core.views import SHELL_ASSETS

pytestmark = pytest.mark.django_db


def test_manifest_is_valid_for_install(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/manifest+json")
    data = json.loads(resp.content)
    for key in ("name", "short_name", "start_url", "scope", "display", "icons", "theme_color", "background_color"):
        assert key in data
    assert data["display"] == "standalone" and data["scope"] == "/"
    assert data["background_color"] == "#FAF7F2"
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i["purpose"] == "maskable" for i in data["icons"])


def test_manifest_icons_exist():
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "icon.svg"):
        assert finders.find(f"icons/{name}"), name


def test_serviceworker_served_from_root_scope(client):
    resp = client.get("/serviceworker.js")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/javascript")
    assert resp["Service-Worker-Allowed"] == "/"
    assert "no-cache" in resp["Cache-Control"]
    body = resp.content.decode()
    assert 'const VERSION = "test";' in body
    assert 'const OFFLINE_URL = "/offline/";' in body
    assert "CLEAR_USER_CACHE" in body
    assert "partly-user-" in body
    for prefix in ("/api/", "/payments/", "/accounts/"):
        assert f'"{prefix}"' in body  # never-cache list
    assert "{{" not in body and "{%" not in body


def test_serviceworker_precache_assets_exist():
    for asset in SHELL_ASSETS:
        assert finders.find(asset), asset


def test_offline_page(client):
    resp = client.get(reverse("core:offline"))
    assert resp.status_code == 200
    assert "You&#x27;re offline" in resp.content.decode() or "You're offline" in resp.content.decode()
