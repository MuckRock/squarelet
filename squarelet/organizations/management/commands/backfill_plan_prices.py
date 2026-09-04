# Django
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Standard Library
import collections
import logging

# Squarelet
from squarelet.organizations.models.payment import PlanPrice, SubscriptionItem
from squarelet.organizations.plan_mapping import (
    DEFERRED_SLUGS,
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
    """
    return max(item.quantity - item.plan.minimum_users, 0)


def legacy_bill_cents(item):
    """What this line bills today, under the old per-user formula."""
    plan = item.plan
    return 100 * (plan.base_price + blocks_held(item) * plan.price_per_user)


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
        """
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

        undecomposed = {
            item.plan.slug
            for item in pending
            if item.plan.slug not in DEFERRED_SLUGS
            and blocks_held(item)
            and is_billing(item)
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

        for plan_slug, packs in PACK_DECOMPOSITION.items():
            base = LEGACY_PLAN_MAP.get((plan_slug, True))
            if base is None:
                continue
            for pack_slug in packs:
                target = (pack_slug, base[1], "standard", "")
                if not PlanPrice.objects.filter(
                    plan__slug=pack_slug,
                    interval=base[1],
                    label="standard",
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

        try:
            plan_price, packs = self._plan_for(item)
        except CommandError as exc:
            self.stdout.write(self.style.ERROR(f"  ! {org.slug}: {exc}"))
            return "failed"

        summary = f"{item.plan.slug} -> {plan_price}"
        if packs:
            summary += "".join(f" + {qty} x {price.plan.slug}" for price, qty in packs)
        self.stdout.write(self.style.SUCCESS(f"  + {org.slug}: {summary}"))
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
        if blocks and is_billing(item):
            for pack_slug in PACK_DECOMPOSITION.get(item.plan.slug, ()):
                packs.append(
                    (
                        PlanPrice.objects.select_related("plan").get(
                            plan__slug=pack_slug,
                            interval=interval,
                            label="standard",
                            code="",
                            active=True,
                        ),
                        blocks,
                    )
                )

        # A comped line bills nothing either way, so there is no sum to check.
        if is_billing(item):
            new = plan_price.amount + sum(price.amount * qty for price, qty in packs)
            old = legacy_bill_cents(item)
            if new != old:
                raise CommandError(
                    f"would change the bill: {item.plan.slug} at quantity "
                    f"{item.quantity} bills ${old / 100:,.2f} today, "
                    f"${new / 100:,.2f} after.  Fix the price matrix or "
                    f"PACK_DECOMPOSITION before migrating this subscriber."
                )
        return plan_price, packs

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

        with transaction.atomic():
            item.plan = plan_price.plan
            item.plan_price = plan_price
            fields = ["plan", "plan_price"]
            if packs:
                # The base line covers the tier itself.  Leaving the block
                # count on it would bill the flat Price that many times over
                # - thirty times the tier for a subscriber holding thirty
                # blocks - and would break the entitlement shape 2e depends
                # on.
                item.quantity = 1
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
        if other:
            self.stdout.write(
                self.style.ERROR(
                    "  the unexpected ones are a bug - every other line "
                    "should have been handled by this run"
                )
            )
