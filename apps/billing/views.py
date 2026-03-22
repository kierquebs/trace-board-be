"""
Billing views.

GET  /api/billing/plans/              — Public: list available plans
POST /api/billing/subscribe/          — Technician: start subscription via PayMongo
GET  /api/billing/status/             — Technician: my subscription status
POST /api/billing/cancel/             — Technician: cancel subscription
POST /api/billing/webhooks/paymongo/  — PayMongo webhook (no auth)
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTechnician

from .models import Payment, Plan, Subscription
from .serializers import PlanSerializer, SubscriptionSerializer, SubscribeSerializer

logger = logging.getLogger(__name__)


class PlanListView(APIView):
    """GET /api/billing/plans/ — Open to all."""
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        plans = Plan.objects.filter(is_active=True)
        serializer = PlanSerializer(plans, many=True)
        return Response({"data": serializer.data})


class SubscribeView(APIView):
    """
    POST /api/billing/subscribe/

    Initiates a PayMongo subscription checkout.
    Returns a checkout URL the client redirects to.
    """
    permission_classes = [IsAuthenticated, IsTechnician]

    def post(self, request: Request) -> Response:
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan_slug = serializer.validated_data["plan_slug"]

        try:
            plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            return Response({"error": "Invalid plan."}, status=status.HTTP_400_BAD_REQUEST)

        # Check for existing active subscription
        try:
            existing = request.user.subscription
            if existing.is_active:
                return Response(
                    {"error": "You already have an active subscription."},
                    status=status.HTTP_409_CONFLICT,
                )
        except Subscription.DoesNotExist:
            pass

        # TODO: Call PayMongo API to create payment link
        # For now, return a placeholder response structure
        # Full PayMongo integration implemented in billing/paymongo.py
        checkout_url = _create_paymongo_checkout(request.user, plan)

        return Response(
            {
                "data": {
                    "checkout_url": checkout_url,
                    "plan": plan_slug,
                }
            },
            status=status.HTTP_201_CREATED,
        )


class SubscriptionStatusView(APIView):
    """GET /api/billing/status/"""
    permission_classes = [IsAuthenticated, IsTechnician]

    def get(self, request: Request) -> Response:
        try:
            sub = request.user.subscription
            serializer = SubscriptionSerializer(sub)
            return Response({"data": serializer.data})
        except Subscription.DoesNotExist:
            return Response({"data": None})


class CancelSubscriptionView(APIView):
    """POST /api/billing/cancel/"""
    permission_classes = [IsAuthenticated, IsTechnician]

    def post(self, request: Request) -> Response:
        try:
            sub = request.user.subscription
        except Subscription.DoesNotExist:
            return Response(
                {"error": "No active subscription found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not sub.is_active:
            return Response(
                {"error": "Subscription is already cancelled or expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub.cancel()
        logger.info("User %d cancelled subscription %d", request.user.pk, sub.pk)
        return Response({"data": {"detail": "Subscription cancelled. Access continues until period end."}})


class PayMongoWebhookView(APIView):
    """
    POST /api/billing/webhooks/paymongo/

    Receives PayMongo webhook events and updates subscription/payment records.
    No auth required — verified via HMAC signature.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        # Verify webhook signature
        sig_header = request.headers.get("Paymongo-Signature", "")
        if not self._verify_signature(request.body, sig_header):
            logger.warning("PayMongo webhook: invalid signature")
            return Response(status=status.HTTP_400_BAD_REQUEST)

        payload = request.data
        event_type = payload.get("data", {}).get("attributes", {}).get("type", "")

        logger.info("PayMongo webhook received: %s", event_type)

        handlers = {
            "payment.paid": self._handle_payment_paid,
            "payment.failed": self._handle_payment_failed,
            "subscription.created": self._handle_subscription_created,
            "subscription.cancelled": self._handle_subscription_cancelled,
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                handler(payload)
            except Exception as exc:
                logger.exception("Webhook handler error for %s: %s", event_type, exc)
                return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_200_OK)

    def _verify_signature(self, body: bytes, sig_header: str) -> bool:
        secret = settings.PAYMONGO_WEBHOOK_SECRET
        if not secret:
            logger.warning("PAYMONGO_WEBHOOK_SECRET not set — skipping signature check")
            return True  # Skip in dev if not configured

        try:
            # PayMongo uses HMAC-SHA256
            expected = hmac.new(
                secret.encode(), body, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, sig_header)
        except Exception:
            return False

    def _handle_payment_paid(self, payload: dict) -> None:
        """Create Payment record and activate/extend subscription."""
        attrs = payload["data"]["attributes"]
        pm_id = payload["data"]["id"]
        amount_centavos = attrs.get("amount", 0)
        amount_php = amount_centavos / 100

        # Upsert payment record
        Payment.objects.update_or_create(
            paymongo_payment_id=pm_id,
            defaults={
                "amount_php": amount_php,
                "status": Payment.PaymentStatus.PAID,
                "payment_method": attrs.get("source", {}).get("type", ""),
                "raw_webhook_data": payload,
            },
        )

    def _handle_payment_failed(self, payload: dict) -> None:
        pm_id = payload["data"]["id"]
        Payment.objects.filter(paymongo_payment_id=pm_id).update(
            status=Payment.PaymentStatus.FAILED,
            raw_webhook_data=payload,
        )

    def _handle_subscription_created(self, payload: dict) -> None:
        logger.info("Subscription created via PayMongo: %s", payload.get("data", {}).get("id"))

    def _handle_subscription_cancelled(self, payload: dict) -> None:
        pm_sub_id = payload.get("data", {}).get("id", "")
        Subscription.objects.filter(paymongo_subscription_id=pm_sub_id).update(
            status=Subscription.Status.CANCELLED
        )


def _create_paymongo_checkout(user, plan: Plan) -> str:
    """
    Placeholder — will call PayMongo Checkout Session API.
    Returns a redirect URL for the client.
    """
    # TODO: Implement PayMongo API call
    # import requests
    # response = requests.post("https://api.paymongo.com/v1/checkout_sessions", ...)
    return f"https://checkout.paymongo.com/placeholder?plan={plan.slug}"
