from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.core.constants import Vibe
from apps.events.models import Event


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event

    host = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Hangout {n}")
    description = "Bring snacks."
    vibe_category = Vibe.JAM
    area_name = "Viman Nagar"
    exact_address = factory.Sequence(lambda n: f"SECRET-ADDR-{n}, Lane 7")
    start_time = factory.LazyFunction(lambda: timezone.now() + timedelta(days=2))
    end_time = factory.LazyAttribute(lambda o: o.start_time + timedelta(hours=3))
    rsvp_deadline = factory.LazyAttribute(lambda o: o.start_time)
    capacity = 10
    status = Event.Status.PUBLISHED
    platform_fee_status = Event.FeeStatus.WAIVED

    class Params:
        draft = factory.Trait(status=Event.Status.DRAFT, platform_fee_status=Event.FeeStatus.PENDING)
        paid_entry = factory.Trait(is_free_entry=False, venue_entry_fee_inr=200)
