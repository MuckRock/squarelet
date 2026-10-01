# Django
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Standard Library
import collections
import logging

# Squarelet
from squarelet.oidc.middleware import send_cache_invalidations
from squarelet.organizations.entitlement_shape import grants_old, scaling_pairs
from squarelet.organizations.models.payment import (
    PlanPrice,
    Subscription,
    SubscriptionItem,
    _stripe_price_id,
)
from squarelet.organizations.plan_mapping import (
    COHORT_SLUG,
    DEFERRED_SLUGS,
    DROPPED_WITH_BLOCKS,
    EXPECTED_GRANT_CHANGES,
    LEGACY_PLAN_MAP,
    PACK_DECOMPOSITION,
)

logger = logging.getLogger(__name__)

# Pack lines are this command's output, never its input.
PACK_SLUGS = {slug for packs in PACK_DECOMPOSITION.values() for slug in packs}


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


def resource_totals(plan_quantities):
    """What (plan, quantity) lines grant, per client and resource.

    Keyed on client and resource, not entitlement: consolidation swaps one
    plan's entitlements for another's, and it is the numbers that must hold.
    """
    totals = collections.Counter()
    for plan, quantity in plan_quantities:
        for entitlement in plan.entitlements.all():
            for key, amount in grants_old(entitlement.resources, quantity).items():
                totals[(entitlement.client_id, key)] += amount
    return totals


def blocks_grant(item):
    """Whether this line's blocks grant anything beyond its plan's minimum."""
    return resource_totals([(item.plan, item.quantity)]) != resource_totals(
        [(item.plan, item.plan.minimum_users)]
    )


