from django.contrib import admin

from .models import RSVP, Invitation


@admin.register(RSVP)
class RSVPAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "status", "plus_ones", "checked_in", "requested_at")
    list_filter = ("status", "checked_in")
    search_fields = ("event__title", "user__username", "user__email")
    raw_id_fields = ("event", "user", "via_invitation")
    readonly_fields = ("checkin_token", "created_at", "updated_at")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("event", "invitee_email", "invitee_user", "status", "sent_at", "responded_at")
    list_filter = ("status",)
    search_fields = ("event__title", "invitee_email", "invitee_user__username")
    raw_id_fields = ("event", "invited_by", "invitee_user")
    readonly_fields = ("invite_token", "created_at")
