import json
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.payments import services
from apps.payments.models import PlatformPayment
from apps.payments.providers.base import ProviderError
from apps.payments.providers.mock import SIGNATURE_HEADER, MockProvider

pytestmark = pytest.mark.django_db
Status = PlatformPayment.Status
WEBHOOK = reverse("payments:webhook", args=["mock"])


@pytest.fixture
def draft():
    return EventFactory(draft=True, title="Rooftop jam")


@pytest.fixture
def payment(draft):
    return services.start_checkout(draft, draft.host)


def post_webhook(client, body, signature=None, **extra):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    if signature is None:
        signature = MockProvider.sign(body)
    headers = {} if signature is False else {SIGNATURE_HEADER: signature}
    return client.post(WEBHOOK, data=body, content_type="application/json", headers=headers, **extra)


def captured_body(payment, **overrides):
    data = {"event": "payment.captured", "order_id": payment.provider_order_id,
            "payment_id": "mockpay_abc123", "amount_paise": payment.amount_paise}
    data.update(overrides)
    return data


# --- starting checkout -----------------------------------------------------------
def test_start_requires_login_and_post(client, draft):
    url = reverse("payments:start", args=[draft.slug])
    assert client.post(url).status_code == 302 and "/accounts/login/" in client.post(url).url
    client.force_login(draft.host)
    assert client.get(url).status_code == 405


def test_start_is_host_only(client, draft):
    client.force_login(UserFactory())
    assert client.post(reverse("payments:start", args=[draft.slug])).status_code == 404
    assert not PlatformPayment.objects.exists()


def test_start_creates_order_and_redirects_to_checkout(client, draft):
    client.force_login(draft.host)
    resp = client.post(reverse("payments:start", args=[draft.slug]))
    payment = PlatformPayment.objects.get()
    assert resp.url == reverse("payments:checkout", args=[payment.provider_order_id])
    assert (payment.status, payment.amount_inr, payment.provider, payment.user) == (Status.CREATED, 49, "mock", draft.host)
    draft.refresh_from_db()
    assert draft.status == Event.Status.DRAFT


def test_start_reuses_the_open_order(draft, payment):
    assert services.start_checkout(draft, draft.host).pk == payment.pk
    assert PlatformPayment.objects.count() == 1


def test_start_rejects_published_and_past_events(client):
    published = EventFactory()
    with pytest.raises(services.CheckoutError):
        services.start_checkout(published, published.host)

    past = timezone.now() - timedelta(hours=2)
    stale = EventFactory(draft=True, start_time=past, end_time=past + timedelta(hours=5), rsvp_deadline=past)
    client.force_login(stale.host)
    resp = client.post(reverse("payments:start", args=[stale.slug]))
    assert resp.url == stale.get_absolute_url() and not PlatformPayment.objects.exists()


def test_zero_fee_publishes_without_payment(settings, draft):
    settings.PLATFORM_LISTING_FEE_INR = 0
    assert services.start_checkout(draft, draft.host) is None
    draft.refresh_from_db()
    assert (draft.status, draft.platform_fee_status) == (Event.Status.PUBLISHED, Event.FeeStatus.WAIVED)


def test_provider_outage_charges_nothing(client, draft, monkeypatch):
    def boom(self, amount_paise, receipt):
        raise ProviderError("down")
    monkeypatch.setattr(MockProvider, "create_order", boom)
    client.force_login(draft.host)
    resp = client.post(reverse("payments:start", args=[draft.slug]))
    assert resp.url == draft.get_absolute_url() and not PlatformPayment.objects.exists()


# --- webhook: the only path that publishes ----------------------------------------
def test_valid_capture_publishes_the_event(client, draft, payment):
    resp = post_webhook(client, captured_body(payment))
    assert resp.status_code == 200 and resp.json() == {"result": "captured"}
    payment.refresh_from_db()
    draft.refresh_from_db()
    assert payment.status == Status.CAPTURED and payment.captured_at and payment.provider_payment_id == "mockpay_abc123"
    assert draft.status == Event.Status.PUBLISHED
    assert draft.platform_fee_status == Event.FeeStatus.PAID
    assert draft.platform_payment_id == "mockpay_abc123" and draft.published_at
    assert draft.title in client.get(reverse("events:feed")).content.decode()


@pytest.mark.parametrize("signature", ["deadbeef", "", False])
def test_bad_or_missing_signature_is_rejected(client, draft, payment, signature):
    resp = post_webhook(client, captured_body(payment), signature=signature)
    assert resp.status_code == 400
    payment.refresh_from_db()
    draft.refresh_from_db()
    assert payment.status == Status.CREATED and draft.status == Event.Status.DRAFT


