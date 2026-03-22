from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    plans = [
        dict(
            slug="starter",
            name="Starter",
            price_php=299,
            sort_order=1,
            features={"annotations": False, "restricted_boards": False},
        ),
        dict(
            slug="pro",
            name="Pro",
            price_php=599,
            sort_order=2,
            features={"annotations": True, "restricted_boards": True},
        ),
        dict(
            slug="shop",
            name="Shop",
            price_php=1499,
            sort_order=3,
            features={"annotations": True, "restricted_boards": True, "shared_workspace": True},
        ),
    ]
    for p in plans:
        Plan.objects.update_or_create(slug=p.pop("slug"), defaults=p)


def unseed_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Plan.objects.filter(slug__in=["starter", "pro", "shop"]).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed_plans, unseed_plans)]
