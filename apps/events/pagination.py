"""Keyset ("load more") pagination over (start_time, id), with signed cursors."""
from datetime import datetime

from django.core import signing
from django.db.models import Q

PAGE_SIZE = 20
_SALT = "partly.feed.cursor"


def encode_cursor(event):
    return signing.dumps(f"{event.start_time.isoformat()}|{event.pk}", salt=_SALT, compress=True)


def decode_cursor(raw):
    """Return (start_time, id) or None for a missing or tampered cursor."""
    if not raw:
        return None
    try:
        value = signing.loads(raw, salt=_SALT)
        iso, pk = value.rsplit("|", 1)
        return datetime.fromisoformat(iso), int(pk)
    except (signing.BadSignature, ValueError, TypeError, AttributeError):
        return None


def paginate(qs, raw_cursor, page_size=PAGE_SIZE):
    """qs must be ordered by (start_time, id). Returns (items, next_cursor | None)."""
    position = decode_cursor(raw_cursor)
    if position:
        start, pk = position
        qs = qs.filter(Q(start_time__gt=start) | Q(start_time=start, id__gt=pk))
    rows = list(qs[: page_size + 1])
    items = rows[:page_size]
    next_cursor = encode_cursor(items[-1]) if len(rows) > page_size else None
    return items, next_cursor
