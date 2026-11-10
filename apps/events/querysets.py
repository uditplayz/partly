from django.db import models
from django.apps import apps
from django.db.models import F, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
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
        """Annotate seats_used (confirmed guests plus their plus-ones) and spots_left, in one query."""
        RSVP = apps.get_model("rsvps", "RSVP")
        used = (
            RSVP.objects.filter(event=OuterRef("pk"), status="CONFIRMED")
            .order_by()
            .values("event")
            .annotate(n=Sum(F("plus_ones") + 1))
            .values("n")
        )
        return self.annotate(
            seats_used=Coalesce(Subquery(used, output_field=IntegerField()), 0)
        ).annotate(spots_left=F("capacity") - F("seats_used"))

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
