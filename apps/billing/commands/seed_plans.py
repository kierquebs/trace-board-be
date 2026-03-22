"""
Management command: seed_plans

Creates the three subscription plans if they don't already exist.
Safe to run multiple times (idempotent via get_or_create).

Usage:
    python manage.py seed_plans
"""
from django.core.management.base import BaseCommand

from apps.billing.models import Plan


PLANS = [
    {
        "name": "Starter",
        "slug": "starter",
        "price_php": "299.00",
        "max_seats": 1,
        "sort_order": 1,
        "features": {
            "annotations": False,
            "restricted_boards": False,
            "net_tracing": True,
        },
    },
    {
        "name": "Pro",
        "slug": "pro",
        "price_php": "599.00",
        "max_seats": 1,
        "sort_order": 2,
        "features": {
            "annotations": True,
            "restricted_boards": True,
            "net_tracing": True,
        },
    },
    {
        "name": "Shop",
        "slug": "shop",
        "price_php": "1499.00",
        "max_seats": 5,
        "sort_order": 3,
        "features": {
            "annotations": True,
            "restricted_boards": True,
            "net_tracing": True,
            "shared_workspace": True,
        },
    },
]


class Command(BaseCommand):
    help = "Seed subscription plans (Starter / Pro / Shop). Idempotent."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for plan_data in PLANS:
            plan, created = Plan.objects.update_or_create(
                slug=plan_data["slug"],
                defaults={
                    "name": plan_data["name"],
                    "price_php": plan_data["price_php"],
                    "max_seats": plan_data["max_seats"],
                    "sort_order": plan_data["sort_order"],
                    "features": plan_data["features"],
                    "is_active": True,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  Created: {plan.name} (₱{plan.price_php}/mo)")
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f"  Updated: {plan.name} (₱{plan.price_php}/mo)")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {created_count} created, {updated_count} already existed."
            )
        )
