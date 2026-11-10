from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Report(models.Model):
    """A member's report about an event or another member. Reviewed by staff in the admin."""

    class Reason(models.TextChoices):
        UNSAFE = "UNSAFE", "Feels unsafe"
        HARASSMENT = "HARASSMENT", "Harassment or threats"
        SCAM = "SCAM", "Scam or fake listing"
        UNDERAGE = "UNDERAGE", "Alcohol with under-age guests"
        ILLEGAL = "ILLEGAL", "Illegal activity"
        OTHER = "OTHER", "Something else"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACTIONED = "ACTIONED", "Action taken"
        DISMISSED = "DISMISSED", "Dismissed"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="reports_made")
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reports_received"
    )
    reason = models.CharField(max_length=12, choices=Reason.choices)
    details = models.TextField(blank=True, max_length=600)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    staff_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A report is about an event or a member, not both and not neither.
            models.CheckConstraint(
                condition=(Q(event__isnull=False) & Q(user__isnull=True)) | (Q(event__isnull=True) & Q(user__isnull=False)),
                name="report_has_one_target",
            ),
            # One open report per person per target, so nobody can flood the queue.
            models.UniqueConstraint(
                fields=["reporter", "event"], condition=Q(status="OPEN", event__isnull=False), name="report_one_open_per_event"
            ),
            models.UniqueConstraint(
                fields=["reporter", "user"], condition=Q(status="OPEN", user__isnull=False), name="report_one_open_per_user"
            ),
        ]
        indexes = [models.Index(fields=["status", "-created_at"], name="report_status_created_idx")]

    def __str__(self):
        return f"{self.get_reason_display()} ({self.status})"


class Block(models.Model):
    """`blocker` does not want to deal with `blocked`. Works in both directions for RSVPs."""

    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_made")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="block_unique_pair"),
            models.CheckConstraint(condition=~Q(blocker=F("blocked")), name="block_not_self"),
        ]

    @classmethod
    def exists_between(cls, a, b):
        """True if either of the two has blocked the other."""
        return cls.objects.filter(Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)).exists()

    def __str__(self):
        return f"{self.blocker_id} blocks {self.blocked_id}"
