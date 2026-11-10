"""Builds and sends every email. Each builder takes a primary key, reloads the row and
re-checks its state first, so a retried or duplicated task never sends something stale.

Return value: True = sent, False = skipped because the state no longer calls for it.
A send failure raises; the Celery task decides whether to retry (see tasks.py).
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.rsvps import qr
from apps.rsvps.models import RSVP, Invitation

REMINDER_24H = "24h"
REMINDER_2H = "2h"
REMINDER_KINDS = (REMINDER_24H, REMINDER_2H)


def absolute(path):
    return settings.SITE_URL.rstrip("/") + path


def _when(event):
    return timezone.localtime(event.start_time).strftime("%a %d %b, %I:%M %p")


def _send(subject, greeting, lines, to, *, button=None, footer="", attachments=()):
    if not to:
        return False
    context = {"title": subject, "greeting": greeting, "lines": lines, "button": button, "footer": footer}
    message = EmailMultiAlternatives(
        subject,
        render_to_string("emails/message.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [to],
    )
    message.attach_alternative(render_to_string("emails/message.html", context), "text/html")
    for filename, content, mimetype in attachments:
        message.attach(filename, content, mimetype)
    message.send(fail_silently=False)
    return True


def _entry(event):
    return f"Entry: {event.entry_label}" + (f" ({event.entry_fee_notes})" if event.entry_fee_notes else "")


def _rsvp(rsvp_id):
    return RSVP.objects.select_related("event", "event__host", "user").filter(pk=rsvp_id).first()


def rsvp_confirmed(rsvp_id):
    rsvp = _rsvp(rsvp_id)
    if rsvp is None or rsvp.status != RSVP.Status.CONFIRMED:
        return False
    event = rsvp.event
    lines = [
        f"You're in for {event.title}, hosted by {event.host.name}.",
        f"When: {_when(event)}",
        f"Where: {event.exact_address}",
        _entry(event),
    ]
    if rsvp.plus_ones:
        lines.append(f"Plus-ones: {rsvp.plus_ones}")
    lines.append("Your QR pass is attached. Show it at the door, or open it from My Tickets.")
    return _send(
        f"You're in: {event.title}",
        f"Hi {rsvp.user.name},",
        lines,
        rsvp.user.email,
        button={"label": "Open my tickets", "url": absolute(reverse("rsvps:tickets"))},
        footer="Please keep the address and the pass to yourself.",
        attachments=[("partly-pass.png", qr.png_bytes(rsvp), "image/png")],
    )


def host_new_request(rsvp_id):
    rsvp = _rsvp(rsvp_id)
    if rsvp is None or rsvp.status != RSVP.Status.PENDING_APPROVAL:
        return False
    event = rsvp.event
    lines = [f"{rsvp.user.name} (@{rsvp.user.username}) wants to join {event.title}."]
    if rsvp.plus_ones:
        lines.append(f"They'd bring {rsvp.plus_ones} plus-one(s).")
    if rsvp.note_to_host:
        lines.append(f'Their note: "{rsvp.note_to_host}"')
    return _send(
        f"New request for {event.title}",
        f"Hi {event.host.name},",
        lines,
        event.host.email,
        button={"label": "Approve or decline", "url": absolute(reverse("rsvps:manage", args=[event.slug]))},
    )


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
    try:
        sent = _send(
            f"{invitation.invited_by.name} invited you: {event.title}",
            "Hi,",
            [
                f"{invitation.invited_by.name} invited you to {event.title}.",
                f"When: {_when(event)}",
                f"Area: {event.area_name}",
                _entry(event),
            ],
            to,
            button={"label": "Respond", "url": absolute(reverse("rsvps:invitation", args=[invitation.invite_token]))},
            footer="The exact address unlocks once you accept and have a spot.",
        )
    except Exception:
        Invitation.objects.filter(pk=invitation.pk).update(sent_at=None)
        raise
    if not sent:
        Invitation.objects.filter(pk=invitation.pk).update(sent_at=None)
    return sent


def event_cancelled(rsvp_id):
    rsvp = _rsvp(rsvp_id)
    if rsvp is None or rsvp.event.status != rsvp.event.Status.CANCELLED or rsvp.status != RSVP.Status.CANCELLED:
        return False
    event = rsvp.event
    return _send(
        f"Cancelled: {event.title}",
        f"Hi {rsvp.user.name},",
        [
            f"{event.host.name} has cancelled {event.title}, planned for {_when(event)}.",
            "Your QR pass no longer works. Sorry about the change of plans.",
        ],
        rsvp.user.email,
        button={"label": "Find something else", "url": absolute(reverse("events:feed"))},
    )


def reminder(rsvp_id, kind):
    if kind not in REMINDER_KINDS:
        raise ValueError(f"Unknown reminder kind: {kind!r}")
    rsvp = _rsvp(rsvp_id)
    if rsvp is None or rsvp.status != RSVP.Status.CONFIRMED or rsvp.event.status != rsvp.event.Status.PUBLISHED:
        return False
    event = rsvp.event
    lead = "starts in about 2 hours" if kind == REMINDER_2H else "is coming up within the next day"
    return _send(
        f"Reminder: {event.title}",
        f"Hi {rsvp.user.name},",
        [
            f"{event.title} {lead}.",
            f"When: {_when(event)}",
            f"Where: {event.exact_address}",
            "Have your QR pass ready. It's saved for offline use if you've opened My Tickets.",
        ],
        rsvp.user.email,
        button={"label": "Open my pass", "url": absolute(reverse("rsvps:tickets"))},
    )
