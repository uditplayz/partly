import json
import threading

import pytest
from django.contrib.staticfiles import finders
from django.core import mail, signing
from django.db import connection
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.events.tests.factories import EventFactory
from apps.rsvps import checkin, qr, services
from apps.rsvps.models import RSVP
from apps.rsvps.tests.factories import one_seat_event

pytestmark = pytest.mark.django_db
S = RSVP.Status
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def event():
    return EventFactory(capacity=6, max_plus_ones=2)


@pytest.fixture
def guest_rsvp(event):
    return services.request_rsvp(UserFactory(display_name="Asha Rao"), event, plus_ones=1)


def scan(client, event, payload):
    return client.post(reverse("rsvps:api_checkin", args=[event.slug]), data=json.dumps({"payload": payload}),
                       content_type="application/json")


# --- the QR payload -------------------------------------------------------------------
def test_payload_round_trips_and_resists_tampering(guest_rsvp):
    payload = qr.payload_for(guest_rsvp)
    assert qr.read_payload(payload) == (guest_rsvp.checkin_token, guest_rsvp.event_id)
    assert qr.read_payload(payload[:-2] + "xx") is None
    assert qr.read_payload(payload.replace(payload[5], "A" if payload[5] != "A" else "B", 1)) is None
    for junk in ("", "hello", None, 42, "x" * 2000, str(guest_rsvp.checkin_token)):
        assert qr.read_payload(junk) is None


def test_payload_signed_with_another_salt_or_shape_is_rejected(guest_rsvp):
    wrong_salt = signing.dumps({"t": str(guest_rsvp.checkin_token), "e": guest_rsvp.event_id}, salt="something.else")
    assert qr.read_payload(wrong_salt) is None
    assert qr.read_payload(signing.dumps({"e": 1}, salt=qr.SALT)) is None
    assert qr.read_payload(signing.dumps({"t": "not-a-uuid", "e": 1}, salt=qr.SALT)) is None


def test_qr_renders_as_svg_and_png(guest_rsvp):
    assert qr.svg_inline(guest_rsvp).startswith("<svg") and "<?xml" not in qr.svg_inline(guest_rsvp)
    assert b"<svg" in qr.svg_bytes(guest_rsvp)
    assert qr.png_bytes(guest_rsvp).startswith(PNG_MAGIC)


# --- every scan outcome -----------------------------------------------------------------
def test_verified_then_already_checked_in(client, event, guest_rsvp):
    client.force_login(event.host)
    payload = qr.payload_for(guest_rsvp)
    first = scan(client, event, payload).json()
    assert first["result"] == "verified"
    assert first["guest"]["name"] == "Asha Rao" and first["guest"]["plus_ones"] == 1 and first["guest"]["checked_in_at"]
    assert first["stats"] == {"confirmed": 1, "checked_in": 1, "people_confirmed": 2, "people_checked_in": 2}
    guest_rsvp.refresh_from_db()
    stamped = guest_rsvp.checked_in_at
    assert guest_rsvp.checked_in and stamped

    second = scan(client, event, payload).json()
    assert second["result"] == "already_checked_in" and second["guest"]["name"] == "Asha Rao"
    guest_rsvp.refresh_from_db()
    assert guest_rsvp.checked_in_at == stamped  # the first scan's time is kept


def test_invalid_for_garbage_and_forgeries(client, event, guest_rsvp):
    client.force_login(event.host)
    forged = signing.dumps({"t": str(guest_rsvp.checkin_token), "e": event.pk}, key="attacker-key", salt=qr.SALT)
    for payload in ("https://example.com", str(guest_rsvp.checkin_token), forged, qr.payload_for(guest_rsvp)[:-1]):
        data = scan(client, event, payload).json()
        assert data["result"] == "invalid" and data["guest"] is None
    guest_rsvp.refresh_from_db()
    assert not guest_rsvp.checked_in


def test_wrong_event_reveals_nothing_and_checks_nobody_in(client, event, guest_rsvp):
    other = EventFactory(host=event.host)
    client.force_login(event.host)
    data = scan(client, other, qr.payload_for(guest_rsvp)).json()
    assert data["result"] == "wrong_event" and data["guest"] is None
    guest_rsvp.refresh_from_db()
    assert not guest_rsvp.checked_in


