from django.contrib import admin

from .models import PlatformPayment


@admin.register(PlatformPayment)
class PlatformPaymentAdmin(admin.ModelAdmin):
    list_display = ("provider_order_id", "event", "user", "amount_inr", "provider", "status", "needs_refund", "created_at")
    list_filter = ("status", "provider", "needs_refund")
    search_fields = ("provider_order_id", "provider_payment_id", "user__username", "event__title")
    raw_id_fields = ("event", "user")
    readonly_fields = ("provider_order_id", "provider_payment_id", "raw_payload", "created_at", "updated_at", "captured_at")
