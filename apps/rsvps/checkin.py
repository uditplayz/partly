"""Door check-in. Scanning a pass and the manual fallback both end up here."""
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from . import qr
from .models import RSVP
from .services import RSVPError

VERIFIED = "verified"
ALREADY = "already_checked_in"
INVALID = "invalid"
WRONG_EVENT = "wrong_event"
NOT_CONFIRMED = "not_confirmed"


def stats(event):
    """Counts for the host's door screen. 'people' includes plus-ones."""
    party = F("plus_ones") + 1
    inside = Q(checked_in=True)
    row = RSVP.objects.filter(event=event, status=RSVP.Status.CONFIRMED).aggregate(
        n_confirmed=Count("id"),
        n_in=Count("id", filter=inside),
        p_confirmed=Sum(party),
        p_in=Sum(party, filter=inside),
    )
    return {
        "confirmed": row["n_confirmed"] or 0,
        "checked_in": row["n_in"] or 0,
        "people_confirmed": row["p_confirmed"] or 0,
        "people_checked_in": row["p_in"] or 0,
    }


def _clock(dt):
    local = timezone.localtime(dt)
    return f"{local.strftime('%I').lstrip('0') or '12'}:{local.strftime('%M %p')}"


def _result(code, event, rsvp=None):
    guest = None
    if rsvp is not None:
        guest = {
            "name": rsvp.user.name,
            "plus_ones": rsvp.plus_ones,
            "checked_in_at": _clock(rsvp.checked_in_at) if rsvp.checked_in_at else None,
        }
    return {"result": code, "guest": guest, "stats": stats(event)}


@transaction.atomic
def check_in(event, payload):
    """Validate a scanned payload for `event` and check the guest in once.

    The RSVP row is locked while we look at it, so two phones scanning the same
    pass at the same moment get one 'verified' and one 'already_checked_in'.
    """
    parsed = qr.read_payload(payload)
    if parsed is None:
        return _result(INVALID, event)
    token, event_id = parsed
    if event_id != event.pk:
        return _result(WRONG_EVENT, event)  # a real pass, for another event: say nothing about its owner

    rsvp = RSVP.objects.select_for_update().filter(checkin_token=token, event=event).first()
    if rsvp is None:
        return _result(INVALID, event)  # the token was rotated: an old pass
    if rsvp.status != RSVP.Status.CONFIRMED:
        return _result(NOT_CONFIRMED, event, rsvp)
    if rsvp.checked_in:
        return _result(ALREADY, event, rsvp)

    rsvp.checked_in = True
    rsvp.checked_in_at = timezone.now()
    rsvp.save(update_fields=["checked_in", "checked_in_at", "updated_at"])
    return _result(VERIFIED, event, rsvp)


@transaction.atomic
def manual_check_in(rsvp_id, host):
    """Fallback for a guest whose phone died: the host ticks them off the list."""
    rsvp = RSVP.objects.select_for_update(of=("self",)).filter(pk=rsvp_id, event__host=host).first()
    if rsvp is None:
        raise RSVP.DoesNotExist
    if rsvp.status != RSVP.Status.CONFIRMED:
        raise RSVPError("Only confirmed guests can be checked in.")
    if rsvp.checked_in:
        raise RSVPError("This guest is already checked in.")
    rsvp.checked_in = True
    rsvp.checked_in_at = timezone.now()
    rsvp.save(update_fields=["checked_in", "checked_in_at", "updated_at"])
    return rsvp
