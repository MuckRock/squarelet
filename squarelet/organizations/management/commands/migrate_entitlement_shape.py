# Django
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Standard Library
import collections

# Squarelet
from squarelet.organizations.entitlement_shape import (
    grant_new,
    grant_old,
    reshape,
    scaling_pairs,
)
from squarelet.organizations.models.payment import Entitlement, SubscriptionItem
from squarelet.organizations.plan_mapping import PACK_SLUGS


class Command(BaseCommand):
    """Move every entitlement onto a shape both grant formulas agree on.

    Clients compute `base + max(quantity - minimum_users, 0) * per_user` and
    will move to `base * quantity`; with `minimum_users = 1` and
    `per_user = base` they agree, so either client can switch at any time.
    Writes only `Entitlement.resources`.  Needs the pricing migration first,
    which puts every tier line at quantity 1.
    """

    help = "Move every entitlement onto a shape both grant formulas agree on"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))

        self._preflight()

        counts = collections.Counter()
        with transaction.atomic():
            for entitlement in Entitlement.objects.prefetch_related("plans").order_by(
                "pk"
            ):
                counts[self._migrate(entitlement)] += 1
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            f"\n{counts['reshaped']} reshaped, {counts['unchanged']} already "
            f"in shape, {counts['not_scaled']} do not scale with quantity"
        )

    def _preflight(self):
        """Refuse while any line on a scaling tier is above quantity 1.

        The formulas agree only at quantity 1: an Organization line at 30
        would grant 1,500 instead of 300, to every client at once.  Packs
        are meant to be `base * q`, and a plan with no per-unit rate grants
        the same at any quantity, so neither is refused.
        """
        carrying = [
            item
            for item in SubscriptionItem.objects.select_related(
                "subscription__organization", "plan"
            )
            .prefetch_related("plan__entitlements")
            .exclude(plan__slug__in=PACK_SLUGS)
            .filter(quantity__gt=1)
            if any(
                scaling_pairs(entitlement.resources)
                for entitlement in item.plan.entitlements.all()
            )
        ]
        if carrying:
            lines = "\n".join(
                f"  - {item.subscription.organization.slug}: {item.plan.slug} "
                f"at quantity {item.quantity}"
                for item in carrying
            )
            raise CommandError(
                f"{len(carrying)} line(s) are not at quantity 1, and this "
                f"step would multiply their grant instead of preserving it. "
                f"Decompose or normalise them first:\n{lines}"
            )

        mixed = [
            entitlement.slug
            for entitlement in Entitlement.objects.prefetch_related("plans")
            if self._is_pack(entitlement) and self._is_tier(entitlement)
        ]
        if mixed:
            raise CommandError(
                "These entitlements sit on both a pack plan and a tier, so "
                "there is no single correct transform for them: "
                + ", ".join(sorted(mixed))
            )

    @staticmethod
    def _is_pack(entitlement):
        # A pack holds a per-unit value, a tier a flat grant; they reshape in
        # opposite directions.
        return any(plan.slug in PACK_SLUGS for plan in entitlement.plans.all())

    @staticmethod
    def _is_tier(entitlement):
        return any(plan.slug not in PACK_SLUGS for plan in entitlement.plans.all())

    def _migrate(self, entitlement):
        is_pack = self._is_pack(entitlement)
        target = reshape(entitlement.resources, is_pack=is_pack)

        if not scaling_pairs(entitlement.resources):
            self.stdout.write(
                f"  . {entitlement.slug}: no quantity-scaled resources, left alone"
            )
            return "not_scaled"
        if target == entitlement.resources:
            self.stdout.write(f"  = {entitlement.slug}: already in shape")
            return "unchanged"

        kind = "pack" if is_pack else "tier"
        self.stdout.write(
            self.style.SUCCESS(
                f"  + {entitlement.slug} ({kind}): "
                f"{entitlement.resources} -> {target}"
            )
        )
        self._check_grants(entitlement, target)
        entitlement.resources = target
        entitlement.save(update_fields=["resources"])
        return "reshaped"

    def _check_grants(self, entitlement, target):
        """Refuse a reshape that changes what anyone receives.

        Checked at every quantity held and always at 1, which covers unsold
        packs and EntitlementGrants (served at quantity 1).  Raising rolls
        back every entitlement: one wrong number means the transform is
        wrong for that shape.
        """
        held = set(
            SubscriptionItem.objects.filter(plan__entitlements=entitlement)
            .values_list("quantity", flat=True)
            .distinct()
        )
        for quantity in sorted(held | {1}):
            before = grant_old(entitlement.resources, quantity)
            after_old = grant_old(target, quantity)
            after_new = grant_new(target, quantity)
            agree = before == after_old == after_new
            self.stdout.write(
                f"      quantity {quantity}: {before} today, {after_old} "
                f"under the old formula, {after_new} under the new"
                + ("" if agree else "  <-- CHANGED")
            )
            if not agree:
                raise CommandError(
                    f"{entitlement.slug}: reshaping would change the grant "
                    f"at quantity {quantity} - {before} today, {after_old} "
                    f"under the old formula, {after_new} under the new.  "
                    f"The transform is wrong for this shape; nothing was "
                    f"written."
                )
