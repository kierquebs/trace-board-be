from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    TECHNICIAN = "technician", "Technician"


class User(AbstractUser):
    """
    Custom user model with role-based access.

    Two roles exist:
      - admin: platform staff, full access, no subscription needed
      - technician: paying customer, needs active subscription to view boards
    """

    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.TECHNICIAN,
        db_index=True,
    )
    phone = models.CharField(max_length=20, blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    is_suspended = models.BooleanField(
        default=False,
        help_text=_("Suspended users cannot log in or access any features."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_joined"]
        verbose_name = "user"
        verbose_name_plural = "users"

    # ------------------------------------------------------------------
    # Role helpers
    # ------------------------------------------------------------------

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_technician(self) -> bool:
        return self.role == UserRole.TECHNICIAN

    @property
    def has_active_subscription(self) -> bool:
        """
        True if the user can access board content.
        Admins always return True — they bypass billing entirely.
        Technicians must have an active/trial Subscription record.
        """
        if self.is_admin:
            return True
        try:
            return self.subscription.is_active  # type: ignore[union-attr]
        except Exception:
            return False

    @property
    def subscription_tier(self) -> str | None:
        """Return the plan slug ('starter', 'pro', 'shop') or None."""
        if self.is_admin:
            return "admin"
        try:
            sub = self.subscription  # type: ignore[union-attr]
            return sub.plan.slug if sub.is_active else None
        except Exception:
            return None

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"
