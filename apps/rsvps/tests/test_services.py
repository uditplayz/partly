import threading
from datetime import timedelta

import pytest
from django.core import mail
from django.db import IntegrityError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.rsvps import services
from apps.rsvps.models import RSVP
from apps.rsvps.services import RSVPError
from apps.rsvps.tests.factories import one_seat_event

pytestmark = pytest.mark.django_db
S = RSVP.Status


def join(event, **kw):
    return services.request_rsvp(UserFactory(), event, **kw)


def statuses(event):
    return list(RSVP.objects.filter(event=event).order_by("requested_at", "id").values_list("status", flat=True))


# --- requesting --------------------------------------------------------------------
def test_open_event_with_room_confirms_and_emails_the_address(django_capture_on_commit_callbacks):
    event = EventFactory(capacity=4)
    with django_capture_on_commit_callbacks(execute=True):
        rsvp = join(event)
    assert rsvp.status == S.CONFIRMED and rsvp.confirmed_at
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [rsvp.user.email] and event.exact_address in mail.outbox[0].body


def test_no_email_if_the_transaction_rolls_back(django_capture_on_commit_callbacks):
    event = EventFactory()
    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                join(event)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
    assert mail.outbox == [] and not RSVP.objects.exists()


def test_approval_event_goes_pending_and_emails_the_host(django_capture_on_commit_callbacks):
    event = EventFactory(requires_host_approval=True)
    with django_capture_on_commit_callbacks(execute=True):
        rsvp = join(event, note="Kabir's flatmate")
    assert rsvp.status == S.PENDING_APPROVAL
    assert mail.outbox[0].to == [event.host.email]
    assert "Kabir's flatmate" in mail.outbox[0].body and event.exact_address not in mail.outbox[0].body
    assert event.address_for(rsvp.user) is None


def test_full_event_waitlists():
    event = EventFactory(capacity=2)
    assert [join(event).status for _ in range(3)] == [S.CONFIRMED, S.CONFIRMED, S.WAITLISTED]


def test_plus_ones_count_as_seats():
    event = EventFactory(capacity=4, max_plus_ones=2)
    assert join(event, plus_ones=2).status == S.CONFIRMED  # 3 of 4 taken
    assert join(event, plus_ones=1).status == S.WAITLISTED  # needs 2, 1 left
    assert join(event).status == S.CONFIRMED  # a single still fits
    assert services.seats_used(event) == 4


def test_guards():
    host_event = EventFactory()
    with pytest.raises(RSVPError, match="hosting"):
        services.request_rsvp(host_event.host, host_event)
    with pytest.raises(RSVPError, match="isn't open"):
        join(EventFactory(draft=True))
    with pytest.raises(RSVPError, match="isn't open"):
        join(EventFactory(status=Event.Status.CANCELLED))
    with pytest.raises(RSVPError, match="plus-ones"):
        join(EventFactory(max_plus_ones=0), plus_ones=1)
    with pytest.raises(RSVPError, match="up to 2"):
        join(EventFactory(max_plus_ones=2), plus_ones=3)


def test_deadline_guard():
    start = timezone.now() + timedelta(hours=5)
    closed = EventFactory(start_time=start, rsvp_deadline=timezone.now() - timedelta(minutes=1))
    with pytest.raises(RSVPError, match="closed"):
        join(closed)


def test_cannot_rsvp_twice():
    event = EventFactory(capacity=2)
    user = UserFactory()
    services.request_rsvp(user, event)
    with pytest.raises(RSVPError, match="already have a spot"):
        services.request_rsvp(user, event)
    assert RSVP.objects.count() == 1


# --- host decisions ------------------------------------------------------------------
def test_approve_confirms_or_waitlists_when_full():
    event = EventFactory(capacity=2, requires_host_approval=True)
    a, b, c = join(event), join(event), join(event)
    assert services.seats_used(event) == 0  # pending requests hold no seats
    assert services.approve(a.pk, event.host).status == S.CONFIRMED
    assert services.approve(b.pk, event.host).status == S.CONFIRMED
    assert services.approve(c.pk, event.host).status == S.WAITLISTED
    with pytest.raises(RSVPError, match="already handled"):
        services.approve(a.pk, event.host)


