from django.contrib import admin, messages

from . import services
from .models import Block, Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reason", "status", "event", "user", "reporter")
    list_filter = ("status", "reason")
    search_fields = ("details", "event__title", "user__username", "reporter__username")
    raw_id_fields = ("reporter", "event", "user")
    readonly_fields = ("created_at", "handled_at")
    actions = ["dismiss", "take_down_event", "suspend_user"]

    @admin.action(description="Dismiss selected reports")
    def dismiss(self, request, queryset):
        for report in queryset.filter(status=Report.Status.OPEN):
            services.resolve(report, Report.Status.DISMISSED)

    @admin.action(description="Cancel the reported event (guests are told) and mark actioned")
    def take_down_event(self, request, queryset):
        done = 0
        for report in queryset.select_related("event", "event__host").filter(event__isnull=False):
            if services.take_down_event(report.event):
                done += 1
            services.resolve(report, Report.Status.ACTIONED, "Event cancelled by staff.")
        self.message_user(request, f"Cancelled {done} event(s).", messages.SUCCESS)

    @admin.action(description="Suspend the reported member (cancels their upcoming events) and mark actioned")
    def suspend_user(self, request, queryset):
        done = 0
        for report in queryset.select_related("user").filter(user__isnull=False):
            if report.user.is_superuser:
                self.message_user(request, "Superuser accounts can't be suspended here.", messages.WARNING)
                continue
            services.suspend_user(report.user)
            services.resolve(report, Report.Status.ACTIONED, "Account suspended by staff.")
            done += 1
        self.message_user(request, f"Suspended {done} account(s).", messages.SUCCESS)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created_at")
    raw_id_fields = ("blocker", "blocked")
