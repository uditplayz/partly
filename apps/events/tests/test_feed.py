from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Event
from apps.events.pagination import PAGE_SIZE, encode_cursor
from apps.events.tests.factories import EventFactory

pytestmark = pytest.mark.django_db
FEED = reverse("events:feed")


def titles(resp):
    return [e.title for e in resp.context["events"]]


def test_feed_lists_only_published_upcoming():
    EventFactory(title="visible")
    EventFactory(title="draft", draft=True)
    EventFactory(title="cancelled", status=Event.Status.CANCELLED)
    past = timezone.now() - timedelta(days=2)
    EventFactory(title="past", start_time=past, end_time=past + timedelta(hours=2), rsvp_deadline=past)
    assert titles(FEED_GET()) == ["visible"]


def FEED_GET(query="", **headers):
    from django.test import Client
    return Client().get(FEED + query, headers=headers)


def test_feed_is_ordered_by_start_time():
    now = timezone.now()
    EventFactory(title="later", start_time=now + timedelta(days=3))
    EventFactory(title="sooner", start_time=now + timedelta(days=1))
    assert titles(FEED_GET()) == ["sooner", "later"]


def count_feed_queries(client):
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(FEED).status_code == 200
    return len(ctx.captured_queries)


def test_feed_query_count_is_constant(client):
    EventFactory.create_batch(5)
    few = count_feed_queries(client)
    EventFactory.create_batch(15)
    assert count_feed_queries(client) == few
    assert few <= 2


def test_exact_address_never_in_feed_html(client):
    events = EventFactory.create_batch(3)
    for resp in (client.get(FEED), client.get(FEED + "?partial=1")):
        html = resp.content.decode()
        for e in events:
            assert e.exact_address not in html
            assert e.title in html


def test_feed_query_does_not_even_load_the_address(client):
    EventFactory()
    with CaptureQueriesContext(connection) as ctx:
        client.get(FEED)
    event_sql = [q["sql"] for q in ctx.captured_queries if "events_event" in q["sql"]]
    assert event_sql and all("exact_address" not in sql for sql in event_sql)


def test_partial_returns_only_the_list(client):
    EventFactory(title="Card me")
    for resp in (client.get(FEED + "?partial=1"), client.get(FEED, headers={"X-Requested-With": "fetch"})):
        html = resp.content.decode()
        assert "Card me" in html
        assert "<html" not in html and "bottom-nav" not in html and "data-feed-filters" not in html


def test_full_page_has_filters_and_cards(client):
    EventFactory(title="Card me")
    html = client.get(FEED).content.decode()
    assert "data-feed-filters" in html and "Card me" in html and "js/feed.js" in html


def test_card_shows_badges(client):
    EventFactory(title="Paid one", paid_entry=True, capacity=8, requires_host_approval=True)
    html = client.get(FEED).content.decode()
    assert "₹200 at door" in html and "8 spots" in html and "Host approves" in html


def test_keyset_pagination_has_no_gaps_or_duplicates(client):
    base = timezone.now() + timedelta(days=1)
    # several events share a start time, to exercise the id tiebreaker
    created = [EventFactory(title=f"e{i:02d}", start_time=base + timedelta(hours=i // 3)) for i in range(PAGE_SIZE * 2 + 5)]
    seen, cursor, pages = [], None, 0
    while True:
        resp = client.get(FEED, {"cursor": cursor} if cursor else {})
        seen += titles(resp)
        cursor = resp.context["next_cursor"]
        pages += 1
        if not cursor:
            break
    assert pages == 3
    assert seen == [e.title for e in sorted(created, key=lambda e: (e.start_time, e.pk))]


def test_load_more_link_keeps_filters(client):
    EventFactory.create_batch(PAGE_SIZE + 1, vibe_category="STUDY")
    html = client.get(FEED + "?vibe=STUDY&free=1").content.decode()
    assert "data-load-more" in html
    assert "vibe=STUDY&amp;free=1&amp;cursor=" in html


def test_tampered_cursor_falls_back_to_first_page(client):
    events = EventFactory.create_batch(3)
    forged = encode_cursor(events[0])[:-3] + "abc"
    resp = client.get(FEED, {"cursor": forged})
    assert resp.status_code == 200
    assert len(resp.context["events"]) == 3


def test_empty_states(client):
    assert "warming up" in client.get(FEED).content.decode()
    EventFactory(vibe_category="JAM")
    assert "Nothing matches" in client.get(FEED + "?vibe=GAMING").content.decode()
