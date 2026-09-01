# Django
from django.core.management.base import BaseCommand, CommandError

# Standard Library
import logging
from collections import Counter

# Squarelet
from squarelet.organizations.models.payment import Plan, PlanPrice

logger = logging.getLogger(__name__)

CURRENCY = "usd"

# The full target price list.  Amounts are in cents, matching
# PlanPrice.amount and Stripe's unit_amount.
#
# Hardcoded rather than derived from the legacy plans on purpose: these
# create immutable Stripe Prices, and the legacy rows they came from are
# archived once nothing points at them.  This matrix is the authoritative
# list of what the tiers cost; each row was chosen against the legacy plan
# it replaces so that no existing subscriber's bill changes.
#
# Comped rows have amount 0 and get no Stripe Price at all - comped
# subscriptions never reach Stripe, so there is nothing for a Price to bill
# against.  Their PlanPrice.stripe_price_id stays blank.
PRICE_MATRIX = [
    # plan slug,               interval,  label,       code, cents
    ("professional", "monthly", "standard", "", 4_000),
    ("professional", "annual", "standard", "", 48_000),
    ("professional", "monthly", "comped", "", 0),
    ("organization", "monthly", "standard", "", 10_000),
    ("organization", "annual", "standard", "", 120_000),
    ("organization", "monthly", "comped", "", 0),
    ("documentcloud-premium", "monthly", "standard", "", 1_000),
    ("sunlight-essential", "monthly", "standard", "", 68_000),
    ("sunlight-essential", "annual", "standard", "", 800_000),
    ("sunlight-essential", "monthly", "nonprofit", "", 35_000),
    ("sunlight-essential", "annual", "nonprofit", "", 400_000),
    ("sunlight-enhanced", "monthly", "standard", "", 138_000),
    ("sunlight-enhanced", "annual", "standard", "", 1_600_000),
    ("sunlight-enhanced", "monthly", "nonprofit", "", 68_000),
    ("sunlight-enhanced", "annual", "nonprofit", "", 800_000),
    ("sunlight-enterprise", "monthly", "standard", "", 275_000),
    ("sunlight-enterprise", "annual", "standard", "", 3_200_000),
    ("sunlight-enterprise", "annual", "comped", "", 0),
    ("scoutpost-pro", "monthly", "standard", "", 1_000),
    ("scoutpost-team", "monthly", "standard", "", 5_000),
    ("muckrock-request-pack", "monthly", "standard", "", 1_000),
    ("muckrock-request-pack", "annual", "standard", "", 12_000),
    ("documentcloud-credit-pack", "monthly", "standard", "", 1_000),
    ("documentcloud-credit-pack", "annual", "standard", "", 12_000),
    ("scoutpost-credit-pack", "monthly", "standard", "", 1_000),
    ("scoutpost-credit-pack", "annual", "standard", "", 12_000),
    # Admin keeps its own Plan rather than consolidating - it is the only
    # plan granting staff access across all three products - but still needs
    # a price, so that plan_price can eventually be made non-null for every
    # subscription.
    ("admin", "monthly", "comped", "", 0),
    # Individually negotiated rates.  Each is a price of its own rather than
    # a coupon on top of list, because Stripe has no negative coupon and so
    # cannot express a rate *above* list at all; below-list deals use the
    # same mechanism rather than being handled a second way.  `insideclimate`
    # is a bespoke Organization rate; `legacy-basic` preserves the older,
    # cheaper Sunlight Basic rate for the subscribers who still hold it.
    ("organization", "monthly", "standard", "insideclimate", 3_000),
    ("sunlight-essential", "annual", "standard", "legacy-basic", 200_000),
]


