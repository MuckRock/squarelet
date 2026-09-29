# Django
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.utils import timezone

# Standard Library
import os
from datetime import timedelta

# Third Party
from oidc_provider.models import Client

# Squarelet
from squarelet.organizations.management.commands.consolidate_stripe_products import (
    CANONICAL_SLUGS,
)
from squarelet.organizations.models import (
    Entitlement,
    Organization,
    OrganizationChangeLog,
    Plan,
    Subscription,
    SubscriptionItem,
)
from squarelet.organizations.signals import make_stripe_plan
from squarelet.users.models import User

# Every subscriber shape release 5 migrates, manufactured rather than copied
# from production: no personal data on a review app, and no Stripe ids from an
# account it cannot reach.  Entitlement resources are production's (dumped
# 2026-09-21).

MUCKROCK = "muckrock"
DOCUMENTCLOUD = "documentcloud"

# (plan slug) -> (client, resources)
ENTITLEMENTS = {
    "organization": [
        (
            MUCKROCK,
            {
                "base_requests": 50,
                "feature_level": 2,
                "minimum_users": 5,
                "requests_per_user": 10,
            },
        ),
        (
            DOCUMENTCLOUD,
            {
                "feature_level": 2,
                "minimum_users": 5,
                "base_ai_credits": 5000,
                "ai_credits_per_user": 500,
            },
        ),
    ],
    "professional": [
        (
            MUCKROCK,
            {
                "base_requests": 20,
                "feature_level": 1,
                "minimum_users": 1,
                "requests_per_user": 0,
            },
        ),
        (
            DOCUMENTCLOUD,
            {
                "feature_level": 1,
                "minimum_users": 1,
                "base_ai_credits": 2000,
                "ai_credits_per_user": 0,
            },
        ),
    ],
    "custom-crp": [
        (
            MUCKROCK,
            {
                "base_requests": 50,
                "feature_level": 2,
                "minimum_users": 75,
                "requests_per_user": 5,
            },
        ),
        (
            DOCUMENTCLOUD,
            {
                "feature_level": 2,
                "minimum_users": 75,
                "base_ai_credits": 5000,
                "ai_credits_per_user": 500,
            },
        ),
    ],
    "beta": [
        (
            MUCKROCK,
            {
                "base_requests": 5,
                "feature_level": 1,
                "minimum_users": 1,
                "requests_per_user": 0,
            },
        ),
    ],
    "education-grant": [
        (
            MUCKROCK,
            {
                "base_requests": 50,
                "feature_level": 2,
                "minimum_users": 35,
                "requests_per_user": 0,
            },
        ),
        (
            DOCUMENTCLOUD,
            {
                "feature_level": 2,
                "minimum_users": 35,
                "base_ai_credits": 5000,
                "ai_credits_per_user": 0,
            },
        ),
    ],
    "insideclimate-news-plan": [
        (
            MUCKROCK,
            {
                "base_requests": 15,
                "feature_level": 2,
                "minimum_users": 80,
                "requests_per_user": 0,
            },
        ),
    ],
    "muckrock-request-pack": [
        (MUCKROCK, {"base_requests": 0, "minimum_users": 0, "requests_per_user": 10}),
    ],
    "documentcloud-credit-pack": [
        (
            DOCUMENTCLOUD,
            {"minimum_users": 0, "base_ai_credits": 0, "ai_credits_per_user": 500},
        ),
    ],
}

# Legacy plans at production's prices.
# (slug, name, base_price, minimum_users, price_per_user, for_groups, annual)
LEGACY_PLANS = [
    ("organization", "Organization", 100, 5, 10, True, False),
    ("organization-annual", "Organization (Annual)", 1200, 5, 120, True, True),
    (
        "organization-flexible-users-annual",
        "Organization - Flexible Users (Annual Invoice)",
        0,
        5,
        0,
        True,
        True,
    ),
    ("professional", "Professional", 40, 1, 0, False, False),
    ("custom-crp", "Custom CRP", 100, 75, 10, True, False),
    ("beta", "Beta", 0, 1, 0, False, False),
    ("education-grant", "Education Grant", 0, 35, 0, True, False),
    ("premium-org-comp", "Premium Org Comp", 0, 5, 0, True, False),
    ("insideclimate-news-plan", "InsideClimate News Plan", 30, 80, 0, True, False),
    (
        "sunlight-basic-annual",
        "Sunlight Research Desk Membership - Basic (Annual)",
        2000,
        5,
        120,
        True,
        True,
    ),
    (
        "sunlight-nonprofit-essential-annual",
        "Sunlight Research Center - Essential (Annual, Non-Profit)",
        4000,
        5,
        120,
        True,
        True,
    ),
    (
        "election-accountability-cohort",
        "Election Accountability Cohort",
        3000,
        5,
        120,
        True,
        True,
    ),
    ("documentcloud-premium", "DocumentCloud Premium", 10, 1, 10, True, False),
]

