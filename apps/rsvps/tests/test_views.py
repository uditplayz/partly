from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.rsvps import services
from apps.rsvps.models import RSVP

pytestmark = pytest.mark.django_db
S = RSVP.Status


def page(client, event):
    return client.get(event.get_absolute_url()).content.decode()


# --- guest flow -------------------------------------------------------------------------
def test_rsvp_requires_login_and_post(client):
    event = EventFactory()
    url = reverse("rsvps:create", args=[event.slug])
    resp = client.post(url)
    assert resp.status_code == 302 and "/accounts/login/" in resp.url
    client.force_login(UserFactory())
    assert client.get(url).status_code == 405
    assert not RSVP.objects.exists()


def test_anonymous_event_page_prompts_login(client):
    event = EventFactory()
    html = page(client, event)
    assert "Log in to RSVP" in html and event.exact_address not in html


def test_rsvp_unlocks_address_and_cancel_locks_it_again(auth_client, user):
    event = EventFactory(max_plus_ones=2)
    assert "I'm in" in page(auth_client, event)
    resp = auth_client.post(reverse("rsvps:create", args=[event.slug]), {"plus_ones": "2"})
    assert resp.url == event.get_absolute_url()
    rsvp = RSVP.objects.get(user=user)
    assert (rsvp.status, rsvp.plus_ones) == (S.CONFIRMED, 2)

    html = page(auth_client, event)
    assert event.exact_address in html and "You're in" in html and "Cancel my RSVP" in html

    auth_client.post(reverse("rsvps:cancel", args=[event.slug]))
    html = page(auth_client, event)
    assert event.exact_address not in html and "I'm in" in html


def test_pending_and_waitlisted_guests_do_not_see_the_address(auth_client, user):
    screened = EventFactory(requires_host_approval=True)
    assert "Request to join" in page(auth_client, screened)
    auth_client.post(reverse("rsvps:create", args=[screened.slug]), {"note": "Friend of Meera"})
    html = page(auth_client, screened)
    assert "Waiting for the host" in html and screened.exact_address not in html
    assert RSVP.objects.get(user=user).note_to_host == "Friend of Meera"

    full = EventFactory(capacity=2)
    services.request_rsvp(UserFactory(), full), services.request_rsvp(UserFactory(), full)
    assert "Join the waitlist" in page(auth_client, full)
    auth_client.post(reverse("rsvps:create", args=[full.slug]))
    html = page(auth_client, full)
    assert "on the waitlist" in html and full.exact_address not in html


def test_bad_plus_ones_and_closed_events_are_refused(auth_client):
    event = EventFactory(max_plus_ones=1)
    auth_client.post(reverse("rsvps:create", args=[event.slug]), {"plus_ones": "4"})
    auth_client.post(reverse("rsvps:create", args=[event.slug]), {"plus_ones": "99"})
    assert not RSVP.objects.exists()

    closed = EventFactory(start_time=timezone.now() + timedelta(hours=3), rsvp_deadline=timezone.now() - timedelta(minutes=5))
    assert "RSVPs are closed" in page(auth_client, closed)
    auth_client.post(reverse("rsvps:create", args=[closed.slug]))
    assert not RSVP.objects.exists()
    assert auth_client.post(reverse("rsvps:create", args=[EventFactory(draft=True).slug])).status_code == 404


def test_host_sees_manage_link_not_the_rsvp_box(client):
    event = EventFactory(requires_host_approval=True)
    services.request_rsvp(UserFactory(), event)
    client.force_login(event.host)
    html = page(client, event)
    assert "Manage guests · 1 waiting" in html and "Request to join" not in html and "Cancel event" in html


# --- My Tickets -----------------------------------------------------------------------------
def test_my_tickets_requires_login(client):
    resp = client.get(reverse("rsvps:tickets"))
    assert resp.status_code == 302 and "/accounts/login/" in resp.url


