import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.core.middleware import SERVICE_WORKER_POLICY, build_policy
from apps.events.tests.factories import EventFactory
from apps.rsvps import services

pytestmark = pytest.mark.django_db

SCRIPT = re.compile(r"<script\b([^>]*)>", re.I)


def directive(policy, name):
    for part in policy.split(";"):
        part = part.strip()
        if part.startswith(name + " "):
            return part.split()[1:]
    return None


def pages(client):
    host, guest = UserFactory(), UserFactory()
    event = EventFactory(host=host, capacity=5)
    services.request_rsvp(guest, event)
    draft = EventFactory(host=host, draft=True)
    client.force_login(host)
    urls = [
        "/", event.get_absolute_url(), reverse("events:my_hosting"), reverse("events:create"),
        reverse("rsvps:manage", args=[event.slug]), reverse("rsvps:scanner", args=[event.slug]),
        reverse("rsvps:tickets"), reverse("core:offline"), reverse("accounts:login"), reverse("accounts:signup"),
    ]
    return urls


def test_every_page_has_a_policy_and_every_inline_script_carries_the_nonce(client):
    for url in pages(client):
        resp = client.get(url, follow=True)
        assert resp.status_code == 200, url
        policy = resp["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", policy).group(1)
        html = resp.content.decode()
        for attrs in SCRIPT.findall(html):
            if "src=" in attrs or 'type="application/json"' in attrs:
                continue
            assert f'nonce="{nonce}"' in attrs, f"inline script without the nonce on {url}"


def test_the_nonce_changes_on_every_request(client):
    nonces = {re.search(r"'nonce-([^']+)'", client.get("/")["Content-Security-Policy"]).group(1) for _ in range(5)}
    assert len(nonces) == 5


def test_policy_is_strict_for_normal_pages(client):
    policy = client.get("/")["Content-Security-Policy"]
    assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy
    assert directive(policy, "script-src")[0] == "'self'" and "razorpay" not in policy
    assert directive(policy, "frame-ancestors") == ["'none'"] and directive(policy, "object-src") == ["'none'"]
    assert directive(policy, "form-action") == ["'self'"]
    assert "https://fonts.googleapis.com" in directive(policy, "style-src")
    assert "https://fonts.gstatic.com" in directive(policy, "font-src")


def test_only_the_razorpay_checkout_page_gets_the_wider_policy():
    wide, strict = build_policy("n", razorpay=True), build_policy("n")
    assert "https://checkout.razorpay.com" in directive(wide, "script-src")
    assert "https://api.razorpay.com" in directive(wide, "frame-src")
    assert directive(strict, "frame-src") == ["'none'"] and "razorpay" not in strict


def test_the_service_worker_may_fetch_fonts_and_nothing_else_remote(client):
    resp = client.get("/serviceworker.js")
    assert resp["Content-Security-Policy"] == SERVICE_WORKER_POLICY
    connect = directive(SERVICE_WORKER_POLICY, "connect-src")
    assert set(connect) == {"'self'", "https://fonts.googleapis.com", "https://fonts.gstatic.com"}


def test_camera_allowed_for_our_pages_only(client):
    header = client.get("/")["Permissions-Policy"]
    assert "camera=(self)" in header and "microphone=()" in header and "geolocation=()" in header


def test_report_only_mode_and_off_switch(client, settings):
    settings.CSP_REPORT_ONLY = True
    resp = client.get("/")
    assert "Content-Security-Policy" not in resp and "Content-Security-Policy-Report-Only" in resp
    settings.CSP_ENABLED = False
    resp = client.get("/")
    assert "Content-Security-Policy" not in resp and "Content-Security-Policy-Report-Only" not in resp


def test_admin_is_left_alone(client):
    assert "Content-Security-Policy" not in client.get("/admin/login/")


def test_the_mock_checkout_page_stays_on_the_strict_policy(client):
    host = UserFactory()
    draft = EventFactory(host=host, draft=True)
    client.force_login(host)
    resp = client.post(reverse("payments:start", args=[draft.slug]), follow=True)
    assert resp.status_code == 200 and "razorpay" not in resp["Content-Security-Policy"]


# --- static scans: nothing the policy would block may creep back in ------------------------------
TEMPLATES = [p for p in Path(settings.BASE_DIR, "templates").rglob("*.html") if "emails" not in p.parts]


def test_no_inline_handlers_style_attributes_or_style_blocks_in_page_templates():
    pattern = re.compile(r"\son\w+\s*=|\sstyle\s*=|<style\b|javascript:", re.I)
    offenders = [f"{p.name}: {m.group(0)!r}" for p in TEMPLATES for m in pattern.finditer(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_only_the_theme_bootstrap_script_is_inline():
    inline = []
    for p in TEMPLATES:
        text = p.read_text(encoding="utf-8")
        for attrs in SCRIPT.findall(text):
            if "src=" not in attrs and "application/json" not in attrs:
                inline.append((p.name, attrs.strip()))
    assert inline == [("base.html", 'nonce="{{ csp_nonce }}"')]
