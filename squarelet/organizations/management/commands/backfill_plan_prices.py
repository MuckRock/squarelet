# Django
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Standard Library
import collections
import logging

# Squarelet
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.models.payment import (
    PlanPrice,
    Subscription,
    SubscriptionItem,
)
from squarelet.organizations.plan_mapping import (
    COHORT_SLUG,
    DEFERRED_SLUGS,
    LEGACY_PLAN_MAP,
)

logger = logging.getLogger(__name__)


def is_billing(item):
    """Whether Stripe is charging for this line.

    Read off the parent: the line's own `subscription_id` is the foreign key,
    always set, and would make every comped organization look paid.
    """
    return bool(item.subscription.subscription_id)


def blocks_held(item):
    """Resource blocks this line holds over its group plan's minimum."""
    if not item.plan.for_groups:
        return 0
    return max(item.quantity - item.plan.minimum_users, 0)


def legacy_bill_cents(item):
    """What Stripe charges for this line today.

    A group plan is a graduated price: a flat base up to its minimum, then
    per block, so quantity does not multiply the base.  Anything else is per
    unit.
    """
    plan = item.plan
    if plan.for_groups:
        return 100 * (plan.base_price + blocks_held(item) * plan.price_per_user)
    return 100 * plan.base_price * item.quantity


def target_quantity(item):
    """The line's quantity once it bills a flat Price, which quantity multiplies.

    A group plan's base did not multiply, so its line drops to one unit.
    """
    if item.plan.for_groups:
        return 1
    return item.quantity


