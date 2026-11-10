from django.contrib import admin, messages

from . import services
from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "host", "vibe_category", "area_name", "start_time", "status", "platform_fee_status")
    list_filter = ("status", "platform_fee_status", "vibe_category")
    search_fields = ("title", "area_name", "host__username")
    readonly_fields = ("slug", "published_at", "created_at", "updated_at")
    raw_id_fields = ("host",)
    actions = ["waive_fee_and_publish"]

    @admin.action(description="Waive fee & publish selected drafts")
    def waive_fee_and_publish(self, request, queryset):
        count = 0
        for event in queryset.filter(status=Event.Status.DRAFT):
            services.waive_and_publish(event)
            count += 1
        self.message_user(request, f"Published {count} event(s).", messages.SUCCESS)
