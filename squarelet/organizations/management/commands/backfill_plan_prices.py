# Django
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Standard Library
import collections
import logging

# Squarelet
from squarelet.organizations.models.payment import PlanPrice, Subscription

logger = logging.getLogger(__name__)

# Where each legacy plan's subscriptions land, keyed on the legacy slug and
# whether the subscription is actually billing.
#
# The slug alone is not enough.  Admins granted free access for years by
# putting organizations on a paid plan without a Stripe subscription, so
# `organization` means the standard price for its paying subscribers and the
# comped price for those.  `is_billing` - whether a Stripe subscription
# exists - is what separates them.
#
# Derived from the plan-mapping document; see it for why each target was
# chosen.  Values are (canonical slug, interval, label, code).
LEGACY_PLAN_MAP = {
    # MuckRock Professional
    ("professional", True): ("professional", "monthly", "standard", ""),
    ("professional", False): ("professional", "monthly", "comped", ""),
    ("professional-pre-paid", True): ("professional", "annual", "standard", ""),
    # Beta - early users grandfathered onto a free plan, not a distinct tier
    ("beta", False): ("professional", "monthly", "comped", ""),
    ("beta", True): ("professional", "monthly", "comped", ""),
    # MuckRock Organization
    ("organization", False): ("organization", "monthly", "comped", ""),
    # Comped organizations, previously each with their own plan
    ("muckrock-editorial-partner", False): (
        "organization",
        "monthly",
        "comped",
        "",
    ),
    ("premium-org-comp", False): ("organization", "monthly", "comped", ""),
    ("education-grant", False): ("organization", "monthly", "comped", ""),
    ("startsmall-grants", False): ("organization", "monthly", "comped", ""),
    ("education-plan", False): ("organization", "monthly", "comped", ""),
    # A negotiated rate, so a price of its own rather than a coupon
    ("insideclimate-news-plan", True): (
        "organization",
        "monthly",
        "standard",
        "insideclimate",
    ),
    # Sunlight
    ("sunlight-enterprise-rnn", False): (
        "sunlight-enterprise",
        "annual",
        "comped",
        "",
    ),
    # Admin keeps its own plan - the only one granting staff access across
    # all three products - and simply gains a comped price.
    ("admin", False): ("admin", "monthly", "comped", ""),
}

# Deliberately left alone.  Each needs a decision or an action outside this
# migration; see the plan-mapping and reconciliation documents.
DEFERRED_SLUGS = {
    # Pays $0 by manual invoice for 200 blocks; needs a conversation before
    # anyone moves them onto a real price.
    "organization-flexible-users-annual",
    # Two organizations going opposite ways - one cancelled, one comped - so
    # the slug alone cannot decide.
    "custom-crp",
    # Its one subscription belongs to an organization that was merged away.
    "sunlight-premium-annual",
}


def is_billing(subscription):
    """Whether Stripe is charging for this subscription.

    Presence of a subscription id is the signal.  Rows pointing at a
    cancelled Stripe subscription would confuse this, which is why the
    Stripe reconciliation is a prerequisite - it drove those to zero.
    """
    return bool(subscription.subscription_id)