def test_only_the_host_can_approve_or_decline():
    event = EventFactory(requires_host_approval=True)
    rsvp = join(event)
    stranger = UserFactory()
    with pytest.raises(RSVP.DoesNotExist):
        services.approve(rsvp.pk, stranger)
    with pytest.raises(RSVP.DoesNotExist):
        services.decline(rsvp.pk, stranger)
    rsvp.refresh_from_db()
    assert rsvp.status == S.PENDING_APPROVAL


def test_decline_blocks_a_new_request_and_rotates_the_token():
    event = EventFactory(requires_host_approval=True)
    rsvp = join(event)
    old_token = rsvp.checkin_token
    declined = services.decline(rsvp.pk, event.host)
    assert declined.status == S.DECLINED and declined.checkin_token != old_token
    with pytest.raises(RSVPError, match="couldn't fit"):
        services.request_rsvp(rsvp.user, event)


def test_removing_a_confirmed_guest_promotes_the_waitlist():
    event = one_seat_event()
    first, second = join(event), join(event)
    services.decline(first.pk, event.host)
    second.refresh_from_db()
    assert second.status == S.CONFIRMED


def test_cannot_remove_a_checked_in_guest():
    event = EventFactory()
    rsvp = join(event)
    RSVP.objects.filter(pk=rsvp.pk).update(checked_in=True, checked_in_at=timezone.now())
    with pytest.raises(RSVPError, match="checked in"):
        services.decline(rsvp.pk, event.host)


# --- cancelling, re-entry and the waitlist ---------------------------------------------
def test_cancel_resets_the_pass_and_re_rsvp_reuses_the_row():
    event = EventFactory(capacity=3)
    user = UserFactory()
    rsvp = services.request_rsvp(user, event)
    now = timezone.now()
    RSVP.objects.filter(pk=rsvp.pk).update(checked_in=True, checked_in_at=now, reminder_24h_sent_at=now, reminder_2h_sent_at=now)
    first_token = rsvp.checkin_token

    cancelled = services.cancel(event, user)
    assert cancelled.status == S.CANCELLED and cancelled.checkin_token != first_token
    assert (cancelled.checked_in, cancelled.checked_in_at, cancelled.confirmed_at) == (False, None, None)
    assert (cancelled.reminder_24h_sent_at, cancelled.reminder_2h_sent_at) == (None, None)

    again = services.request_rsvp(user, event)
    assert again.pk == rsvp.pk and RSVP.objects.count() == 1
    assert again.status == S.CONFIRMED and again.checkin_token not in (first_token, cancelled.checkin_token)
    assert again.reminder_2h_sent_at is None and not again.checked_in

    with pytest.raises(RSVPError, match="don't have an RSVP"):
        services.cancel(event, UserFactory())


def test_waitlist_is_first_come_first_served():
    event = EventFactory(capacity=2)
    a, b, w1, w2, w3 = (join(event) for _ in range(5))
    services.cancel(event, a.user)
    assert statuses(event) == [S.CANCELLED, S.CONFIRMED, S.CONFIRMED, S.WAITLISTED, S.WAITLISTED]
    services.cancel(event, b.user)
    w2.refresh_from_db()
    w3.refresh_from_db()
    assert (w2.status, w3.status) == (S.CONFIRMED, S.WAITLISTED)


def test_a_party_that_does_not_fit_is_skipped_not_blocking():
    event = EventFactory(capacity=2, max_plus_ones=2)
    a, b = join(event), join(event)
    big = join(event, plus_ones=1)  # needs 2
    solo = join(event)
    services.cancel(event, a.user)  # frees 1
    big.refresh_from_db()
    solo.refresh_from_db()
    assert (big.status, solo.status) == (S.WAITLISTED, S.CONFIRMED)
    assert services.seats_used(event) == 2


def test_rejoining_goes_to_the_back_of_the_waitlist():
    event = one_seat_event()
    holder, early, late = join(event), join(event), join(event)
    services.cancel(event, early.user)
    services.request_rsvp(early.user, event)  # back in, but behind `late`
    services.cancel(event, holder.user)
    late.refresh_from_db()
    early.refresh_from_db()
    assert (late.status, early.status) == (S.CONFIRMED, S.WAITLISTED)


