from rest_framework import serializers
from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "name", "slug", "price_php", "max_seats", "features", "sort_order"]
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_slug = serializers.CharField(source="plan.slug", read_only=True)
    price_php = serializers.DecimalField(
        source="plan.price_php", max_digits=10, decimal_places=2, read_only=True
    )
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan_name",
            "plan_slug",
            "price_php",
            "status",
            "payment_method",
            "current_period_start",
            "current_period_end",
            "trial_end",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class SubscribeSerializer(serializers.Serializer):
    plan_slug = serializers.ChoiceField(choices=["starter", "pro", "shop"])
    payment_method = serializers.ChoiceField(
        choices=["gcash", "maya", "card"],
        default="gcash",
    )
