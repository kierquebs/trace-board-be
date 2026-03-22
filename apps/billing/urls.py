from django.urls import path
from .views import (
    PlanListView,
    SubscribeView,
    SubscriptionStatusView,
    CancelSubscriptionView,
    PayMongoWebhookView,
)

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="billing-plans"),
    path("subscribe/", SubscribeView.as_view(), name="billing-subscribe"),
    path("status/", SubscriptionStatusView.as_view(), name="billing-status"),
    path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
    path("webhooks/paymongo/", PayMongoWebhookView.as_view(), name="billing-webhook-paymongo"),
]
