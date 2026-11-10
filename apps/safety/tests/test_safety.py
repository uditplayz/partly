import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.rsvps import services as rsvp_services
from apps.rsvps.models import RSVP
from apps.safety import services
from apps.safety.models import Block, Report

pytestmark = pytest.mark.django_db
S = RSVP.Status


# --- reports --------------------------------------------------------------------------------
def test_report_an_event_and_a_member(client):
    me, host = UserFactory(), UserFactory()
    event = EventFactory(host=host)
    client.force_login(me)
    resp = client.post(reverse("safety:report", args=["event", event.slug]), {"reason": "UNSAFE", "details": "Strangers at the door"})
    assert resp.status_code == 302
    resp = client.post(reverse("safety:report", args=["user", host.username]), {"reason": "SCAM"})
    assert resp.status_code == 302
    assert Report.objects.filter(reporter=me, event=event, reason="UNSAFE").exists()
    assert Report.objects.filter(reporter=me, user=host, reason="SCAM").exists()


def test_reports_need_login_and_a_valid_reason(client):
    event = EventFactory()
    url = reverse("safety:report", args=["event", event.slug])
    assert client.get(url).status_code == 302 and "/accounts/login/" in client.get(url).url
    client.force_login(UserFactory())
    assert client.post(url, {"reason": "NOPE"}).status_code == 200
    assert not Report.objects.exists()


def test_one_open_report_per_person_per_target_and_no_self_reports(client):
    me, host = UserFactory(), UserFactory()
    event = EventFactory(host=host)
    services.create_report(me, reason="OTHER", event=event)
    with pytest.raises(services.SafetyError):
        services.create_report(me, reason="SCAM", event=event)
    with pytest.raises(services.SafetyError):
        services.create_report(host, reason="OTHER", event=event)
    with pytest.raises(services.SafetyError):
        services.create_report(me, reason="OTHER", user=me)
    # once handled, the same person can report again
    report = Report.objects.get()
    services.resolve(report, Report.Status.DISMISSED)
    services.create_report(me, reason="OTHER", event=event)


def test_a_report_must_have_exactly_one_target():
    me = UserFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(reporter=me, reason="OTHER")
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(reporter=me, reason="OTHER", event=EventFactory(), user=UserFactory())


def test_drafts_cannot_be_reported_and_404(client):
    client.force_login(UserFactory())
    assert client.get(reverse("safety:report", args=["event", EventFactory(draft=True).slug])).status_code == 404


# --- blocking -------------------------------------------------------------------------------
def test_host_blocking_a_guest_removes_their_spot_and_frees_it():
    host, pest, waiting = UserFactory(), UserFactory(), UserFactory()
    event = EventFactory(host=host, capacity=2)
    held = rsvp_services.request_rsvp(pest, event)
    rsvp_services.request_rsvp(UserFactory(), event)
    queued = rsvp_services.request_rsvp(waiting, event)
    assert queued.status == S.WAITLISTED
    assert services.block(host, pest) is True
    held.refresh_from_db(), queued.refresh_from_db()
    assert held.status == S.DECLINED and queued.status == S.CONFIRMED  # the waitlist moved up


def test_blocking_works_both_ways_for_rsvps():
    host, guest = UserFactory(), UserFactory()
    event = EventFactory(host=host)
    services.block(guest, host)
    with pytest.raises(rsvp_services.RSVPError, match="can't join"):
        rsvp_services.request_rsvp(guest, event)
    other = EventFactory(host=guest)
    with pytest.raises(rsvp_services.RSVPError, match="can't join"):
        rsvp_services.request_rsvp(host, other)


def test_guest_blocking_a_host_cancels_their_own_rsvp():
    host, guest = UserFactory(), UserFactory()
    event = EventFactory(host=host)
    rsvp = rsvp_services.request_rsvp(guest, event)
    services.block(guest, host)
    rsvp.refresh_from_db()
    assert rsvp.status == S.CANCELLED


def test_block_is_idempotent_not_self_and_unblock_restores():
    a, b = UserFactory(), UserFactory()
    assert services.block(a, b) is True and services.block(a, b) is False
    with pytest.raises(services.SafetyError):
        services.block(a, a)
    with pytest.raises(IntegrityError), transaction.atomic():
        Block.objects.create(blocker=a, blocked=a)
    assert services.unblock(a, b) is True and services.unblock(a, b) is False
    rsvp_services.request_rsvp(b, EventFactory(host=a))  # allowed again


def test_feed_hides_events_of_blocked_hosts_in_both_directions(client):
    me, blocked_host, blocker_host, fine = UserFactory(), UserFactory(), UserFactory(), UserFactory()
    for h in (blocked_host, blocker_host, fine):
        EventFactory(host=h, title=f"by {h.username}")
    Block.objects.create(blocker=me, blocked=blocked_host)
    Block.objects.create(blocker=blocker_host, blocked=me)
    client.force_login(me)
    html = client.get("/").content.decode()
    assert f"by {fine.username}" in html
    assert f"by {blocked_host.username}" not in html and f"by {blocker_host.username}" not in html
    client.logout()
    assert f"by {blocked_host.username}" in client.get("/").content.decode()  # anonymous visitors see all


def test_block_views(client):
    me, other = UserFactory(), UserFactory()
    client.force_login(me)
    assert client.get(reverse("safety:block", args=[other.username])).status_code == 405
    client.post(reverse("safety:block", args=[other.username]))
    assert Block.objects.filter(blocker=me, blocked=other).exists()
    assert other.name in client.get(reverse("safety:blocked")).content.decode()
    client.post(reverse("safety:unblock", args=[other.username]))
    assert not Block.objects.exists()


def test_profile_shows_report_and_block_to_other_members_only(client):
    me, other = UserFactory(), UserFactory()
    client.force_login(me)
    html = client.get(reverse("public_profile", args=[other.username])).content.decode()
    assert "Report " in html and "Block " in html
    html = client.get(reverse("public_profile", args=[me.username])).content.decode()
    assert "Delete my account" in html and "Block " not in html


# --- staff actions --------------------------------------------------------------------------
def test_staff_can_take_down_an_event_and_suspend_a_member(django_capture_on_commit_callbacks):
    host, guest = UserFactory(), UserFactory()
    event = EventFactory(host=host)
    rsvp = rsvp_services.request_rsvp(guest, event)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.take_down_event(event) is True
    event.refresh_from_db(), rsvp.refresh_from_db()
    assert event.status == Event.Status.CANCELLED and rsvp.status == S.CANCELLED

    second = EventFactory(host=host)
    services.suspend_user(host)
    host.refresh_from_db(), second.refresh_from_db()
    assert host.is_active is False and second.status == Event.Status.CANCELLED


def test_admin_actions_work(admin_client):
    reporter, host = UserFactory(), UserFactory()
    event = EventFactory(host=host)
    report = services.create_report(reporter, reason="UNSAFE", event=event)
    resp = admin_client.post(
        reverse("admin:safety_report_changelist"),
        {"action": "take_down_event", "_selected_action": [report.pk]},
        follow=True,
    )
    assert resp.status_code == 200
    report.refresh_from_db(), event.refresh_from_db()
    assert report.status == Report.Status.ACTIONED and event.status == Event.Status.CANCELLED