class Command(BaseCommand):
    """Move every subscription line onto its consolidated plan and price.

    Needs `consolidate_stripe_products` to have created the prices.  A line
    whose price costs nothing moves to its organization's free subscription.
    """

    help = "Move every subscription line onto its consolidated plan and price"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything",
        )
        parser.add_argument(
            "--actor",
            help=(
                "Username recorded as granted_by on migrated comped lines.  "
                "Required unless --dry-run."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))

        actor = self._resolve_actor(options["actor"], dry_run)
        pending = self._pending()
        self._preflight(pending)

        # Each line commits on its own, so one failure leaves the rest done
        # and a re-run picks it up.
        counts = collections.Counter()
        for item in pending:
            counts[self._migrate(item, actor, dry_run)] += 1

        self.stdout.write(
            f"\n{counts['migrated']} migrated, {counts['done']} already done, "
            f"{counts['deferred']} deferred, {counts['failed']} failed"
        )
        if not dry_run:
            self._report_remaining()
            self._report_cohort()
        if counts["failed"]:
            raise CommandError(
                f"{counts['failed']} line(s) failed; everything else is "
                f"committed.  Fix the causes and re-run."
            )

    def _resolve_actor(self, username, dry_run):
        if not username:
            if dry_run:
                return None
            raise CommandError(
                "--actor is required: migrated comped lines record who "
                "authorized them."
            )
        user_model = get_user_model()
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"No such user: {username}") from exc

    @staticmethod
    def _pending():
        return list(
            SubscriptionItem.objects.select_related(
                "subscription__organization", "plan", "plan_price"
            ).order_by("plan__slug", "pk")
        )

    def _preflight(self, pending):
        """Refuse before writing anything unless every line is accounted for."""
        pending = [
            item
            for item in pending
            if not item.plan_price_id and item.plan.slug not in DEFERRED_SLUGS
        ]
        keys = {(item.plan.slug, is_billing(item)) for item in pending}

        unmapped = sorted(key for key in keys if key not in LEGACY_PLAN_MAP)
        if unmapped:
            raise CommandError(
                "No mapping for: "
                + ", ".join(f"{slug} (billing={billing})" for slug, billing in unmapped)
                + ".  Add them to LEGACY_PLAN_MAP or DEFERRED_SLUGS."
            )

        # Stripe keeps charging a line whatever its local price says.
        comped_but_billing = sorted(
            slug
            for slug, billing in keys
            if billing and _target(slug, True)[2] == "comped"
        )
        if comped_but_billing:
            raise CommandError(
                "These are billing on Stripe but map to a comped price; cancel "
                "the Stripe subscription or change the mapping first: "
                + ", ".join(comped_but_billing)
            )

        # A free subscription cannot end, so the move would drop the date or
        # take the organization's free row down with it.
        ending_comps = sorted(
            f"{item.subscription.organization.slug} ({item.plan.slug})"
            for item in pending
            if item.subscription.cancelled
            and _target(item.plan.slug, is_billing(item))[2] == "comped"
        )
        if ending_comps:
            raise CommandError(
                "These comped lines are on subscriptions that are ending; let "
                "them lapse or resubscribe them first: " + ", ".join(ending_comps)
            )

        holding_blocks = sorted(
            {item.plan.slug for item in pending if blocks_held(item)}
        )
        if holding_blocks:
            raise CommandError(
                "These have subscribers holding resource blocks, which need "
                "pack lines: " + ", ".join(holding_blocks)
            )

        missing = sorted(
            {_target(*key) for key in keys}
            - set(
                PlanPrice.objects.filter(active=True).values_list(
                    "plan__slug", "interval", "label", "code"
                )
            )
        )
        # The cohort bills at both cadences; the map names only one.
        if any(slug == COHORT_SLUG for slug, _billing in keys):
            missing += self._missing_cohort_prices(pending)
        if missing:
            raise CommandError(
                "These target prices do not exist - run "
                "consolidate_stripe_products first: " + str(missing)
            )

        collisions = self._collisions(pending)
        if collisions:
            raise CommandError(
                "These subscriptions carry several lines that would collapse "
                "onto one plan; resolve by hand first: " + str(collisions)
            )

    @staticmethod
    def _missing_cohort_prices(pending):
        slug, _interval, label, code = _target(COHORT_SLUG, True)
        needed = {
            item.subscription.interval
            for item in pending
            if item.plan.slug == COHORT_SLUG
        }
        held = set(
            PlanPrice.objects.filter(
                plan__slug=slug, label=label, code=code, active=True
            ).values_list("interval", flat=True)
        )
        return [(slug, interval, label, code) for interval in sorted(needed - held)]

    @staticmethod
    def _collisions(pending):
        """Lines that would land on one plan on one subscription.

        SubscriptionItem is unique on (subscription, plan); caught here, not as
        an IntegrityError half way through the run.  A comped line lands on its
        organization's free row, not the one it is on.
        """

        def where(subscription, target):
            if target[2] == "comped":
                return ("free", subscription.organization_id)
            return subscription.pk

        landing = collections.defaultdict(list)
        for item in pending:
            target = _target(item.plan.slug, is_billing(item))
            landing[(where(item.subscription, target), target[0])].append(
                item.plan.slug
            )

        held = SubscriptionItem.objects.exclude(
            pk__in={item.pk for item in pending}
        ).select_related("subscription", "plan", "plan_price")
        for other in held:
            place = (
                ("free", other.subscription.organization_id)
                if other.subscription.kind == "free"
                else other.subscription_id
            )
            if (place, other.plan.slug) in landing:
                landing[(place, other.plan.slug)].append(
                    f"{other.plan.slug} (already held)"
                )

        return {
            f"{place} -> {slug}": slugs
            for (place, slug), slugs in landing.items()
            if len(slugs) > 1
        }

    # -- per line ----------------------------------------------------------

    def _migrate(self, item, actor, dry_run):
        org = item.subscription.organization
        if item.plan.slug in DEFERRED_SLUGS:
            self.stdout.write(f"  ~ {org.slug}: {item.plan.slug} deferred")
            return "deferred"
        if item.plan_price_id:
            self.stdout.write(f"  = {org.slug}: {item.plan.slug} on {item.plan_price}")
            return "done"

        try:
            plan_price = self._price_for(item)
        except CommandError as exc:
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"

        self.stdout.write(
            self.style.SUCCESS(f"  + {org.slug}: {item.plan.slug} -> {plan_price}")
        )
        if dry_run:
            return "migrated"
        try:
            self._write(item, plan_price, actor)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("backfill_plan_prices failed for %s", org.slug)
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"
        return "migrated"

    @staticmethod
    def _price_for(item):
        """The line's target price; raises if it would change the bill."""
        slug, interval, label, code = _target(item.plan.slug, is_billing(item))
        if item.plan.slug == COHORT_SLUG:
            # The one plan billing at two cadences: the line's own subscription
            # says which.
            interval = item.subscription.interval
        plan_price = PlanPrice.objects.select_related("plan").get(
            plan__slug=slug, interval=interval, label=label, code=code, active=True
        )

        if is_billing(item):
            new = plan_price.amount * target_quantity(item)
            old = legacy_bill_cents(item)
            if item.plan.slug == COHORT_SLUG and plan_price.interval == "monthly":
                # The plan states the annual figure for every cohort line.
                new *= 12
            if new != old:
                raise CommandError(
                    f"would change the bill: {item.plan.slug} at quantity "
                    f"{item.quantity} bills ${old / 100:,.2f} today, "
                    f"${new / 100:,.2f} after"
                )
        return plan_price

    @staticmethod
    def _write(item, plan_price, actor):
        legacy_name = item.plan.name
        with transaction.atomic():
            item.plan = plan_price.plan
            item.plan_price = plan_price
            item.quantity = target_quantity(item)
            if plan_price.amount == 0:
                item.granted_reason = f"Migrated from legacy {legacy_name} plan"
                item.granted_by = actor
                _move_to_free_subscription(item)
            item.save()
            # The line's plan, and so its entitlements, just changed.
            organization = item.subscription.organization
            transaction.on_commit(
                lambda: send_cache_invalidations("organization", organization.uuid)
            )

    # -- reports -----------------------------------------------------------

    def _report_cohort(self):
        """Each cohort line's cadence, which the money check cannot see."""
        lines = SubscriptionItem.objects.select_related(
            "subscription__organization", "plan_price"
        ).filter(plan_price__code="election-cohort")
        for item in lines:
            self.stdout.write(
                f"  cohort {item.subscription.organization.slug}: "
                f"{item.plan_price.interval} at ${item.plan_price.amount / 100:,.2f}"
            )

    def _report_remaining(self):
        remaining = SubscriptionItem.objects.filter(plan_price__isnull=True)
        deferred = remaining.filter(plan__slug__in=DEFERRED_SLUGS).count()
        other = remaining.count() - deferred
        self.stdout.write(
            f"still without a price: {deferred} deferred, {other} unexpected"
        )


def _target(slug, billing):
    return LEGACY_PLAN_MAP[(slug, billing)]


def _move_to_free_subscription(item):
    """Put a line that now costs nothing on its organization's free row.

    Free and paid never share a subscription.  A row left with only this line
    becomes the free row itself when the organization has none.
    """
    subscription = item.subscription
    if subscription.kind == "free":
        return
    free = Subscription.objects.filter(
        organization=subscription.organization, kind="free"
    ).first()
    alone = not subscription.items.exclude(pk=item.pk).exists()
    if free is None and alone:
        subscription.kind = "free"
        subscription.save(update_fields=["kind"])
        return
    if free is None:
        free = Subscription.objects.create(
            organization=subscription.organization,
            kind="free",
            interval=subscription.interval,
        )
    item.subscription = free
    if alone:
        # Saved first, so the row it leaves is empty when deleted.
        item.save()
        subscription.invoices.update(subscription=free)
        subscription.delete()
