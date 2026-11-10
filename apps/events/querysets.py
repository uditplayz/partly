from django.db import models
from django.db.models import F, IntegerField, Value
from django.utils import timezone

# Everything an event card needs, and nothing more. `exact_address`, `description`
# and `entry_fee_notes` are deliberately absent so the feed query never loads them.
CARD_FIELDS = (
    "id",
    "slug",
    "title",
    "vibe_category",
    "area_name",
    "start_time",
    "end_time",
    "capacity",
    "is_free_entry",
    "venue_entry_fee_inr",
    "requires_host_approval",
    "status",
    "host__id",
    "host__username",
    "host__display_name",
)


class EventQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=self.model.Status.PUBLISHED)

    def upcoming(self, now=None):
        # end_time, not start_time, so events already under way stay listed.
        return self.filter(end_time__gte=now or timezone.now())

    def with_seats(self):
        # Phase 4 replaces Value(0) with a Subquery summing 1 + plus_ones over CONFIRMED RSVPs.
        return self.annotate(seats_used=Value(0, output_field=IntegerField())).annotate(
            spots_left=F("capacity") - F("seats_used")
        )

    def for_feed(self, now=None):
        return (
            self.published()
            .upcoming(now)
            .select_related("host")
            .only(*CARD_FIELDS)
            .with_seats()
            .order_by("start_time", "id")
        )

    def hosted_by(self, user):
        return self.filter(host=user)
