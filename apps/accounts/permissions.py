from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class IsAdmin(BasePermission):
    """
    Grants access only to admin-role users who are not suspended.
    Use on all /api/admin/* endpoints.
    """

    message = "Admin access required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_admin
            and not request.user.is_suspended
        )


class IsTechnician(BasePermission):
    """
    Grants access only to technician-role users who are not suspended.
    Note: being a technician does NOT imply having an active subscription.
    Pair with HasActiveSubscription for board-viewing endpoints.
    """

    message = "Technician access required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_technician
            and not request.user.is_suspended
        )


class IsAdminOrTechnician(BasePermission):
    """
    Grants access to any authenticated, non-suspended user regardless of role.
    For endpoints shared between both roles (e.g. profile, logout).
    """

    message = "Authentication required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and not request.user.is_suspended
        )


class HasActiveSubscription(BasePermission):
    """
    Grants access when the user has an active subscription (or is an admin).

    - Admin users always pass.
    - Technicians need a Subscription row with status active/trial.
    - Suspended users always fail (handled before this check).

    Use on all board-viewing and annotation endpoints.
    """

    message = "An active subscription is required to access board content."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_admin:
            return True
        return request.user.has_active_subscription


class CanViewBoard(BasePermission):
    """
    Object-level permission that checks a BoardFile is accessible by this user.

    Rules:
      - Admins can view any board regardless of status.
      - Disabled boards are invisible to all technicians.
      - Restricted boards require matching subscription tier.
      - Enabled boards are accessible to any active subscriber.

    Must be used together with HasActiveSubscription on the view-level check.
    The object-level check handles the board-specific rules.
    """

    message = "You do not have permission to view this board."

    TIER_ORDER: dict[str, int] = {"starter": 1, "pro": 2, "shop": 3}

    def has_object_permission(
        self, request: Request, view: APIView, obj: object
    ) -> bool:
        # Circular import guard — BoardFile imported inside method
        from apps.boards.models import BoardStatus

        if request.user.is_admin:
            return True

        board_status = obj.status  # type: ignore[union-attr]

        if board_status == BoardStatus.DISABLED:
            return False

        if board_status == BoardStatus.RESTRICTED:
            user_tier = request.user.subscription_tier
            if not user_tier:
                return False
            user_level = self.TIER_ORDER.get(user_tier, 0)
            required_level = self.TIER_ORDER.get(obj.min_tier, 1)  # type: ignore[union-attr]
            return user_level >= required_level

        # BoardStatus.ENABLED — any active subscriber can view
        return True