def test_signature_covers_the_exact_body(client, draft, payment):
    signed = json.dumps(captured_body(payment)).encode()
    tampered = signed.replace(payment.provider_order_id.encode(), b"mock_someone_elses_order")
    assert post_webhook(client, tampered, signature=MockProvider.sign(signed)).status_code == 400


def test_duplicate_webhook_is_idempotent(client, draft, payment):
    post_webhook(client, captured_body(payment))
    draft.refresh_from_db()
    first_published_at = draft.published_at
    resp = post_webhook(client, captured_body(payment, payment_id="mockpay_other"))
    assert resp.status_code == 200 and resp.json() == {"result": "already_captured"}
    draft.refresh_from_db()
    payment.refresh_from_db()
    assert draft.published_at == first_published_at and draft.platform_payment_id == "mockpay_abc123"
    assert payment.provider_payment_id == "mockpay_abc123"


def test_amount_mismatch_does_not_publish(client, draft, payment):
    resp = post_webhook(client, captured_body(payment, amount_paise=100))
    assert resp.json() == {"result": "amount_mismatch"}
    payment.refresh_from_db()
    draft.refresh_from_db()
    assert draft.status == Event.Status.DRAFT
    assert payment.status == Status.FAILED and payment.needs_refund


def test_failed_webhook_keeps_the_draft(client, draft, payment):
    resp = post_webhook(client, {"event": "payment.failed", "order_id": payment.provider_order_id, "reason": "Declined"})
    assert resp.json() == {"result": "failed"}
    payment.refresh_from_db()
    draft.refresh_from_db()
    assert payment.status == Status.FAILED and payment.failure_reason == "Declined" and not payment.needs_refund
    assert draft.status == Event.Status.DRAFT


def test_unknown_order_and_unknown_event_are_acknowledged(client, payment):
    assert post_webhook(client, captured_body(payment, order_id="mock_nope")).json() == {"result": "unknown_order"}
    assert post_webhook(client, {"event": "refund.created"}).json() == {"result": "ignored"}


def test_unreadable_body_is_a_400(client):
    assert post_webhook(client, b"not json").status_code == 400


def test_late_capture_on_expired_order_still_publishes(client, draft, payment):
    PlatformPayment.objects.filter(pk=payment.pk).update(status=Status.EXPIRED)
    assert post_webhook(client, captured_body(payment)).json() == {"result": "captured"}
    draft.refresh_from_db()
    assert draft.status == Event.Status.PUBLISHED


def test_second_payment_for_a_published_event_is_flagged_for_refund(client, draft, payment):
    PlatformPayment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=45))
    services.expire_stale_orders()
    second = services.start_checkout(draft, draft.host)
    assert second.pk != payment.pk
    post_webhook(client, captured_body(second, payment_id="mockpay_second"))
    resp = post_webhook(client, captured_body(payment, payment_id="mockpay_first"))
    assert resp.json() == {"result": "not_publishable"}
    payment.refresh_from_db()
    assert payment.needs_refund and payment.status == Status.FAILED
    assert PlatformPayment.objects.filter(event=draft, status=Status.CAPTURED).count() == 1


def test_capture_after_draft_deleted_is_flagged_for_refund(client, draft, payment):
    draft.delete()
    assert post_webhook(client, captured_body(payment)).json() == {"result": "not_publishable"}
    payment.refresh_from_db()
    assert payment.event is None and payment.needs_refund


def test_webhook_needs_no_csrf_token_and_no_login(draft, payment):
    resp = post_webhook(Client(enforce_csrf_checks=True), captured_body(payment))
    assert resp.status_code == 200


def test_webhook_rejects_get_and_inactive_providers(client, settings, payment):
    assert client.get(WEBHOOK).status_code == 405
    assert client.post(reverse("payments:webhook", args=["razorpay"]), data=b"{}", content_type="application/json").status_code == 404
    settings.PAYMENT_PROVIDER = "razorpay"
    assert post_webhook(client, captured_body(payment)).status_code == 404


def test_database_allows_one_capture_per_event(draft, payment):
    PlatformPayment.objects.filter(pk=payment.pk).update(status=Status.CAPTURED)
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformPayment.objects.create(event=draft, user=draft.host, amount_inr=49, provider="mock",
                                       provider_order_id="mock_dup", status=Status.CAPTURED)


