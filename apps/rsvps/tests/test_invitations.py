import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.events.tests.factories import EventFactory
from apps.rsvps import services
from apps.rsvps.models import RSVP, Invitation
from apps.rsvps.services import RSVPError
from apps.rsvps.tests.factories import one_seat_event

pytestmark = pytest.mark.django_db
S = RSVP.Status


def invite(event, email):
    return services.create_invitation(event, event.host, email)[0]


# --- creating ---------------------------------------------------------------------------
def test_invite_emails_a_link_and_marks_it_sent(django_capture_on_commit_callbacks):
    event = EventFactory()
    with django_capture_on_commit_callbacks(execute=True):
        inv, created = services.create_invitation(event, event.host, "  Riya@College.edu ")
    inv.refresh_from_db()
    assert created and inv.invitee_email == "riya@college.edu" and inv.invitee_user is None and inv.sent_at
    message = mail.outbox[0]
    assert message.to == ["riya@college.edu"]
    assert reverse("rsvps:invitation", args=[inv.invite_token]) in message.body
    assert event.exact_address not in message.body


def test_invite_auto_links_an_existing_account_ignoring_case():
    event = EventFactory()
    friend = UserFactory(email="meera@example.com")
    assert invite(event, "MEERA@Example.com").invitee_user == friend


def test_inviting_twice_returns_the_first_invite():
    event = EventFactory()
    first = invite(event, "riya@college.edu")
    again, created = services.create_invitation(event, event.host, "RIYA@college.edu")
    assert not created and again.pk == first.pk and Invitation.objects.count() == 1


def test_invite_guards():
    event = EventFactory()
    with pytest.raises(RSVPError, match="Only the host"):
        services.create_invitation(event, UserFactory(), "x@example.com")
    with pytest.raises(RSVPError, match="your own"):
        services.create_invitation(event, event.host, event.host.email.upper())
    draft = EventFactory(draft=True)
    with pytest.raises(RSVPError, match="Publish"):
        services.create_invitation(draft, draft.host, "x@example.com")


