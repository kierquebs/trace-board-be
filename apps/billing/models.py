from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.Model):
    """
    Subscription plan definition.

    Three tiers (seeded via data migration):
      starter  — ₱299/mo  — 1 seat, standard boards
      pro      — ₱599/mo  — 1 seat, all boards, annotations
      shop     — ₱1499/mo — 5 seats, shared workspace, restricted boards
    """

    name = models.CharField(max_length=50)                        # "Starter", "Pro", "Shop"
    slug = models.SlugField(unique=True)                          # "starter", "pro", "shop"
    price_php = models.DecimalField(max_digits=10, decimal_places=2)
    max_seats = models.IntegerField(default=1)
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return f"{self.name} — ₱{self.price_php}/mo"


class Subscription(models.Model):
    """
    A technician's active subscription.
    OneToOne with User — a technician has at most one subscription.
    Admins do not have subscriptions; access is controlled by role.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past Due"
        CANCELLED = "cancelled", "Cancelled"
        TRIAL = "trial", "Trial"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices)

    # PayMongo integration
    paymongo_subscription_id = models.CharField(max_length=100, blank=True, db_index=True)
    payment_method = models.CharField(
        max_length=30,
        blank=True,
        help_text="gcash | maya | card",
    )

    # Billing period
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    trial_end = models.DateTimeField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} — {self.plan.name} ({self.status})"

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        if self.status == self.Status.TRIAL and self.trial_end:
            return now < self.trial_end
        return self.status == self.Status.ACTIVE and now < self.current_period_end

    @property
    def tier_slug(self) -> str:
        return self.plan.slug

    def cancel(self) -> None:
        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(update_fields=["status", "cancelled_at", "updated_at"])


class Payment(models.Model):
    """
    Individual payment record linked to a subscription.
    Created on each successful PayMongo webhook event.
    """

    class PaymentStatus(models.TextChoices):
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments",
    )

    paymongo_payment_id = models.CharField(max_length=100, unique=True)
    amount_php = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices)
    payment_method = models.CharField(max_length=30, blank=True)

    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    raw_webhook_data = models.JSONField(default=dict)  # Full PayMongo event payload
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Payment {self.paymongo_payment_id} — ₱{self.amount_php} ({self.status})"
