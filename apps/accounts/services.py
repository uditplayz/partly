"""Account lifecycle. Deleting an account anonymises it rather than removing the row, because
payment records (kept for accounting) and past events point at it."""
from django.db import transaction

from apps.events.models import Event
from apps.rsvps import services as rsvp_services
from apps.rsvps.models import RSVP, Invitation
from apps.safety.models import Block


class DeletionError(Exception):
    pass


@transaction.atomic
def delete_account(user):
    if user.is_superuser or user.is_staff:
        raise DeletionError("Staff accounts can't be deleted here. Ask another admin to remove it.")

    # Events you host: drafts go, live events are cancelled and guests are told, old ones stay.
    for event in Event.objects.filter(host=user):
        if event.status == Event.Status.DRAFT:
            event.delete()
        elif event.status == Event.Status.PUBLISHED:
            rsvp_services.host_cancel_event(event, user)

    # Spots you hold at other people's events go back to the waitlist.
    for rsvp in RSVP.objects.filter(user=user, status__in=RSVP.ACTIVE_STATUSES).select_related("event"):
        if rsvp.event.status == Event.Status.PUBLISHED:
            try:
                rsvp_services.cancel(rsvp.event, user)
            except rsvp_services.RSVPError:
                pass

    # Other people's email addresses that you invited are theirs, not ours to keep.
    Invitation.objects.filter(invited_by=user).delete()
    Invitation.objects.filter(invitee_user=user).update(invitee_email="")
    Block.objects.filter(blocker=user).delete()
    Block.objects.filter(blocked=user).delete()
    RSVP.objects.filter(user=user).update(note_to_host="")

    user.username = f"deleted-{user.pk}"
    user.email = f"deleted-{user.pk}@deleted.invalid"
    user.display_name = "Deleted user"
    user.first_name = user.last_name = ""
    user.bio = ""
    user.campus_tag = ""
    user.vibe_tags = []
    user.is_active = False
    user.set_unusable_password()
    user.save()
    return user
