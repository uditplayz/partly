from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.events.models import Event
from apps.rsvps import services as rsvp_services
from apps.rsvps.models import RSVP

from .models import Block, Report


class SafetyError(Exception):
    pass


def block(blocker, blocked):
    """Block someone, and take both of you out of each other's upcoming events."""
    if blocker.pk == blocked.pk:
        raise SafetyError("You can't block yourself.")
    try:
        with transaction.atomic():
            Block.objects.create(blocker=blocker, blocked=blocked)
    except IntegrityError:
        return False  # already blocked
    upcoming = Event.objects.filter(status=Event.Status.PUBLISHED, end_time__gte=timezone.now())
    # Their spots at your events go.
    theirs = RSVP.objects.filter(user=blocked, event__in=upcoming.filter(host=blocker), status__in=RSVP.ACTIVE_STATUSES)
    for rsvp in theirs:
        try:
            rsvp_services.decline(rsvp.pk, blocker)
        except (rsvp_services.RSVPError, RSVP.DoesNotExist):
            pass  # already checked in or already handled
    # Your spots at their events go too.
    yours = RSVP.objects.filter(user=blocker, event__in=upcoming.filter(host=blocked), status__in=RSVP.ACTIVE_STATUSES)
    for rsvp in yours.select_related("event"):
        try:
            rsvp_services.cancel(rsvp.event, blocker)
        except rsvp_services.RSVPError:
            pass
    return True


def unblock(blocker, blocked):
    return Block.objects.filter(blocker=blocker, blocked=blocked).delete()[0] > 0


def create_report(reporter, *, reason, details="", event=None, user=None):
    if (event is None) == (user is None):
        raise SafetyError("A report is about an event or a member.")
    if user is not None and user.pk == reporter.pk:
        raise SafetyError("You can't report yourself.")
    if event is not None and event.host_id == reporter.pk:
        raise SafetyError("You can't report your own event.")
    try:
        with transaction.atomic():
            return Report.objects.create(reporter=reporter, event=event, user=user, reason=reason, details=details[:600])
    except IntegrityError:
        raise SafetyError("You already have an open report about this. We'll look into it.")


def resolve(report, status, note=""):
    report.status = status
    report.staff_note = note or report.staff_note
    report.handled_at = timezone.now()
    report.save(update_fields=["status", "staff_note", "handled_at"])


def take_down_event(event):
    """Staff action: cancel a published event and tell its guests."""
    if event.status == Event.Status.PUBLISHED:
        rsvp_services.host_cancel_event(event, event.host)
        return True
    return False


def suspend_user(user):
    """Staff action: lock the account and cancel the user's upcoming events."""
    for event in Event.objects.filter(host=user, status=Event.Status.PUBLISHED):
        rsvp_services.host_cancel_event(event, user)
    user.is_active = False
    user.save(update_fields=["is_active"])
