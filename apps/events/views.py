from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from . import services
from .filters import FeedFilterForm
from .forms import EventForm
from .models import Event
from .pagination import paginate


def wants_partial(request):
    return request.GET.get("partial") == "1" or request.headers.get("X-Requested-With") == "fetch"


class FeedView(TemplateView):
    template_name = "events/feed.html"
    partial_template_name = "partials/event_card_list.html"

    def get_template_names(self):
        return [self.partial_template_name if wants_partial(self.request) else self.template_name]

    def get_context_data(self, **kwargs):
        now = timezone.now()
        filters = FeedFilterForm(self.request.GET or None)
        qs = filters.apply(Event.objects.for_feed(now).visible_to(self.request.user), now)
        events, next_cursor = paginate(qs, self.request.GET.get("cursor"))

        params = self.request.GET.copy()
        params.pop("cursor", None)
        params.pop("partial", None)
        return super().get_context_data(
            events=events,
            filters=filters,
            next_cursor=next_cursor,
            query_string=params.urlencode(),
            is_first_page=not self.request.GET.get("cursor"),
            now=now,
            **kwargs,
        )


class EventDetailView(DetailView):
    template_name = "events/detail.html"
    context_object_name = "event"

    def get_object(self, queryset=None):
        event = get_object_or_404(Event.objects.select_related("host").with_seats(), slug=self.kwargs["slug"])
        if not event.is_visible_to(self.request.user):
            raise Http404
        return event

    def get_context_data(self, **kwargs):
        event, user = self.object, self.request.user
        is_host = event.is_host(user)
        my_rsvp = event.rsvps.filter(user=user).first() if user.is_authenticated and not is_host else None
        return super().get_context_data(
            address=event.address_for(user),
            is_host=is_host,
            my_rsvp=my_rsvp,
            rsvp_open=event.status == Event.Status.PUBLISHED and timezone.now() < event.rsvp_deadline,
            plus_one_range=range(event.max_plus_ones + 1),
            pending_count=event.rsvps.filter(status="PENDING_APPROVAL").count() if is_host else 0,
            **kwargs,
        )


class HostEventMixin(LoginRequiredMixin):
    """Scopes lookups to the current user's own events. Anyone else gets a 404, not a 403."""

    def get_object(self, queryset=None):
        return get_object_or_404(Event.objects.hosted_by(self.request.user), slug=self.kwargs["slug"])


class EventCreateView(LoginRequiredMixin, CreateView):
    form_class = EventForm
    template_name = "events/form.html"

    def form_valid(self, form):
        self.object = services.create_draft(self.request.user, form)
        messages.success(self.request, "Draft saved. Publish it when you're ready.")
        return redirect(self.object.get_absolute_url())


class EventUpdateView(HostEventMixin, UpdateView):
    form_class = EventForm
    template_name = "events/form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            event = self.get_object()
            if not event.is_editable:
                messages.info(request, "Cancelled or finished events can't be edited.")
                return redirect(event.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = services.update_event(self.object, form)
        messages.success(self.request, "Changes saved.")
        return redirect(self.object.get_absolute_url())


class EventDeleteView(HostEventMixin, View):
    http_method_names = ["post"]

    def post(self, request, slug):
        event = self.get_object()
        try:
            services.delete_draft(event)
        except ValueError as exc:
            messages.info(request, str(exc))
            return redirect(event.get_absolute_url())
        messages.success(request, "Draft deleted.")
        return redirect("events:my_hosting")


class MyHostingView(LoginRequiredMixin, TemplateView):
    template_name = "events/my_hosting.html"

    def get_context_data(self, **kwargs):
        now = timezone.now()
        events = list(Event.objects.hosted_by(self.request.user).with_seats().order_by("start_time", "id"))
        drafts = [e for e in events if e.status == Event.Status.DRAFT]
        live = [e for e in events if e.status == Event.Status.PUBLISHED and e.end_time >= now]
        past = [e for e in events if e not in drafts and e not in live]
        past.reverse()  # most recent first
        return super().get_context_data(drafts=drafts, live=live, past=past, **kwargs)
