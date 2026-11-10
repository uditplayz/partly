from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events import services
from apps.events.models import Event
from apps.events.tests.factories import EventFactory

pytestmark = pytest.mark.django_db


def assert_rejected(**overrides):
    with pytest.raises(IntegrityError), transaction.atomic():
        EventFactory(**overrides)


def test_end_must_follow_start():
    start = timezone.now() + timedelta(days=1)
    assert_rejected(start_time=start, end_time=start, rsvp_deadline=start)


def test_deadline_cannot_follow_start():
    start = timezone.now() + timedelta(days=1)
    assert_rejected(start_time=start, rsvp_deadline=start + timedelta(minutes=1))


@pytest.mark.parametrize("capacity", [1, 101])
def test_capacity_range(capacity):
    assert_rejected(capacity=capacity)


def test_plus_ones_cap():
    assert_rejected(max_plus_ones=6)


def test_free_event_cannot_have_fee():
    assert_rejected(is_free_entry=True, venue_entry_fee_inr=Decimal("100"))


def test_paid_event_needs_fee():
    assert_rejected(is_free_entry=False, venue_entry_fee_inr=Decimal("0"))


def test_published_requires_paid_or_waived_fee():
    assert_rejected(status=Event.Status.PUBLISHED, platform_fee_status=Event.FeeStatus.PENDING)


def test_draft_with_pending_fee_is_fine():
    assert EventFactory(draft=True).pk


def test_slug_generated_unique_and_stable():
    a = EventFactory(title="Rooftop Jam!")
    b = EventFactory(title="Rooftop Jam!")
    assert a.slug.startswith("rooftop-jam-") and len(a.slug) == len("rooftop-jam-") + 6
    assert a.slug != b.slug
    original = a.slug
    a.title = "Something else"
    a.save()
    a.refresh_from_db()
    assert a.slug == original


def test_slug_falls_back_for_unsluggable_title():
    assert EventFactory(title="🎉🎉").slug.startswith("event-")


def test_failed_constraint_does_not_leave_a_slug_behind():
    start = timezone.now() + timedelta(days=1)
    event = Event(host=UserFactory(), title="Bad", exact_address="x", area_name="y", vibe_category="JAM",
                  start_time=start, end_time=start - timedelta(hours=1), rsvp_deadline=start)
    with pytest.raises(IntegrityError), transaction.atomic():
        event.save()
    assert event.slug == ""


def test_address_only_for_host():
    event = EventFactory()
    assert event.address_for(event.host) == event.exact_address
    assert event.address_for(UserFactory()) is None
    from django.contrib.auth.models import AnonymousUser
    assert event.address_for(AnonymousUser()) is None


def test_entry_label():
    assert EventFactory().entry_label == "FREE"
    assert EventFactory(paid_entry=True).entry_label == "₹200 at door"


def test_visibility():
    draft = EventFactory(draft=True)
    assert draft.is_visible_to(draft.host)
    assert not draft.is_visible_to(UserFactory())
    assert EventFactory().is_visible_to(UserFactory())


def test_waive_and_publish_only_from_draft():
    draft = EventFactory(draft=True)
    published = services.waive_and_publish(draft)
    assert published.status == Event.Status.PUBLISHED
    assert published.platform_fee_status == Event.FeeStatus.WAIVED
    assert published.published_at is not None

    cancelled = EventFactory(status=Event.Status.CANCELLED)
    assert services.waive_and_publish(cancelled).status == Event.Status.CANCELLED


def test_delete_draft_only():
    with pytest.raises(ValueError):
        services.delete_draft(EventFactory())
    draft = EventFactory(draft=True)
    services.delete_draft(draft)
    assert not Event.objects.filter(pk=draft.pk).exists()
