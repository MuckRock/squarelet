# Django
from django.core.management.base import BaseCommand
from django.db import transaction

# Standard Library
import collections

# Squarelet
from squarelet.organizations.models.payment import Plan
from squarelet.organizations.plan_mapping import LEGACY_PLAN_MAP, PACK_DECOMPOSITION

PACK_SLUGS = {slug for packs in PACK_DECOMPOSITION.values() for slug in packs}


def canonical_slugs():
    """Every plan the consolidation keeps.

    Derived from the mapping rather than listed again, so a plan cannot be
    archived by forgetting to write it down somewhere.
    """
    return {target[0] for target in LEGACY_PLAN_MAP.values()} | PACK_SLUGS


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

        # Cancelled lines do not count: they are the record of what someone
        # used to be on, and they keep pointing at the archived plan quite
        # happily.  A live line means somebody is still being served by it.
        live = plan.subscription_items.exclude(cancelled=True).count()
        sellable = plan.prices.filter(active=True).count()
        if live or sellable:
            self.stdout.write(
                f"  ~ {plan.slug}: still in use "
                f"({live} live line(s), {sellable} active price(s))"
            )
            return "in_use"

        cancelled = plan.subscription_items.filter(cancelled=True).count()
        detail = f" (keeps {cancelled} cancelled line(s))" if cancelled else ""
        self.stdout.write(self.style.SUCCESS(f"  - {plan.slug}: archived{detail}"))
        plan.archived = True
        plan.save(update_fields=["archived"])
        return "archived"