def test_not_confirmed_for_waitlisted_and_pending_passes(client):
    full = one_seat_event()
    services.request_rsvp(UserFactory(), full)
    waitlisted = services.request_rsvp(UserFactory(), full)
    client.force_login(full.host)
    assert scan(client, full, qr.payload_for(waitlisted)).json()["result"] == "not_confirmed"

    screened = EventFactory(requires_host_approval=True)
    pending = services.request_rsvp(UserFactory(), screened)
    client.force_login(screened.host)
    assert scan(client, screened, qr.payload_for(pending)).json()["result"] == "not_confirmed"
    assert not RSVP.objects.filter(checked_in=True).exists()


def test_old_pass_dies_when_the_rsvp_is_cancelled_or_rejoined(client, event, guest_rsvp):
    client.force_login(event.host)
    old = qr.payload_for(guest_rsvp)
    services.cancel(event, guest_rsvp.user)
    assert scan(client, event, old).json()["result"] == "invalid"

    rejoined = services.request_rsvp(guest_rsvp.user, event)
    assert scan(client, event, old).json()["result"] == "invalid"  # screenshot of the old pass
    assert scan(client, event, qr.payload_for(rejoined)).json()["result"] == "verified"


def test_removed_guest_cannot_get_in(client, event, guest_rsvp):
    client.force_login(event.host)
    old = qr.payload_for(guest_rsvp)
    services.decline(guest_rsvp.pk, event.host)
    assert scan(client, event, old).json()["result"] == "invalid"


# --- API access ----------------------------------------------------------------------------
def test_api_is_host_only(client, event, guest_rsvp):
    payload = qr.payload_for(guest_rsvp)
    stats_url = reverse("rsvps:api_checkin_stats", args=[event.slug])
    assert scan(client, event, payload).status_code == 401
    assert client.get(stats_url).status_code == 401

    client.force_login(guest_rsvp.user)  # a guest can't check themselves in
    assert scan(client, event, payload).status_code == 404
    assert client.get(stats_url).status_code == 404

    client.force_login(event.host)
    assert client.get(reverse("rsvps:api_checkin", args=[event.slug])).status_code == 405
    assert client.get(stats_url).json() == {
        "stats": {"confirmed": 1, "checked_in": 0, "people_confirmed": 2, "people_checked_in": 0}
    }
    guest_rsvp.refresh_from_db()
    assert not guest_rsvp.checked_in


def test_api_requires_csrf_token(event, guest_rsvp):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(event.host)
    assert scan(strict, event, qr.payload_for(guest_rsvp)).status_code == 403
    guest_rsvp.refresh_from_db()
    assert not guest_rsvp.checked_in


def test_api_rejects_malformed_requests(client, event):
    client.force_login(event.host)
    url = reverse("rsvps:api_checkin", args=[event.slug])
    for body in (b"not json", b"{}", b'{"payload": 5}', b"[]"):
        assert client.post(url, data=body, content_type="application/json").status_code == 400


def test_api_responses_are_never_cached(client, event, guest_rsvp):
    client.force_login(event.host)
    assert "no-store" in scan(client, event, "x")["Cache-Control"]
    assert "no-store" in client.get(reverse("rsvps:api_checkin_stats", args=[event.slug]))["Cache-Control"]


