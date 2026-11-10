"""RSVP and invitation rules. Every change to who holds a seat happens here.

Seat safety: each function that can change seats first locks the event row
(SELECT ... FOR UPDATE), so seat decisions for one event run one at a time.
Lock order is always event first, then RSVP rows.
"""
from functools import partial

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.events.models import Event

from . import notifications
from .models import RSVP, Invitation

Status = RSVP.Status


class RSVPError(Exception):
    """A rule was broken. The message is safe to show the user."""


def _lock_event(event_id):
    return Event.objects.select_for_update().get(pk=event_id)


def seats_used(event):
    total = RSVP.objects.filter(event=event, status=Status.CONFIRMED).aggregate(n=Sum(F("plus_ones") + 1))["n"]
    return total or 0


def _confirm(rsvp):
    rsvp.status = Status.CONFIRMED
    rsvp.confirmed_at = timezone.now()
    rsvp.save()
    transaction.on_commit(partial(notifications.rsvp_confirmed, rsvp.pk))


def _place(rsvp, event):
    """Give the RSVP a seat if its whole party fits, else waitlist it. Event must be locked."""
    if event.capacity - seats_used(event) >= rsvp.party_size:
        _confirm(rsvp)
    else:
        rsvp.status = Status.WAITLISTED
        rsvp.save()


def _promote(event):
    """First come, first served. A party that doesn't fit is skipped, not allowed to block the queue."""
    free = event.capacity - seats_used(event)
    promoted = []
    waiting = RSVP.objects.select_for_update().filter(event=event, status=Status.WAITLISTED).order_by("requested_at", "id")
    for rsvp in waiting:
        if free <= 0:
            break
        if rsvp.party_size <= free:
            _confirm(rsvp)
            free -= rsvp.party_size
            promoted.append(rsvp)
    return promoted


@transaction.atomic
def promote_waitlist(event_id):
    """Public entry point, e.g. after a host raises the capacity."""
    event = _lock_event(event_id)
    return _promote(event) if event.status == Event.Status.PUBLISHED else []


@transaction.atomic
def request_rsvp(user, event, plus_ones=0, note="", invitation=None):
    """Create or re-open the user's RSVP. An invitation skips host approval, never capacity."""
    event = _lock_event(event.pk)
    now = timezone.now()
    if event.status != Event.Status.PUBLISHED:
        raise RSVPError("This event isn't open for RSVPs.")
    if now >= event.rsvp_deadline:
        raise RSVPError("RSVPs have closed for this event.")
    if user.pk == event.host_id:
        raise RSVPError("You're hosting this one.")
    if not 0 <= plus_ones <= event.max_plus_ones:
        raise RSVPError(
            "This event doesn't allow plus-ones." if event.max_plus_ones == 0
            else f"You can bring up to {event.max_plus_ones} plus-one(s)."
        )

    rsvp = RSVP.objects.select_for_update().filter(event=event, user=user).first()
    if rsvp is None:
        rsvp = RSVP(event=event, user=user)
    elif rsvp.status == Status.CONFIRMED:
        raise RSVPError("You already have a spot.")
    elif rsvp.status == Status.WAITLISTED:
        raise RSVPError("You're already on the waitlist.")
    elif rsvp.status == Status.PENDING_APPROVAL and invitation is None:
        raise RSVPError("Your request is already with the host.")
    elif rsvp.status == Status.DECLINED and invitation is None:
        raise RSVPError("The host couldn't fit you in for this one.")
    else:
        rsvp._reset_lifecycle()  # re-entry on the same row: fresh pass token, fresh reminders

    rsvp.plus_ones = plus_ones
    rsvp.note_to_host = (note or "")[:200]
    rsvp.requested_at = now
    rsvp.via_invitation = invitation

    if event.requires_host_approval and invitation is None:
        rsvp.status = Status.PENDING_APPROVAL
        rsvp.save()
        transaction.on_commit(partial(notifications.host_new_request, rsvp.pk))
    else:
        _place(rsvp, event)
    return rsvp


def _lock_for_host(rsvp_id, host):
    """Lock the event, then the RSVP. Raises RSVP.DoesNotExist unless `host` hosts the event."""
    event_id = RSVP.objects.filter(pk=rsvp_id, event__host=host).values_list("event_id", flat=True).first()
    if event_id is None:
        raise RSVP.DoesNotExist
    event = _lock_event(event_id)
    return RSVP.objects.select_for_update().get(pk=rsvp_id), event


@transaction.atomic
def approve(rsvp_id, host):
    rsvp, event = _lock_for_host(rsvp_id, host)
    if rsvp.status != Status.PENDING_APPROVAL:
        raise RSVPError("That request was already handled.")
    if event.status != Event.Status.PUBLISHED:
        raise RSVPError("This event is no longer open.")
    _place(rsvp, event)  # approved but full means waitlisted, and auto-promoted later
    return rsvp