def test_database_constraints():
    event = EventFactory()
    user = UserFactory()
    Invitation.objects.create(event=event, invited_by=event.host, invitee_email="a@example.com")
    Invitation.objects.create(event=event, invited_by=event.host, invitee_email="b@example.com")  # both have no user: fine
    with pytest.raises(IntegrityError), transaction.atomic():
        Invitation.objects.create(event=event, invited_by=event.host, invitee_email="A@Example.com")
    Invitation.objects.create(event=event, invited_by=event.host, invitee_email="c@example.com", invitee_user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Invitation.objects.create(event=event, invited_by=event.host, invitee_email="d@example.com", invitee_user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Invitation.objects.create(event=event, invited_by=event.host)  # nobody invited


# --- accepting ---------------------------------------------------------------------------
def test_accepting_skips_approval():
    event = EventFactory(requires_host_approval=True)
    friend = UserFactory()
    inv = invite(event, friend.email)
    rsvp = services.accept_invitation(inv.invite_token, friend)
    inv.refresh_from_db()
    assert rsvp.status == S.CONFIRMED and rsvp.via_invitation == inv
    assert inv.status == Invitation.Status.ACCEPTED and inv.responded_at and inv.invitee_user == friend


def test_accepting_still_respects_capacity():
    event = one_seat_event(requires_host_approval=True)
    services.approve(services.request_rsvp(UserFactory(), event).pk, event.host)  # takes the last seat
    friend = UserFactory()
    rsvp = services.accept_invitation(invite(event, friend.email).invite_token, friend)
    assert rsvp.status == S.WAITLISTED and services.seats_used(event) == 2


def test_accepting_upgrades_a_pending_request():
    event = EventFactory(requires_host_approval=True)
    friend = UserFactory()
    pending = services.request_rsvp(friend, event)
    old_token = pending.checkin_token
    rsvp = services.accept_invitation(invite(event, friend.email).invite_token, friend)
    assert rsvp.pk == pending.pk and rsvp.status == S.CONFIRMED and rsvp.checkin_token != old_token


def test_invite_overrides_an_earlier_decline():
    event = EventFactory(requires_host_approval=True)
    friend = UserFactory()
    services.decline(services.request_rsvp(friend, event).pk, event.host)
    assert services.accept_invitation(invite(event, friend.email).invite_token, friend).status == S.CONFIRMED


def test_invite_only_works_for_the_invited_person():
    event = EventFactory(requires_host_approval=True)
    friend = UserFactory()
    linked = invite(event, friend.email)
    by_email = invite(event, "notyet@example.com")
    stranger = UserFactory()
    with pytest.raises(RSVPError, match="different account"):
        services.accept_invitation(linked.invite_token, stranger)
    with pytest.raises(RSVPError, match="notyet@example.com"):
        services.accept_invitation(by_email.invite_token, stranger)
    assert not RSVP.objects.exists()

    late_signup = UserFactory(email="NotYet@example.com")
    assert services.accept_invitation(by_email.invite_token, late_signup).status == S.CONFIRMED


def test_used_invite_cannot_be_reused_after_cancelling():
    event = EventFactory(requires_host_approval=True)
    friend = UserFactory()
    inv = invite(event, friend.email)
    services.accept_invitation(inv.invite_token, friend)
    assert services.accept_invitation(inv.invite_token, friend).status == S.CONFIRMED  # harmless repeat
    services.cancel(event, friend)
    with pytest.raises(RSVPError, match="already been used"):
        services.accept_invitation(inv.invite_token, friend)


def test_declining_an_invite():
    event = EventFactory()
    friend = UserFactory()
    inv = invite(event, friend.email)
    assert services.decline_invitation(inv.invite_token, friend).status == Invitation.Status.DECLINED
    with pytest.raises(RSVPError, match="already responded"):
        services.decline_invitation(inv.invite_token, friend)
    assert not RSVP.objects.exists()


# --- pages ---------------------------------------------------------------------------------
def test_landing_page_for_anonymous_visitor(client):
    event = EventFactory()
    inv = invite(event, "riya@college.edu")
    url = reverse("rsvps:invitation", args=[inv.invite_token])
    html = client.get(url).content.decode()
    assert event.title in html and "Log in to respond" in html and event.exact_address not in html
    resp = client.post(url, {"action": "accept"})
    assert resp.status_code == 302 and "/accounts/login/" in resp.url and not RSVP.objects.exists()


def test_accept_and_decline_through_the_page(client):
    event = EventFactory(requires_host_approval=True, max_plus_ones=2)
    friend = UserFactory()
    inv = invite(event, friend.email)
    client.force_login(friend)
    url = reverse("rsvps:invitation", args=[inv.invite_token])
    assert "Accept invite" in client.get(url).content.decode()
    resp = client.post(url, {"action": "accept", "plus_ones": "1"})
    assert resp.url == event.get_absolute_url()
    rsvp = RSVP.objects.get()
    assert (rsvp.status, rsvp.plus_ones) == (S.CONFIRMED, 1)
    assert event.exact_address in client.get(event.get_absolute_url()).content.decode()

    other = invite(EventFactory(), friend.email)
    resp = client.post(reverse("rsvps:invitation", args=[other.invite_token]), {"action": "decline"})
    other.refresh_from_db()
    assert resp.url == reverse("events:feed") and other.status == Invitation.Status.DECLINED


def test_wrong_account_sees_why_and_cannot_accept(client):
    event = EventFactory()
    inv = invite(event, "riya@college.edu")
    client.force_login(UserFactory())
    url = reverse("rsvps:invitation", args=[inv.invite_token])
    html = client.get(url).content.decode()
    assert "riya@college.edu" in html and "Accept invite" not in html
    client.post(url, {"action": "accept"})
    assert not RSVP.objects.exists()


def test_unknown_invite_is_a_404(client):
    assert client.get("/invite/00000000-0000-4000-8000-000000000000/").status_code == 404


def test_host_invite_form(client):
    event = EventFactory()
    url = reverse("rsvps:invite", args=[event.slug])
    client.force_login(UserFactory())
    assert client.post(url, {"emails": "a@example.com"}).status_code == 404
    client.force_login(event.host)
    assert client.get(url).status_code == 405

    client.post(url, {"emails": "a@example.com, B@example.com\na@example.com"})
    assert sorted(Invitation.objects.values_list("invitee_email", flat=True)) == ["a@example.com", "b@example.com"]
    client.post(url, {"emails": "a@example.com; not-an-email"})
    client.post(url, {"emails": "a@example.com c@example.com"})
    assert Invitation.objects.count() == 3
    html = client.get(reverse("rsvps:manage", args=[event.slug])).content.decode()
    assert "c@example.com" in html
