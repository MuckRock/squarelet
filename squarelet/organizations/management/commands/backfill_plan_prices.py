# Django
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Standard Library
import collections
import logging

# Squarelet
from squarelet.organizations.entitlement_shape import grants_old
from squarelet.organizations.models.payment import PlanPrice, SubscriptionItem
from squarelet.organizations.plan_mapping import (
    DEFERRED_SLUGS,
    EXPECTED_GRANT_CHANGES,
    LEGACY_PLAN_MAP,
    PACK_DECOMPOSITION,
)

logger = logging.getLogger(__name__)

# Every pack any legacy plan decomposes into.  Lines on these plans are an
# output of this command, never an input.
PACK_SLUGS = {slug for packs in PACK_DECOMPOSITION.values() for slug in packs}


def is_billing(item):
    """Whether Stripe is charging for this line.

    The Stripe id lives on the parent subscription.  Reading `subscription_id`
    off the line itself would read the foreign key column, which is always
    set - every line would look like it was billing, and every comped
    organization would be handed a paid price.

    Rows pointing at a cancelled Stripe subscription would confuse this,
    which is why the Stripe reconciliation is a prerequisite - it drove
    those to zero.
    """
    return bool(item.subscription.subscription_id)


def blocks_held(item):
    """Resource blocks this line holds over its plan's minimum.

    "Resource blocks" is what `quantity` actually means - pricing was
    decoupled from member headcount years ago, whatever `price_per_user` and
    `minimum_users` are called.

    Only a group plan has them.  Anything else was priced `per_unit` with no
    included tier, so its `minimum_users` never entered the arithmetic and
    subtracting it here would invent blocks that were never sold.
    """
    if not item.plan.for_groups:
        return 0
    return max(item.quantity - item.plan.minimum_users, 0)


def legacy_bill_cents(item):
    """What Stripe charges for this line today.

    Two shapes, and `make_stripe_plan` picks between them on `for_groups`:

    - a group plan is a *graduated tiered* price - a flat `base_price` for
      everything up to `minimum_users`, then `price_per_user` per block
      above it.  Quantity does not multiply the base;
    - anything else is `per_unit` at `base_price`, where quantity does.

    Getting this wrong in the safe-looking direction is what makes a
    subscriber at exactly their minimum bill five times over.
    """
    plan = item.plan
    if plan.for_groups:
        return 100 * (plan.base_price + blocks_held(item) * plan.price_per_user)
    return 100 * plan.base_price * item.quantity


def blocks_grant(item):
    """Whether this line's blocks grant anything beyond the tier's base.

    True when any entitlement on the plan scales with quantity, so that
    dropping the line to quantity 1 without a pack would change what the
    organization receives.
    """
    return resource_totals([(item.plan, item.quantity)]) != resource_totals(
        [(item.plan, item.plan.minimum_users)]
    )


def target_quantity(item):
    """What the line's quantity becomes once it bills a flat Price.

    Every new PlanPrice is `per_unit`, so quantity multiplies it.  A group
    plan's flat base was tier one of a graduated price and did not multiply,
    so its line has to drop to 1 and let a pack carry the blocks - whether
    or not it holds any.  A subscriber sitting exactly on their minimum has
    no blocks and is precisely the one this catches: quantity 5 against a
    flat $100 Price is $500 a month.

    A per-unit plan's quantity was already a multiplier and stays as it is.
    """
    if item.plan.for_groups:
        return 1
    return item.quantity


def resource_totals(plan_quantities):
    """What a set of (plan, quantity) lines grants, per client and resource.

    Keyed on the client and the resource name rather than on the
    entitlement, because consolidation is precisely the act of swapping one
    plan's entitlement rows for another's - the objects differ on purpose,
    and it is the numbers that have to survive.
    """
    totals = collections.Counter()
    for plan, quantity in plan_quantities:
        for entitlement in plan.entitlements.all():
            for base_key, amount in grants_old(entitlement.resources, quantity).items():
                totals[(entitlement.client_id, base_key)] += amount
    return totals