# Every tier and pack, so every target price can exist.  Not the staff-only
# admin plan: nothing seeded lands on it.
CANONICAL_PLANS = [
    (slug, slug.replace("-", " ").title())
    for slug in sorted(CANONICAL_SLUGS - {"admin"})
]

# A cohort subscriber billed monthly on a plan that says annual, as one is.
INTERVAL_OVERRIDES = {"mig-cohort-monthly": "monthly"}

# Every subscriber shape the command has a branch for.
# (org slug, plan slug, quantity, billing, cancelled)
SUBSCRIBERS = [
    # Block-holders, as production's twelve are: Organization at 6 to 18.
    ("mig-org-6", "organization", 6, True, False),
    ("mig-org-7", "organization", 7, True, False),
    ("mig-org-10", "organization", 10, True, False),
    ("mig-org-15", "organization", 15, True, False),
    ("mig-org-18", "organization", 18, True, False),
    ("mig-org-annual-10", "organization-annual", 10, True, False),
    # On the minimum: one unit, no pack.
    ("mig-org-min", "organization", 5, True, False),
    # 200 comped blocks: a free pack.
    ("mig-flexible", "organization-flexible-users-annual", 205, False, False),
    # At quantity 1, as every individual line in production is; above it,
    # release 6 would refuse the line.
    ("mig-pro", "professional", 1, True, False),
    ("mig-crp-a", "custom-crp", 75, True, False),
    ("mig-crp-b", "custom-crp", 75, True, False),
    # Comped: moved to the free subscription with a granted_reason.
    ("mig-beta", "beta", 1, False, False),
    ("mig-education", "education-grant", 35, False, False),
    ("mig-premium-comp", "premium-org-comp", 5, False, False),
    # Negotiated rates.
    ("mig-insideclimate", "insideclimate-news-plan", 80, True, False),
    ("mig-sunlight-basic", "sunlight-basic-annual", 5, True, False),
    ("mig-nonprofit", "sunlight-nonprofit-essential-annual", 5, True, False),
    # The cohort: renewing, ending, and billed monthly.
    ("mig-cohort-active", "election-accountability-cohort", 5, True, False),
    ("mig-cohort-leaving", "election-accountability-cohort", 5, True, True),
    ("mig-cohort-monthly", "election-accountability-cohort", 5, True, False),
    # One individual at quantity 1, as production has it.
    ("mig-dc-premium", "documentcloud-premium", 1, True, False),
]


SEEDED_ORGS = {org for org, *_ in SUBSCRIBERS}


