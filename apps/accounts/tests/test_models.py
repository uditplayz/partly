from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.core.constants import Vibe

pytestmark = pytest.mark.django_db


def test_custom_user_is_auth_model(settings):
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_defaults_and_display_name():
    u = UserFactory(display_name="", username="riya")
    assert u.trust_score == Decimal("50.0")
    assert u.vibe_tags == []
    assert u.name == "riya"
    assert u.is_new_member is True


def test_email_is_normalised_and_case_insensitively_unique():
    UserFactory(email="Aditi@Example.com")
    assert User.objects.filter(email="aditi@example.com").exists()
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(username="other", email="ADITI@example.com", password="x")


def test_username_case_insensitively_unique():
    UserFactory(username="Kabir")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(username="kabir", email="k2@example.com", password="x")


def test_vibe_tags_array_contains_lookup():
    u = UserFactory(vibe_tags=[Vibe.JAM, Vibe.STUDY])
    UserFactory(vibe_tags=[Vibe.GAMING])
    assert list(User.objects.filter(vibe_tags__contains=[Vibe.JAM])) == [u]
    assert u.vibe_tag_pairs() == [("JAM", "Jam Session"), ("STUDY", "Study Sesh")]


def test_is_new_member_threshold():
    u = UserFactory(attended_count=2, hosted_completed_count=1)
    assert u.is_new_member is False


def test_initials():
    assert UserFactory(display_name="Aditi Kulkarni").initials == "AK"
