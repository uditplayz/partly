from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.tests.factories import EventFactory
from apps.rsvps.models import RSVP


def one_seat_event(**kwargs):
    """A published event with exactly one free seat (capacity can't go below 2)."""
    event = EventFactory(capacity=2, **kwargs)
    RSVP.objects.create(event=event, user=UserFactory(), status=RSVP.Status.CONFIRMED, confirmed_at=timezone.now())
    return event
