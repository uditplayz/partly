import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import PASSWORD, UserFactory
from apps.accounts.tests.test_views import signup_data
from apps.events.models import Event
from apps.events.tests.factories import EventFactory
from apps.payments.models import PlatformPayment
from apps.rsvps import services as rsvp_services
from apps.rsvps.models import RSVP, Invitation

pytestmark = pytest.mark.django_db


def test_signup_requires_the_age_and_terms_confirmation(client):
    data = signup_data()
    data.pop("accept_terms")
    resp = client.post(reverse("accounts:signup"), data)
    assert resp.status_code == 200 and not User.objects.filter(username="aditi").exists()
    assert "confirm this" in resp.content.decode()
    assert reverse("core:terms") in resp.content.decode()


def test_legal_pages_render_and_use_the_configured_operator(client, settings):
    settings.LEGAL_ENTITY_NAME = "Acme Hangouts LLP"
    settings.SUPPORT_EMAIL = "help@acme.test"
    for name in ("core:terms", "core:privacy", "core:refunds"):
        html = client.get(reverse(name)).content.decode()
        assert "help@acme.test" in html
    assert "Acme Hangouts LLP" in client.get(reverse("core:terms")).content.decode()
    assert f"₹{settings.PLATFORM_LISTING_FEE_INR}" in client.get(reverse("core:refunds")).content.decode()
    footer = client.get("/").content.decode()
    for name in ("core:terms", "core:privacy", "core:refunds"):
        assert reverse(name) in footer


# --- account deletion -----------------------------------------------------------------------
def test_deletion_requires_login_and_the_right_password(client):
    assert client.get(reverse("accounts:delete")).status_code == 302
    user = UserFactory()
    client.force_login(user)
    resp = client.post(reverse("accounts:delete"), {"password": "wrong"})
    assert resp.status_code == 200 and "isn&#x27;t your password" in resp.content.decode()
    user.refresh_from_db()
    assert user.is_active and user.email != f"deleted-{user.pk}@deleted.invalid"


def test_deleting_anonymises_signs_out_and_cleans_up(client, django_capture_on_commit_callbacks):
    me, other = UserFactory(display_name="Real Name", bio="private bio", campus_tag="COEP"), UserFactory()
    mine_live = EventFactory(host=me)
    guest_rsvp = rsvp_services.request_rsvp(other, mine_live)
    draft = EventFactory(host=me, draft=True)
    theirs = EventFactory(host=other, capacity=2)
    my_rsvp = rsvp_services.request_rsvp(me, theirs, note="my private note")
    inv = rsvp_services.create_invitation(mine_live, me, "someone@example.com")[0]
    own_email = me.email
    mail.outbox.clear()

    client.force_login(me)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("accounts:delete"), {"password": PASSWORD})
    assert resp.status_code == 200 and "logged out" in resp.content.decode()
    assert "_auth_user_id" not in client.session

    me.refresh_from_db()
    assert me.is_active is False and me.username == f"deleted-{me.pk}" and me.email.endswith("@deleted.invalid")
    assert me.display_name == "Deleted user" and me.bio == "" and me.campus_tag == "" and not me.has_usable_password()
    mine_live.refresh_from_db(), guest_rsvp.refresh_from_db(), my_rsvp.refresh_from_db()
    assert mine_live.status == Event.Status.CANCELLED and guest_rsvp.status == RSVP.Status.CANCELLED
    assert not Event.objects.filter(pk=draft.pk).exists()
    assert my_rsvp.status == RSVP.Status.CANCELLED and my_rsvp.note_to_host == ""
    assert not Invitation.objects.filter(pk=inv.pk).exists()
    assert [m.to[0] for m in mail.outbox] == [other.email]  # the guest was told the event is off
    assert all(own_email not in m.body for m in mail.outbox)
    assert client.get(reverse("public_profile", args=[f"deleted-{me.pk}"])).status_code == 404

    client.post(reverse("accounts:login"), {"login": own_email, "username": own_email, "password": PASSWORD})
    assert "_auth_user_id" not in client.session


def test_payment_records_survive_deletion(client):
    me = UserFactory()
    event = EventFactory(host=me, draft=True)
    payment = PlatformPayment.objects.create(
        event=event, user=me, amount_inr=49, provider="mock", provider_order_id="order_x", status="CAPTURED"
    )
    client.force_login(me)
    client.post(reverse("accounts:delete"), {"password": PASSWORD})
    payment.refresh_from_db()
    assert payment.user_id == me.pk and payment.event_id is None  # the draft is gone, the payment stays


def test_staff_cannot_delete_themselves_here(client):
    staff = UserFactory(is_staff=True)
    client.force_login(staff)
    client.post(reverse("accounts:delete"), {"password": PASSWORD})
    staff.refresh_from_db()
    assert staff.is_active and staff.username != f"deleted-{staff.pk}"


# --- refunds ---------------------------------------------------------------------------------
def test_staff_can_mark_a_payment_refunded(admin_client):
    host = UserFactory()
    payment = PlatformPayment.objects.create(
        event=EventFactory(host=host, draft=True), user=host, amount_inr=49, provider="razorpay",
        provider_order_id="order_r", status="CAPTURED", needs_refund=True,
    )
    admin_client.post(
        reverse("admin:payments_platformpayment_changelist"),
        {"action": "mark_refunded", "_selected_action": [payment.pk]},
    )
    payment.refresh_from_db()
    assert payment.needs_refund is False and payment.refunded_at is not None
