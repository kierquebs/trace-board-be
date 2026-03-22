"""
Tests for custom permission classes.
These guard the entire security model of the app.
"""
import pytest
from unittest.mock import MagicMock

from apps.accounts.permissions import (
    CanViewBoard,
    HasActiveSubscription,
    IsAdmin,
    IsTechnician,
)
from apps.boards.models import BoardStatus


def _make_request(user):
    request = MagicMock()
    request.user = user
    return request


# ─────────────────────────────────────────────────────────────────────────────
# IsAdmin
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestIsAdmin:
    perm = IsAdmin()
    view = MagicMock()

    def test_admin_passes(self, admin_user):
        assert self.perm.has_permission(_make_request(admin_user), self.view)

    def test_technician_fails(self, technician_user):
        assert not self.perm.has_permission(_make_request(technician_user), self.view)

    def test_suspended_admin_fails(self, admin_user):
        admin_user.is_suspended = True
        assert not self.perm.has_permission(_make_request(admin_user), self.view)

    def test_unauthenticated_fails(self):
        user = MagicMock()
        user.is_authenticated = False
        assert not self.perm.has_permission(_make_request(user), self.view)


# ─────────────────────────────────────────────────────────────────────────────
# HasActiveSubscription
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestHasActiveSubscription:
    perm = HasActiveSubscription()
    view = MagicMock()

    def test_admin_always_passes(self, admin_user):
        assert self.perm.has_permission(_make_request(admin_user), self.view)

    def test_subscribed_technician_passes(self, subscribed_technician):
        assert self.perm.has_permission(_make_request(subscribed_technician), self.view)

    def test_unsubscribed_technician_fails(self, technician_user):
        assert not self.perm.has_permission(_make_request(technician_user), self.view)

    def test_suspended_user_fails(self, subscribed_technician):
        subscribed_technician.is_suspended = True
        assert not self.perm.has_permission(_make_request(subscribed_technician), self.view)


# ─────────────────────────────────────────────────────────────────────────────
# CanViewBoard
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCanViewBoard:
    perm = CanViewBoard()
    view = MagicMock()

    def test_admin_can_view_any_board(self, admin_user, disabled_board):
        """Admins bypass all board status checks."""
        assert self.perm.has_object_permission(
            _make_request(admin_user), self.view, disabled_board
        )

    def test_technician_can_view_enabled(self, subscribed_technician, enabled_board):
        assert self.perm.has_object_permission(
            _make_request(subscribed_technician), self.view, enabled_board
        )

    def test_technician_cannot_view_disabled(self, subscribed_technician, disabled_board):
        assert not self.perm.has_object_permission(
            _make_request(subscribed_technician), self.view, disabled_board
        )

    def test_starter_cannot_view_pro_restricted(
        self, db, subscribed_technician, restricted_board
    ):
        """Restricted board requires pro tier; starter subscriber is denied."""
        # subscribed_technician has starter plan (from fixture)
        assert not self.perm.has_object_permission(
            _make_request(subscribed_technician), self.view, restricted_board
        )

    def test_pro_subscriber_can_view_restricted(self, db, admin_user):
        """Pro subscriber meets min_tier=pro requirement."""
        from tests.conftest import UserFactory, PlanFactory, SubscriptionFactory, BoardFileFactory

        pro_plan = PlanFactory(name="Pro", slug="pro", price_php="599.00", sort_order=2)
        pro_user = UserFactory()
        SubscriptionFactory(user=pro_user, plan=pro_plan)

        restricted = BoardFileFactory(
            uploaded_by=admin_user,
            status=BoardStatus.RESTRICTED,
            min_tier="pro",
        )
        assert self.perm.has_object_permission(
            _make_request(pro_user), self.view, restricted
        )
