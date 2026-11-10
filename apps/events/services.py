"""Event state changes live here, never in views. Phase 3 adds checkout-driven publishing."""
from django.db import transaction
from django.utils import timezone

from .models import Event


def create_draft(host, form):
    event = form.save(commit=False)
    event.host = host
    event.status = Event.Status.DRAFT
    event.platform_fee_status = Event.FeeStatus.PENDING
    event.save()
    return event


def update_event(event, form):
    if not event.is_editable:
        raise ValueError("Cancelled or completed events can't be edited.")
    return form.save()


def delete_draft(event):
    if event.status != Event.Status.DRAFT:
        raise ValueError("Only drafts can be deleted.")
    event.delete()


@transaction.atomic
def waive_and_publish(event):
    """Staff-only shortcut until real checkout lands in Phase 3."""
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.status != Event.Status.DRAFT:
        return event
    event.platform_fee_status = Event.FeeStatus.WAIVED
    event.status = Event.Status.PUBLISHED
    event.published_at = timezone.now()
    event.save(update_fields=["platform_fee_status", "status", "published_at", "updated_at"])
    return event
