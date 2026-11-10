"""JSON endpoints for the host's scanner. Host only, CSRF protected, never cached."""
import json

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.events.models import Event

from . import checkin


def _host_event(request, slug):
    """Return (event, None) for the host, or (None, error response)."""
    if not request.user.is_authenticated:
        return None, JsonResponse({"error": "login_required"}, status=401)
    event = Event.objects.filter(slug=slug, host=request.user).first()
    if event is None:
        return None, JsonResponse({"error": "not_found"}, status=404)
    return event, None


@require_POST
@never_cache
def checkin_scan(request, slug):
    event, error = _host_event(request, slug)
    if error:
        return error
    try:
        payload = json.loads(request.body)["payload"]
        if not isinstance(payload, str):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "bad_request"}, status=400)
    return JsonResponse(checkin.check_in(event, payload))


@require_GET
@never_cache
def checkin_stats(request, slug):
    event, error = _host_event(request, slug)
    if error:
        return error
    return JsonResponse({"stats": checkin.stats(event)})