class Command(BaseCommand):
    """Seed every subscriber shape release 5 migrates.

    For a throwaway review app or local dev only: it rewrites the Organization,
    Professional and DocumentCloud Premium plans and their entitlements, and
    refuses to run anywhere else.  Then rehearse: consolidate_stripe_products
    --allow-missing, and backfill_plan_prices --local-only.
    """

    help = "Seed manufactured subscribers in every shape the 2d migration handles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--teardown", action="store_true", help="Remove everything this seeded"
        )

    def handle(self, *args, **options):
        # Heroku sets HEROKU_PR_NUMBER on review apps, which also run as staging.
        if settings.ENV != "dev" and not os.environ.get("HEROKU_PR_NUMBER"):
            raise CommandError(
                "Only for local dev or a review app: this rewrites real plans."
            )
        if options["teardown"]:
            self.teardown()
        else:
            self.seed()

    @transaction.atomic
    def seed(self):
        # Seeded again, each migrated line would get a legacy one beside it.
        if SubscriptionItem.objects.filter(
            subscription__organization__slug__in=SEEDED_ORGS,
            plan_price__isnull=False,
        ).exists():
            raise CommandError("Already rehearsed: run --teardown first.")
        # Saving a paid plan would create a legacy Stripe Plan.
        post_save.disconnect(
            make_stripe_plan,
            sender=Plan,
            dispatch_uid="squarelet.organizations.signals.make_stripe_plan",
        )
        try:
            clients = self._clients()
            plans = self._plans()
        finally:
            post_save.connect(
                make_stripe_plan,
                sender=Plan,
                dispatch_uid="squarelet.organizations.signals.make_stripe_plan",
            )
        self._entitlements(plans, clients)
        actor = self._actor()
        self._subscribers(plans)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSeeded {len(SUBSCRIBERS)} subscribers across "
                f"{len(LEGACY_PLANS)} legacy plans.  Next:\n"
                f"  consolidate_stripe_products --allow-missing\n"
                f"  backfill_plan_prices --local-only "
                f"--actor {actor.username}"
            )
        )

    def _clients(self):
        """One client per product; packs find theirs by resource key."""
        clients = {}
        for name in (MUCKROCK, DOCUMENTCLOUD):
            clients[name], _ = Client.objects.get_or_create(
                client_id=f"mig-{name}",
                defaults={
                    "name": f"Migration seed: {name}",
                    "client_type": "public",
                    "redirect_uris": "https://example.com/",
                },
            )
        return clients

    def _plans(self):
        plans = {}
        for slug, name, base, minimum, per_user, groups, annual in LEGACY_PLANS:
            # Updated, not fetched: the e2e seed makes Organization free.
            plans[slug], _ = Plan.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "base_price": base,
                    "minimum_users": minimum,
                    "price_per_user": per_user,
                    "for_groups": groups,
                    "for_individuals": not groups,
                    "annual": annual,
                    "public": False,
                },
            )
        for slug, name in CANONICAL_PLANS:
            plans[slug], _ = Plan.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "for_groups": True, "for_individuals": False},
            )
        return plans

    def _entitlements(self, plans, clients):
        for plan_slug, specs in ENTITLEMENTS.items():
            plan = plans[plan_slug]
            plan.entitlements.clear()
            for client_name, resources in specs:
                entitlement, _ = Entitlement.objects.update_or_create(
                    client=clients[client_name],
                    slug=f"mig-{plan_slug}",
                    defaults={
                        "name": f"{plan.name} ({client_name})",
                        "resources": resources,
                    },
                )
                plan.entitlements.add(entitlement)
        # Shared with Organization in production.
        org_entitlements = plans["organization"].entitlements.all()
        for slug in (
            "sunlight-basic-annual",
            "sunlight-nonprofit-essential-annual",
            "election-accountability-cohort",
            "premium-org-comp",
            "organization-annual",
            "organization-flexible-users-annual",
            "sunlight-essential",
        ):
            plans[slug].entitlements.set(org_entitlements)
        # The one DocumentCloud-only plan: only that half.
        plans["documentcloud-premium"].entitlements.set(
            org_entitlements.filter(client=clients[DOCUMENTCLOUD])
        )

    def _actor(self):
        # create_user makes the individual organization a user needs.
        actor = User.objects.filter(username="mig-actor").first()
        if actor is None:
            # Named as the grantor only; it never needs to log in.
            actor = User.objects.create_user(
                username="mig-actor", email="mig-actor@example.com", password=None
            )
        return actor

    def _subscribers(self, plans):
        period_end = timezone.now() + timedelta(days=20)
        for org_slug, plan_slug, quantity, billing, cancelled in SUBSCRIBERS:
            org, _ = Organization.objects.get_or_create(
                slug=org_slug,
                defaults={
                    "name": org_slug.replace("mig-", "Migration ").title(),
                    "individual": False,
                },
            )
            plan = plans[plan_slug]
            interval = INTERVAL_OVERRIDES.get(
                org_slug, "annual" if plan.annual else "monthly"
            )
            subscription, _ = Subscription.objects.update_or_create(
                organization=org,
                interval=interval,
                collection_method="charge_automatically",
                defaults={
                    # Fake, so the line reads as billing; nothing reaches Stripe.
                    "subscription_id": f"sub_mig_{org_slug}" if billing else "",
                    "current_period_end": period_end,
                },
            )
            if cancelled:
                subscription.mark_cancelled(period_end)
            else:
                subscription.clear_cancellation()
            subscription.save(update_fields=Subscription.CANCELLATION_FIELDS)
            SubscriptionItem.objects.update_or_create(
                subscription=subscription,
                plan=plan,
                defaults={
                    "quantity": quantity,
                    "plan_price": None,
                    "stripe_item_id": f"si_mig_{org_slug}" if billing else "",
                },
            )
            self.stdout.write(
                f"  {org_slug}: {plan_slug} x{quantity}"
                f"{' (comped)' if not billing else ''}"
                f"{' (cancelling)' if cancelled else ''}"
            )

    @transaction.atomic
    def teardown(self):
        # Exactly what was seeded: a real "mig-" slug is not ours to delete.
        orgs = Organization.objects.filter(slug__in=SEEDED_ORGS)
        actor = User.objects.filter(username="mig-actor").first()
        # Change logs protect the user and plans they name.
        OrganizationChangeLog.objects.filter(
            Q(organization__in=orgs) | Q(user=actor)
        ).delete()
        # Before the user: migrated comped lines name it as their grantor.
        SubscriptionItem.objects.filter(subscription__organization__in=orgs).delete()
        Subscription.objects.filter(organization__in=orgs).delete()
        count = orgs.count()
        orgs.delete()
        if actor is not None:
            individual = actor.individual_organization
            actor.delete()
            individual.delete()
        Entitlement.objects.filter(
            slug__in={f"mig-{plan_slug}" for plan_slug in ENTITLEMENTS}
        ).delete()
        Client.objects.filter(
            client_id__in={f"mig-{name}" for name in (MUCKROCK, DOCUMENTCLOUD)}
        ).delete()
        self.stdout.write(f"Removed {count} seeded organizations and their lines.")