def test_approved_but_waitlisted_guest_is_promoted_without_asking_again():
    event = one_seat_event(requires_host_approval=True)
    a, b = join(event), join(event)
    services.approve(a.pk, event.host)
    assert services.approve(b.pk, event.host).status == S.WAITLISTED
    services.cancel(event, a.user)
    b.refresh_from_db()
    assert b.status == S.CONFIRMED


def test_raising_capacity_promotes_and_lowering_below_confirmed_is_refused(client):
    event = EventFactory(capacity=2)
    a, b, c = join(event), join(event), join(event)
    client.force_login(event.host)
    start = timezone.localtime(event.start_time)

    def edit(capacity):
        fmt = "%Y-%m-%dT%H:%M"
        return client.post(reverse("events:edit", args=[event.slug]), {
            "title": event.title, "vibe_category": event.vibe_category, "description": "x", "area_name": event.area_name,
            "exact_address": event.exact_address, "start_time": start.strftime(fmt),
            "end_time": (start + timedelta(hours=3)).strftime(fmt), "rsvp_deadline": "", "capacity": str(capacity),
            "max_plus_ones": "0", "is_free_entry": "on", "venue_entry_fee_inr": "", "entry_fee_notes": "",
        })

    assert edit(3).status_code == 302
    c.refresh_from_db()
    assert c.status == S.CONFIRMED
    resp = edit(2)
    assert resp.status_code == 200 and "capacity" in resp.context["form"].errors


def test_host_cancelling_the_event_releases_everyone():
    event = EventFactory(capacity=2)
    a, b = join(event), join(event)
    token = a.checkin_token
    with pytest.raises(RSVPError):
        services.host_cancel_event(event, UserFactory())
    assert services.host_cancel_event(event, event.host) == 2
    event.refresh_from_db()
    a.refresh_from_db()
    assert event.status == Event.Status.CANCELLED
    assert statuses(event) == [S.CANCELLED, S.CANCELLED] and a.checkin_token != token
    with pytest.raises(RSVPError):
        join(event)


# --- address and counters ----------------------------------------------------------------
def test_only_confirmed_guests_get_the_address():
    event = one_seat_event()
    confirmed, waitlisted = join(event), join(event)
    assert event.address_for(confirmed.user) == event.exact_address
    assert event.address_for(waitlisted.user) is None
    services.cancel(event, confirmed.user)
    assert event.address_for(confirmed.user) is None
    assert event.address_for(waitlisted.user) == event.exact_address  # promoted


def test_feed_counts_confirmed_seats_and_open_filter_hides_full_events(client):
    roomy = EventFactory(title="roomy", capacity=4, max_plus_ones=1)
    full = EventFactory(title="packed", capacity=2)
    join(roomy, plus_ones=1)
    join(full), join(full), join(full)
    by_title = {e.title: e for e in Event.objects.with_seats()}
    assert (by_title["roomy"].seats_used, by_title["roomy"].spots_left) == (2, 2)
    assert (by_title["packed"].seats_used, by_title["packed"].spots_left) == (2, 0)

    html = client.get(reverse("events:feed")).content.decode()
    assert "2/4 left" in html and "Full" in html
    open_only = client.get(reverse("events:feed") + "?open=1").content.decode()
    assert "roomy" in open_only and "packed" not in open_only


def test_database_refuses_check_in_without_confirmation():
    rsvp = join(one_seat_event())
    waitlisted = join(rsvp.event)
    with pytest.raises(IntegrityError), transaction.atomic():
        RSVP.objects.filter(pk=waitlisted.pk).update(checked_in=True)


def test_database_allows_one_rsvp_per_user_per_event():
    rsvp = join(EventFactory())
    with pytest.raises(IntegrityError), transaction.atomic():
        RSVP.objects.create(event=rsvp.event, user=rsvp.user)


# --- concurrency ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_ten_people_racing_for_the_last_two_seats():
    event = EventFactory(capacity=4)
    join(event), join(event)  # two seats left
    racers = [UserFactory() for _ in range(10)]
    barrier = threading.Barrier(len(racers))
    errors = []

    def go(user):
        try:
            barrier.wait(timeout=15)
            services.request_rsvp(user, event)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=go, args=(u,)) for u in racers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    racer_statuses = list(RSVP.objects.filter(user__in=racers).values_list("status", flat=True))
    assert racer_statuses.count(S.CONFIRMED) == 2
    assert racer_statuses.count(S.WAITLISTED) == 8
    assert services.seats_used(event) == event.capacity
