"""Query audit: a page must cost the same number of queries whether it lists 2 rows or 12.
A rising count means an N+1 slipped in."""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.tests.factories import EventFactory
from apps.rsvps import services
from apps.rsvps.models import RSVP

pytestmark = pytest.mark.django_db


def count(client, url):
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url)
    assert resp.status_code == 200, url
    return len(ctx)


def test_my_tickets_does_not_grow_with_the_number_of_rsvps(client):
    me = UserFactory()
    client.force_login(me)

    def add(n):
        for _ in range(n):
            services.request_rsvp(me, EventFactory(host=UserFactory(), capacity=5))

    add(2)
    small = count(client, reverse("rsvps:tickets"))
    add(10)
    assert count(client, reverse("rsvps:tickets")) == small


def test_guest_manager_does_not_grow_with_the_number_of_guests(client):
    host = UserFactory()
    event = EventFactory(host=host, capacity=100, requires_host_approval=True)
    client.force_login(host)
    url = reverse("rsvps:manage", args=[event.slug])

    def add(n):
        for _ in range(n):
            services.request_rsvp(UserFactory(), event)

    add(2)
    small = count(client, url)
    add(10)
    for rsvp in RSVP.objects.filter(event=event)[:6]:
        services.approve(rsvp.pk, host)
    for i in range(4):
        services.create_invitation(event, host, f"friend{i}@example.com")
    assert count(client, url) == small


def test_host_dashboard_does_not_grow_with_the_number_of_events(client):
    host = UserFactory()
    client.force_login(host)
    url = reverse("events:my_hosting")
    past_start = timezone.now() - timedelta(days=3)

    def add(n):
        for _ in range(n):
            services.request_rsvp(UserFactory(), EventFactory(host=host))
            EventFactory(host=host, draft=True)
            EventFactory(host=host, start_time=past_start, end_time=past_start + timedelta(hours=3), rsvp_deadline=past_start)

    add(1)
    small = count(client, url)
    add(6)
    assert count(client, url) == small


def test_event_detail_is_flat_as_the_event_fills_up(client):
    event = EventFactory(capacity=60)
    guest = UserFactory()
    client.force_login(guest)
    services.request_rsvp(guest, event)
    url = event.get_absolute_url()
    for _ in range(2):
        services.request_rsvp(UserFactory(), event)
    small = count(client, url)
    for _ in range(20):
        services.request_rsvp(UserFactory(), event)
    assert count(client, url) == small
