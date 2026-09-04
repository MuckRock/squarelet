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
from squarelet.organizations.plan_mapping import PACK_DECOMPOSITION

# Every pack plan.  An entitlement attached to one of these holds a
# per-unit value; anything else holds a tier's flat grant, and the two
# transform in opposite directions.
PACK_SLUGS = {slug for packs in PACK_DECOMPOSITION.values() for slug in packs}


class Command(BaseCommand):
    """Move every entitlement onto a shape both grant formulas agree on.

    Clients compute `base + max(quantity - minimum_users, 0) * per_user`;
    the target is `base * quantity`.  With `minimum_users = 1` and
    `per_user = base` those are the same expression, so MuckRock and
    DocumentCloud can switch formulas whenever they like, in either order,
    and no number moves.  That is the whole point of this step: it removes
    the need for anyone to deploy in step with anything.

    Changes no prices.  `Entitlement.resources` is the only thing written.

    Run after the pricing migration, which is what puts every tier line at
    quantity 1 - the precondition below.
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
        """Refuse while any tier line still carries a block count.

        The identity this step relies on is exact at quantity 1 and at no
        other quantity.  Applied to a line still holding 30 blocks, an
        Organization grants 50 + 29 x 50 = 1,500 instead of 300 - silently,
        and to every client at once.

        Packs are exempt: their `base` carries the per-unit value, so
        `base * q` is what they are supposed to mean.
        """
        carrying = list(
            SubscriptionItem.objects.select_related(
                "subscription__organization", "plan"
            )
            .exclude(plan__slug__in=PACK_SLUGS)
            .filter(quantity__gt=1)
        )
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
        self._show_grants(entitlement, target)
        entitlement.resources = target
        entitlement.save(update_fields=["resources"])
        return "reshaped"

    def _show_grants(self, entitlement, target):
        """Before and after, at the quantities subscribers actually hold.

        The arithmetic is the point of this step, so print it rather than
        asking anyone to trust it.  Every row should show the same number
        three times.
        """
        quantities = sorted(
            SubscriptionItem.objects.filter(plan__entitlements=entitlement)
            .values_list("quantity", flat=True)
            .distinct()
        )
        for quantity in quantities:
            before = grant_old(entitlement.resources, quantity)
            after_old = grant_old(target, quantity)
            after_new = grant_new(target, quantity)
            flag = "" if before == after_old == after_new else "  <-- CHANGED"
            self.stdout.write(
                f"      quantity {quantity}: {before} today, {after_old} "
                f"under the old formula, {after_new} under the new{flag}"
            )
