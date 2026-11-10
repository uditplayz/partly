"""QR passes. The QR holds a signed payload, so a pass can't be forged or edited.

The payload names the RSVP's check-in token and its event. The token changes whenever
an RSVP is cancelled, declined or re-requested, which makes old screenshots useless.
"""
import io
import uuid

import segno
from django.core import signing

SALT = "partly.checkin"
MAX_PAYLOAD_LENGTH = 512
DARK = "#1C1A17"
LIGHT = "#FFFFFF"  # always white behind the code so it scans in dark mode too


def payload_for(rsvp):
    return signing.dumps({"t": str(rsvp.checkin_token), "e": rsvp.event_id}, salt=SALT)


def read_payload(text):
    """Return (token, event_id) for a genuine payload, or None for anything else."""
    if not isinstance(text, str) or not text or len(text) > MAX_PAYLOAD_LENGTH:
        return None
    try:
        data = signing.loads(text.strip(), salt=SALT)
        return uuid.UUID(data["t"]), int(data["e"])
    except (signing.BadSignature, KeyError, TypeError, ValueError, AttributeError):
        return None


def _code(rsvp):
    return segno.make(payload_for(rsvp), error="m")


def svg_inline(rsvp, scale=6):
    """SVG markup to place straight into a page (no XML declaration)."""
    return _code(rsvp).svg_inline(scale=scale, border=3, dark=DARK, light=LIGHT)


def svg_bytes(rsvp, scale=8):
    out = io.BytesIO()
    _code(rsvp).save(out, kind="svg", scale=scale, border=3, dark=DARK, light=LIGHT)
    return out.getvalue()


def png_bytes(rsvp, scale=10):
    out = io.BytesIO()
    _code(rsvp).save(out, kind="png", scale=scale, border=3, dark=DARK, light=LIGHT)
    return out.getvalue()
