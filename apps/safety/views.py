from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.events.models import Event

from . import services
from .forms import ReportForm
from .models import Block

User = get_user_model()


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def report(request, kind, key):
    if kind == "event":
        target = get_object_or_404(Event.objects.exclude(status=Event.Status.DRAFT), slug=key)
        label, back, subject = target.title, target.get_absolute_url(), {"event": target}
    elif kind == "user":
        target = get_object_or_404(User, username__iexact=key, is_active=True)
        label, back, subject = f"@{target.username}", reverse("public_profile", args=[target.username]), {"user": target}
    else:
        return redirect("events:feed")
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_report(request.user, **form.cleaned_data, **subject)
        except services.SafetyError as exc:
            messages.info(request, str(exc))
        else:
            messages.success(request, "Thanks. We'll look into it. You may not hear back, but every report is read.")
        return redirect(back)
    return render(request, "safety/report.html", {"form": form, "label": label, "back": back})


@require_POST
@login_required
def block(request, username):
    target = get_object_or_404(User, username__iexact=username, is_active=True)
    try:
        created = services.block(request.user, target)
    except services.SafetyError as exc:
        messages.info(request, str(exc))
        return redirect("safety:blocked")
    messages.success(request, f"{target.name} is blocked." if created else f"{target.name} was already blocked.")
    return redirect("safety:blocked")


@require_POST
@login_required
def unblock(request, username):
    target = get_object_or_404(User, username__iexact=username)
    if services.unblock(request.user, target):
        messages.success(request, f"{target.name} is unblocked.")
    return redirect("safety:blocked")


@never_cache
@login_required
def blocked(request):
    rows = Block.objects.filter(blocker=request.user).select_related("blocked").order_by("-created_at")
    return render(request, "safety/blocked.html", {"rows": rows})
