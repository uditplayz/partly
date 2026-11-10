from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.events.models import Event

from . import checkin, qr, services
from .forms import InviteForm, RSVPForm
from .models import RSVP, Invitation

Status = RSVP.Status


def _hosted_event(request, slug):
    """404 for anyone but the host, so slugs aren't confirmed to exist."""
    return get_object_or_404(Event.objects.hosted_by(request.user).with_seats(), slug=slug)


# --- guest actions ---------------------------------------------------------------------
@require_POST
@login_required
def rsvp_create(request, slug):
    event = get_object_or_404(Event, slug=slug, status=Event.Status.PUBLISHED)
    form = RSVPForm(request.POST)
    if not form.is_valid():
        messages.info(request, "Check the number of plus-ones and try again.")
        return redirect(event.get_absolute_url())
    try:
        rsvp = services.request_rsvp(
            request.user, event, form.cleaned_data["plus_ones"], form.cleaned_data["note"],
            age_confirmed=form.cleaned_data["age_confirmed"],
        )
    except services.RSVPError as exc:
        messages.info(request, str(exc))
        return redirect(event.get_absolute_url())
    messages.success(request, {
        Status.CONFIRMED: "You're in. The address is unlocked below.",
        Status.WAITLISTED: "It's full, so you're on the waitlist. You'll move up automatically if a spot opens.",
        Status.PENDING_APPROVAL: "Request sent. The host will get back to you.",
    }[rsvp.status])
    return redirect(event.get_absolute_url())


@require_POST
@login_required
def rsvp_cancel(request, slug):
    event = get_object_or_404(Event, slug=slug)
    try:
        services.cancel(event, request.user)
        messages.success(request, "Your RSVP is cancelled.")
    except services.RSVPError as exc:
        messages.info(request, str(exc))
    if event.is_visible_to(request.user):
        return redirect(event.get_absolute_url())
    return redirect("rsvps:tickets")


@require_GET
@login_required
def my_plans(request):
    now = timezone.now()
    rsvps = list(
        RSVP.objects.filter(
            user=request.user, status__in=RSVP.ACTIVE_STATUSES,
            event__status=Event.Status.PUBLISHED, event__end_time__gte=now,
        ).select_related("event", "event__host").order_by("event__start_time", "id")
    )
    for rsvp in rsvps:  # the address and the QR pass are attached here, only for confirmed guests
        confirmed = rsvp.status == Status.CONFIRMED
        rsvp.address = rsvp.event.exact_address if confirmed else None
        rsvp.qr_svg = qr.svg_inline(rsvp) if confirmed else None
    return render(request, "rsvps/my_plans.html", {"rsvps": rsvps, "now": now})


@require_GET
@login_required
def qr_image(request, token, fmt):
    """A confirmed guest's QR pass as an image. Only the guest and the event's host can fetch it."""
    rsvp = get_object_or_404(
        RSVP.objects.filter(Q(user=request.user) | Q(event__host=request.user)),
        checkin_token=token, status=Status.CONFIRMED,
    )
    if fmt == "png":
        response = HttpResponse(qr.png_bytes(rsvp), content_type="image/png")
    else:
        response = HttpResponse(qr.svg_bytes(rsvp), content_type="image/svg+xml")
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# --- host actions ----------------------------------------------------------------------
@require_GET
@login_required
def scanner(request, slug):
    event = _hosted_event(request, slug)
    if event.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED):
        raise Http404
    return render(request, "rsvps/scanner.html", {"event": event, "stats": checkin.stats(event)})


@require_POST
@login_required
def manual_checkin(request, pk):
    rsvp = get_object_or_404(RSVP.objects.select_related("event", "user"), pk=pk, event__host=request.user)
    try:
        checkin.manual_check_in(pk, request.user)
        messages.success(request, f"{rsvp.user.name} is checked in.")
    except services.RSVPError as exc:
        messages.info(request, str(exc))
    return redirect("rsvps:manage", slug=rsvp.event.slug)


