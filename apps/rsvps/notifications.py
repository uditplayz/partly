"""Plain, synchronous emails for Phase 4. Each takes a primary key, reloads the row and
re-checks its state before sending. Phase 6 moves these onto Celery tasks with HTML
templates and the QR attachment.

They are called through transaction.on_commit, so an email never describes a change
that was rolled back. A mail failure is logged and never breaks the request.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import RSVP, Invitation

logger = logging.getLogger(__name__)


def absolute(path):
    return settings.SITE_URL.rstrip("/") + path


def _when(event):
    return timezone.localtime(event.start_time).strftime("%a %d %b, %I:%M %p")


def _send(subject, body, to):
    if not to:
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])
        return True
    except Exception:  # noqa: BLE001 (mail must never break a request)
        logger.exception("Could not send %r to %s", subject, to)
        return False


def rsvp_confirmed(rsvp_id):
    rsvp = RSVP.objects.select_related("event", "event__host", "user").filter(pk=rsvp_id).first()
    if rsvp is None or rsvp.status != RSVP.Status.CONFIRMED:
        return False
    event = rsvp.event
    lines = [
        f"Hi {rsvp.user.name},",
        "",
        f"You're in for {event.title}, hosted by {event.host.name}.",
        "",
        f"When: {_when(event)}",
        f"Where: {event.exact_address}",
        f"Entry: {event.entry_label}" + (f" ({event.entry_fee_notes})" if event.entry_fee_notes else ""),
    ]
    if rsvp.plus_ones:
        lines.append(f"Plus-ones: {rsvp.plus_ones}")
    lines += ["", "Please keep the address to yourself.", f"Your plans: {absolute(reverse('rsvps:tickets'))}"]
    return _send(f"You're in: {event.title}", "\n".join(lines), rsvp.user.email)


def host_new_request(rsvp_id):
    rsvp = RSVP.objects.select_related("event", "event__host", "user").filter(pk=rsvp_id).first()
    if rsvp is None or rsvp.status != RSVP.Status.PENDING_APPROVAL:
        return False
    event = rsvp.event
    lines = [
        f"Hi {event.host.name},",
        "",
        f"{rsvp.user.name} (@{rsvp.user.username}) wants to join {event.title}.",
    ]
    if rsvp.plus_ones:
        lines.append(f"They'd bring {rsvp.plus_ones} plus-one(s).")
    if rsvp.note_to_host:
        lines.append(f'Their note: "{rsvp.note_to_host}"')
    lines += ["", f"Approve or decline: {absolute(reverse('rsvps:manage', args=[event.slug]))}"]
    return _send(f"New request for {event.title}", "\n".join(lines), event.host.email)


def invitation_created(invitation_id):
    invitation = Invitation.objects.select_related("event", "invited_by", "invitee_user").filter(pk=invitation_id).first()
    if invitation is None or invitation.status != Invitation.Status.SENT or invitation.sent_at:
        return False
    # Claim it first so two workers can't both send; release the claim if sending fails.
    claimed = Invitation.objects.filter(pk=invitation.pk, sent_at__isnull=True).update(sent_at=timezone.now())
    if not claimed:
        return False
    event = invitation.event
    to = invitation.invitee_email or (invitation.invitee_user.email if invitation.invitee_user_id else "")
    body = "\n".join([
        f"{invitation.invited_by.name} invited you to {event.title}.",
        "",
        f"When: {_when(event)}",
        f"Area: {event.area_name}",
        f"Entry: {event.entry_label}",
        "",
        f"Respond here: {absolute(reverse('rsvps:invitation', args=[invitation.invite_token]))}",
        "",
        "The exact address unlocks once you accept and have a spot.",
    ])
    if not _send(f"{invitation.invited_by.name} invited you: {event.title}", body, to):
        Invitation.objects.filter(pk=invitation.pk).update(sent_at=None)
        return False
    return True
