"""Trust score. Stored on the user and recomputed by Celery, never per request.

    score = 50 + 30 * attendance_rate + 2 * min(events_hosted, 10) - 5 * min(host_cancellations, 4)

clamped to 0..100. All inputs come from the database, not from running counters:
  * attended   = CONFIRMED RSVPs, checked in, on COMPLETED events
  * no_show    = CONFIRMED RSVPs, not checked in, on COMPLETED events
  * attendance_rate = attended / (attended + no_show), or 0 with no history
  * events_hosted   = the user's COMPLETED events
  * host_cancellations = events the user cancelled after publishing them

A new account scores 50. Perfect attendance tops out at 80 before hosting credit.
Users with fewer than NEW_MEMBER_THRESHOLD past events are shown as "New" instead of a number.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Q

BASE = Decimal("50")
ATTENDANCE_WEIGHT = Decimal("30")
HOSTING_POINTS, HOSTING_CAP = 2, 10
CANCEL_PENALTY, CANCEL_CAP = 5, 4


def compute(attended, no_show, hosted, host_cancellations):
    total = attended + no_show
    rate = Decimal(attended) / Decimal(total) if total else Decimal(0)
    score = (
        BASE
        + ATTENDANCE_WEIGHT * rate
        + HOSTING_POINTS * min(hosted, HOSTING_CAP)
        - CANCEL_PENALTY * min(host_cancellations, CANCEL_CAP)
    )
    return max(Decimal(0), min(Decimal(100), score)).quantize(Decimal("0.1"))


def recompute(user_ids=None):
    """Recompute and save counts + score for the given users (all users when None). Returns how many."""
    from apps.events.models import Event
    from apps.rsvps.models import RSVP

    User = get_user_model()
    users = User.objects.all() if user_ids is None else User.objects.filter(pk__in=list(user_ids))
    ids = list(users.values_list("pk", flat=True))
    if not ids:
        return 0

    done = Q(event__status=Event.Status.COMPLETED, status=RSVP.Status.CONFIRMED)
    rsvp_rows = (
        RSVP.objects.filter(user_id__in=ids)
        .values("user_id")
        .annotate(
            attended=Count("id", filter=done & Q(checked_in=True)),
            no_show=Count("id", filter=done & Q(checked_in=False)),
        )
    )
    rsvp_stats = {row["user_id"]: row for row in rsvp_rows}

    host_rows = (
        Event.objects.filter(host_id__in=ids)
        .values("host_id")
        .annotate(
            hosted=Count("id", filter=Q(status=Event.Status.COMPLETED)),
            cancelled=Count("id", filter=Q(status=Event.Status.CANCELLED, published_at__isnull=False)),
        )
    )
    host_stats = {row["host_id"]: row for row in host_rows}

    changed = []
    for user in User.objects.filter(pk__in=ids):
        r = rsvp_stats.get(user.pk, {})
        h = host_stats.get(user.pk, {})
        user.attended_count = r.get("attended", 0)
        user.no_show_count = r.get("no_show", 0)
        user.hosted_completed_count = h.get("hosted", 0)
        user.trust_score = compute(user.attended_count, user.no_show_count, user.hosted_completed_count, h.get("cancelled", 0))
        changed.append(user)
    User.objects.bulk_update(changed, ["attended_count", "no_show_count", "hosted_completed_count", "trust_score"], batch_size=500)
    return len(changed)
