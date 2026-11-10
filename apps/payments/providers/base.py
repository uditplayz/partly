"""Provider interface. A provider creates orders and turns raw webhooks into WebhookEvents."""
from dataclasses import dataclass, field

from django.conf import settings


class InvalidSignature(Exception):
    """The webhook signature is missing or wrong."""


class ProviderError(Exception):
    """The provider could not create an order (network, credentials, bad response)."""


@dataclass(frozen=True)
class WebhookEvent:
    kind: str  # "captured" | "failed" | "ignored"
    order_id: str = ""
    payment_id: str = ""
    amount_paise: int = 0
    reason: str = ""
    raw: dict = field(default_factory=dict)


class BaseProvider:
    name = ""
    checkout_template = ""

    def create_order(self, amount_paise, receipt):
        """Return the provider's order id."""
        raise NotImplementedError

    def parse_webhook(self, body, headers):
        """Verify the signature over the raw body, then return a WebhookEvent.

        Raises InvalidSignature for a bad signature and ValueError for an unreadable body.
        """
        raise NotImplementedError

    def checkout_context(self, payment, request):
        return {}


def get_provider(name=None):
    from .mock import MockProvider
    from .razorpay import RazorpayProvider

    name = name or settings.PAYMENT_PROVIDER
    providers = {MockProvider.name: MockProvider, RazorpayProvider.name: RazorpayProvider}
    try:
        return providers[name]()
    except KeyError:
        raise ProviderError(f"Unknown payment provider: {name}") from None
