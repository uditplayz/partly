import re

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

pytestmark = pytest.mark.django_db


def read_static(path):
    with open(finders.find(path), encoding="utf-8") as fh:
        return fh.read()


def test_home_renders_shell(client):
    resp = client.get(reverse("events:feed"))
    html = resp.content.decode()
    assert resp.status_code == 200
    assert 'rel="manifest"' in html
    assert "js/sw-register.js" in html
    assert 'class="bottom-nav' in html
    for label in ("Explore", "Host +", "My Tickets", "Profile"):
        assert label in html


def test_fonts_are_bricolage_and_atkinson(client):
    html = client.get(reverse("events:feed")).content.decode()
    assert "Bricolage+Grotesque" in html and "Atkinson+Hyperlegible" in html


def test_tokens_define_palette_and_radius():
    css = read_static("css/tokens.css")
    for token in ("#FAF7F2", "#1C1A17", "#5E7D6A", "#C4704F", "--p-radius: 12px",
                  "Bricolage Grotesque", "Atkinson Hyperlegible", '[data-bs-theme="dark"]'):
        assert token in css, token


def test_no_alarm_red_in_design_css():
    css = (read_static("css/tokens.css") + read_static("css/app.css")).lower()
    for red in ("#dc3545", "#ff0000", "#f00;"):
        assert red not in css, red
    assert not re.search(r":\s*red\s*[;}!]", css)


def test_bottom_nav_marks_active_tab(auth_client):
    html = auth_client.get(reverse("core:tickets")).content.decode()
    assert 'bottom-nav__item is-active" href="/tickets/"' in html


@pytest.mark.parametrize("name", ["core:tickets", "events:create", "events:my_hosting"])
def test_placeholder_sections_require_login(client, name):
    resp = client.get(reverse(name))
    assert resp.status_code == 302 and "/accounts/login/" in resp.url
