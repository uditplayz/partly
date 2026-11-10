import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def signup_data(**overrides):
    data = {
        "display_name": "Aditi",
        "username": "aditi",
        "email": "aditi@example.com",
        "campus_tag": "COEP",
        "password1": "S0me-strong-pass!",
        "password2": "S0me-strong-pass!",
        "accept_terms": "on",
    }
    data.update(overrides)
    return data


def test_signup_creates_user_and_logs_in(client):
    resp = client.post(reverse("accounts:signup"), signup_data())
    assert resp.status_code == 302 and resp.url == reverse("events:feed")
    user = User.objects.get(username="aditi")
    assert user.display_name == "Aditi"
    assert int(client.session["_auth_user_id"]) == user.pk


def test_signup_rejects_duplicate_email_any_case(client):
    UserFactory(email="taken@example.com")
    resp = client.post(reverse("accounts:signup"), signup_data(email="TAKEN@example.com"))
    assert resp.status_code == 200
    assert "already has an account" in resp.content.decode()


def test_signup_rejects_duplicate_username_any_case(client):
    UserFactory(username="aditi")
    resp = client.post(reverse("accounts:signup"), signup_data(username="ADITI", email="new@example.com"))
    assert resp.status_code == 200
    assert "taken" in resp.content.decode()


def test_signup_redirects_when_logged_in(auth_client):
    assert auth_client.get(reverse("accounts:signup")).status_code == 302


@pytest.mark.parametrize("identifier", ["kabir", "KABIR", "kabir@example.com", "Kabir@Example.com"])
def test_login_with_username_or_email(client, identifier):
    UserFactory(username="kabir", email="kabir@example.com")
    resp = client.post(reverse("accounts:login"), {"username": identifier, "password": PASSWORD})
    assert resp.status_code == 302
    assert "_auth_user_id" in client.session


def test_login_wrong_password(client):
    UserFactory(username="kabir")
    resp = client.post(reverse("accounts:login"), {"username": "kabir", "password": "nope"})
    assert resp.status_code == 200
    assert "_auth_user_id" not in client.session


def test_logout_requires_post(auth_client):
    assert auth_client.get(reverse("accounts:logout")).status_code == 405


def test_logout_renders_cache_clearing_interstitial(auth_client):
    resp = auth_client.post(reverse("accounts:logout"))
    assert resp.status_code == 200
    assert "_auth_user_id" not in auth_client.session
    html = resp.content.decode()
    assert "js/logout.js" in html
    assert 'data-logout-redirect="/"' in html
    assert "no-store" in resp["Cache-Control"]


def test_logout_never_skips_interstitial_even_with_next(auth_client):
    resp = auth_client.post(reverse("accounts:logout") + "?next=/u/someone/")
    assert resp.status_code == 200
    assert 'data-logout-redirect="/u/someone/"' in resp.content.decode()


def test_logout_ignores_offsite_next(auth_client):
    resp = auth_client.post(reverse("accounts:logout") + "?next=https://evil.example/")
    assert 'data-logout-redirect="/"' in resp.content.decode()


def test_logout_script_posts_clear_user_cache():
    with open(finders.find("js/logout.js"), encoding="utf-8") as fh:
        js = fh.read()
    assert "CLEAR_USER_CACHE" in js and "partly-user-" in js


def test_profile_requires_login(client):
    resp = client.get(reverse("accounts:profile"))
    assert resp.status_code == 302 and reverse("accounts:login") in resp.url


def test_own_profile_shows_settings(auth_client, user):
    resp = auth_client.get(reverse("accounts:profile"))
    html = resp.content.decode()
    assert resp.status_code == 200
    assert user.name in html and "Log out" in html and "data-theme-switch" in html


def test_profile_edit_updates_vibes(auth_client, user):
    resp = auth_client.post(
        reverse("accounts:profile_edit"),
        {"display_name": "New Name", "campus_tag": "KP", "bio": "hi", "vibe_tags": ["JAM", "GAMING"]},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.display_name == "New Name"
    assert user.vibe_tags == ["JAM", "GAMING"]


def test_profile_edit_rejects_unknown_vibe(auth_client):
    resp = auth_client.post(reverse("accounts:profile_edit"), {"display_name": "x", "vibe_tags": ["RAVE"]})
    assert resp.status_code == 200


def test_public_profile(client):
    UserFactory(username="meera", display_name="Meera", vibe_tags=["JAM"])
    resp = client.get(reverse("public_profile", args=["Meera"]))
    html = resp.content.decode()
    assert resp.status_code == 200
    assert "Meera" in html and "Jam Session" in html and "Log out" not in html


def test_public_profile_404(client):
    assert client.get(reverse("public_profile", args=["ghost"])).status_code == 404
