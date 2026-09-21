# Django
from django.core.management.base import BaseCommand
from django.db import transaction

# Standard Library
import collections

# Squarelet
from squarelet.organizations.management.commands.consolidate_stripe_products import (
    CANONICAL_SLUGS,
)
from squarelet.organizations.models.payment import Plan


def canonical_slugs():
    """Every plan the consolidation keeps: the price matrix, verbatim.

    Not derived from the mapping.  That gave the mapping's *targets* plus
    a local copy of the pack list built from PACK_DECOMPOSITION - the
    derivation #805 replaced for classifying packs - and it missed five
    plans: two packs nothing decomposes into yet, and three tiers no legacy
    plan maps onto.  They survived only because consolidation had given
    them prices, and any environment where this ran first archived them
    for good.  The matrix is what we sell; that is the list.
    """
    return set(CANONICAL_SLUGS)


def sellable_through(plan):
    """Whether a purchase can still be made *through* this plan.

    A plan is sellable when it holds an active price of its own.  The
    legacy entry rows - `sunlight-essential-annual`, `sunlight-nonprofit-*`
    - hold none, and used to count as sellable anyway because the purchase
    flow picked them and `resolve_purchase` mapped them to the canonical
    tier's price.  The plan page now picks the interval and the rate
    itself and those rows' URLs redirect to it, so nothing is bought
    through them any more, and the plain test archives them.
    """
    return plan.prices.filter(active=True).exists()


class Command(BaseCommand):
    """Archive the legacy plans nobody is on any more.

    A plan is finished once no live subscription sits on it and it has no
    active price: everyone has been moved off, and it cannot be bought
    because there is nothing to bill.

    **Archived, not deleted, and deliberately so.** `OrganizationChangeLog`
    holds four PROTECT foreign keys to `Plan` and writes an entry on every
    subscription change, so any plan anyone ever subscribed to is
    referenced by history - deleting the row would mean destroying the
    record of who used to be on what.  `SubscriptionItem.plan` is CASCADE
    on top of that, so a plan still carrying cancelled lines would take
    them with it.  Nothing here is worth losing for a shorter list, and a
    flag is reversible where a delete is not.

    Archived plans are excluded from `Plan.objects.choices()`, so they stop
    being offered - including to an organization currently on one, since a
    retired plan is retired for renewals too.
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
            # Every plan, archived ones included: the run has to see what
            # it archived last time to report it as already done.
            for plan in Plan.objects.including_archived().order_by("slug"):
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
                    "Plans still in use are not a failure here - they mean "
                    "the pricing migration has not finished moving everyone "
                    "off them."
                )
            )

    def _consider(self, plan, keep):
        if plan.slug in keep:
            return "keep"
        if plan.archived:
            return "already"

        # Every line counts, cancelled or not.  A cancelled line is not the
        # record of someone who left - that is OrganizationChangeLog - it is
        # a subscriber still billed and still served until `cancel_at`, who
        # can press Resubscribe and be live again.  Archiving under them
        # left one Sunlight subscriber renewing on an archived plan.  The
        # sweep deletes the line when its date arrives; the plan becomes
        # archivable on the run after that.
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
