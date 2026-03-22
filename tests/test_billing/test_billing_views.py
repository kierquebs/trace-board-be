"""
Tests for billing views:
  POST /api/billing/subscribe/
  GET  /api/billing/status/
  POST /api/billing/cancel/
  POST /api/billing/webhooks/paymongo/
"""
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.billing.models import Payment, Subscription
from tests.conftest import PlanFactory, SubscriptionFactory, UserFactory


# ── Helpers ────────────────────────────────────────────────────────────────────

def _auth_client(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _webhook_payload(event_type: str, pm_id: str = "pay_123", amount: int = 29900, metadata: dict | None = None) -> dict:
    return {
        "data": {
            "id": pm_id,
            "attributes": {
                "type": event_type,
                "amount": amount,
                "source": {"type": "gcash"},
                "metadata": metadata or {},
            },
        }
    }


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── Subscribe ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_subscribe_returns_checkout_url(starter_plan, technician_user):
    client = _auth_client(technician_user)
    with patch("apps.billing.paymongo.create_checkout_session", return_value="https://checkout.paymongo.com/cs_test") as mock:
        resp = client.post("/api/billing/subscribe/", {"plan_slug": "starter"}, format="json")

    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["data"]["checkout_url"] == "https://checkout.paymongo.com/cs_test"
    assert resp.data["data"]["plan"] == "starter"
    mock.assert_called_once()


@pytest.mark.django_db
def test_subscribe_invalid_plan(technician_user):
    client = _auth_client(technician_user)
    resp = client.post("/api/billing/subscribe/", {"plan_slug": "nonexistent"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_subscribe_already_active(subscribed_technician):
    client = _auth_client(subscribed_technician)
    with patch("apps.billing.paymongo.create_checkout_session"):
        resp = client.post("/api/billing/subscribe/", {"plan_slug": "starter"}, format="json")
    assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
def test_subscribe_paymongo_error_returns_502(starter_plan, technician_user):
    import requests as http_requests
    client = _auth_client(technician_user)
    with patch("apps.billing.paymongo.create_checkout_session", side_effect=http_requests.HTTPError("api down")):
        resp = client.post("/api/billing/subscribe/", {"plan_slug": "starter"}, format="json")
    assert resp.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.django_db
def test_subscribe_requires_auth():
    client = APIClient()
    resp = client.post("/api/billing/subscribe/", {"plan_slug": "starter"}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ── Status ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_subscription_status_active(subscribed_technician):
    client = _auth_client(subscribed_technician)
    resp = client.get("/api/billing/status/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"]["status"] == "active"


@pytest.mark.django_db
def test_subscription_status_no_subscription(technician_user):
    client = _auth_client(technician_user)
    resp = client.get("/api/billing/status/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"] is None


# ── Cancel ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cancel_subscription(subscribed_technician):
    client = _auth_client(subscribed_technician)
    resp = client.post("/api/billing/cancel/")
    assert resp.status_code == status.HTTP_200_OK
    subscribed_technician.subscription.refresh_from_db()
    assert subscribed_technician.subscription.status == Subscription.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_no_subscription(technician_user):
    client = _auth_client(technician_user)
    resp = client.post("/api/billing/cancel/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_cancel_already_cancelled(db):
    user = UserFactory()
    plan = PlanFactory()
    sub = SubscriptionFactory(user=user, plan=plan, status=Subscription.Status.CANCELLED)
    client = _auth_client(user)
    resp = client.post("/api/billing/cancel/")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Webhook: payment.paid ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_payment_paid_activates_subscription(db, settings):
    settings.PAYMONGO_WEBHOOK_SECRET = ""  # Skip sig check in dev
    user = UserFactory()
    plan = PlanFactory(slug="starter", price_php="299.00")

    payload = _webhook_payload(
        "payment.paid",
        pm_id="pay_abc",
        amount=29900,
        metadata={"user_id": str(user.pk), "plan_slug": "starter"},
    )
    client = APIClient()
    resp = client.post(
        "/api/billing/webhooks/paymongo/",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert resp.status_code == status.HTTP_200_OK
    sub = Subscription.objects.get(user=user)
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.plan == plan
    payment = Payment.objects.get(paymongo_payment_id="pay_abc")
    assert payment.subscription == sub
    assert payment.user == user
    assert payment.status == Payment.PaymentStatus.PAID


@pytest.mark.django_db
def test_webhook_payment_paid_missing_metadata(db, settings):
    settings.PAYMONGO_WEBHOOK_SECRET = ""
    payload = _webhook_payload("payment.paid", pm_id="pay_xyz", metadata={})
    client = APIClient()
    resp = client.post(
        "/api/billing/webhooks/paymongo/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    # Should not crash — returns 200 and logs the error
    assert resp.status_code == status.HTTP_200_OK
    assert not Subscription.objects.exists()


@pytest.mark.django_db
def test_webhook_invalid_signature(db, settings):
    settings.PAYMONGO_WEBHOOK_SECRET = "secret123"
    payload = _webhook_payload("payment.paid")
    client = APIClient()
    resp = client.post(
        "/api/billing/webhooks/paymongo/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_PAYMONGO_SIGNATURE="bad_signature",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_webhook_valid_signature(db, settings):
    secret = "mysecret"
    settings.PAYMONGO_WEBHOOK_SECRET = secret
    user = UserFactory()
    PlanFactory(slug="starter")

    payload = _webhook_payload(
        "payment.paid",
        metadata={"user_id": str(user.pk), "plan_slug": "starter"},
    )
    body = json.dumps(payload).encode()
    sig = _sign(body, secret)

    client = APIClient()
    resp = client.post(
        "/api/billing/webhooks/paymongo/",
        data=body,
        content_type="application/json",
        HTTP_PAYMONGO_SIGNATURE=sig,
    )
    assert resp.status_code == status.HTTP_200_OK


# ── Webhook: payment.failed ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_webhook_payment_failed_updates_record(db, settings):
    settings.PAYMONGO_WEBHOOK_SECRET = ""
    user = UserFactory()
    plan = PlanFactory()
    sub = SubscriptionFactory(user=user, plan=plan)
    Payment.objects.create(
        paymongo_payment_id="pay_fail",
        subscription=sub,
        user=user,
        amount_php="299.00",
        status=Payment.PaymentStatus.PAID,
    )

    payload = _webhook_payload("payment.failed", pm_id="pay_fail")
    client = APIClient()
    resp = client.post(
        "/api/billing/webhooks/paymongo/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert Payment.objects.get(paymongo_payment_id="pay_fail").status == Payment.PaymentStatus.FAILED
