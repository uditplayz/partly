"""Razorpay adapter tests. No network: order creation is stubbed, webhooks are signed locally."""
import json

import pytest
from django.urls import reverse

from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.payments import services
from apps.payments.models import PlatformPayment
from apps.payments.providers.base import InvalidSignature, ProviderError
from apps.payments.providers.razorpay import SIGNATURE_HEADER, RazorpayProvider

pytestmark = pytest.mark.django_db
WEBHOOK = reverse("payments:webhook", args=["razorpay"])


@pytest.fixture(autouse=True)
def razorpay_settings(settings, monkeypatch):
    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = "rzp_test_key"
    settings.RAZORPAY_KEY_SECRET = "rzp_test_secret"
    settings.RAZORPAY_WEBHOOK_SECRET = "whsec_test"
    monkeypatch.setattr(RazorpayProvider, "create_order", lambda self, amount_paise, receipt: "order_TestOrder123")


@pytest.fixture
def draft():
    return EventFactory(draft=True, title="Pottery night")


def rzp_body(event="payment.captured", order_id="order_TestOrder123", payment_id="pay_Test987", amount=4900, **entity):
    return json.dumps({
        "entity": "event", "event": event,
        "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_id, "amount": amount, "currency": "INR", **entity}}},
    }).encode()


def post(client, body, signature=None):
    return client.post(WEBHOOK, data=body, content_type="application/json",
                       headers={SIGNATURE_HEADER: signature or RazorpayProvider.sign(body)})


def test_parse_captured_event():
    body = rzp_body()
    event = RazorpayProvider().parse_webhook(body, {SIGNATURE_HEADER: RazorpayProvider.sign(body)})
    assert (event.kind, event.order_id, event.payment_id, event.amount_paise) == ("captured", "order_TestOrder123", "pay_Test987", 4900)


def test_parse_failed_and_other_events():
    body = rzp_body(event="payment.failed", error_description="Insufficient funds")
    event = RazorpayProvider().parse_webhook(body, {SIGNATURE_HEADER: RazorpayProvider.sign(body)})
    assert (event.kind, event.reason) == ("failed", "Insufficient funds")

    other = json.dumps({"event": "refund.processed", "payload": {}}).encode()
    assert RazorpayProvider().parse_webhook(other, {SIGNATURE_HEADER: RazorpayProvider.sign(other)}).kind == "ignored"


def test_bad_signature_raises():
    with pytest.raises(InvalidSignature):
        RazorpayProvider().parse_webhook(rzp_body(), {SIGNATURE_HEADER: "nope"})
    with pytest.raises(InvalidSignature):
        RazorpayProvider().parse_webhook(rzp_body(), {})


def test_missing_webhook_secret_rejects_everything(settings):
    settings.RAZORPAY_WEBHOOK_SECRET = ""
    body = rzp_body()
    with pytest.raises(InvalidSignature):
        RazorpayProvider().parse_webhook(body, {SIGNATURE_HEADER: RazorpayProvider.sign(body)})


def test_full_flow_publishes_on_webhook(client, draft):
    client.force_login(draft.host)
    resp = client.post(reverse("payments:start", args=[draft.slug]))
    payment = PlatformPayment.objects.get()
    assert payment.provider == "razorpay" and payment.provider_order_id == "order_TestOrder123"

    html = client.get(resp.url).content.decode()
    assert "checkout.razorpay.com/v1/checkout.js" in html
    assert "rzp_test_key" in html and "order_TestOrder123" in html
    assert "rzp_test_secret" not in html and "whsec_test" not in html

    assert post(client, rzp_body(), signature="forged").status_code == 400
    draft.refresh_from_db()
    assert draft.status == Event.Status.DRAFT

    assert post(client, rzp_body()).json() == {"result": "captured"}
    draft.refresh_from_db()
    assert draft.status == Event.Status.PUBLISHED and draft.platform_payment_id == "pay_Test987"
    assert post(client, rzp_body()).json() == {"result": "already_captured"}


def test_mock_webhook_is_hidden_when_razorpay_is_active(client):
    assert client.post(reverse("payments:webhook", args=["mock"]), data=b"{}", content_type="application/json").status_code == 404


def test_create_order_without_keys_fails_cleanly(settings, monkeypatch, draft):
    monkeypatch.undo()
    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = ""
    settings.RAZORPAY_KEY_SECRET = ""
    with pytest.raises(ProviderError):
        services.start_checkout(draft, draft.host)
    assert not PlatformPayment.objects.exists()