class Command(BaseCommand):
    """Create the Stripe Products and Prices behind the consolidated plans.

    One Stripe Product per plan, with a Price for each (interval, label)
    variant, plus the PlanPrice row pointing at it.

    Safe to re-run: a plan that already has a stripe_product_id keeps it,
    and an existing PlanPrice for a given (plan, interval, label) is left
    alone.  Re-running after a partial failure completes the remainder.

    Deliberately NOT wrapped in a transaction.  Stripe objects cannot be
    rolled back, so a transaction spanning these calls would risk creating
    Products and Prices whose IDs are then discarded - leaving orphans in
    Stripe and no local record of them.  Each ID is saved immediately
    instead, so an interrupted run leaves a consistent partial state that
    re-running finishes.
    """

    help = "Create Stripe Products and Prices for the consolidated plans"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without calling Stripe",
        )
        parser.add_argument(
            "--allow-missing",
            action="store_true",
            help=(
                "Skip plans that do not exist instead of failing.  For dev "
                "and staging databases seeded with a subset of plans - never "
                "on production, where a missing tier means it would silently "
                "end up with no Stripe Product or Prices."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - Stripe will not be called"))

        plans = self._load_plans(options["allow_missing"])

        counts = Counter()
        for slug in dict.fromkeys(row[0] for row in PRICE_MATRIX):
            if slug in plans and self._ensure_product(plans[slug], dry_run):
                counts["products"] += 1

        for slug, interval, label, code, amount in PRICE_MATRIX:
            if slug not in plans:
                continue
            counts[
                self._ensure_price(
                    plans[slug], (interval, label, code, amount), dry_run=dry_run
                )
            ] += 1

        summary = (
            f"\n{counts['products']} products, {counts['created']} priced rows, "
            f"{counts['comped']} comped rows (no Stripe Price), "
            f"{counts['skipped']} already present"
        )
        if counts["completed"]:
            summary += f", {counts['completed']} completed from an earlier partial run"
        self.stdout.write(summary)

    def _load_plans(self, allow_missing):
        slugs = {row[0] for row in PRICE_MATRIX}
        plans = {p.slug: p for p in Plan.objects.filter(slug__in=slugs)}
        missing = sorted(slugs - set(plans))
        if missing and not allow_missing:
            raise CommandError(
                f"These plans do not exist: {missing}.  Run the tier and pack "
                f"migrations first.\n\n"
                f"If those migrations have already run, a pack plan can still "
                f"be absent: 0082 resolves each pack's OIDC client by finding "
                f"which client's entitlements carry its resource key "
                f"(base_requests, base_ai_credits, base_credits), and skips "
                f"the pack when no client carries the key or more than one "
                f"does.  Check that before assuming the migration was "
                f"missed.\n\n"
                f"Pass --allow-missing to skip them (dev and staging only)."
            )
        for slug in missing:
            self.stdout.write(self.style.WARNING(f"! {slug}: no such plan, skipping"))
        return plans

    def _ensure_product(self, plan, dry_run):
        if plan.stripe_product_id:
            self.stdout.write(f"= product {plan.slug}: {plan.stripe_product_id}")
            return False
        self.stdout.write(self.style.SUCCESS(f"+ product {plan.slug} ({plan.name})"))
        if dry_run:
            return True
        self.stdout.write(f"    -> {plan.ensure_stripe_product()}")
        return True

    @staticmethod
    def _variant(interval, label, code):
        return f"{interval}/{label}" + (f"/{code}" if code else "")

    def _ensure_price(self, plan, spec, *, dry_run):
        interval, label, code, amount = spec
        existing = PlanPrice.objects.filter(
            plan=plan, interval=interval, label=label, code=code, active=True
        ).first()
        if existing is not None:
            # A row is only finished if it needed no Stripe Price (comped) or
            # already has one.  A previous run that created the row and then
            # failed on the Stripe call leaves it active and blank, and
            # skipping on the strength of the row's mere existence would
            # strand it there for good while reporting success.
            if existing.amount == 0 or existing.stripe_price_id:
                self.stdout.write(
                    f"= price {plan.slug} {self._variant(interval, label, code)}"
                )
                return "skipped"

            variant = self._variant(interval, label, code)
            self.stdout.write(
                self.style.WARNING(
                    f"~ price {plan.slug} {variant}: no Stripe Price, completing"
                )
            )
            if not dry_run:
                self.stdout.write(f"    -> {existing.ensure_stripe_price()}")
            return "completed"

        if amount == 0:
            variant = self._variant(interval, label, code)
            self.stdout.write(
                self.style.SUCCESS(
                    f"+ price {plan.slug} {variant}: comped, no Stripe Price"
                )
            )
            if not dry_run:
                PlanPrice.objects.create(
                    plan=plan,
                    stripe_price_id="",
                    interval=interval,
                    label=label,
                    code=code,
                    amount=0,
                    currency=CURRENCY,
                )
            return "comped"

        self.stdout.write(
            self.style.SUCCESS(
                f"+ price {plan.slug} {self._variant(interval, label, code)}: "
                f"${amount / 100:,.2f}"
            )
        )
        if dry_run:
            return "created"

        plan_price = PlanPrice.objects.create(
            plan=plan,
            stripe_price_id="",
            interval=interval,
            label=label,
            code=code,
            amount=amount,
            currency=CURRENCY,
        )
        self.stdout.write(f"    -> {plan_price.ensure_stripe_price()}")
        return "created"
