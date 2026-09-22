# Django
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.utils import timezone

# Standard Library
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

# Every shape release 5 has to handle, manufactured rather than restored.
#
# A production snapshot would test this too, but it carries PII onto a
# review app and Stripe ids from an account the review app cannot reach,
# so every billing line reads as unidentified.  Manufactured data has
# neither problem and tests every branch of the command on purpose - the
# one thing it cannot do is find a subscriber in a shape nobody thought of,
# which is what the mapping-vs-production query in the runbook is for.
#
# Entitlement resources are production's, verbatim from a 2026-09-21 dump.
# The two things that matter about them: DocumentCloud's key is
# `base_ai_credits` / `ai_credits_per_user` (not `base_credits`, which is
# Scoutpost's), and the Organization tier scales on *both* clients - 10
# requests and 500 credits per block - which is the whole reason the grant
# check has a rule for the dropped DocumentCloud half.

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

# Legacy plans, priced as production prices them.  `for_groups` decides
# whether `minimum_users` and `price_per_user` enter the arithmetic.
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

# Every canonical tier and pack, as 0082 seeds them - the whole price
# matrix, not only the ones a seeded subscriber lands on.  The backfill's
# preflight refuses to run unless every target price exists, and
# consolidate_stripe_products creates a price only for a plan that exists,
# so a missing tier here is a refusal there.  Free here: their real prices
# are the PlanPrice rows consolidation creates.
CANONICAL_PLANS = [
    (slug, slug.replace("-", " ").title()) for slug in sorted(CANONICAL_SLUGS)
]

# Every subscriber shape the command has a branch for.
# (org slug, plan slug, quantity, billing, cancelled)
SUBSCRIBERS = [
    # The twelve production block-holders' shapes: Organization at 6..18.
    ("mig-org-6", "organization", 6, True, False),
    ("mig-org-7", "organization", 7, True, False),
    ("mig-org-10", "organization", 10, True, False),
    ("mig-org-15", "organization", 15, True, False),
    ("mig-org-18", "organization", 18, True, False),
    ("mig-org-annual-10", "organization-annual", 10, True, False),
    # Exactly on minimum: drops to quantity 1 with no pack.
    ("mig-org-min", "organization", 5, True, False),
    # 200 comped blocks -> a comped pack line.
    ("mig-flexible", "organization-flexible-users-annual", 205, False, False),
    # Per-unit plan.  At quantity 1, because production has no individual
    # line above it (confirmed 2026-09-22) - and a per-unit line that *is*
    # above 1 blocks the entitlement shape migration, which would make
    # this seed unable to rehearse the step after the one it is for.
    # That a per-unit plan keeps its quantity is covered by
    # test_a_per_unit_plan_keeps_its_quantity.
    ("mig-pro", "professional", 1, True, False),
    # Both Custom CRP organizations, at their 75 minimum.
    ("mig-crp-a", "custom-crp", 75, True, False),
    ("mig-crp-b", "custom-crp", 75, True, False),
    # Comped conversions: granted_reason gets populated.
    ("mig-beta", "beta", 1, False, False),
    ("mig-education", "education-grant", 35, False, False),
    ("mig-premium-comp", "premium-org-comp", 5, False, False),
    # Coded prices.
    ("mig-insideclimate", "insideclimate-news-plan", 80, True, False),
    ("mig-sunlight-basic", "sunlight-basic-annual", 5, True, False),
    # Nonprofit label: the re-run must not reprice this one.
    ("mig-nonprofit", "sunlight-nonprofit-essential-annual", 5, True, False),
    # Deferred, one active and one winding down.
    ("mig-cohort-active", "election-accountability-cohort", 5, True, False),
    ("mig-cohort-leaving", "election-accountability-cohort", 5, True, True),
    # DocumentCloud Premium: one individual at quantity 1, as production
    # has it.  No blocks, so no pack; $10 -> $10; and the grant is the same
    # 5,000 credits either side.  (A seeded version of this at quantity 4
    # was refused by the grant check - the plan's minimum_users is 1 but
    # the DC:Organization entitlement it shares has minimum_users 5, so
    # blocks between bill and grant nothing.  Real, and documented in Plan
    # Mapping, but nobody holds that shape, and seeding it was a guess
    # nothing exercises.)
    ("mig-dc-premium", "documentcloud-premium", 1, True, False),
]


