from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.http import QueryDict

from apps.events.filters import FeedFilterForm, tonight_cutoff, weekend_window
from apps.events.models import Event
from apps.events.tests.factories import EventFactory

IST = ZoneInfo("Asia/Kolkata")


def ist(*args):
    return datetime(*args, tzinfo=IST)


# --- pure time windows ---------------------------------------------------------
def test_tonight_cutoff_in_the_evening_is_4am_tomorrow():
    assert tonight_cutoff(ist(2026, 11, 11, 23, 0)) == ist(2026, 11, 12, 4, 0)


def test_tonight_cutoff_after_midnight_is_4am_today():
    assert tonight_cutoff(ist(2026, 11, 12, 2, 0)) == ist(2026, 11, 12, 4, 0)


def test_tonight_cutoff_in_the_morning_is_4am_tomorrow():
    assert tonight_cutoff(ist(2026, 11, 12, 9, 0)) == ist(2026, 11, 13, 4, 0)


def test_weekend_window_on_a_wednesday_is_the_coming_weekend():
    start, end = weekend_window(ist(2026, 11, 11, 12, 0))  # Wednesday
    assert start == ist(2026, 11, 13, 17, 0)  # Friday 17:00
    assert end == ist(2026, 11, 15, 23, 59, 59)  # Sunday


def test_weekend_window_on_friday_morning_is_this_weekend():
    start, _ = weekend_window(ist(2026, 11, 13, 10, 0))
    assert start == ist(2026, 11, 13, 17, 0)


def test_weekend_window_during_the_weekend_starts_now():
    now = ist(2026, 11, 14, 15, 0)  # Saturday afternoon
    start, end = weekend_window(now)
    assert start == now and end == ist(2026, 11, 15, 23, 59, 59)


def test_weekend_window_on_sunday_night_is_still_this_weekend():
    _, end = weekend_window(ist(2026, 11, 15, 22, 0))
    assert end == ist(2026, 11, 15, 23, 59, 59)


# --- applying filters ------------------------------------------------------------
def apply(query, now):
    return set(FeedFilterForm(QueryDict(query)).apply(Event.objects.for_feed(now), now).values_list("title", flat=True))


@pytest.mark.django_db
def test_when_filters():
    now = ist(2026, 11, 11, 18, 0)  # Wednesday evening
    EventFactory(title="tonight", start_time=ist(2026, 11, 11, 21, 0))
    EventFactory(title="after-midnight", start_time=ist(2026, 11, 12, 1, 0))
    EventFactory(title="thursday", start_time=ist(2026, 11, 12, 19, 0))
    EventFactory(title="saturday", start_time=ist(2026, 11, 14, 20, 0))
    EventFactory(title="next-week", start_time=ist(2026, 11, 18, 20, 0))
    EventFactory(title="already-over", start_time=ist(2026, 11, 11, 10, 0), end_time=ist(2026, 11, 11, 12, 0),
                 rsvp_deadline=ist(2026, 11, 11, 10, 0))

    assert apply("when=tonight", now) == {"tonight", "after-midnight"}
    assert apply("when=weekend", now) == {"saturday"}
    assert apply("", now) == {"tonight", "after-midnight", "thursday", "saturday", "next-week"}


@pytest.mark.django_db
def test_in_progress_event_stays_listed():
    now = ist(2026, 11, 11, 21, 0)
    EventFactory(title="live", start_time=ist(2026, 11, 11, 20, 0), end_time=ist(2026, 11, 11, 23, 0),
                 rsvp_deadline=ist(2026, 11, 11, 20, 0))
    assert apply("when=tonight", now) == {"live"}


@pytest.mark.django_db
def test_vibe_area_free_and_open_combine():
    now = ist(2026, 11, 11, 12, 0)
    start = ist(2026, 11, 12, 19, 0)
    EventFactory(title="jam-kp-free", vibe_category="JAM", area_name="Koregaon Park", start_time=start)
    EventFactory(title="jam-kp-paid", vibe_category="JAM", area_name="Koregaon Park", start_time=start, paid_entry=True)
    EventFactory(title="study-kp", vibe_category="STUDY", area_name="koregaon park lane 5", start_time=start)
    EventFactory(title="jam-baner", vibe_category="JAM", area_name="Baner", start_time=start)

    assert apply("vibe=JAM&area=koregaon", now) == {"jam-kp-free", "jam-kp-paid"}
    assert apply("vibe=JAM&area=koregaon&free=1", now) == {"jam-kp-free"}
    assert apply("vibe=JAM&vibe=STUDY&area=KOREGAON", now) == {"jam-kp-free", "jam-kp-paid", "study-kp"}
    assert apply("open=1&area=baner", now) == {"jam-baner"}  # seats_used is 0 until Phase 4


@pytest.mark.django_db
def test_invalid_params_are_ignored():
    now = ist(2026, 11, 11, 12, 0)
    EventFactory(title="one", start_time=ist(2026, 11, 12, 19, 0))
    assert apply("when=someday&vibe=RAVE&free=maybe&area=" + "x" * 200, now) == {"one"}


def test_is_filtered_flag():
    assert not FeedFilterForm(QueryDict("")).is_filtered
    assert not FeedFilterForm(QueryDict("when=upcoming")).is_filtered
    assert FeedFilterForm(QueryDict("when=tonight")).is_filtered
    assert FeedFilterForm(QueryDict("vibe=JAM")).is_filtered
