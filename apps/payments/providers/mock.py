"""Sandbox provider: a fake UPI screen. It still signs its webhooks, so the real
verification and publishing path is exercised end to end."""
import hashlib
import hmac
import json
import secrets

import segno
from django.conf import settings
from django.utils.safestring import mark_safe

from .base import BaseProvider, InvalidSignature, WebhookEvent

SIGNATURE_HEADER = "X-Mock-Signature"


class MockProvider(BaseProvider):
    name = "mock"
    checkout_template = "payments/checkout_mock.html"

    def create_order(self, amount_paise, receipt):
        return f"mock_{secrets.token_hex(12)}"

    @staticmethod
    def sign(body):
        return hmac.new(settings.MOCK_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    def build_webhook(self, payment, success=True):
        """What the fake bank 'sends' us: (raw body, headers)."""
        payload = {
            "event": "payment.captured" if success else "payment.failed",
            "order_id": payment.provider_order_id,
            "payment_id": f"mockpay_{secrets.token_hex(10)}",
            "amount_paise": payment.amount_paise,
        }
        if not success:
            payload["reason"] = "Payment declined in the sandbox"
        body = json.dumps(payload).encode()
        return body, {SIGNATURE_HEADER: self.sign(body)}

    def parse_webhook(self, body, headers):
        signature = headers.get(SIGNATURE_HEADER) or ""
        if not hmac.compare_digest(signature, self.sign(body)):
            raise InvalidSignature
        try:
            data = json.loads(body)
            kind = {"payment.captured": "captured", "payment.failed": "failed"}.get(data.get("event"), "ignored")
            return WebhookEvent(
                kind=kind,
                order_id=str(data.get("order_id", "")),
                payment_id=str(data.get("payment_id", "")),
                amount_paise=int(data.get("amount_paise", 0)),
                reason=str(data.get("reason", ""))[:200],
                raw=data,
            )
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise ValueError("Unreadable webhook body") from exc

    def checkout_context(self, payment, request):
        upi = f"upi://pay?pa=partly@mockbank&pn=Partly&am={payment.amount_display}&cu=INR&tn={payment.provider_order_id}"
        qr = segno.make(upi, error="m").svg_inline(scale=4, border=2, dark="#1C1A17", light="#FFFFFF")
        return {"upi_qr_svg": mark_safe(qr), "upi_id": "partly@mockbank"}
