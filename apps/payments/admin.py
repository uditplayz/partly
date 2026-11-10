from django.contrib import admin, messages
from django.utils import timezone

from .models import PlatformPayment


@admin.register(PlatformPayment)
class PlatformPaymentAdmin(admin.ModelAdmin):
    list_display = ("provider_order_id", "event", "user", "amount_inr", "provider", "status", "needs_refund", "refunded_at", "created_at")
    list_filter = ("status", "provider", "needs_refund")
    search_fields = ("provider_order_id", "provider_payment_id", "user__username", "event__title")
    raw_id_fields = ("event", "user")
    actions = ["mark_refunded"]

    @admin.action(description="Mark as refunded (do this AFTER refunding in the Razorpay dashboard)")
    def mark_refunded(self, request, queryset):
        count = queryset.filter(refunded_at__isnull=True).update(needs_refund=False, refunded_at=timezone.now())
        self.message_user(request, f"Marked {count} payment(s) as refunded.", messages.SUCCESS)
    readonly_fields = ("provider_order_id", "provider_payment_id", "raw_payload", "created_at", "updated_at", "captured_at")  # refunded_at is set by the action above
