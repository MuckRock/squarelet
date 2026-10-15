# Django
from django.core.management.base import BaseCommand
from django.db import transaction

# Standard Library
import collections

# Squarelet
from squarelet.organizations.management.commands.consolidate_stripe_products import (
    CANONICAL_SLUGS,
)
from squarelet.organizations.models.payment import Plan, PlanPrice
from squarelet.organizations.plan_mapping import resolve_target


def canonical_slugs():
    """Every plan the consolidation keeps: the price matrix, verbatim.

    Not derived from the mapping, whose targets miss packs and tiers no
    legacy plan maps onto; those would be archived.
    """
    return set(CANONICAL_SLUGS)


def sellable_through(plan):
    """Whether a purchase can still be made through this plan.

    Purchases pick a row like `sunlight-essential-annual` that holds no price
    of its own and resolve to the tier's, so ask whether its target has an
    active price.  Once the UI picks interval and label directly and these
    rows leave the mapping, the same test archives them.
    """
    if plan.prices.filter(active=True).exists():
        return True
    target = resolve_target(plan.slug)
    if target is None:
        return False
    slug, interval, label, code = target
    return PlanPrice.objects.filter(
        plan__slug=slug, interval=interval, label=label, code=code, active=True
    ).exists()


class Command(BaseCommand):
    """Archive the legacy plans nobody is on any more.

    A plan is finished once no line sits on it and nothing can be bought
    through it.  Archived, not deleted: the change log references every plan
    anyone was on, and a flag can be undone.
    """

    help = "Archive the legacy plans nobody is on any more"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing anything",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))

        keep = canonical_slugs()
        counts = collections.Counter()

        with transaction.atomic():
            for plan in Plan.objects.order_by("slug"):
                counts[self._consider(plan, keep)] += 1
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            f"\n{counts['archived']} archived, {counts['in_use']} still in "
            f"use, {counts['already']} already archived, {counts['keep']} "
            f"kept as canonical"
        )
        if counts["in_use"]:
            self.stdout.write(
                self.style.WARNING(
                    "Plans still in use mean the pricing migration has not "
                    "moved everyone off them yet."
                )
            )

    def _consider(self, plan, keep):
        if plan.slug in keep:
            return "keep"
        if plan.archived:
            return "already"

        # Cancelled lines count: they are served until `cancel_at` and can
        # resubscribe.  The sweep deletes them, and the next run archives.
        lines = plan.subscription_items.count()
        sellable = sellable_through(plan)
        if lines or sellable:
            why = f"{lines} line(s)" + (", still purchasable" if sellable else "")
            self.stdout.write(f"  ~ {plan.slug}: still in use ({why})")
            return "in_use"

        self.stdout.write(self.style.SUCCESS(f"  - {plan.slug}: archived"))
        plan.archived = True
        plan.save(update_fields=["archived"])
        return "archived"