# --- two phones, one pass ---------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_simultaneous_scans_check_in_exactly_once():
    event = EventFactory(capacity=6)
    rsvp = services.request_rsvp(UserFactory(), event)
    payload = qr.payload_for(rsvp)
    barrier = threading.Barrier(6)
    results, errors = [], []

    def go():
        try:
            barrier.wait(timeout=15)
            results.append(checkin.check_in(event, payload)["result"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert results.count("verified") == 1 and results.count("already_checked_in") == 5


# --- manual fallback ----------------------------------------------------------------------------
def test_manual_check_in_from_the_guest_list(client, event, guest_rsvp):
    url = reverse("rsvps:manual_checkin", args=[guest_rsvp.pk])
    client.force_login(UserFactory())
    assert client.post(url).status_code == 404
    client.force_login(event.host)
    assert client.get(url).status_code == 405
    assert client.post(url).url == reverse("rsvps:manage", args=[event.slug])
    guest_rsvp.refresh_from_db()
    assert guest_rsvp.checked_in and guest_rsvp.checked_in_at
    assert scan(client, event, qr.payload_for(guest_rsvp)).json()["result"] == "already_checked_in"
    html = client.get(reverse("rsvps:manage", args=[event.slug])).content.decode()
    assert "Checked in" in html and "Open door scanner" in html


def test_manual_check_in_needs_a_confirmed_guest():
    full = one_seat_event()
    services.request_rsvp(UserFactory(), full)
    waitlisted = services.request_rsvp(UserFactory(), full)
    with pytest.raises(services.RSVPError):
        checkin.manual_check_in(waitlisted.pk, full.host)


# --- pass images ----------------------------------------------------------------------------------
def test_qr_image_only_for_the_guest_and_the_host(client, event, guest_rsvp):
    svg = reverse("rsvps:qr_svg", args=[guest_rsvp.checkin_token])
    png = reverse("rsvps:qr_png", args=[guest_rsvp.checkin_token])
    assert client.get(svg).status_code == 302  # anonymous: login

    client.force_login(UserFactory())
    assert client.get(svg).status_code == 404 and client.get(png).status_code == 404

    client.force_login(guest_rsvp.user)
    resp = client.get(svg)
    assert resp.status_code == 200 and resp["Content-Type"] == "image/svg+xml" and b"<svg" in resp.content
    assert "private" in resp["Cache-Control"]
    resp = client.get(png)
    assert resp["Content-Type"] == "image/png" and resp.content.startswith(PNG_MAGIC)

    client.force_login(event.host)
    assert client.get(svg).status_code == 200


def test_qr_image_gone_after_cancel_and_absent_while_pending(client, event, guest_rsvp):
    old = reverse("rsvps:qr_svg", args=[guest_rsvp.checkin_token])
    client.force_login(guest_rsvp.user)
    services.cancel(event, guest_rsvp.user)
    assert client.get(old).status_code == 404

    screened = EventFactory(requires_host_approval=True)
    pending = services.request_rsvp(guest_rsvp.user, screened)
    assert client.get(reverse("rsvps:qr_svg", args=[pending.checkin_token])).status_code == 404


# --- pages -------------------------------------------------------------------------------------------
def test_my_tickets_shows_a_pass_only_when_confirmed(client, event, guest_rsvp):
    screened = EventFactory(title="Screened one", requires_host_approval=True)
    services.request_rsvp(guest_rsvp.user, screened)
    client.force_login(guest_rsvp.user)
    resp = client.get(reverse("rsvps:tickets"))
    html = resp.content.decode()
    assert html.count("Show QR pass") == 1 and html.count('class="pass-modal__qr"') == 1
    assert f'id="pass-{guest_rsvp.pk}"' in html and "<svg" in html and "Asha Rao" in html
    by_title = {r.event.title: r for r in resp.context["rsvps"]}
    assert by_title[event.title].qr_svg and by_title["Screened one"].qr_svg is None


def test_event_page_links_confirmed_guest_to_their_pass(client, event, guest_rsvp):
    client.force_login(guest_rsvp.user)
    assert "Show my QR pass" in client.get(event.get_absolute_url()).content.decode()


def test_scanner_page_is_host_only(client, event):
    url = reverse("rsvps:scanner", args=[event.slug])
    assert client.get(url).status_code == 302
    client.force_login(UserFactory())
    assert client.get(url).status_code == 404
    client.force_login(event.host)
    html = client.get(url).content.decode()
    assert "vendor/html5-qrcode/html5-qrcode.min.js" in html and "js/scanner.js" in html
    assert reverse("rsvps:api_checkin", args=[event.slug]) in html and "data-csrf=" in html

    draft = EventFactory(draft=True, host=event.host)
    assert client.get(reverse("rsvps:scanner", args=[draft.slug])).status_code == 404


def test_scanner_assets_exist_and_handle_every_result():
    assert finders.find("vendor/html5-qrcode/html5-qrcode.min.js")
    with open(finders.find("js/scanner.js"), encoding="utf-8") as fh:
        js = fh.read()
    for code in (checkin.VERIFIED, checkin.ALREADY, checkin.INVALID, checkin.WRONG_EVENT, checkin.NOT_CONFIRMED):
        assert code in js
    assert "X-CSRFToken" in js


# --- offline + email ------------------------------------------------------------------------------------
def test_service_worker_keeps_tickets_offline_but_never_the_api(client):
    body = client.get("/serviceworker.js").content.decode()
    assert 'const TICKETS_PREFIX = "/tickets/";' in body and "url.pathname.startsWith(TICKETS_PREFIX)" in body
    assert '"/api/"' in body and "CLEAR_USER_CACHE" in body


def test_signed_in_pages_warm_the_tickets_cache(client, auth_client):
    assert 'data-warm-url="/tickets/"' in auth_client.get(reverse("events:feed")).content.decode()
    assert "data-warm-url" not in Client().get(reverse("events:feed")).content.decode()


def test_confirmation_email_attaches_the_pass(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.request_rsvp(UserFactory(), EventFactory())
    name, content, mimetype = mail.outbox[0].attachments[0]
    assert (name, mimetype) == ("partly-pass.png", "image/png") and content.startswith(PNG_MAGIC)