class Command(BaseCommand):
    """Point existing subscriptions at their new PlanPrice.

    Sets `plan_price` and repoints `plan` to the canonical tier, in one
    operation: several legacy plans consolidate onto a single canonical row,
    so there is no PlanPrice to look up via the old plan.

    Subscriptions still billing on a per-user plan are **not** touched.  They
    need splitting into a base subscription plus usage packs, which changes
    what Stripe charges and therefore happens per subscriber at renewal - see
    the Migration Path section of the plan.  Everything else is a local
    pointer update that changes nobody's bill.

    Run `consolidate_stripe_products` first; this needs the PlanPrice rows to
    exist.
    """

    help = "Point existing subscriptions at their new PlanPrice"

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

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written"))

        actor = self._resolve_actor(options["actor"], dry_run)
        pending = self._pending()
        self._preflight(pending)

        counts = collections.Counter()
        with transaction.atomic():
            for sub in pending:
                counts[self._migrate(sub, actor, dry_run)] += 1
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            f"\n{counts['migrated']} migrated, {counts['deferred']} deferred"
        )
        self._report_remaining()

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
        """Subscriptions this step handles.

        Everything except those still billing on a per-user plan, which the
        renewal-time split handles instead.
        """
        return list(
            Subscription.objects.select_related("organization", "plan")
            .filter(plan_price__isnull=True)
            .exclude(plan__price_per_user__gt=0, subscription_id__isnull=False)
            .order_by("plan__slug", "pk")
        )

    def _preflight(self, pending):
        """Refuse to write anything unless every case is accounted for.

        Deliberately no log-and-skip fallback.  A silent skip leaves
        `plan_price` null, which fails step 3c later and much less legibly
        than stopping here.
        """
        unmapped = {
            (sub.plan.slug, is_billing(sub))
            for sub in pending
            if sub.plan.slug not in DEFERRED_SLUGS
            and (sub.plan.slug, is_billing(sub)) not in LEGACY_PLAN_MAP
        }
        if unmapped:
            raise CommandError(
                "No mapping for: "
                + ", ".join(
                    f"{slug} (billing={billing})" for slug, billing in sorted(unmapped)
                )
                + ".  Add them to LEGACY_PLAN_MAP or DEFERRED_SLUGS."
            )

        missing = set()
        for target in LEGACY_PLAN_MAP.values():
            slug, interval, label, code = target
            if not PlanPrice.objects.filter(
                plan__slug=slug,
                interval=interval,
                label=label,
                code=code,
                active=True,
            ).exists():
                missing.add(target)
        if missing:
            raise CommandError(
                "These target prices do not exist - run "
                "consolidate_stripe_products first: " + str(sorted(missing))
            )

        # Several legacy plans collapse onto one canonical plan, so an
        # organization holding two of them would violate
        # Subscription.unique_together ("organization", "plan") mid-loop and
        # abort the transaction.  Report it up front instead.
        seen = collections.defaultdict(list)
        for sub in pending:
            key = (sub.plan.slug, is_billing(sub))
            if key not in LEGACY_PLAN_MAP:
                continue
            seen[(sub.organization_id, LEGACY_PLAN_MAP[key][0])].append(sub.plan.slug)
        collisions = {k: v for k, v in seen.items() if len(v) > 1}
        if collisions:
            raise CommandError(
                "These organizations hold several subscriptions that would "
                "collapse onto one plan; resolve by hand first: "
                + str(
                    {f"org {org} -> {plan}": v for (org, plan), v in collisions.items()}
                )
            )

    def _migrate(self, sub, actor, dry_run):
        if sub.plan.slug in DEFERRED_SLUGS:
            self.stdout.write(f"  ~ {sub.organization.slug}: {sub.plan.slug} deferred")
            return "deferred"

        slug, interval, label, code = LEGACY_PLAN_MAP[(sub.plan.slug, is_billing(sub))]
        plan_price = PlanPrice.objects.select_related("plan").get(
            plan__slug=slug,
            interval=interval,
            label=label,
            code=code,
            active=True,
        )

        legacy_name = sub.plan.name  # captured before repointing
        self.stdout.write(
            self.style.SUCCESS(
                f"  + {sub.organization.slug}: {sub.plan.slug} -> {plan_price}"
            )
        )
        if dry_run:
            return "migrated"

        sub.plan = plan_price.plan
        sub.plan_price = plan_price
        fields = ["plan", "plan_price"]
        if label == "comped":
            # Migrated comps carry the same provenance the admin path
            # requires, so "why is this organization free" stays answerable.
            sub.granted_reason = f"Migrated from legacy {legacy_name} plan"
            sub.granted_by = actor
            fields += ["granted_reason", "granted_by"]
        sub.save(update_fields=fields)
        return "migrated"

    def _report_remaining(self):
        """What is left, and why - so a non-zero count is not alarming."""
        per_user = (
            Subscription.objects.filter(plan_price__isnull=True)
            .filter(plan__price_per_user__gt=0, subscription_id__isnull=False)
            .count()
        )
        deferred = (
            Subscription.objects.filter(plan_price__isnull=True)
            .filter(plan__slug__in=DEFERRED_SLUGS)
            .count()
        )
        self.stdout.write(
            f"still without a plan_price: {per_user} awaiting their "
            f"renewal-time split, {deferred} deferred by choice"
        )
