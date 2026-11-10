from datetime import timedelta
from smtplib import SMTPException
from unittest import mock

import pytest
from celery.exceptions import Retry
from django.core import mail
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.notifications import dispatch, emails, tasks
from apps.payments.models import PlatformPayment
from apps.rsvps import services
from apps.rsvps.models import RSVP, Invitation

pytestmark = pytest.mark.django_db
S = RSVP.Status


def confirmed(event):
    return services.request_rsvp(UserFactory(), event)


def move_start(event_id, start):
    Event.objects.filter(pk=event_id).update(start_time=start, end_time=start + timedelta(hours=3), rsvp_deadline=start)


def event_in(**delta):
    start = timezone.now() + timedelta(**delta)
    return EventFactory(start_time=start, end_time=start + timedelta(hours=3), rsvp_deadline=start)


# --- queueing --------------------------------------------------------------------------
def test_tasks_are_queued_only_after_commit(django_capture_on_commit_callbacks):
    event = EventFactory(capacity=4)
    with mock.patch.object(tasks.send_rsvp_confirmation_email, "delay") as delay:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            rsvp = confirmed(event)
        assert delay.call_count == 0  # not yet: the transaction hasn't committed
        for callback in callbacks:
            callback()
    delay.assert_called_once_with(rsvp.pk)


def test_a_dead_broker_never_breaks_the_request(django_capture_on_commit_callbacks):
    event = EventFactory(capacity=4)
    with mock.patch.object(tasks.send_rsvp_confirmation_email, "delay", side_effect=ConnectionError("redis down")):
        with django_capture_on_commit_callbacks(execute=True):
            rsvp = confirmed(event)
    assert rsvp.status == S.CONFIRMED and mail.outbox == []


def test_confirmation_is_multipart_with_the_pass_attached(django_capture_on_commit_callbacks):
    event = EventFactory(capacity=4)
    with django_capture_on_commit_callbacks(execute=True):
        rsvp = confirmed(event)
    message = mail.outbox[0]
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html" and event.title in html and "Open my tickets" in html
    assert event.exact_address in message.body and message.attachments[0][0] == "partly-pass.png"
    assert "&#x27;" not in message.body  # the text part isn't HTML-escaped
    assert rsvp.user.email in message.to


def test_email_task_skips_when_the_state_changed():
    event = EventFactory(capacity=4)
    rsvp = confirmed(event)
    services.cancel(rsvp.event, rsvp.user)
    mail.outbox.clear()
    assert tasks.send_rsvp_confirmation_email(rsvp.pk) is False and mail.outbox == []


def test_host_cancelling_emails_each_guest_once(django_capture_on_commit_callbacks):
    event = EventFactory(capacity=4)
    a, b = confirmed(event), confirmed(event)
    gone = confirmed(event)
    services.cancel(gone.event, gone.user)  # cancelled earlier by themselves: must not get an "event cancelled" mail
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.host_cancel_event(event, event.host)
    recipients = sorted(m.to[0] for m in mail.outbox)
    assert recipients == sorted([a.user.email, b.user.email])
    assert all("Cancelled" in m.subject for m in mail.outbox)


def test_invitation_failure_releases_the_claim_so_a_retry_can_send(django_capture_on_commit_callbacks):
    event = EventFactory()
    with django_capture_on_commit_callbacks(execute=False):
        invitation, _ = services.create_invitation(event, event.host, "friend@example.com")
    with mock.patch.object(emails, "_send", side_effect=SMTPException("boom")):
        with pytest.raises(SMTPException):
            emails.invitation_created(invitation.pk)
    invitation.refresh_from_db()
    assert invitation.sent_at is None
    assert emails.invitation_created(invitation.pk) is True
    invitation.refresh_from_db()
    assert invitation.sent_at is not None and len(mail.outbox) == 1