class Command(BaseCommand):
    """Move every subscription line onto its consolidated plan and price.

    Needs `consolidate_stripe_products` to have created the prices.  A line
    whose price costs nothing moves to its organization's free subscription.
    Stripe is updated per subscription with proration off, since the amounts
    are checked to be unchanged.
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
        parser.add_argument(
            "--local-only",
            action="store_true",
            help=(
                "Write local state without calling Stripe, to rehearse against "
                "a database with no usable Stripe account.  Never for the real "
                "run: Stripe would go on billing the old prices."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        local_only = options["local_only"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))
        elif local_only:
            self.stdout.write(self.style.WARNING("LOCAL ONLY - Stripe untouched"))

        actor = self._resolve_actor(options["actor"], dry_run)
        pending = self._pending()
        self._preflight(pending)

        # Each line commits on its own, so one failure leaves the rest done
        # and a re-run picks it up.
        counts = collections.Counter()
        for item in pending:
            counts[self._migrate(item, actor, dry_run, local_only)] += 1

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
                "subscription__organization", "plan", "plan_price__plan"
            )
            .prefetch_related("plan__entitlements")
            .exclude(plan__slug__in=PACK_SLUGS)
            .order_by("plan__slug", "pk")
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

        missing = sorted(
            (
                {_target(*key) for key in keys if key[0] != COHORT_SLUG}
                | _pack_targets(pending)
            )
            - set(
                PlanPrice.objects.filter(active=True).values_list(
                    "plan__slug", "interval", "label", "code"
                )
            )
        )
        # The cohort bills at both cadences; its lines say which they need.
        missing += self._missing_cohort_prices(pending)
        if missing:
            raise CommandError(
                "These target prices do not exist - run "
                "consolidate_stripe_products first: " + str(missing)
            )

        # Stripe keeps charging a line whatever its local price says.
        free = {key: _lands_free(*key) for key in keys}
        comped_but_billing = sorted(
            slug for slug, billing in keys if billing and free[(slug, billing)]
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
            if item.subscription.cancelled and free[(item.plan.slug, is_billing(item))]
        )
        if ending_comps:
            raise CommandError(
                "These comped lines are on subscriptions that are ending; let "
                "them lapse or resubscribe them first: " + ", ".join(ending_comps)
            )

        # Blocks need a pack when they bill or grant something; a comped
        # plan's flat grant is the same at any count.
        undecomposed = sorted(
            {
                item.plan.slug
                for item in pending
                if blocks_held(item)
                and (is_billing(item) or blocks_grant(item))
                and item.plan.slug not in PACK_DECOMPOSITION
            }
        )
        if undecomposed:
            raise CommandError(
                "These have subscribers holding resource blocks but no entry "
                "in PACK_DECOMPOSITION: " + ", ".join(undecomposed)
            )

        collisions = self._collisions(pending, free)
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
    def _collisions(pending, free):
        """Lines that would land on one plan on one subscription.

        SubscriptionItem is unique on (subscription, plan); caught here, not as
        an IntegrityError or an overwritten pack half way through the run.  A
        comped line lands on its organization's free row, not the one it is on.
        """

        landing = collections.defaultdict(list)
        for item in pending:
            key = (item.plan.slug, is_billing(item))
            place = (
                ("free", item.subscription.organization_id)
                if free[key]
                else item.subscription_id
            )
            landing[(place, _target(*key)[0])].append(item.plan.slug)
            for pack_slug, *_rest in _pack_keys(item):
                landing[(place, pack_slug)].append(f"{item.plan.slug} blocks")

        held = SubscriptionItem.objects.exclude(
            pk__in={item.pk for item in pending}
        ).select_related("subscription", "plan")
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

    def _migrate(self, item, actor, dry_run, local_only):
        org = item.subscription.organization
        if item.plan.slug in DEFERRED_SLUGS:
            self.stdout.write(f"  ~ {org.slug}: {item.plan.slug} deferred")
            return "deferred"
        if item.plan_price_id:
            self.stdout.write(f"  = {org.slug}: {item.plan.slug} on {item.plan_price}")
            return "done"

        try:
            plan_price, packs = self._prices_for(item)
            note = self._check_grants(item, plan_price, packs)
            if dry_run and is_billing(item) and not local_only:
                _identify(item, write=False)
        except CommandError as exc:
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"

        summary = f"{item.plan.slug} -> {plan_price}" + "".join(
            f" + {quantity} x {price.plan.slug}" for price, quantity in packs
        )
        self.stdout.write(self.style.SUCCESS(f"  + {org.slug}: {summary}"))
        if note:
            self.stdout.write(f"      {note}")
        if dry_run:
            return "migrated"
        try:
            self._write(item, plan_price, packs, actor, local_only)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("backfill_plan_prices failed for %s", org.slug)
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"
        return "migrated"

    @staticmethod
    def _prices_for(item):
        """The line's target price and pack lines; raises if the bill changes."""
        slug, _map_interval, label, code = _target(item.plan.slug, is_billing(item))
        plan_price = PlanPrice.objects.select_related("plan").get(
            plan__slug=slug,
            interval=_interval(item),
            label=label,
            code=code,
            active=True,
        )
        blocks = blocks_held(item)
        packs = [
            (
                PlanPrice.objects.select_related("plan").get(
                    plan__slug=pack_slug,
                    interval=interval,
                    label=pack_label,
                    code=pack_code,
                    active=True,
                ),
                blocks,
            )
            for pack_slug, interval, pack_label, pack_code in _pack_keys(item)
        ]

        if is_billing(item):
            new = plan_price.amount * target_quantity(item) + sum(
                price.amount * quantity for price, quantity in packs
            )
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
        return plan_price, packs

    @staticmethod
    def _check_grants(item, plan_price, packs):
        """Refuse if the organization would receive a different amount.

        Returns a note when the change is one decided on: listed in
        EXPECTED_GRANT_CHANGES, or a block-holder's DROPPED_WITH_BLOCKS
        resources falling to the tier's base.
        """
        before = resource_totals([(item.plan, item.quantity)])
        after = resource_totals(
            [(plan_price.plan, target_quantity(item))]
            + [(price.plan, quantity) for price, quantity in packs]
        )
        if before == after:
            return None
        # The decided changes are all gains; a loss is never one of them.
        gains_only = all(after[key] >= before[key] for key in before)
        if item.plan.slug in EXPECTED_GRANT_CHANGES and gains_only:
            return f"grant changes as decided: {EXPECTED_GRANT_CHANGES[item.plan.slug]}"

        if packs:
            carried = set()
            for price, _quantity in packs:
                carried |= set(resource_totals([(price.plan, 1)]))
            at_base = resource_totals([(item.plan, item.plan.minimum_users)])
            unexplained = {
                key
                for key in set(before) | set(after)
                if after[key]
                != (
                    at_base[key]
                    if key not in carried and key[1] in DROPPED_WITH_BLOCKS
                    else before[key]
                )
            }
            if not unexplained:
                changed = {
                    key: f"{before[key]} -> {after[key]}"
                    for key in set(before) | set(after)
                    if before[key] != after[key]
                }
                return f"block overage not carried by a pack, as decided: {changed}"

        raise CommandError(
            f"would change what this organization receives: {dict(before)} "
            f"today, {dict(after)} after.  Add a pack that covers it, or record "
            f"it in EXPECTED_GRANT_CHANGES."
        )

    @staticmethod
    def _write(item, plan_price, packs, actor, local_only):
        """Local rows, then Stripe, in one transaction.

        A Stripe failure leaves no local trace, so a saved line's Stripe half
        succeeded and a re-run need not touch Stripe.
        """
        stripe = is_billing(item) and not local_only
        if stripe:
            _identify(item, write=True)
        legacy_name = item.plan.name
        # Only the fields this sets: the row was read at the start of the run.
        fields = ["plan", "plan_price", "quantity"]
        with transaction.atomic():
            item.quantity = target_quantity(item)
            item.plan = plan_price.plan
            item.plan_price = plan_price
            if Subscription.kind_for(plan_price.plan, plan_price) == "free":
                item.granted_reason = f"Migrated from legacy {legacy_name} plan"
                item.granted_by = actor
                fields += ["granted_reason", "granted_by", "subscription"]
                _move_to_free_subscription(item)
            item.save(update_fields=fields)
            for pack_price, quantity in packs:
                defaults = {"plan_price": pack_price, "quantity": quantity}
                if Subscription.kind_for(pack_price.plan, pack_price) == "free":
                    defaults["granted_reason"] = item.granted_reason
                    defaults["granted_by"] = actor
                SubscriptionItem.objects.update_or_create(
                    subscription=item.subscription,
                    plan=pack_price.plan,
                    defaults=defaults,
                )
            if stripe:
                # One call for the tier and its packs, so no invoice is ever
                # half migrated.  Reloaded: it was read at the start of the run.
                item.subscription.refresh_from_db()
                item.subscription.stripe_modify(proration_behavior="none")
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
        ).filter(plan_price__code=_target(COHORT_SLUG, True)[3])
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

        # What `migrate_entitlement_shape` refuses on, named in the run that
        # can still fix it.
        blocking = [
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
        if blocking:
            self.stdout.write(
                f"{len(blocking)} line(s) still above quantity 1, which blocks "
                f"the entitlement shape migration:"
            )
            for item in blocking:
                self.stdout.write(
                    f"  - {item.subscription.organization.slug}: "
                    f"{item.plan.slug} at quantity {item.quantity}"
                )


def _target(slug, billing):
    return LEGACY_PLAN_MAP[(slug, billing)]


def _lands_free(slug, billing):
    """Whether this legacy plan's target belongs on the free subscription."""
    tier, _interval, label, code = _target(slug, billing)
    price = (
        PlanPrice.objects.select_related("plan")
        .filter(plan__slug=tier, label=label, code=code, active=True)
        .first()
    )
    return Subscription.kind_for(price.plan, price) == "free"


def _stripe_ids(subscription):
    """Each paid line's Stripe item id, as Stripe holds it.

    Matched by the line's current price or plan; a subscription holding one
    paid line and one Stripe item pairs them whatever the price, which covers
    the few items on a price no plan names.  Blank where nothing matches.
    """
    paid = [
        line
        for line in subscription.items.select_related("plan", "plan_price")
        if not line.is_free
    ]
    stripe_sub = subscription.stripe_subscription
    if stripe_sub is None:
        return {line: line.stripe_item_id for line in paid}
    stripe_items = stripe_sub["items"]["data"]
    by_price = {
        _stripe_price_id(stripe_item): stripe_item["id"] for stripe_item in stripe_items
    }
    # An id Stripe no longer holds is as good as none.
    held = set(by_price.values())
    ids = {
        line: (line.stripe_item_id if line.stripe_item_id in held else "")
        or by_price.get(line.stripe_price_id)
        or by_price.get(line.plan.stripe_id, "")
        for line in paid
    }
    if len(paid) == 1 and len(stripe_items) == 1 and not ids[paid[0]]:
        ids[paid[0]] = stripe_items[0]["id"]
    return ids


def _identify(item, write):
    """Make sure every paid line on the subscription has its Stripe item id.

    Needed before the price changes: repointed, a line matches nothing, and
    one sent without an id is added beside the old item: billed twice.  The
    modify sends every paid line, so the others count too.  Saves the ids
    found when `write`.
    """
    ids = _stripe_ids(item.subscription)
    unidentified = sorted(
        line.plan.slug for line, item_id in ids.items() if not item_id
    )
    if unidentified:
        raise CommandError(
            f"no Stripe item id for {', '.join(unidentified)}, so the new price "
            f"would be added beside the old one.  Identify it first."
        )
    if write:
        for line, item_id in ids.items():
            if line.stripe_item_id != item_id:
                line.stripe_item_id = item_id
                line.save(update_fields=["stripe_item_id"])
        item.refresh_from_db(fields=["stripe_item_id"])


def _pack_label(label):
    """A pack takes its tier's label, so a comped organization's costs nothing."""
    return "comped" if label == "comped" else "standard"


def _interval(item):
    """The cadence a line is migrated at: the cohort's own, else the map's."""
    if item.plan.slug == COHORT_SLUG:
        return item.subscription.interval
    return _target(item.plan.slug, is_billing(item))[1]


def _pack_keys(item):
    """The (slug, interval, label, code) of each pack the line's blocks become."""
    if not blocks_held(item):
        return []
    label = _pack_label(_target(item.plan.slug, is_billing(item))[2])
    return [
        (pack_slug, _interval(item), label, "")
        for pack_slug in PACK_DECOMPOSITION.get(item.plan.slug, ())
    ]


def _pack_targets(pending):
    """The pack prices the pending lines' blocks decompose into."""
    return {key for item in pending for key in _pack_keys(item)}


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
        # Moved first, so the row it leaves is empty when deleted.
        item.save(update_fields=["subscription"])
        subscription.invoices.update(subscription=free)
        subscription.delete()
