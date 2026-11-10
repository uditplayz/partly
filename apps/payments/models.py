from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q


class PlatformPayment(models.Model):
    """One attempt by a host to pay the flat listing fee for one event."""

    class Provider(models.TextChoices):
        MOCK = "mock", "Mock (sandbox)"
        RAZORPAY = "razorpay", "Razorpay"

    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        CAPTURED = "CAPTURED", "Captured"
        FAILED = "FAILED", "Failed"
        EXPIRED = "EXPIRED", "Expired"

    # SET_NULL so the payment record survives if the host deletes the draft.
    event = models.ForeignKey("events.Event", null=True, on_delete=models.SET_NULL, related_name="payments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="platform_payments")
    amount_inr = models.DecimalField(max_digits=8, decimal_places=2)
    provider = models.CharField(max_length=12, choices=Provider.choices)
    provider_order_id = models.CharField(max_length=64, unique=True)
    provider_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    # Money arrived but the event could not be published with it. A person must refund it.
    needs_refund = models.BooleanField(default=False)
    refunded_at = models.DateTimeField(null=True, blank=True, help_text="Set when staff refunded it in the provider dashboard")
    failure_reason = models.CharField(max_length=200, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    captured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event"], condition=Q(status="CAPTURED"), name="payment_one_capture_per_event"
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="payment_status_created_idx")]

    def __str__(self):
        return f"{self.provider_order_id} ({self.status})"

    @property
    def amount_paise(self):
        return int(self.amount_inr * 100)

    @property
    def amount_display(self):
        return f"{Decimal(self.amount_inr).normalize():f}"

    @property
    def is_open(self):
        return self.status == self.Status.CREATED