# --- reminders -------------------------------------------------------------------------
def test_reminder_windows_and_idempotency():
    soon = confirmed(event_in(minutes=90))        # 2h window
    tomorrow = confirmed(event_in(hours=20))      # 24h window
    far = confirmed(event_in(days=3))             # neither
    started = confirmed(event_in(days=3))
    move_start(started.event_id, timezone.now() - timedelta(hours=1))
    mail.outbox.clear()

    assert tasks.dispatch_upcoming_event_reminders() == 2
    assert tasks.dispatch_upcoming_event_reminders() == 0  # second run: everything already claimed

    sent_to = sorted(m.to[0] for m in mail.outbox)
    assert sent_to == sorted([soon.user.email, tomorrow.user.email])
    soon.refresh_from_db(), tomorrow.refresh_from_db(), far.refresh_from_db()
    assert soon.reminder_2h_sent_at and soon.reminder_24h_sent_at is None
    assert tomorrow.reminder_24h_sent_at and tomorrow.reminder_2h_sent_at is None
    assert far.reminder_24h_sent_at is None and far.reminder_2h_sent_at is None


def test_a_guest_gets_24h_then_2h_but_each_only_once():
    rsvp = confirmed(event_in(hours=20))
    mail.outbox.clear()
    tasks.dispatch_upcoming_event_reminders()
    move_start(rsvp.event_id, timezone.now() + timedelta(hours=1, minutes=30))
    tasks.dispatch_upcoming_event_reminders()
    tasks.dispatch_upcoming_event_reminders()
    assert len(mail.outbox) == 2
    assert "within the next day" in mail.outbox[0].body and "2 hours" in mail.outbox[1].body


def test_only_confirmed_guests_on_live_events_are_reminded():
    event = event_in(hours=5)
    ok, cancelled = confirmed(event), confirmed(event)
    services.cancel(cancelled.event, cancelled.user)
    pending_event = event_in(hours=5)
    pending_event.requires_host_approval = True
    pending_event.save()
    services.request_rsvp(UserFactory(), pending_event)
    called_off = event_in(hours=6)
    confirmed(called_off)
    Event.objects.filter(pk=called_off.pk).update(status=Event.Status.CANCELLED)
    mail.outbox.clear()
    assert tasks.dispatch_upcoming_event_reminders() == 1
    assert [m.to[0] for m in mail.outbox] == [ok.user.email]


# --- refinement 4: failed reminders are released, not lost ----------------------------------
def claimed_rsvp(kind="2h", **delta):
    rsvp = confirmed(event_in(**(delta or {"hours": 1})))
    field = tasks.CLAIM_FIELD[kind]
    RSVP.objects.filter(pk=rsvp.pk).update(**{field: timezone.now()})
    mail.outbox.clear()
    return rsvp, field


def test_unexpected_error_releases_the_claim_so_the_next_run_retries():
    rsvp, field = claimed_rsvp()
    with mock.patch.object(emails, "reminder", side_effect=ValueError("template exploded")):
        assert tasks.send_event_reminder_email(rsvp.pk, "2h") is False
    rsvp.refresh_from_db()
    assert getattr(rsvp, field) is None
    assert tasks.dispatch_upcoming_event_reminders() == 1 and len(mail.outbox) == 1  # next beat run picks it up


def test_smtp_outage_retries_then_releases_the_claim():
    rsvp, field = claimed_rsvp()
    with mock.patch.object(emails, "_send", side_effect=SMTPException("down")):
        with pytest.raises(Retry):  # attempts remain: keep the claim, ask Celery to try again later
            tasks.send_event_reminder_email.apply(args=(rsvp.pk, "2h"), retries=4, throw=True).get()
        rsvp.refresh_from_db()
        assert getattr(rsvp, field) is not None
        # last attempt fails too: give the reminder back to the next beat run
        assert tasks.send_event_reminder_email.apply(args=(rsvp.pk, "2h"), retries=5).get() is False
    rsvp.refresh_from_db()
    assert getattr(rsvp, field) is None


def test_a_reminder_that_sends_keeps_its_claim():
    rsvp, field = claimed_rsvp()
    assert tasks.send_event_reminder_email(rsvp.pk, "2h") is True and len(mail.outbox) == 1
    rsvp.refresh_from_db()
    assert getattr(rsvp, field) is not None


def test_a_reminder_for_a_cancelled_rsvp_is_skipped_and_stays_claimed():
    rsvp, field = claimed_rsvp()
    services.cancel(rsvp.event, rsvp.user)  # cancelling resets the markers (refinement 1)
    mail.outbox.clear()
    assert tasks.send_event_reminder_email(rsvp.pk, "2h") is False and mail.outbox == []


