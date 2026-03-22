"""
PayMongo API client.

Only creates Checkout Sessions (one-time payment links).
PayMongo docs: https://developers.paymongo.com/reference/checkout-session-resource
"""
import base64
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAYMONGO_API_BASE = "https://api.paymongo.com/v1"


def _auth_header() -> str:
    encoded = base64.b64encode(f"{settings.PAYMONGO_SECRET_KEY}:".encode()).decode()
    return f"Basic {encoded}"


def create_checkout_session(user, plan, success_url: str, cancel_url: str) -> str:
    """
    Create a PayMongo Checkout Session for the given user and plan.

    Returns the checkout URL to redirect the client to.
    Raises requests.HTTPError on API failure.
    """
    payload = {
        "data": {
            "attributes": {
                "billing": {
                    "name": user.get_full_name() or user.username,
                    "email": user.email,
                    "phone": getattr(user, "phone", "") or "",
                },
                "line_items": [
                    {
                        "currency": "PHP",
                        "amount": int(plan.price_php * 100),  # centavos
                        "description": f"TraceBoard {plan.name} — 1 month",
                        "name": f"TraceBoard {plan.name}",
                        "quantity": 1,
                    }
                ],
                "payment_method_types": ["gcash", "maya", "card"],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {
                    "user_id": str(user.pk),
                    "plan_slug": plan.slug,
                },
            }
        }
    }

    response = requests.post(
        f"{PAYMONGO_API_BASE}/checkout_sessions",
        json=payload,
        headers={
            "Authorization": _auth_header(),
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    response.raise_for_status()

    data = response.json()
    checkout_url: str = data["data"]["attributes"]["checkout_url"]
    logger.info(
        "PayMongo checkout session created for user %s plan %s", user.pk, plan.slug
    )
    return checkout_url
