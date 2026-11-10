import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.events.forms import EventForm
from apps.events.tests.factories import EventFactory
from apps.rsvps import services
from apps.rsvps.models import RSVP
from apps.rsvps.services import RSVPError

pytestmark = pytest.mark.django_db


def test_age_rule_needs_a_confirmation():
    event = EventFactory(min_age=21)
    with pytest.raises(RSVPError, match="21 or over"):
        services.request_rsvp(UserFactory(), event)
    assert not RSVP.objects.exists()
    rsvp = services.request_rsvp(UserFactory(), event, age_confirmed=True)
    assert rsvp.status == RSVP.Status.CONFIRMED


def test_events_without_a_rule_do_not_ask():
    assert services.request_rsvp(UserFactory(), EventFactory()).status == RSVP.Status.CONFIRMED


def test_rsvp_view_and_box_enforce_and_show_the_checkbox(client):
    event = EventFactory(min_age=18)
    client.force_login(UserFactory())
    html = client.get(event.get_absolute_url()).content.decode()
    assert 'name="age_confirmed"' in html and "18 and over" in html
    client.post(reverse("rsvps:create", args=[event.slug]), {"plus_ones": 0})
    assert not RSVP.objects.exists()
    client.post(reverse("rsvps:create", args=[event.slug]), {"plus_ones": 0, "age_confirmed": "on"})
    assert RSVP.objects.filter(event=event).count() == 1


def test_invitation_acceptance_also_needs_the_confirmation(client):
    host, guest = UserFactory(), UserFactory()
    event = EventFactory(host=host, min_age=21)
    inv, _ = services.create_invitation(event, host, guest.email)
    client.force_login(guest)
    assert 'name="age_confirmed"' in client.get(reverse("rsvps:invitation", args=[inv.invite_token])).content.decode()
    client.post(reverse("rsvps:invitation", args=[inv.invite_token]), {"action": "accept"})
    assert not RSVP.objects.exists()
    client.post(reverse("rsvps:invitation", args=[inv.invite_token]), {"action": "accept", "age_confirmed": "on"})
    assert RSVP.objects.filter(event=event, user=guest).exists()


def form_data(**overrides):
    from datetime import timedelta

    from django.utils import timezone

    start = timezone.now() + timedelta(days=3)
    data = {
        "title": "Rooftop", "vibe_category": "JAM", "description": "x", "area_name": "Viman Nagar", "exact_address": "Flat 1",
        "start_time": start.strftime("%Y-%m-%dT%H:%M"), "end_time": (start + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"),
        "capacity": 10, "max_plus_ones": 0, "is_free_entry": "on",
    }
    data.update(overrides)
    return data


def test_drinks_events_must_declare_an_age_rule():
    form = EventForm(form_data(vibe_category="DRINKS"))
    assert not form.is_valid() and "min_age" in form.errors
    assert EventForm(form_data(vibe_category="DRINKS", min_age=21)).is_valid()
    assert EventForm(form_data(vibe_category="JAM")).is_valid()  # no rule needed elsewhere, defaults to 0