# --- pages the browser loads never publish -----------------------------------------
def test_browser_pages_never_publish(client, draft, payment):
    client.force_login(draft.host)
    order = payment.provider_order_id
    assert client.get(reverse("payments:checkout", args=[order])).status_code == 200
    assert client.get(reverse("payments:return", args=[order])).status_code == 200
    data = client.get(reverse("payments:status", args=[order])).json()
    assert data == {"status": "CREATED", "published": False, "event_url": draft.get_absolute_url()}
    draft.refresh_from_db()
    payment.refresh_from_db()
    assert draft.status == Event.Status.DRAFT and payment.status == Status.CREATED


def test_payment_pages_are_owner_only(client, payment):
    order = payment.provider_order_id
    urls = [reverse(f"payments:{name}", args=[order]) for name in ("checkout", "return", "status")]
    for url in urls:
        assert client.get(url).status_code == 302  # anonymous: login
    client.force_login(UserFactory())
    for url in urls:
        assert client.get(url).status_code == 404
    assert client.post(reverse("payments:mock_pay", args=[order])).status_code == 404


def test_checkout_page_shows_fee_and_sandbox_note(client, draft, payment):
    client.force_login(draft.host)
    html = client.get(reverse("payments:checkout", args=[payment.provider_order_id])).content.decode()
    assert "₹49" in html and "Sandbox checkout" in html and "<svg" in html and draft.title in html


def test_closed_order_checkout_redirects_to_status(client, draft, payment):
    PlatformPayment.objects.filter(pk=payment.pk).update(status=Status.EXPIRED)
    client.force_login(draft.host)
    resp = client.get(reverse("payments:checkout", args=[payment.provider_order_id]))
    assert resp.url == reverse("payments:return", args=[payment.provider_order_id])
    assert "expired" in client.get(resp.url).content.decode()


# --- the sandbox bank ---------------------------------------------------------------
def test_mock_pay_success_end_to_end(client, draft):
    client.force_login(draft.host)
    checkout_url = client.post(reverse("payments:start", args=[draft.slug])).url
    order = PlatformPayment.objects.get().provider_order_id
    assert client.get(checkout_url).status_code == 200
    resp = client.post(reverse("payments:mock_pay", args=[order]), {"outcome": "success"})
    assert resp.url == reverse("payments:return", args=[order])
    assert "You're live" in client.get(resp.url).content.decode()
    draft.refresh_from_db()
    assert draft.status == Event.Status.PUBLISHED and draft.platform_fee_status == Event.FeeStatus.PAID
    client.logout()
    assert draft.title in client.get(reverse("events:feed")).content.decode()


def test_mock_pay_failure_then_retry(client, draft):
    client.force_login(draft.host)
    client.post(reverse("payments:start", args=[draft.slug]))
    first = PlatformPayment.objects.get()
    resp = client.post(reverse("payments:mock_pay", args=[first.provider_order_id]), {"outcome": "fail"})
    html = client.get(resp.url).content.decode()
    assert "didn't go through" in html and "Try again" in html
    draft.refresh_from_db()
    assert draft.status == Event.Status.DRAFT

    client.post(reverse("payments:start", args=[draft.slug]))
    assert PlatformPayment.objects.count() == 2  # a failed order is not reused


def test_mock_pay_disabled_when_provider_is_not_mock(client, settings, draft, payment):
    settings.PAYMENT_PROVIDER = "razorpay"
    client.force_login(draft.host)
    assert client.post(reverse("payments:mock_pay", args=[payment.provider_order_id])).status_code == 404
    draft.refresh_from_db()
    assert draft.status == Event.Status.DRAFT


# --- expiry --------------------------------------------------------------------------
def test_expire_stale_orders(draft, payment):
    assert services.expire_stale_orders() == 0
    PlatformPayment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=31))
    fresh = PlatformPayment.objects.create(event=None, user=draft.host, amount_inr=49, provider="mock", provider_order_id="mock_fresh")
    assert services.expire_stale_orders() == 1
    payment.refresh_from_db()
    fresh.refresh_from_db()
    assert payment.status == Status.EXPIRED and fresh.status == Status.CREATED


def test_stale_open_order_is_not_reused(draft, payment):
    PlatformPayment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=31))
    assert services.start_checkout(draft, draft.host).pk != payment.pk


# --- host UI ---------------------------------------------------------------------------
def test_draft_detail_shows_publish_button_to_host(client, draft):
    client.force_login(draft.host)
    html = client.get(draft.get_absolute_url()).content.decode()
    assert reverse("payments:start", args=[draft.slug]) in html and "Publish · ₹49" in html


def test_published_detail_has_no_publish_button(client):
    event = EventFactory()
    client.force_login(event.host)
    assert reverse("payments:start", args=[event.slug]) not in client.get(event.get_absolute_url()).content.decode()
