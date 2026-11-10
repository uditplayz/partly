import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

MAX_PLUS_ONES = 5


class RSVP(models.Model):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        CONFIRMED = "CONFIRMED", "Confirmed"
        WAITLISTED = "WAITLISTED", "Waitlisted"
        DECLINED = "DECLINED", "Declined"
        CANCELLED = "CANCELLED", "Cancelled"

    ACTIVE_STATUSES = (Status.PENDING_APPROVAL, Status.CONFIRMED, Status.WAITLISTED)

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="rsvps")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rsvps")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_APPROVAL)
    plus_ones = models.PositiveSmallIntegerField(default=0)
    note_to_host = models.CharField(max_length=200, blank=True)
    via_invitation = models.ForeignKey(
        "rsvps.Invitation", null=True, blank=True, on_delete=models.SET_NULL, related_name="rsvps"
    )

    # QR check-in (the scanner arrives in Phase 5).
    checkin_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    checked_in = models.BooleanField(default=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)

    # Refreshed on every (re)request, so the waitlist stays first come, first served
    # even though a cancelled RSVP reuses its row.
    requested_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reminder_24h_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_2h_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="rsvp_one_per_user_per_event"),
            models.CheckConstraint(condition=Q(checked_in=False) | Q(status="CONFIRMED"), name="rsvp_checkin_needs_confirmed"),
            models.CheckConstraint(condition=Q(plus_ones__lte=MAX_PLUS_ONES), name="rsvp_plus_ones_max"),
        ]
        indexes = [
            models.Index(fields=["event", "status"], name="rsvp_event_status_idx"),
            models.Index(fields=["user", "status"], name="rsvp_user_status_idx"),
            models.Index(fields=["event", "requested_at"], condition=Q(status="WAITLISTED"), name="rsvp_waitlist_fifo_idx"),
        ]

    def __str__(self):
        return f"{self.user} → {self.event} ({self.status})"

    @property
    def party_size(self):
        return 1 + self.plus_ones

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    def _reset_lifecycle(self):
        """Run on every cancel, decline or re-request: the old QR pass stops working
        and reminders start over. The caller saves."""
        self.checkin_token = uuid.uuid4()
        self.checked_in = False
        self.checked_in_at = None
        self.confirmed_at = None
        self.reminder_24h_sent_at = None
        self.reminder_2h_sent_at = None


class Invitation(models.Model):
    class Status(models.TextChoices):
        SENT = "SENT", "Sent"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="invitations")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invitations_sent")
    invitee_email = models.EmailField(blank=True)
    invitee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="invitations_received"
    )
    invite_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(invitee_email="") | Q(invitee_user__isnull=False), name="invitation_has_invitee"
            ),
            models.UniqueConstraint(
                "event", Lower("invitee_email"), condition=~Q(invitee_email=""), name="invitation_unique_email_per_event"
            ),
            models.UniqueConstraint(
                fields=["event", "invitee_user"], condition=Q(invitee_user__isnull=False),
                name="invitation_unique_user_per_event",
            ),
        ]

    def __str__(self):
        return f"{self.invitee_label} → {self.event}"

    @property
    def invitee_label(self):
        return self.invitee_user.name if self.invitee_user_id else self.invitee_email