@require_GET
@login_required
def manage(request, slug):
    event = _hosted_event(request, slug)
    rsvps = list(RSVP.objects.filter(event=event).select_related("user").order_by("requested_at", "id"))
    confirmed = [r for r in rsvps if r.status == Status.CONFIRMED]
    return render(request, "rsvps/manage.html", {
        "event": event,
        "pending": [r for r in rsvps if r.status == Status.PENDING_APPROVAL],
        "confirmed": confirmed,
        "waitlisted": [r for r in rsvps if r.status == Status.WAITLISTED],
        "checked_in_count": sum(r.party_size for r in confirmed if r.checked_in),
        "can_scan": event.status in (Event.Status.PUBLISHED, Event.Status.COMPLETED),
        "invitations": Invitation.objects.filter(event=event).select_related("invitee_user"),
        "invite_form": InviteForm(),
    })


def _host_rsvp_action(request, pk, action, done_message):
    rsvp = get_object_or_404(RSVP.objects.select_related("event", "user"), pk=pk, event__host=request.user)
    try:
        result = action(pk, request.user)
        messages.success(request, done_message(result, rsvp.user.name))
    except services.RSVPError as exc:
        messages.info(request, str(exc))
    return redirect("rsvps:manage", slug=rsvp.event.slug)


@require_POST
@login_required
def approve(request, pk):
    def message(rsvp, name):
        if rsvp.status == Status.CONFIRMED:
            return f"{name} is confirmed."
        return f"{name} is approved, but the event is full. They're first in line on the waitlist."
    return _host_rsvp_action(request, pk, services.approve, message)


@require_POST
@login_required
def decline(request, pk):
    return _host_rsvp_action(request, pk, services.decline, lambda rsvp, name: f"{name} won't be on the list.")


@require_POST
@login_required
def invite(request, slug):
    event = _hosted_event(request, slug)
    form = InviteForm(request.POST)
    if not form.is_valid():
        messages.info(request, " ".join(form.errors["emails"]))
        return redirect("rsvps:manage", slug=event.slug)
    sent, repeats, problems = 0, 0, []
    for email in form.cleaned_data["emails"]:
        try:
            _, created = services.create_invitation(event, request.user, email)
            sent += created
            repeats += not created
        except services.RSVPError as exc:
            problems.append(str(exc))
    if sent:
        messages.success(request, f"Invited {sent} {'person' if sent == 1 else 'people'}.")
    if repeats:
        messages.info(request, f"{repeats} already had an invite.")
    for problem in dict.fromkeys(problems):
        messages.info(request, problem)
    return redirect("rsvps:manage", slug=event.slug)


@require_POST
@login_required
def cancel_event(request, slug):
    event = _hosted_event(request, slug)
    try:
        affected = services.host_cancel_event(event, request.user)
        messages.success(request, f"Event cancelled. {affected} RSVP{'' if affected == 1 else 's'} released.")
    except services.RSVPError as exc:
        messages.info(request, str(exc))
    return redirect(event.get_absolute_url())


# --- invitations -----------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def invitation(request, token):
    inv = get_object_or_404(Invitation.objects.select_related("event", "event__host", "invited_by"), invite_token=token)
    event = inv.event

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        try:
            if request.POST.get("action") == "decline":
                services.decline_invitation(token, request.user)
                messages.success(request, "Invite declined. Maybe next time.")
                return redirect("events:feed")
            form = RSVPForm(request.POST)
            plus_ones = form.cleaned_data["plus_ones"] if form.is_valid() else 0
            aged = form.is_valid() and form.cleaned_data["age_confirmed"]
            rsvp = services.accept_invitation(token, request.user, plus_ones, age_confirmed=aged)
            messages.success(
                request,
                "You're in. The address is unlocked below." if rsvp.status == Status.CONFIRMED
                else "It's full right now, so you're on the waitlist.",
            )
            return redirect(event.get_absolute_url())
        except services.RSVPError as exc:
            messages.info(request, str(exc))
            return redirect("rsvps:invitation", token=token)

    problem = None
    if request.user.is_authenticated:
        try:
            services.check_invitee(inv, request.user)
        except services.RSVPError as exc:
            problem = str(exc)
    return render(request, "rsvps/invitation.html", {
        "invitation": inv,
        "event": event,
        "problem": problem,
        "is_open": event.status == Event.Status.PUBLISHED and timezone.now() < event.rsvp_deadline,
        "plus_one_range": range(event.max_plus_ones + 1),
    })
