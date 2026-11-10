import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.constants import Vibe

from .querysets import EventQuerySet

SLUG_SUFFIX_CHARS = string.ascii_lowercase + string.digits
MAX_PLUS_ONES = 5


def _slug_suffix(n=6):
    return "".join(secrets.choice(SLUG_SUFFIX_CHARS) for _ in range(n))


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    class FeeStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        WAIVED = "WAIVED", "Waived"

    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="hosted_events")
    title = models.CharField(max_length=100)
    slug = models.SlugField(max_length=64, unique=True, editable=False)
    description = models.TextField(blank=True)
    vibe_category = models.CharField(max_length=20, choices=Vibe.choices)

    area_name = models.CharField(
        "area / landmark", max_length=120, help_text="Shown publicly, e.g. Viman Nagar or Hostel Block C"
    )
    # Never render this directly. Go through Event.address_for(user).
    exact_address = models.TextField(help_text="Only confirmed guests see this")

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    rsvp_deadline = models.DateTimeField()

    capacity = models.PositiveSmallIntegerField(default=10)
    max_plus_ones = models.PositiveSmallIntegerField(default=0)
    requires_host_approval = models.BooleanField(default=False)

    is_free_entry = models.BooleanField(default=True)
    venue_entry_fee_inr = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    entry_fee_notes = models.CharField(max_length=140, blank=True)

    platform_fee_status = models.CharField(max_length=10, choices=FeeStatus.choices, default=FeeStatus.PENDING)
    platform_payment_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["start_time", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="event_end_after_start"),
            models.CheckConstraint(condition=Q(rsvp_deadline__lte=F("start_time")), name="event_deadline_before_start"),
            models.CheckConstraint(condition=Q(capacity__gte=2, capacity__lte=100), name="event_capacity_range"),
            models.CheckConstraint(condition=Q(max_plus_ones__lte=MAX_PLUS_ONES), name="event_plus_ones_max"),
            models.CheckConstraint(
                condition=Q(is_free_entry=True, venue_entry_fee_inr=0) | Q(is_free_entry=False, venue_entry_fee_inr__gt=0),
                name="event_fee_matches_entry_type",
            ),
            models.CheckConstraint(
                condition=~Q(status="PUBLISHED") | Q(platform_fee_status__in=["PAID", "WAIVED"]),
                name="event_published_requires_fee",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "start_time"], name="event_status_start_idx"),
            models.Index(fields=["vibe_category", "start_time"], name="event_vibe_start_idx"),
            models.Index(fields=["host", "status"], name="event_host_status_idx"),
            GinIndex(fields=["area_name"], opclasses=["gin_trgm_ops"], name="event_area_trgm_idx"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.slug:
            return super().save(*args, **kwargs)
        base = (slugify(self.title)[:50].strip("-")) or "event"
        for attempt in range(3):
            self.slug = f"{base}-{_slug_suffix()}"
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                # Retry only on a genuine slug collision; anything else (a check
                # constraint, say) is re-raised with the slug cleared for a clean retry.
                collided = Event.objects.filter(slug=self.slug).exists()
                if attempt == 2 or not collided:
                    self.slug = ""
                    raise
        return None

    def get_absolute_url(self):
        return reverse("events:detail", args=[self.slug])

    # --- access rules ---------------------------------------------------------
    def is_host(self, user):
        return bool(user and user.is_authenticated and user.pk == self.host_id)

    def address_for(self, user):
        """The single gate for the private address: the host and confirmed guests only."""
        if self.is_host(user):
            return self.exact_address
        if user and user.is_authenticated and self.rsvps.filter(user=user, status="CONFIRMED").exists():
            return self.exact_address
        return None

    def is_visible_to(self, user):
        return self.status in (self.Status.PUBLISHED, self.Status.COMPLETED) or self.is_host(user)

    @property
    def is_editable(self):
        return self.status in (self.Status.DRAFT, self.Status.PUBLISHED)

    # --- display helpers ------------------------------------------------------
    @property
    def is_live(self):
        now = timezone.now()
        return self.status == self.Status.PUBLISHED and self.start_time <= now <= self.end_time

    @property
    def entry_label(self):
        if self.is_free_entry:
            return "FREE"
        fee = Decimal(str(self.venue_entry_fee_inr)).normalize()
        return f"₹{fee:f} at door"

    @property
    def spots_total(self):
        return self.capacity
