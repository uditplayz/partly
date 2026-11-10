"""Razorpay adapter: Orders API for creation, HMAC-SHA256 webhooks for confirmation.

Uses only the standard library, so there is no SDK dependency. Enable it with
PAYMENT_PROVIDER=razorpay plus RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and
RAZORPAY_WEBHOOK_SECRET, and point a Razorpay webhook (payment.captured,
payment.failed) at /payments/webhook/razorpay/.
"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.urls import reverse

from .base import BaseProvider, InvalidSignature, ProviderError, WebhookEvent

ORDERS_URL = "https://api.razorpay.com/v1/orders"
SIGNATURE_HEADER = "X-Razorpay-Signature"


class RazorpayProvider(BaseProvider):
    name = "razorpay"
    checkout_template = "payments/checkout_razorpay.html"

    def create_order(self, amount_paise, receipt):
        if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
            raise ProviderError("Razorpay keys are not configured.")
        auth = base64.b64encode(f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()).decode()
        request = urllib.request.Request(
            ORDERS_URL,
            data=json.dumps({"amount": amount_paise, "currency": "INR", "receipt": receipt[:40]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (fixed https URL)
                return json.load(response)["id"]
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            raise ProviderError("Could not create a Razorpay order.") from exc

    @staticmethod
    def sign(body):
        return hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    def parse_webhook(self, body, headers):
        signature = headers.get(SIGNATURE_HEADER) or ""
        if not settings.RAZORPAY_WEBHOOK_SECRET or not hmac.compare_digest(signature, self.sign(body)):
            raise InvalidSignature
        try:
            data = json.loads(body)
            event = data.get("event")
            kind = {"payment.captured": "captured", "order.paid": "captured", "payment.failed": "failed"}.get(event, "ignored")
            if kind == "ignored":
                return WebhookEvent(kind="ignored", raw=data)
            entity = data["payload"]["payment"]["entity"]
            return WebhookEvent(
                kind=kind,
                order_id=str(entity.get("order_id") or ""),
                payment_id=str(entity.get("id") or ""),
                amount_paise=int(entity.get("amount") or 0),
                reason=str(entity.get("error_description") or "")[:200],
                raw=data,
            )
        except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
            raise ValueError("Unreadable webhook body") from exc

    def checkout_context(self, payment, request):
        return {
            "razorpay_options": {
                "key": settings.RAZORPAY_KEY_ID,
                "order_id": payment.provider_order_id,
                "amount": payment.amount_paise,
                "currency": "INR",
                "name": settings.SITE_NAME,
                "description": f"Listing fee: {payment.event.title}" if payment.event else "Listing fee",
                "prefill": {"email": payment.user.email, "name": payment.user.name},
                "theme": {"color": "#5E7D6A"},
            },
            "return_url": reverse("payments:return", args=[payment.provider_order_id]),
        }
