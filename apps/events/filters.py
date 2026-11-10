"""Feed filters. Invalid input is ignored rather than raising errors."""
from datetime import datetime, time, timedelta

from django import forms
from django.utils import timezone

from apps.core.constants import Vibe

TONIGHT_CUTOFF = time(4, 0)  # "tonight" runs until 04:00
WEEKEND_START = time(17, 0)  # Friday 17:00


class When:
    UPCOMING = "upcoming"
    TONIGHT = "tonight"
    WEEKEND = "weekend"
    CHOICES = [(UPCOMING, "Upcoming"), (TONIGHT, "Tonight"), (WEEKEND, "This weekend")]


def tonight_cutoff(now):
    """End of 'tonight' in local time: 04:00 tomorrow, or 04:00 today if it's past midnight."""
    local = timezone.localtime(now)
    day = local.date() if local.time() < TONIGHT_CUTOFF else local.date() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, TONIGHT_CUTOFF))


def weekend_window(now):
    """(start, end) of the current or next weekend: Fri 17:00 to Sun 23:59:59 local."""
    local = timezone.localtime(now)
    weekday = local.weekday()  # Mon=0 … Sun=6
    if weekday in (5, 6) or (weekday == 4 and local.time() >= WEEKEND_START):
        friday = local.date() - timedelta(days=weekday - 4)
    else:
        friday = local.date() + timedelta(days=(4 - weekday) % 7)
    start = timezone.make_aware(datetime.combine(friday, WEEKEND_START))
    end = timezone.make_aware(datetime.combine(friday + timedelta(days=2), time(23, 59, 59)))
    return max(start, now), end


class FeedFilterForm(forms.Form):
    vibe = forms.MultipleChoiceField(choices=Vibe.choices, required=False)
    area = forms.CharField(required=False, max_length=60, strip=True)
    when = forms.ChoiceField(choices=When.CHOICES, required=False)
    free = forms.BooleanField(required=False)
    open = forms.BooleanField(required=False)

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.is_valid()  # populate cleaned_data; bad fields are simply dropped

    def value(self, name, default=None):
        return getattr(self, "cleaned_data", {}).get(name) or default

    @property
    def is_filtered(self):
        cd = getattr(self, "cleaned_data", {})
        return any([cd.get("vibe"), cd.get("area"), cd.get("free"), cd.get("open"),
                    cd.get("when") not in (None, "", When.UPCOMING)])

    def apply(self, qs, now=None):
        now = now or timezone.now()
        cd = getattr(self, "cleaned_data", {})
        if vibes := cd.get("vibe"):
            qs = qs.filter(vibe_category__in=vibes)
        if area := cd.get("area"):
            qs = qs.filter(area_name__icontains=area)
        when = cd.get("when") or When.UPCOMING
        if when == When.TONIGHT:
            qs = qs.filter(start_time__lt=tonight_cutoff(now))
        elif when == When.WEEKEND:
            start, end = weekend_window(now)
            qs = qs.filter(start_time__lte=end, end_time__gte=start)
        if cd.get("free"):
            qs = qs.filter(is_free_entry=True)
        if cd.get("open"):
            qs = qs.filter(spots_left__gt=0)
        return qs