class Command(BaseCommand):
    """Move every subscription onto the consolidated pricing model.

    One run covering all of it: set `plan_price`, repoint `plan` to the
    canonical tier, split per-user subscribers into a base line plus usage
    packs, and push the result to Stripe with proration suppressed.

    These were two steps once - a local backfill, then a decomposition timed
    to each subscriber's renewal.  Doing them together is both simpler and
    safer.  The switchover has to call `modify` on every subscription
    anyway, so adding a subscriber's pack line is the same API call, and
    nobody passes through an intermediate state where they are billed
    wrongly.

    Run `consolidate_stripe_products` first; this needs the PlanPrice rows
    to exist.
    """

    help = "Move every subscription onto the consolidated pricing model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything",
        )
        parser.add_argument(
            "--actor",
            help=(
                "Username recorded as granted_by on migrated comped "
                "subscriptions.  Required unless --dry-run."
            ),
        )
        parser.add_argument(
            "--local-only",
            action="store_true",
            help=(
                "Write local state without calling Stripe.  For rehearsing "
                "against a database with no usable Stripe account behind it; "
                "never for the real run, which would leave Stripe billing the "
                "old Prices."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        local_only = options["local_only"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))
        elif local_only:
            self.stdout.write(
                self.style.WARNING("LOCAL ONLY - Stripe will not be updated")
            )

        actor = self._resolve_actor(options["actor"], dry_run)
        pending = self._pending()
        self._preflight(pending)

        # Deliberately not one transaction around the whole run.  Stripe
        # cannot be rolled back, so a run that failed part way through and
        # discarded the local record of what Stripe had already done would be
        # the worst outcome available.  Each subscription commits on its own.
        counts = collections.Counter()
        for item in pending:
            counts[self._migrate(item, actor, dry_run, local_only)] += 1

        self.stdout.write(
            f"\n{counts['migrated']} migrated, {counts['deferred']} deferred, "
            f"{counts['failed']} failed"
        )
        if dry_run:
            # Both reports below read the database after the run.  A dry
            # run writes nothing, so they would say every line is still
            # unmigrated and still at its old quantity - true, and useless,
            # and the "unexpected" one used to call it a bug.
            self.stdout.write(
                "\n(dry run: what remains is what was there - the "
                "remaining-lines report only means something after a real run)"
            )
        else:
            self._report_remaining()
        if counts["failed"]:
            raise CommandError(
                f"{counts['failed']} subscription(s) failed; everything else "
                f"is committed.  Fix the causes and re-run - this command is "
                f"idempotent."
            )

    def _resolve_actor(self, username, dry_run):
        # Imported here rather than at module scope: get_user_model() must
        # not run before the app registry is ready.
        # pylint: disable=import-outside-toplevel
        # Django
        from django.contrib.auth import get_user_model

        if not username:
            if dry_run:
                return None
            raise CommandError(
                "--actor is required: migrated comped subscriptions record "
                "who authorized them."
            )
        user_model = get_user_model()
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"No such user: {username}") from exc

    def _pending(self):
        """Every subscription line, including ones already migrated.

        Deliberately not filtered on `plan_price__isnull=True`.  A line whose
        local half succeeded and whose Stripe half did not would look done
        and be skipped forever - which is exactly the state a re-run needs to
        repair.  Re-processing a finished line is harmless: the target is a
        pure function of the legacy plan, and `modify` is a no-op once the
        items already match.
        """
        return list(
            SubscriptionItem.objects.select_related(
                "subscription__organization", "plan", "plan_price"
            )
            # Pack lines from an earlier run are an output, not an input.
            # Re-deriving blocks from a base line already set to quantity 1
            # would silently drop every pack.
            .exclude(plan__slug__in=PACK_SLUGS).order_by("plan__slug", "pk")
        )

    def _preflight(self, pending):
        """Refuse to write anything unless every case is accounted for.

        Deliberately no log-and-skip fallback.  A silent skip leaves
        `plan_price` null, which surfaces much later and much less legibly -
        as a failure to make the column non-null, long after the run that
        caused it.

        Only lines still needing a target.  A migrated line's plan is the
        canonical one, and asking the map about *that* is asking the wrong
        question - for a migrated comp it is a key the map does not hold,
        which aborted every re-run over one.
        """
        pending = [item for item in pending if not item.plan_price_id]
        unmapped = {
            (item.plan.slug, is_billing(item))
            for item in pending
            if item.plan.slug not in DEFERRED_SLUGS
            and (item.plan.slug, is_billing(item)) not in LEGACY_PLAN_MAP
        }
        if unmapped:
            raise CommandError(
                "No mapping for: "
                + ", ".join(
                    f"{slug} (billing={billing})" for slug, billing in sorted(unmapped)
                )
                + ".  Add them to LEGACY_PLAN_MAP or DEFERRED_SLUGS."
            )

        # A line needs a pack when its blocks *do* something - bill, or
        # grant - and no pack exists to carry that.  Billing blocks always
        # count.  A comped line's blocks count only if its entitlement
        # scales with them: a custom comped plan with a flat entitlement
        # and a block count nobody has looked at in years grants the same
        # at 30 as at 1, and demanding a pack for it would be inventing a
        # grant.  Gating on billing alone let a comped line whose blocks
        # *do* scale through preflight, to be refused one at a time by
        # `_check_grants` - the failure this preflight exists to surface
        # up front.
        undecomposed = {
            item.plan.slug
            for item in pending
            if item.plan.slug not in DEFERRED_SLUGS
            and blocks_held(item)
            and (is_billing(item) or blocks_grant(item))
            and item.plan.slug not in PACK_DECOMPOSITION
        }
        if undecomposed:
            raise CommandError(
                "These plans have subscribers holding resource blocks but no "
                "entry in PACK_DECOMPOSITION: " + ", ".join(sorted(undecomposed))
            )

        missing = self._missing_prices()
        if missing:
            raise CommandError(
                "These target prices do not exist - run "
                "consolidate_stripe_products first: " + str(sorted(missing))
            )

        collisions = self._collisions(pending)
        if collisions:
            raise CommandError(
                "These subscriptions carry several lines that would collapse "
                "onto one plan; resolve by hand first: "
                + str(
                    {
                        f"subscription {sub_id} -> {plan}": v
                        for (sub_id, plan), v in collisions.items()
                    }
                )
            )

    @staticmethod
    def _missing_prices():
        """Targets named by the mapping tables that nothing has created yet."""
        missing = set()
        for target in set(LEGACY_PLAN_MAP.values()):
            slug, interval, label, code = target
            if not PlanPrice.objects.filter(
                plan__slug=slug,
                interval=interval,
                label=label,
                code=code,
                active=True,
            ).exists():
                missing.add(target)

        # A pack takes its base tier's label, so a decomposed plan needs
        # its packs at every label its subscribers can arrive under: the
        # standard pack for billing block-holders and the comped one for
        # comped block-holders.  Checking only standard let a comped
        # organization above its minimum reach `_plan_for`, whose bare
        # `.get()` then raised DoesNotExist - not a CommandError, so
        # nothing caught it, and the run died mid-way with earlier
        # subscribers already committed and pushed to Stripe.
        for plan_slug, packs in PACK_DECOMPOSITION.items():
            for billing in (True, False):
                base = LEGACY_PLAN_MAP.get((plan_slug, billing))
                if base is None:
                    continue
                pack_label = "comped" if base[2] == "comped" else "standard"
                for pack_slug in packs:
                    target = (pack_slug, base[1], pack_label, "")
                    if not PlanPrice.objects.filter(
                        plan__slug=pack_slug,
                        interval=base[1],
                        label=pack_label,
                        code="",
                        active=True,
                    ).exists():
                        missing.add(target)
        return missing

    def _collisions(self, pending):
        """Lines that would end up duplicated on one subscription.

        Several legacy plans collapse onto a single canonical one, and
        SubscriptionItem is unique on (subscription, plan) -- not on
        (organization, plan), since the split moved the organization to the
        parent.  Two lines on the *same* subscription collapsing onto one
        plan is therefore the collision; two on different subscriptions of
        the same organization is legitimate.

        Catching this before anything is written matters: otherwise the run
        aborts part way through on a bare IntegrityError, with earlier
        subscriptions already committed and Stripe already changed.
        """
        seen = collections.defaultdict(list)
        for item in pending:
            key = (item.plan.slug, is_billing(item))
            if key not in LEGACY_PLAN_MAP:
                continue
            seen[(item.subscription_id, LEGACY_PLAN_MAP[key][0])].append(item.plan.slug)
        if not seen:
            return {}

        # A line this step leaves alone still occupies (subscription, plan),
        # so a pending line landing on its canonical plan collides with it
        # just as surely as with another pending line.
        held = (
            SubscriptionItem.objects.exclude(pk__in={item.pk for item in pending})
            .filter(
                subscription_id__in={sub_id for sub_id, _ in seen},
                plan__slug__in={slug for _, slug in seen},
            )
            .values_list("subscription_id", "plan__slug")
        )
        for sub_id, slug in held:
            if (sub_id, slug) in seen:
                seen[(sub_id, slug)].append(f"{slug} (already held)")

        return {k: v for k, v in seen.items() if len(v) > 1}

    # -- per subscription ----------------------------------------------

    def _migrate(self, item, actor, dry_run, local_only):
        org = item.subscription.organization
        if item.plan.slug in DEFERRED_SLUGS:
            self.stdout.write(f"  ~ {org.slug}: {item.plan.slug} deferred")
            return "deferred"
        if item.plan_price_id:
            # Already migrated.  Its target is the price it holds, not
            # whatever `LEGACY_PLAN_MAP` says about its *current* plan -
            # which is now the canonical one, whose plain entry is the
            # standard monthly price.  Re-deriving moved a nonprofit to
            # list price with the money check reading the canonical plan's
            # own `base_price` and passing; re-resolved an annual line to
            # monthly, which Stripe refuses; and for a migrated comp looked
            # up a key the map does not hold, failing preflight on exactly
            # the run meant to repair a failed Stripe half.
            return self._settle(item, dry_run, local_only)

        try:
            plan_price, packs, note = self._plan_for(item)
        except CommandError as exc:
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"

        summary = f"{item.plan.slug} -> {plan_price}"
        if packs:
            summary += "".join(f" + {qty} x {price.plan.slug}" for price, qty in packs)
        self.stdout.write(self.style.SUCCESS(f"  + {org.slug}: {summary}"))
        if note:
            self.stdout.write(f"      {note}")
        if dry_run:
            return "migrated"

        try:
            self._write(item, plan_price, packs, actor, local_only=local_only)
        except Exception as exc:  # pylint: disable=broad-except
            # One subscription failing must not stop the rest.  Whatever went
            # wrong - a Stripe error, a row changed underneath us - the
            # remaining subscribers still need migrating, and a re-run picks
            # this one up because nothing filters on "already done".
            logger.exception("backfill_plan_prices failed for %s", org.slug)
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"
        return "migrated"

    def _settle(self, item, dry_run, local_only):
        """Finish a line whose local half is done: make sure Stripe agrees.

        The re-run exists for one reason - a line whose row committed and
        whose Stripe call did not.  So this pushes the subscription's
        current lines at Stripe, which for a line Stripe already holds
        correctly is a no-op and for one it does not is the missing half.
        Nothing about the line itself is re-decided.
        """
        org = item.subscription.organization
        self.stdout.write(
            f"  = {org.slug}: {item.plan.slug} already on {item.plan_price}"
        )
        if dry_run or local_only or not is_billing(item):
            return "migrated"
        try:
            item.subscription.stripe_modify(proration_behavior="none")
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("backfill_plan_prices failed for %s", org.slug)
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"
        return "migrated"

    def _plan_for(self, item):
        """The target price and pack lines for one legacy line.

        Raises if the arithmetic does not reproduce the current bill.  The
        matrix was built to preserve it, but `proration_behavior="none"`
        only suppresses the mid-cycle adjustment - the *next* invoice bills
        the new Price whatever it says.  A mismatch found here is a wrong
        number in the matrix; a mismatch found later is a customer being
        overcharged.
        """
        slug, interval, label, code = LEGACY_PLAN_MAP[
            (item.plan.slug, is_billing(item))
        ]
        plan_price = PlanPrice.objects.select_related("plan").get(
            plan__slug=slug,
            interval=interval,
            label=label,
            code=code,
            active=True,
        )

        blocks = blocks_held(item)
        packs = []
        if blocks:
            # A pack takes the tier's own label.  A comped organization's
            # blocks grant real resources and must survive decomposition,
            # but the line has to cost nothing - otherwise the subscription
            # stops being free and a later start() would bill it.
            pack_label = "comped" if label == "comped" else "standard"
            for pack_slug in PACK_DECOMPOSITION.get(item.plan.slug, ()):
                packs.append(
                    (
                        PlanPrice.objects.select_related("plan").get(
                            plan__slug=pack_slug,
                            interval=interval,
                            label=pack_label,
                            code="",
                            active=True,
                        ),
                        blocks,
                    )
                )

        # A comped line bills nothing either way, so there is no sum to check.
        if is_billing(item):
            new = plan_price.amount * target_quantity(item) + sum(
                price.amount * qty for price, qty in packs
            )
            old = legacy_bill_cents(item)
            if new != old:
                raise CommandError(
                    f"would change the bill: {item.plan.slug} at quantity "
                    f"{item.quantity} bills ${old / 100:,.2f} today, "
                    f"${new / 100:,.2f} after.  Fix the price matrix or "
                    f"PACK_DECOMPOSITION before migrating this subscriber."
                )
        note = self._check_grants(item, plan_price, packs)
        return plan_price, packs, note

    def _check_grants(self, item, plan_price, packs):
        """Refuse if the organization would receive a different amount.

        Consolidation repoints the line at a different plan, and a plan is
        where entitlements hang - so a subscription can keep billing exactly
        the same money while what it grants moves underneath it.  A comped
        organization on a custom plan is the sharp case: its own entitlement
        is flat, Organization's scales, and it carries a block count nobody
        has needed to look at in years.

        Compared before repointing, because `item.plan` is about to change.
        Returns a note for the caller to print under the subscriber's line
        when the change is one somebody decided on, so it reads next to the
        org it is about rather than the one above it.
        """
        before = resource_totals([(item.plan, item.quantity)])
        after = resource_totals(
            [(plan_price.plan, target_quantity(item))]
            + [(price.plan, quantity) for price, quantity in packs]
        )
        if before == after:
            return None

        reason = EXPECTED_GRANT_CHANGES.get(item.plan.slug)
        if reason is not None:
            return f"grant changes as decided: {reason}"

        if packs:
            # Decomposition keeps only what its packs carry, by decision:
            # a legacy block granted MuckRock requests *and* DocumentCloud
            # credits, one pack covers the requests, and the credit
            # overage - 37 used across all twelve block-holders, ever - is
            # dropped so the bill stays identical.  See PACK_DECOMPOSITION.
            #
            # So the rule for a block-holder is: every resource a pack
            # carries must come out at exactly the legacy number, and the
            # only resources allowed to change are ones no pack carries,
            # which may fall to the tier's base and no further.  Anything
            # else - a pack that under-delivers, or a resource nobody
            # decided to drop - is still refused.  Waiving the whole check
            # via EXPECTED_GRANT_CHANGES would have covered every
            # Organization subscriber, not the twelve this is about.
            carried = set()
            for price, _quantity in packs:
                carried |= set(resource_totals([(price.plan, 1)]))
            at_base = resource_totals([(item.plan, item.plan.minimum_users)])
            unexplained = {
                key
                for key in set(before) | set(after)
                if (key in carried and before[key] != after[key])
                or (key not in carried and after[key] != at_base[key])
            }
            if not unexplained:
                lost = {
                    key: before[key] - after[key]
                    for key in before
                    if before[key] != after[key]
                }
                return f"block overage not carried by a pack, as decided: {lost}"

        raise CommandError(
            f"would change what this organization receives: "
            f"{dict(before)} today, {dict(after)} after.  Either add a pack "
            f"that covers the difference, or record it in "
            f"EXPECTED_GRANT_CHANGES with the reason."
        )

    def _write(self, item, plan_price, packs, actor, *, local_only):
        """Commit one subscription: local rows, then Stripe, then done.

        Stripe is called inside the transaction so that a Stripe failure
        leaves no local trace of a change that did not happen.  The reverse
        - Stripe succeeding and the commit failing - is the survivable
        direction: the next run finds the same line, computes the same
        target, and `modify` settles it.
        """
        subscription = item.subscription
        legacy_name = item.plan.name  # captured before repointing

        if is_billing(item) and not local_only:
            # Identify this line on Stripe *before* repointing it, because
            # the plan is what identifies it: `sync_stripe_item_ids` matches
            # Stripe's lines by Price, and once `plan_price` points at the
            # new one it matches nothing.  A line described to Stripe with
            # no id is a request to *add* a line - and since the new Price
            # differs from the legacy one, Stripe accepts it.  The legacy
            # line stays, the new one is added, and the next invoice bills
            # both.
            #
            # Release 2's `backfill_stripe_item_ids` should have reached
            # every line already; this is what makes that a checked
            # dependency rather than an assumed one.
            stripe_sub = subscription.stripe_subscription
            if stripe_sub is not None:
                subscription.sync_stripe_item_ids(stripe_sub)
                item.refresh_from_db(fields=["stripe_item_id"])
            if not item.stripe_item_id:
                raise CommandError(
                    f"{item.plan.slug}: no Stripe item id, so repointing it "
                    f"would add a second line rather than replace this one.  "
                    f"Run backfill_stripe_item_ids for this organization first."
                )

        with transaction.atomic():
            item.plan = plan_price.plan
            item.plan_price = plan_price
            fields = ["plan", "plan_price"]
            if item.quantity != target_quantity(item):
                # The line covers the tier itself now.  Leaving the block
                # count on it would bill the flat Price that many times over
                # - five times for a subscriber sitting on their minimum,
                # thirty for one holding thirty blocks - and would break the
                # entitlement shape 2e depends on.
                item.quantity = target_quantity(item)
                fields.append("quantity")
            if plan_price.label == "comped":
                # Migrated comps carry the provenance the admin path
                # requires, so "why is this organization free" stays
                # answerable.
                item.granted_reason = f"Migrated from legacy {legacy_name} plan"
                item.granted_by = actor
                fields += ["granted_reason", "granted_by"]
            item.save(update_fields=fields)

            for pack_price, quantity in packs:
                SubscriptionItem.objects.update_or_create(
                    subscription=subscription,
                    plan=pack_price.plan,
                    defaults={"plan_price": pack_price, "quantity": quantity},
                )

            if not local_only:
                # One call carries the repointed base line and any new pack
                # line together, so the subscriber keeps a single invoice and
                # never sees a half-migrated bill.  Proration suppressed: the
                # amounts are identical by construction and checked above, so
                # there is nothing legitimate to prorate.
                subscription.stripe_modify(proration_behavior="none")

    def _report_remaining(self):
        """What is left, and why - so a non-zero count is not alarming."""
        deferred = SubscriptionItem.objects.filter(
            plan_price__isnull=True, plan__slug__in=DEFERRED_SLUGS
        ).count()
        other = (
            SubscriptionItem.objects.filter(plan_price__isnull=True)
            .exclude(plan__slug__in=DEFERRED_SLUGS)
            .count()
        )
        self.stdout.write(
            f"still without a plan_price: {deferred} deferred by choice, "
            f"{other} unexpected"
        )

        # The precondition the entitlement shape migration checks, reported
        # here so a problem surfaces in the run that could have fixed it
        # rather than in the one that cannot.  Group plans only: a per-unit
        # plan keeps its quantity on purpose - a Professional at 3 is three
        # of them - and the shape migration knows to leave those alone.
        above_one = list(
            SubscriptionItem.objects.select_related(
                "subscription__organization", "plan"
            )
            .exclude(plan__slug__in=PACK_SLUGS)
            .filter(quantity__gt=1, plan__for_groups=True)
        )
        if above_one:
            self.stdout.write(
                f"{len(above_one)} line(s) are still above quantity 1, which "
                f"blocks the entitlement shape migration:"
            )
            for item in above_one:
                self.stdout.write(
                    f"  - {item.subscription.organization.slug}: "
                    f"{item.plan.slug} at quantity {item.quantity}"
                )
        if other:
            self.stdout.write(
                self.style.ERROR(
                    "  the unexpected ones are a bug - every other line "
                    "should have been handled by this run"
                )
            )