def test_my_tickets_shows_address_only_when_confirmed(auth_client, user):
    going = EventFactory(title="Going there")
    screened = EventFactory(title="Awaiting answer", requires_host_approval=True)
    dropped = EventFactory(title="Changed my mind")
    services.request_rsvp(user, going)
    services.request_rsvp(user, screened)
    services.request_rsvp(user, dropped)
    services.cancel(dropped, user)
    someone_elses = EventFactory(title="Not mine")
    services.request_rsvp(UserFactory(), someone_elses)

    html = auth_client.get(reverse("rsvps:tickets")).content.decode()
    assert "Going there" in html and going.exact_address in html
    assert "Awaiting answer" in html and screened.exact_address not in html and "Waiting for host" in html
    assert "Changed my mind" not in html and "Not mine" not in html


def test_my_tickets_empty_state_and_cancelled_events_drop_off(auth_client, user):
    assert "No plans yet" in auth_client.get(reverse("rsvps:tickets")).content.decode()
    event = EventFactory(title="Called off")
    services.request_rsvp(user, event)
    services.host_cancel_event(event, event.host)
    assert "Called off" not in auth_client.get(reverse("rsvps:tickets")).content.decode()


# --- host flow --------------------------------------------------------------------------------
def test_manage_page_is_host_only(client):
    event = EventFactory()
    url = reverse("rsvps:manage", args=[event.slug])
    assert client.get(url).status_code == 302
    client.force_login(UserFactory())
    assert client.get(url).status_code == 404
    client.force_login(event.host)
    assert client.get(url).status_code == 200


def test_host_approves_and_declines_from_the_manage_page(client):
    event = EventFactory(capacity=5, requires_host_approval=True)
    yes = services.request_rsvp(UserFactory(display_name="Asha Rao"), event, note="From the jam last week")
    no = services.request_rsvp(UserFactory(display_name="Bilal Khan"), event)
    client.force_login(event.host)
    manage = reverse("rsvps:manage", args=[event.slug])
    html = client.get(manage).content.decode()
    assert "Asha Rao" in html and "From the jam last week" in html and "Approve" in html

    assert client.post(reverse("rsvps:approve", args=[yes.pk])).url == manage
    assert client.post(reverse("rsvps:decline", args=[no.pk])).url == manage
    yes.refresh_from_db()
    no.refresh_from_db()
    assert (yes.status, no.status) == (S.CONFIRMED, S.DECLINED)
    ctx = client.get(manage).context
    assert [r.user.name for r in ctx["confirmed"]] == ["Asha Rao"] and ctx["pending"] == []
    assert ctx["event"].seats_used == 1


def test_other_users_cannot_approve_or_decline(client):
    event = EventFactory(requires_host_approval=True)
    rsvp = services.request_rsvp(UserFactory(), event)
    client.force_login(UserFactory())
    assert client.post(reverse("rsvps:approve", args=[rsvp.pk])).status_code == 404
    assert client.post(reverse("rsvps:decline", args=[rsvp.pk])).status_code == 404
    assert client.get(reverse("rsvps:approve", args=[rsvp.pk])).status_code == 405
    rsvp.refresh_from_db()
    assert rsvp.status == S.PENDING_APPROVAL


def test_host_cancels_event(client):
    event = EventFactory()
    guest = services.request_rsvp(UserFactory(), event)
    url = reverse("rsvps:cancel_event", args=[event.slug])
    client.force_login(UserFactory())
    assert client.post(url).status_code == 404
    client.force_login(event.host)
    assert client.post(url).url == event.get_absolute_url()
    event.refresh_from_db()
    guest.refresh_from_db()
    assert event.status == Event.Status.CANCELLED and guest.status == S.CANCELLED
    assert event.title not in client.get(reverse("events:feed")).content.decode()


def test_nav_and_offline_page_point_at_my_tickets(auth_client):
    html = auth_client.get(reverse("rsvps:tickets")).content.decode()
    assert 'bottom-nav__item is-active" href="/tickets/"' in html
    assert 'href="/tickets/"' in auth_client.get(reverse("core:offline")).content.decode()
