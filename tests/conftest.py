"""
Shared pytest fixtures and factory definitions.
Available in all test modules without explicit import.
"""
import pytest
import factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from apps.boards.models import BoardFile, BoardStatus
from apps.billing.models import Plan, Subscription

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Factories
# ─────────────────────────────────────────────────────────────────────────────

class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user_{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")
    role = "technician"
    is_suspended = False


class AdminUserFactory(UserFactory):
    role = "admin"
    username = factory.Sequence(lambda n: f"admin_{n}")


class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan
        django_get_or_create = ("slug",)

    name = "Starter"
    slug = "starter"
    price_php = "299.00"
    max_seats = 1
    is_active = True
    sort_order = 1


class SubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subscription

    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(PlanFactory)
    status = Subscription.Status.ACTIVE
    current_period_start = factory.LazyFunction(timezone.now)
    current_period_end = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=30)
    )


class BoardFileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BoardFile

    uploaded_by = factory.SubFactory(AdminUserFactory)
    name = factory.Sequence(lambda n: f"Test Board {n}")
    original_filename = factory.Sequence(lambda n: f"board_{n}.brd")
    brand = "Apple"
    model_number = "A2407"
    category = "cellphone"
    status = BoardStatus.ENABLED
    s3_key = factory.Sequence(lambda n: f"boards/abc12345/board_{n}.brd")
    content_hash = factory.Sequence(lambda n: f"{'a' * 63}{n}")
    file_size = 102400
    format = "brd2"
    parse_status = "success"
    part_count = 150
    pin_count = 1200
    net_count = 80


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(db):
    return AdminUserFactory()


@pytest.fixture
def technician_user(db):
    return UserFactory()


@pytest.fixture
def subscribed_technician(db):
    user = UserFactory()
    plan = PlanFactory()
    SubscriptionFactory(user=user, plan=plan)
    return user


@pytest.fixture
def starter_plan(db):
    return PlanFactory(name="Starter", slug="starter", price_php="299.00")


@pytest.fixture
def enabled_board(db, admin_user):
    return BoardFileFactory(uploaded_by=admin_user, status=BoardStatus.ENABLED)


@pytest.fixture
def disabled_board(db, admin_user):
    return BoardFileFactory(uploaded_by=admin_user, status=BoardStatus.DISABLED)


@pytest.fixture
def restricted_board(db, admin_user):
    return BoardFileFactory(
        uploaded_by=admin_user,
        status=BoardStatus.RESTRICTED,
        min_tier="pro",
    )


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def admin_client(db, admin_user):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    refresh = RefreshToken.for_user(admin_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.fixture
def technician_client(db, subscribed_technician):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    refresh = RefreshToken.for_user(subscribed_technician)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.fixture
def unsubscribed_client(db, technician_user):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    refresh = RefreshToken.for_user(technician_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client
