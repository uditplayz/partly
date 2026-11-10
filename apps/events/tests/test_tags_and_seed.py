from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.events.models import Event
from apps.events.templatetags.event_tags import clock, spots_label, when_label

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 11, 18, 0, tzinfo=IST)  # Wednesday 6 PM


def ev(start, hours=3, **kw):
    return SimpleNamespace(start_time=start, end_time=start + timedelta(hours=hours), capacity=8, **kw)


@pytest.mark.parametrize("start, expected", [
    (datetime(2026, 11, 11, 21, 30, tzinfo=IST), "Tonight · 9:30 PM"),
    (datetime(2026, 11, 12, 1, 0, tzinfo=IST), "Tonight · 1 AM"),
    (datetime(2026, 11, 12, 18, 0, tzinfo=IST), "Tomorrow · 6 PM"),
    (datetime(2026, 11, 14, 19, 0, tzinfo=IST), "Sat 14 Nov · 7 PM"),
])
def test_when_label(start, expected):
    assert when_label(ev(start), NOW) == expected


def test_when_label_live():
    assert when_label(ev(NOW - timedelta(hours=1)), NOW) == "Happening now · till 8 PM"


def test_when_label_daytime_today():
    morning = datetime(2026, 11, 11, 8, 0, tzinfo=IST)
    assert when_label(ev(datetime(2026, 11, 11, 11, 0, tzinfo=IST)), morning) == "Today · 11 AM"


def test_clock():
    assert clock(datetime(2026, 1, 1, 0, 5, tzinfo=IST)) == "12:05 AM"


@pytest.mark.parametrize("used, left, expected", [(0, 8, "8 spots"), (5, 3, "3/8 left"), (8, 0, "Full")])
def test_spots_label(used, left, expected):
    assert spots_label(SimpleNamespace(capacity=8, seats_used=used, spots_left=left)) == expected


@pytest.mark.django_db
def test_seed_demo(settings):
    settings.DEBUG = True
    call_command("seed_demo")
    assert Event.objects.published().count() == 40
    assert User.objects.filter(username__startswith="demo_").count() == 6
    assert len(set(Event.objects.values_list("vibe_category", flat=True))) == 7

    call_command("seed_demo")  # second run without --reset is a no-op
    assert Event.objects.count() == 40

    # A demo host with a sandbox payment must not block --reset.
    from apps.payments import services as payment_services
    host = User.objects.get(username="demo_aditi")
    draft = Event.objects.filter(host=host).first()
    Event.objects.filter(pk=draft.pk).update(status="DRAFT", platform_fee_status="PENDING")
    assert payment_services.start_checkout(draft, host) is not None

    call_command("seed_demo", "--reset")
    assert Event.objects.count() == 40


@pytest.mark.django_db
def test_seed_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo")