@transaction.atomic
def decline(rsvp_id, host):
    """Turn down a request, or remove a guest who hasn't checked in yet."""
    rsvp, event = _lock_for_host(rsvp_id, host)
    if not rsvp.is_active:
        raise RSVPError("That request was already handled.")
    if rsvp.checked_in:
        raise RSVPError("This guest has already checked in.")
    held_seat = rsvp.status == Status.CONFIRMED
    rsvp.status = Status.DECLINED
    rsvp._reset_lifecycle()
    rsvp.save()
    if held_seat:
        _promote(event)
    return rsvp


@transaction.atomic
def cancel(event, user):
    """The guest gives up their own RSVP."""
    event = _lock_event(event.pk)
    rsvp = RSVP.objects.select_for_update().filter(event=event, user=user).first()
    if rsvp is None or not rsvp.is_active:
        raise RSVPError("You don't have an RSVP to cancel.")
    held_seat = rsvp.status == Status.CONFIRMED
    rsvp.status = Status.CANCELLED
    rsvp._reset_lifecycle()
    rsvp.save()
    if held_seat and event.status == Event.Status.PUBLISHED:
        _promote(event)
    return rsvp


@transaction.atomic
def host_cancel_event(event, host):
    """Cancel a published event and every active RSVP on it. Returns how many guests were affected."""
    event = _lock_event(event.pk)
    if event.host_id != host.pk:
        raise RSVPError("Only the host can cancel this event.")
    if event.status != Event.Status.PUBLISHED:
        raise RSVPError("Only a published event can be cancelled.")
    event.status = Event.Status.CANCELLED
    event.save(update_fields=["status", "updated_at"])
    affected = 0
    for rsvp in RSVP.objects.select_for_update().filter(event=event, status__in=RSVP.ACTIVE_STATUSES):
        rsvp.status = Status.CANCELLED
        rsvp._reset_lifecycle()
        rsvp.save()
        affected += 1
    return affected


# --- invitations ----------------------------------------------------------------------
def create_invitation(event, host, email):
    """Invite one email address. Returns (invitation, created). Inviting twice returns the first one."""
    email = (email or "").strip().lower()
    if event.host_id != host.pk:
        raise RSVPError("Only the host can invite people.")
    if event.status != Event.Status.PUBLISHED:
        raise RSVPError("Publish the event before inviting people.")
    if not email:
        raise RSVPError("Add an email address.")
    if email == (host.email or "").lower():
        raise RSVPError("That's your own email.")

    # Auto-link: if the address belongs to an account, attach it.
    user = get_user_model().objects.filter(email__iexact=email).first()
    match = Q(invitee_email__iexact=email)
    if user:
        match |= Q(invitee_user=user)
    existing = Invitation.objects.filter(match, event=event).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            invitation = Invitation.objects.create(event=event, invited_by=host, invitee_email=email, invitee_user=user)
            transaction.on_commit(partial(notifications.invitation_created, invitation.pk))
    except IntegrityError:  # two requests raced; the unique constraints kept one
        return Invitation.objects.filter(match, event=event).get(), False
    return invitation, True


def check_invitee(invitation, user):
    """An invite link only works for the person it was sent to."""
    if invitation.invitee_user_id:
        if invitation.invitee_user_id != user.pk:
            raise RSVPError("This invite belongs to a different account.")
    elif (user.email or "").lower() != invitation.invitee_email.lower():
        raise RSVPError(f"This invite was sent to {invitation.invitee_email}. Log in with that email to use it.")


@transaction.atomic
def accept_invitation(token, user, plus_ones=0):
    invitation = Invitation.objects.select_for_update().get(invite_token=token)
    check_invitee(invitation, user)
    existing = RSVP.objects.filter(event_id=invitation.event_id, user=user,
                                   status__in=(Status.CONFIRMED, Status.WAITLISTED)).first()
    if existing is None:
        if invitation.status == Invitation.Status.ACCEPTED:
            raise RSVPError("This invite has already been used.")
        existing = request_rsvp(user, invitation.event, plus_ones=plus_ones, invitation=invitation)
    invitation.status = Invitation.Status.ACCEPTED
    invitation.responded_at = timezone.now()
    invitation.invitee_user = user
    invitation.save()
    return existing


@transaction.atomic
def decline_invitation(token, user):
    invitation = Invitation.objects.select_for_update().get(invite_token=token)
    check_invitee(invitation, user)
    if invitation.status != Invitation.Status.SENT:
        raise RSVPError("You've already responded to this invite.")
    invitation.status = Invitation.Status.DECLINED
    invitation.responded_at = timezone.now()
    invitation.invitee_user = user
    invitation.save()
    return invitation
