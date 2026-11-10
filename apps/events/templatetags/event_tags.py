from datetime import timedelta

from django import template
from django.utils import timezone

from apps.events.filters import tonight_cutoff

register = template.Library()


def _clock(dt):
    """'6 PM' or '9:30 PM'."""
    hour = dt.strftime("%I").lstrip("0") or "12"
    minutes = dt.strftime("%M")
    suffix = dt.strftime("%p")
    return f"{hour} {suffix}" if minutes == "00" else f"{hour}:{minutes} {suffix}"


@register.filter
def clock(value):
    return _clock(timezone.localtime(value)) if value else ""


@register.simple_tag
def when_label(event, now=None):
    """Human date chip: 'Happening now', 'Tonight · 9:30 PM', 'Tomorrow · 6 PM', 'Sat 14 Nov · 6 PM'."""
    now = now or timezone.now()
    start = timezone.localtime(event.start_time)
    if event.start_time <= now <= event.end_time:
        return f"Happening now · till {_clock(timezone.localtime(event.end_time))}"
    today = timezone.localtime(now).date()
    late_night = start.hour >= 17 or start.hour < 4  # evening, or the small hours after midnight
    if event.start_time < tonight_cutoff(now) or start.date() == today:
        return f"{'Tonight' if late_night else 'Today'} · {_clock(start)}"
    if start.date() == today + timedelta(days=1):
        return f"Tomorrow · {_clock(start)}"
    return f"{start.strftime('%a')} {start.day} {start.strftime('%b')} · {_clock(start)}"


@register.simple_tag
def spots_label(event):
    used = getattr(event, "seats_used", 0) or 0
    left = getattr(event, "spots_left", event.capacity)
    if left <= 0:
        return "Full"
    if used == 0:
        return f"{event.capacity} spots"
    return f"{left}/{event.capacity} left"