class Command(BaseCommand):
    """Seed every subscriber shape release 5 has to migrate.

    Idempotent: re-running updates the same rows.  Run it on a review app,
    then rehearse the runbook - consolidate_stripe_products, then
    backfill_plan_prices --dry-run --local-only.  Local-only because these
    subscriptions have no Stripe counterpart; the item-id sync and the
    Stripe call are what a production snapshot with the right keys would
    add, and nothing else.
    """

    help = "Seed manufactured subscribers in every shape the 2d migration handles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--teardown", action="store_true", help="Remove everything this seeded"
        )

    def handle(self, *args, **options):
        if options["teardown"]:
            self.teardown()
        else:
            self.seed()

    @transaction.atomic
    def seed(self):
        # Creating a paid Plan fires `make_stripe_plan`, which creates a
        # legacy Stripe Plan.  Nothing in this seed should reach Stripe -
        # that is the point of it - so the signal is off for the duration.
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
                f"  backfill_plan_prices --dry-run --local-only "
                f"--actor {actor.username}"
            )
        )

    def _clients(self):
        """One OIDC client per resource vocabulary.

        0082 resolves each pack's client by which client's entitlements
        carry its resource key, so the two must exist and must be distinct.
        """
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
            # `update_or_create`, not `get_or_create`: the e2e seed makes
            # `organization` free, and a free Organization defeats the
            # entire rehearsal.  These have to carry production's prices.
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
        # Sunlight and the comped tiers share Organization's entitlements in
        # production; mirror that so the grant check compares like with like.
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
        # DocumentCloud Premium shares only the DocumentCloud half - it is
        # the one DocumentCloud-only plan, and grants nothing on MuckRock.
        # Its blocks are credits, which is why it decomposes to the credit
        # pack and not the request pack.
        plans["documentcloud-premium"].entitlements.set(
            org_entitlements.filter(client=clients[DOCUMENTCLOUD])
        )

    def _actor(self):
        # `create_user`, not `get_or_create`: a user needs an individual
        # organization, which only the manager's create path makes.
        actor = User.objects.filter(username="mig-actor").first()
        if actor is None:
            actor = User.objects.create_user(
                username="mig-actor",
                email="mig-actor@example.com",
                password="mig-actor-password",
                is_staff=True,
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
            interval = "annual" if plan.annual else "monthly"
            subscription, _ = Subscription.objects.update_or_create(
                organization=org,
                interval=interval,
                collection_method="charge_automatically",
                defaults={
                    # A fake id, so `is_billing` reads it as a paid line;
                    # blank for comped.  Nothing here reaches Stripe.
                    "subscription_id": f"sub_mig_{org_slug}" if billing else "",
                    "current_period_end": period_end,
                    "cancelled": cancelled,
                    "cancel_at": (period_end.date() if cancelled else None),
                },
            )
            SubscriptionItem.objects.update_or_create(
                subscription=subscription,
                plan=plan,
                defaults={
                    "quantity": quantity,
                    "plan_price": None,
                    "stripe_item_id": f"si_mig_{org_slug}" if billing else "",
                    "cancelled": cancelled,
                    "cancel_at": (period_end.date() if cancelled else None),
                },
            )
            self.stdout.write(
                f"  {org_slug}: {plan_slug} x{quantity}"
                f"{' (comped)' if not billing else ''}"
                f"{' (cancelling)' if cancelled else ''}"
            )

    @transaction.atomic
    def teardown(self):
        orgs = Organization.objects.filter(slug__startswith="mig-")
        # Change-log rows PROTECT both the user and the plans they name, and
        # a rehearsal run writes one per migrated line.  They are the
        # seed's own history, so they go with it.
        OrganizationChangeLog.objects.filter(
            Q(organization__in=orgs) | Q(user__username="mig-actor")
        ).delete()
        # Then the actor: its individual organization is PROTECTed by the
        # user row, and is slugged `mig-actor` like everything else here.
        User.objects.filter(username="mig-actor").delete()
        SubscriptionItem.objects.filter(subscription__organization__in=orgs).delete()
        Subscription.objects.filter(organization__in=orgs).delete()
        count = orgs.count()
        orgs.delete()
        Entitlement.objects.filter(slug__startswith="mig-").delete()
        Client.objects.filter(client_id__startswith="mig-").delete()
        self.stdout.write(f"Removed {count} seeded organizations and their lines.")
