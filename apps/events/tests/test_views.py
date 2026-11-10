from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.models import Event
from apps.events.tests.factories import EventFactory

pytestmark = pytest.mark.django_db
DT = "%Y-%m-%dT%H:%M"


def form_data(**overrides):
    start = timezone.localtime() + timedelta(days=3)
    data = {
        "title": "Rooftop jam",
        "vibe_category": "JAM",
        "description": "Bring a guitar",
        "area_name": "Koregaon Park",
        "exact_address": "Flat 9, Lane 6",
        "start_time": start.strftime(DT),
        "end_time": (start + timedelta(hours=3)).strftime(DT),
        "rsvp_deadline": "",
        "capacity": "12",
        "max_plus_ones": "1",
        "is_free_entry": "on",
        "venue_entry_fee_inr": "",
        "entry_fee_notes": "",
    }
    data.update(overrides)
    return data


# --- create -----------------------------------------------------------------------
def test_create_requires_login(client):
    resp = client.get(reverse("events:create"))
    assert resp.status_code == 302 and "/accounts/login/" in resp.url


def test_create_saves_a_draft(auth_client, user):
    resp = auth_client.post(reverse("events:create"), form_data())
    event = Event.objects.get()
    assert resp.status_code == 302 and resp.url == event.get_absolute_url()
    assert event.host == user
    assert event.status == Event.Status.DRAFT
    assert event.platform_fee_status == Event.FeeStatus.PENDING
    assert event.rsvp_deadline == event.start_time  # defaulted
    assert event.venue_entry_fee_inr == 0


def test_create_paid_event(auth_client):
    auth_client.post(reverse("events:create"), form_data(is_free_entry="", venue_entry_fee_inr="250", entry_fee_notes="UPI at door"))
    event = Event.objects.get()
    assert not event.is_free_entry and event.venue_entry_fee_inr == 250


def test_free_toggle_clears_fee(auth_client):
    auth_client.post(reverse("events:create"), form_data(venue_entry_fee_inr="300"))
    assert Event.objects.get().venue_entry_fee_inr == 0


@pytest.mark.parametrize("overrides, field", [
    ({"is_free_entry": "", "venue_entry_fee_inr": "0"}, "venue_entry_fee_inr"),
    ({"capacity": "1"}, "capacity"),
    ({"capacity": "101"}, "capacity"),
    ({"max_plus_ones": "6"}, "max_plus_ones"),
    ({"start_time": (timezone.localtime() - timedelta(hours=1)).strftime(DT)}, "start_time"),
])
def test_create_validation(auth_client, overrides, field):
    resp = auth_client.post(reverse("events:create"), form_data(**overrides))
    assert resp.status_code == 200
    assert field in resp.context["form"].errors
    assert not Event.objects.exists()


def test_end_before_start_rejected(auth_client):
    data = form_data()
    data["end_time"] = data["start_time"]
    resp = auth_client.post(reverse("events:create"), data)
    assert "end_time" in resp.context["form"].errors


def test_deadline_after_start_rejected(auth_client):
    data = form_data()
    data["rsvp_deadline"] = data["end_time"]
    resp = auth_client.post(reverse("events:create"), data)
    assert "rsvp_deadline" in resp.context["form"].errors


# --- detail ------------------------------------------------------------------------
def test_published_detail_is_public_but_hides_address(client):
    event = EventFactory()
    html = client.get(event.get_absolute_url()).content.decode()
    assert event.title in html
    assert event.exact_address not in html
    assert "Unlocks once" in html


def test_host_sees_address_on_detail(client):
    event = EventFactory()
    client.force_login(event.host)
    html = client.get(event.get_absolute_url()).content.decode()
    assert event.exact_address in html and "Edit" in html


def test_draft_detail_only_for_host(client):
    draft = EventFactory(draft=True)
    assert client.get(draft.get_absolute_url()).status_code == 404
    client.force_login(UserFactory())
    assert client.get(draft.get_absolute_url()).status_code == 404
    client.force_login(draft.host)
    assert client.get(draft.get_absolute_url()).status_code == 200


# --- edit / delete -------------------------------------------------------------------
def test_edit_is_host_only(client):
    event = EventFactory()
    url = reverse("events:edit", args=[event.slug])
    client.force_login(UserFactory())
    assert client.get(url).status_code == 404
    client.force_login(event.host)
    assert client.get(url).status_code == 200


def test_edit_updates_event(client):
    event = EventFactory(draft=True, title="Old")
    client.force_login(event.host)
    resp = client.post(reverse("events:edit", args=[event.slug]), form_data(title="New title"))
    assert resp.status_code == 302
    event.refresh_from_db()
    assert event.title == "New title" and event.status == Event.Status.DRAFT


def test_cancelled_event_cannot_be_edited(client):
    event = EventFactory(status=Event.Status.CANCELLED)
    client.force_login(event.host)
    resp = client.get(reverse("events:edit", args=[event.slug]))
    assert resp.status_code == 302 and resp.url == event.get_absolute_url()


def test_edit_anonymous_redirects_to_login(client):
    event = EventFactory()
    resp = client.get(reverse("events:edit", args=[event.slug]))
    assert resp.status_code == 302 and "/accounts/login/" in resp.url


def test_delete_draft(client):
    draft = EventFactory(draft=True)
    client.force_login(draft.host)
    resp = client.post(reverse("events:delete", args=[draft.slug]))
    assert resp.status_code == 302 and not Event.objects.filter(pk=draft.pk).exists()


def test_cannot_delete_published_or_others(client):
    event = EventFactory()
    client.force_login(event.host)
    client.post(reverse("events:delete", args=[event.slug]))
    assert Event.objects.filter(pk=event.pk).exists()

    draft = EventFactory(draft=True)
    client.force_login(UserFactory())
    assert client.post(reverse("events:delete", args=[draft.slug])).status_code == 404
    assert client.get(reverse("events:delete", args=[draft.slug])).status_code == 405


# --- my hosting --------------------------------------------------------------------------
def test_my_hosting_requires_login(client):
    assert client.get(reverse("events:my_hosting")).status_code == 302


def test_my_hosting_groups(auth_client, user):
    past = timezone.now() - timedelta(days=3)
    EventFactory(host=user, title="live-one")
    EventFactory(host=user, title="draft-one", draft=True)
    EventFactory(host=user, title="past-one", start_time=past, end_time=past + timedelta(hours=2), rsvp_deadline=past)
    EventFactory(host=user, title="cancelled-one", status=Event.Status.CANCELLED)
    EventFactory(title="someone-elses")
    ctx = auth_client.get(reverse("events:my_hosting")).context
    assert [e.title for e in ctx["live"]] == ["live-one"]
    assert [e.title for e in ctx["drafts"]] == ["draft-one"]
    assert {e.title for e in ctx["past"]} == {"past-one", "cancelled-one"}


def test_nav_points_at_events(client):
    html = client.get(reverse("events:feed")).content.decode()
    assert 'href="/events/new/"' in html and 'bottom-nav__item is-active" href="/"' in html