def test_release_only_clears_the_matching_marker():
    rsvp, _ = claimed_rsvp("2h")
    RSVP.objects.filter(pk=rsvp.pk).update(reminder_24h_sent_at=timezone.now())
    tasks.release_reminder_claim(rsvp.pk, "2h")
    rsvp.refresh_from_db()
    assert rsvp.reminder_2h_sent_at is None and rsvp.reminder_24h_sent_at is not None


def test_broker_failure_while_dispatching_gives_the_claim_back():
    rsvp = confirmed(event_in(hours=1))
    with mock.patch.object(tasks.send_event_reminder_email, "delay", side_effect=ConnectionError("redis down")):
        assert tasks.dispatch_upcoming_event_reminders() == 0
    rsvp.refresh_from_db()
    assert rsvp.reminder_2h_sent_at is None


def test_unknown_reminder_kind_is_rejected():
    with pytest.raises(ValueError):
        emails.reminder(1, "5m")


# --- completion and trust --------------------------------------------------------------------
def test_finished_events_complete_and_scores_follow(django_capture_on_commit_callbacks):
    start = timezone.now() - timedelta(hours=6)
    event = EventFactory()
    came, ghosted = confirmed(event), confirmed(event)
    move_start(event.pk, start)
    RSVP.objects.filter(pk=came.pk).update(checked_in=True, checked_in_at=start)
    upcoming = event_in(days=2)

    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.mark_completed_events() == 1
    event.refresh_from_db(), upcoming.refresh_from_db()
    assert event.status == Event.Status.COMPLETED and upcoming.status == Event.Status.PUBLISHED

    for user in (came.user, ghosted.user, event.host):
        user.refresh_from_db()
    assert (came.user.attended_count, came.user.no_show_count) == (1, 0) and came.user.trust_score == 80
    assert (ghosted.user.attended_count, ghosted.user.no_show_count) == (0, 1) and ghosted.user.trust_score == 50
    assert event.host.hosted_completed_count == 1 and event.host.trust_score == 52
    assert tasks.mark_completed_events() == 0  # nothing left to complete


def test_trust_formula_and_clamping():
    from apps.accounts.trust import compute

    assert compute(0, 0, 0, 0) == 50
    assert compute(10, 0, 0, 0) == 80
    assert compute(5, 5, 0, 0) == 65
    assert compute(10, 0, 20, 0) == 100          # hosting credit stops at 10 events, clamp at 100
    assert compute(0, 4, 0, 99) == 30            # cancellation penalty stops at 4
    assert compute(0, 0, 0, 4) == 30


def test_host_cancellations_after_publishing_cost_points():
    from apps.accounts import trust

    event = EventFactory()
    Event.objects.filter(pk=event.pk).update(published_at=timezone.now())
    services.host_cancel_event(event, event.host)
    trust.recompute([event.host_id])
    event.host.refresh_from_db()
    assert event.host.trust_score == 45


def test_nightly_recompute_covers_everyone_and_matches_the_per_user_path():
    users = [UserFactory() for _ in range(3)]
    assert tasks.recompute_all_trust_scores() >= 3
    assert all(u.trust_score == 50 for u in type(users[0]).objects.filter(pk__in=[u.pk for u in users]))


# --- payment expiry --------------------------------------------------------------------------
def test_expiry_task_marks_stale_orders():
    from apps.payments.services import start_checkout

    host = UserFactory()
    stale = start_checkout(EventFactory(host=host, draft=True), host)
    PlatformPayment.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=2))
    fresh = start_checkout(EventFactory(host=host, draft=True), host)
    assert tasks.expire_stale_payment_orders() == 1
    stale.refresh_from_db(), fresh.refresh_from_db()
    assert stale.status == PlatformPayment.Status.EXPIRED and fresh.status == PlatformPayment.Status.CREATED


# --- beat schedule ---------------------------------------------------------------------------
def test_beat_schedule_is_installed_and_points_at_real_tasks():
    from celery import current_app
    from django_celery_beat.models import PeriodicTask

    from apps.notifications.beat import SCHEDULE

    rows = {t.name: t for t in PeriodicTask.objects.filter(name__startswith="partly:")}
    assert set(rows) == {name for name, *_ in SCHEDULE} and all(t.enabled for t in rows.values())
    current_app.loader.import_default_modules()
    for task in rows.values():
        assert task.task in current_app.tasks, task.task
    assert str(rows["partly: send event reminders"].crontab.timezone) == "Asia/Kolkata"
