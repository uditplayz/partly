"""Listing-fee checkout. The webhook path (handle_webhook -> mark_captured) is the
only code that can publish a paid event. Pages the browser loads never do."""
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.events import services as event_services
from apps.events.models import Event

from .models import PlatformPayment
from .providers.base import get_provider

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """The event can't be taken to checkout. The message is safe to show the host."""


def order_ttl():
    return timedelta(minutes=settings.PAYMENT_ORDER_TTL_MINUTES)


@transaction.atomic
def start_checkout(event, user):
    """Return an open PlatformPayment for this draft, or None if it was published
    straight away because the listing fee is zero."""
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.host_id != user.pk:
        raise CheckoutError("Only the host can publish this event.")
    if event.status != Event.Status.DRAFT:
        raise CheckoutError("This event is already published or closed.")
    if event.start_time <= timezone.now():
        raise CheckoutError("The start time has passed. Edit the event before publishing.")

    fee = Decimal(settings.PLATFORM_LISTING_FEE_INR)
    if fee <= 0:
        event_services.waive_and_publish(event)
        return None

    provider = get_provider()
    existing = PlatformPayment.objects.filter(
        event=event,
        user=user,
        provider=provider.name,
        status=PlatformPayment.Status.CREATED,
        amount_inr=fee,
        created_at__gt=timezone.now() - order_ttl(),
    ).first()
    if existing:
        return existing

    order_id = provider.create_order(int(fee * 100), receipt=f"event-{event.pk}")
    return PlatformPayment.objects.create(
        event=event, user=user, amount_inr=fee, provider=provider.name, provider_order_id=order_id
    )


def handle_webhook(provider_name, body, headers):
    """Verify and apply one webhook. Returns a short result string.

    Raises InvalidSignature or ValueError; the caller turns those into a 400.
    """
    event = get_provider(provider_name).parse_webhook(body, headers)
    if event.kind == "captured":
        return mark_captured(event.order_id, event.payment_id, event.amount_paise, event.raw)
    if event.kind == "failed":
        return mark_failed(event.order_id, event.reason, event.raw)
    return "ignored"


@transaction.atomic
def mark_captured(order_id, payment_id, amount_paise, raw=None):
    """Idempotent: a repeated webhook for a captured payment changes nothing."""
    payment = PlatformPayment.objects.select_for_update().filter(provider_order_id=order_id).first()
    if payment is None:
        logger.warning("Capture webhook for unknown order %s", order_id)
        return "unknown_order"
    if payment.status == PlatformPayment.Status.CAPTURED:
        return "already_captured"
    if payment.needs_refund:
        return "refund_pending"

    payment.raw_payload = raw or {}
    if amount_paise != payment.amount_paise:
        return _flag_for_refund(payment, f"Amount mismatch: got {amount_paise} paise, expected {payment.amount_paise}",
                                "amount_mismatch")

    event = Event.objects.select_for_update().filter(pk=payment.event_id).first() if payment.event_id else None
    if event is None or event.status != Event.Status.DRAFT:
        return _flag_for_refund(payment, "Event was deleted, already published or closed", "not_publishable")

    # A late capture on an EXPIRED or FAILED order still counts: the money arrived.
    payment.status = PlatformPayment.Status.CAPTURED
    payment.provider_payment_id = payment_id or None
    payment.captured_at = timezone.now()
    payment.failure_reason = ""
    payment.save()
    event_services.publish_paid(event, payment_id)
    return "captured"


def _flag_for_refund(payment, reason, result):
    payment.status = PlatformPayment.Status.FAILED
    payment.needs_refund = True
    payment.failure_reason = reason[:200]
    payment.save()
    logger.error("Payment %s needs a refund: %s", payment.provider_order_id, reason)
    return result


@transaction.atomic
def mark_failed(order_id, reason="", raw=None):
    payment = PlatformPayment.objects.select_for_update().filter(provider_order_id=order_id).first()
    if payment is None:
        return "unknown_order"
    if payment.status != PlatformPayment.Status.CREATED:
        return "unchanged"
    payment.status = PlatformPayment.Status.FAILED
    payment.failure_reason = (reason or "Payment failed")[:200]
    payment.raw_payload = raw or {}
    payment.save()
    return "failed"


def expire_stale_orders(now=None):
    """Mark unpaid orders older than the TTL as EXPIRED. Scheduled by Celery beat in Phase 6."""
    cutoff = (now or timezone.now()) - order_ttl()
    return PlatformPayment.objects.filter(
        status=PlatformPayment.Status.CREATED, created_at__lt=cutoff
    ).update(status=PlatformPayment.Status.EXPIRED, updated_at=timezone.now())
