from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import CreateView, DetailView, UpdateView

from .forms import LoginForm, ProfileForm, SignupForm
from .models import User


class SignupView(CreateView):
    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("events:feed")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("events:feed")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object, backend="apps.accounts.backends.EmailOrUsernameBackend")
        messages.success(self.request, f"Welcome to Partly, {self.object.name}.")
        return response


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


@method_decorator(never_cache, name="dispatch")
class LogoutView(auth_views.LogoutView):
    """POST-only logout. Renders an interstitial page that tells the service worker
    to drop its user-scoped cache (cached tickets / QR passes) before redirecting."""

    template_name = "accounts/logged_out.html"
    next_page = None

    def post(self, request, *args, **kwargs):
        # Validated ?next= (falls back to home). We always render the interstitial
        # rather than redirecting, so the SW cache wipe can never be skipped.
        next_url = self.get_redirect_url() or reverse("events:feed")
        auth_logout(request)
        return self.render_to_response(self.get_context_data(next_url=next_url))


class ProfileView(LoginRequiredMixin, DetailView):
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        return super().get_context_data(is_own_profile=True, **kwargs)


class PublicProfileView(DetailView):
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"

    def get_object(self, queryset=None):
        return get_object_or_404(User, username__iexact=self.kwargs["username"], is_active=True)

    def get_context_data(self, **kwargs):
        own = self.request.user.is_authenticated and self.request.user.pk == self.object.pk
        return super().get_context_data(is_own_profile=own, **kwargs)


class ProfileEditView(LoginRequiredMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/profile_edit.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Profile updated.")
        return super().form_valid(form)
