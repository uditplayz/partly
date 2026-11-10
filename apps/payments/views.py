from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.events.models import Event

from . import services
from .models import PlatformPayment
from .providers.base import InvalidSignature, ProviderError, get_provider
from .providers.mock import MockProvider


def _own_payment(request, order_id):
    return get_object_or_404(
        PlatformPayment.objects.select_related("event"), provider_order_id=order_id, user=request.user
    )


@require_POST
@login_required
def start(request, slug):
    event = get_object_or_404(Event.objects.hosted_by(request.user), slug=slug)
    try:
        payment = services.start_checkout(event, request.user)
    except services.CheckoutError as exc:
        messages.info(request, str(exc))
        return redirect(event.get_absolute_url())
    except ProviderError:
        messages.error(request, "We couldn't reach the payment provider. Nothing was charged. Try again in a minute.")
        return redirect(event.get_absolute_url())
    if payment is None:
        messages.success(request, "Your event is live.")
        return redirect(event.get_absolute_url())
    return redirect("payments:checkout", order_id=payment.provider_order_id)


@require_GET
@never_cache
@login_required
def checkout(request, order_id):
    payment = _own_payment(request, order_id)
    if not payment.is_open:
        return redirect("payments:return", order_id=order_id)
    provider = get_provider(payment.provider)
    request.csp_razorpay = provider.name == "razorpay"
    context = {"payment": payment, "event": payment.event, **provider.checkout_context(payment, request)}
    return render(request, provider.checkout_template, context)


@require_POST
@login_required
def mock_pay(request, order_id):
    """The sandbox 'bank'. It sends a signed webhook through the same handler the
    real webhook endpoint uses, then sends the browser to the return page."""
    if settings.PAYMENT_PROVIDER != MockProvider.name:
        raise Http404
    payment = _own_payment(request, order_id)
    if payment.provider != MockProvider.name:
        raise Http404
    body, headers = MockProvider().build_webhook(payment, success=request.POST.get("outcome") != "fail")
    services.handle_webhook(MockProvider.name, body, headers)
    return redirect("payments:return", order_id=order_id)


@require_GET
@never_cache
@login_required
def return_page(request, order_id):
    """Shows the payment's status. Reads only: it never changes a payment or an event."""
    return render(request, "payments/return.html", {"payment": _own_payment(request, order_id)})


@require_GET
@never_cache
@login_required
def status(request, order_id):
    payment = _own_payment(request, order_id)
    event = payment.event
    return JsonResponse({
        "status": payment.status,
        "published": bool(event and event.status == Event.Status.PUBLISHED),
        "event_url": event.get_absolute_url() if event else None,
    })


# The provider's server calls this, so there is no CSRF cookie. Authenticity comes from the
# HMAC signature checked in handle_webhook, and nothing is changed without a valid one.
@csrf_exempt  # NOSONAR
@require_POST
def webhook(request, provider):
    # Only the configured provider's webhook exists. In production that hides the mock one.
    if provider != settings.PAYMENT_PROVIDER:
        raise Http404
    try:
        result = services.handle_webhook(provider, request.body, request.headers)
    except InvalidSignature:
        return JsonResponse({"error": "invalid signature"}, status=400)
    except ValueError:
        return JsonResponse({"error": "unreadable body"}, status=400)
    return JsonResponse({"result": result})
