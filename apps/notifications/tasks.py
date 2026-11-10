"""Celery tasks. Every task takes primary keys and re-checks state before acting."""
import logging
from datetime import timedelta
from smtplib import SMTPException

from celery import shared_task
from django.utils import timezone

from . import dispatch, emails

logger = logging.getLogger(__name__)

# Errors worth retrying: the mail server or network is having a moment.
TRANSIENT = (SMTPException, ConnectionError, TimeoutError, OSError)
CLAIM_FIELD = {emails.REMINDER_24H: "reminder_24h_sent_at", emails.REMINDER_2H: "reminder_2h_sent_at"}

_email_task = shared_task(autoretry_for=TRANSIENT, retry_backoff=True, retry_backoff_max=900, retry_jitter=True, max_retries=5)


@_email_task
def send_rsvp_confirmation_email(rsvp_id):
    return emails.rsvp_confirmed(rsvp_id)


@_email_task
def send_host_new_rsvp_notification(rsvp_id):
    return emails.host_new_request(rsvp_id)


@_email_task
def send_event_invitation_email(invitation_id):
    return emails.invitation_created(invitation_id)


@_email_task
def send_event_cancelled_email(rsvp_id):
    return emails.event_cancelled(rsvp_id)


def release_reminder_claim(rsvp_id, kind):
    """Put the reminder marker back to NULL so the next beat run can claim it again."""
    from apps.rsvps.models import RSVP

    field = CLAIM_FIELD[kind]
    return RSVP.objects.filter(pk=rsvp_id, **{f"{field}__isnull": False}).update(**{field: None})


@shared_task(bind=True, max_retries=5)
def send_event_reminder_email(self, rsvp_id, kind):
    """The dispatcher has already claimed this reminder by stamping reminder_*_sent_at.
    If sending fails for good (retries used up, or an error that retrying won't fix), the
    stamp is cleared so the next dispatcher run tries again instead of silently losing it."""
    try:
        sent = emails.reminder(rsvp_id, kind)
    except TRANSIENT as exc:
        if self.request.retries >= self.max_retries:
            release_reminder_claim(rsvp_id, kind)
            logger.error("Reminder %s for RSVP %s failed after %s retries: %s", kind, rsvp_id, self.max_retries, exc)
            return False
        raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 1) * 30, 900))
    except Exception:
        release_reminder_claim(rsvp_id, kind)
        logger.exception("Reminder %s for RSVP %s failed", kind, rsvp_id)
        return False
    if not sent:
        # Nothing to send any more (cancelled, event gone). Leave the stamp: it must not be re-claimed.
        return False
    return True


@shared_task
def dispatch_upcoming_event_reminders():
    """Beat, every 15 minutes. Windows are wide so a missed run loses nothing:
    2h = start in (now, now+2h], 24h = start in (now+2h, now+24h]. Each RSVP is claimed with a
    conditional UPDATE, so two beat processes can't both send."""
    from apps.events.models import Event
    from apps.rsvps.models import RSVP

    now = timezone.now()
    windows = (
        (emails.REMINDER_2H, now, now + timedelta(hours=2)),
        (emails.REMINDER_24H, now + timedelta(hours=2), now + timedelta(hours=24)),
    )
    queued = 0
    for kind, start, end in windows:
        field = CLAIM_FIELD[kind]
        due = RSVP.objects.filter(
            status=RSVP.Status.CONFIRMED,
            event__status=Event.Status.PUBLISHED,
            event__start_time__gt=start,
            event__start_time__lte=end,
            **{f"{field}__isnull": True},
        ).values_list("pk", flat=True)
        for rsvp_id in list(due):
            claimed = RSVP.objects.filter(pk=rsvp_id, status=RSVP.Status.CONFIRMED, **{f"{field}__isnull": True}).update(
                **{field: now}
            )
            if not claimed:
                continue
            try:
                send_event_reminder_email.delay(rsvp_id, kind)
                queued += 1
            except Exception:  # broker down: give the claim back
                release_reminder_claim(rsvp_id, kind)
                logger.exception("Could not queue reminder %s for RSVP %s", kind, rsvp_id)
    return queued


@shared_task
def recompute_trust_scores(user_ids):
    from apps.accounts import trust

    return trust.recompute(user_ids)


@shared_task
def recompute_all_trust_scores():
    from apps.accounts import trust

    return trust.recompute(None)


@shared_task
def mark_completed_events():
    """Beat, every 15 minutes. Finished events become COMPLETED, then scores are refreshed
    for the host and everyone who held a confirmed spot."""
    from apps.events.services import complete_finished_events
    from apps.rsvps.models import RSVP

    event_ids = complete_finished_events()
    if not event_ids:
        return 0
    from apps.events.models import Event

    users = set(Event.objects.filter(pk__in=event_ids).values_list("host_id", flat=True))
    users |= set(
        RSVP.objects.filter(event_id__in=event_ids, status=RSVP.Status.CONFIRMED).values_list("user_id", flat=True)
    )
    dispatch.enqueue(recompute_trust_scores, sorted(users))
    return len(event_ids)


@shared_task
def expire_stale_payment_orders():
    from apps.payments.services import expire_stale_orders

    return expire_stale_orders()
