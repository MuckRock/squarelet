from django.db import migrations

# Display grouping for the plan page.  Legacy rows consolidate onto these or
# are archived, and internal plans (Admin) never appear on the plan page, so
# both are left blank.
TIER_PRODUCTS = {
    "professional": "muckrock",
    "organization": "muckrock",
    "documentcloud-premium": "documentcloud",
    "sunlight-essential": "sunlight",
    "sunlight-enhanced": "sunlight",
    "sunlight-enterprise": "sunlight",
    "scoutpost-pro": "scoutpost",
    "scoutpost-team": "scoutpost",
}

PACK_PRICE_PER_UNIT = 10

# One add-on pack per product, bought by setting Subscription.quantity.
#
# `resources` deliberately uses the CURRENT formula shape
# (base + max(quantity - minimum_users, 0) * per_user) rather than the flat
# target shape.  Client sites still evaluate that formula, so a flat
# {"base_requests": 10} would grant 10 in total no matter how many units were
# bought.  With base 0 / minimum 0 / per_user 10 it correctly yields
# 10 * quantity today.
#
# A later migration flattens these, at the same time the client sites switch
# to base * quantity.  That conversion must MOVE the per_user value into the
# base for a pack - not simply drop the per-user keys, which is the correct
# transform for a tier.  Applying the tier transform to a pack leaves
# base_requests at 0 and silently grants nothing.
PACKS = [
    {
        "slug": "muckrock-request-pack",
        "name": "MuckRock Request Pack",
        "product": "muckrock",
        "resource_key": "base_requests",
        "description": "Additional MuckRock requests, 10 per pack per month",
        "resources": {
            "base_requests": 0,
            "minimum_users": 0,
            "requests_per_user": 10,
        },
    },
    {
        "slug": "documentcloud-credit-pack",
        "name": "DocumentCloud Credit Pack",
        "product": "documentcloud",
        "resource_key": "base_ai_credits",
        "description": "Additional DocumentCloud AI credits, 500 per pack per month",
        "resources": {
            "base_ai_credits": 0,
            "minimum_users": 0,
            "ai_credits_per_user": 500,
        },
    },
    {
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
    },
]


def client_for(Entitlement, resource_key):
    """Find the OIDC client owning a resource key, or None.

    Resolved from existing data rather than hardcoded primary keys so this
    works across environments - each client uses a distinct resource
    vocabulary.  Returns None where the key is absent (a seeded dev database
    or a fresh test database), leaving nothing to set up.
    """
    clients = set(
        Entitlement.objects.filter(resources__has_key=resource_key).values_list(
            "client_id", flat=True
        )
    )
    return clients.pop() if len(clients) == 1 else None


def create_tiers_and_packs(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    Entitlement = apps.get_model("organizations", "Entitlement")

    for slug, product in TIER_PRODUCTS.items():
        # Environments legitimately differ - dev and test databases are
        # seeded subsets - so a missing tier is skipped rather than fatal.
        Plan.objects.filter(slug=slug).update(product=product)

    for spec in PACKS:
        client_id = client_for(Entitlement, spec["resource_key"])
        if client_id is None:
            continue

        entitlement, _ = Entitlement.objects.update_or_create(
            slug=spec["slug"],
            client_id=client_id,
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "resources": spec["resources"],
            },
        )
        plan, _ = Plan.objects.update_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "product": spec["product"],
                # Packs are priced purely per unit, with
                # Subscription.quantity carrying how many were bought.
                # minimum_users=0 so every unit counts, unlike a tier whose
                # base covers the first few.  These legacy pricing fields
                # are removed once nothing reads them any more.
                "base_price": 0,
                "price_per_user": PACK_PRICE_PER_UNIT,
                "minimum_users": 0,
                # Not directly subscribable from the plan list - packs are
                # offered contextually alongside a base plan.
                "public": False,
                "for_individuals": True,
                "for_groups": True,
                "annual": False,
                "auto_renew": True,
            },
        )
        plan.entitlements.add(entitlement)


def remove_tiers_and_packs(apps, schema_editor):
    Plan = apps.get_model("organizations", "Plan")
    Entitlement = apps.get_model("organizations", "Entitlement")

    slugs = [spec["slug"] for spec in PACKS]

    # PlanPrice.plan is PROTECT, so once consolidate_stripe_products has run
    # the delete below raises ProtectedError with nothing explaining why.
    # Say it plainly instead: those rows point at live Stripe Prices, and
    # silently dropping them here would orphan every one.
    priced = Plan.objects.filter(slug__in=slugs, prices__isnull=False).distinct()
    if priced.exists():
        raise RuntimeError(
            "Cannot reverse: these pack plans still have PlanPrice rows "
            f"({', '.join(sorted(priced.values_list('slug', flat=True)))}). "
            "Those point at Stripe Prices that reversing cannot delete. "
            "Archive them in Stripe and remove the rows first."
        )

    for plan in Plan.objects.filter(slug__in=slugs):
        plan.entitlements.clear()
        plan.delete()
    Plan.objects.filter(slug__in=TIER_PRODUCTS).update(product="")

    # The pack Entitlements are deliberately left in place.  Deleting them
    # here raises "Cannot query Entitlement object: Must be Entitlement
    # instance" - the deletion collector walks the EntitlementGrant m2m and
    # trips over a historical instance being handed to a real-model query.
    # The same delete works fine outside a migration, so this is a
    # historical-model edge case rather than an application problem.
    #
    # Leaving them is harmless: with their plans gone nothing references
    # them, they grant nobody anything, and re-applying this migration
    # reuses them via update_or_create rather than duplicating.


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0081_plan_price"),
    ]

    operations = [
        migrations.RunPython(create_tiers_and_packs, remove_tiers_and_packs),
    ]
