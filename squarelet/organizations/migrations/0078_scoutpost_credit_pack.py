from django.db import migrations

# The third add-on pack, missed when the MuckRock and DocumentCloud packs
# were added in 0076.  Scoutpost Team grants 1,000 credits per unit, so
# overage needs a pack of its own - Scoutpost credits are a separate
# currency from MuckRock requests and DocumentCloud AI credits.
#
# As in 0076, `resources` uses the CURRENT formula shape rather than the
# flat target shape, so it evaluates correctly against today's client
# logic.  Step 3h moves it over.
PACK = {
    "slug": "scoutpost-credit-pack",
    "name": "Scoutpost Credit Pack",
    "product": "scoutpost",
    "resource_key": "base_credits",
    "description": "Additional Scoutpost credits, 1,000 per pack per month",
    "resources": {
        "base_credits": 0,
        "minimum_users": 0,
        "credits_per_user": 1000,
    },
}

PACK_PRICE_PER_UNIT = 10


def create_scoutpost_pack(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    Entitlement = apps.get_model("organizations", "Entitlement")

    # Resolved from data rather than a hardcoded primary key; None on a
    # database with no Scoutpost entitlements (dev and test subsets), where
    # there is nothing to set up.
    clients = set(
        Entitlement.objects.filter(
            resources__has_key=PACK["resource_key"]
        ).values_list("client_id", flat=True)
    )
    if len(clients) != 1:
        return
    client_id = clients.pop()

    entitlement, _ = Entitlement.objects.update_or_create(
        slug=PACK["slug"],
        client_id=client_id,
        defaults={
            "name": PACK["name"],
            "description": PACK["description"],
            "resources": PACK["resources"],
        },
    )
    plan, _ = Plan.objects.update_or_create(
        slug=PACK["slug"],
        defaults={
            "name": PACK["name"],
            "product": PACK["product"],
            "base_price": 0,
            "price_per_user": PACK_PRICE_PER_UNIT,
            "minimum_users": 0,
            "public": False,
            "for_individuals": True,
            "for_groups": True,
            "annual": False,
            "auto_renew": True,
        },
    )
    plan.entitlements.add(entitlement)


def remove_scoutpost_pack(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    Entitlement = apps.get_model("organizations", "Entitlement")
    Plan.objects.filter(slug=PACK["slug"]).delete()
    Entitlement.objects.filter(slug=PACK["slug"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0077_planprice_stripe_price_id_optional"),
    ]

    operations = [
        migrations.RunPython(create_scoutpost_pack, remove_scoutpost_pack),
    ]
