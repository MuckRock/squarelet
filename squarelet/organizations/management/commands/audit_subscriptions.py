# Django
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import get_current_timezone

# Standard Library
import logging
import time
from datetime import datetime, timezone as dt_timezone

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models.payment import Subscription

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

# How close (in seconds) current_period_end timestamps can be and still count as matching
PERIOD_END_TOLERANCE_SECONDS = 60


def _fmt(value):
    if value is None:
        return "None"
    return str(value)


def _datetimes_match(a, b):
    """True if both are None, or if both are within PERIOD_END_TOLERANCE_SECONDS."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    diff = abs((a - b).total_seconds())
    return diff <= PERIOD_END_TOLERANCE_SECONDS


class Command(BaseCommand):
    """Compare local Subscription records against Stripe and report mismatches.

    Checks for:
      - Local subscriptions whose subscription_id doesn't exist on Stripe
      - Stripe subscriptions that have no matching local record (--stripe-orphans)
      - Field mismatches: status, cancel_at_period_end, cancel_at,
        current_period_end, quantity, plan stripe_id
    """

    help = "Audit subscriptions: compare local records against Stripe and report mismatches"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            default=None,
            help="Filter by organization slug",
        )
        parser.add_argument(
            "--show-ok",
            action="store_true",
            help="Also print subscriptions that are in sync",
        )
        parser.add_argument(
            "--stripe-orphans",
            action="store_true",
            help="Also report active Stripe subscriptions with no local record",
        )

    def handle(self, *args, **options):
        show_ok = options["show_ok"]
        check_stripe_orphans = options["stripe_orphans"]
        org_filter = options["org"]

        tz = get_current_timezone()

        # ── 1. Load local subscriptions ──────────────────────────────────────
        qs = Subscription.objects.select_related("plan", "organization").exclude(
            subscription_id=None
        )
        if org_filter:
            qs = qs.filter(organization__slug=org_filter)

        local_subs = list(qs.iterator())
        local_map = {s.subscription_id: s for s in local_subs}

        self.stdout.write(
            f"Loaded {len(local_subs)} local subscription(s) with a Stripe ID.\n"
        )

        # ── 2. Fetch Stripe subscriptions ─────────────────────────────────────
        start = time.monotonic()
        stripe_map = {}

        if org_filter and not check_stripe_orphans:
            # Targeted fetch: only retrieve the specific IDs we need to compare.
            # A full list() would scan the entire Stripe account unnecessarily.
            self.stdout.write(
                f"Fetching {len(local_subs)} Stripe subscription(s) by ID...\n"
            )
            for sub in local_subs:
                try:
                    stripe_sub = stripe.Subscription.retrieve(sub.subscription_id)
                    stripe_map[stripe_sub.id] = stripe_sub
                except stripe.InvalidRequestError:
                    pass  # reported as missing in step 3
            fetched = len(stripe_map)
        else:
            # Bulk fetch: needed when checking orphans or auditing the full account.
            # Only retain a subscription object in memory when it matches a local
            # record or when orphan detection requires it; otherwise discard after
            # scanning to avoid accumulating the full Stripe dataset in RAM.
            self.stdout.write("Fetching Stripe subscriptions (status=all)...\n")
            fetched = 0
            for stripe_sub in stripe.Subscription.list(
                limit=100, status="all"
            ).auto_paging_iter():
                if check_stripe_orphans or stripe_sub.id in local_map:
                    stripe_map[stripe_sub.id] = stripe_sub
                fetched += 1
                if fetched % 500 == 0:
                    self.stdout.write(f"  Scanned {fetched} Stripe records...\n")

        elapsed = time.monotonic() - start
        self.stdout.write(
            f"Fetched {fetched} Stripe subscription(s) in {elapsed:.0f}s.\n\n"
        )

        # ── 3. Compare local vs Stripe ────────────────────────────────────────
        ok = mismatched = missing_on_stripe = 0

        for sub in local_subs:
            stripe_sub = stripe_map.get(sub.subscription_id)

            if stripe_sub is None:
                missing_on_stripe += 1
                self.stdout.write(
                    f"[MISSING ON STRIPE] {sub.organization.name!r} "
                    f"(org {sub.organization.pk}) | "
                    f"plan={sub.plan.slug!r} | "
                    f"subscription_id={sub.subscription_id}\n"
                )
                continue

            diffs = self._compare(sub, stripe_sub, tz)

            if diffs:
                mismatched += 1
                self.stdout.write(
                    f"[MISMATCH] {sub.organization.name!r} "
                    f"(org {sub.organization.pk}) | "
                    f"plan={sub.plan.slug!r} | "
                    f"id={sub.subscription_id}\n"
                )
                for field, local_val, stripe_val in diffs:
                    self.stdout.write(
                        f"  {field}: local={_fmt(local_val)}  stripe={_fmt(stripe_val)}\n"
                    )
            else:
                ok += 1
                if show_ok:
                    self.stdout.write(
                        f"[OK] {sub.organization.name!r} | "
                        f"plan={sub.plan.slug!r} | "
                        f"id={sub.subscription_id}\n"
                    )

        # ── 4. Stripe orphans ─────────────────────────────────────────────────
        stripe_orphans = 0
        if check_stripe_orphans:
            if org_filter:
                # When filtering to a single org, local_map only contains that
                # org's subscription IDs, so comparing against all of stripe_map
                # would falsely flag every other org's subscriptions as orphans.
                # Scope the check to Stripe subscriptions owned by the filtered
                # org's Stripe customer ID(s).
                from squarelet.organizations.models.payment import (  # noqa
                    Customer as StripeCustomer,
                )

                org_customer_ids = set(
                    StripeCustomer.objects.filter(organization__slug=org_filter)
                    .exclude(customer_id=None)
                    .values_list("customer_id", flat=True)
                )
                candidates = {
                    sid: s
                    for sid, s in stripe_map.items()
                    if s.customer in org_customer_ids
                }
                self.stdout.write(
                    f"(--stripe-orphans scoped to org {org_filter!r}: "
                    f"{len(org_customer_ids)} Stripe customer(s), "
                    f"{len(candidates)} subscription(s))\n"
                )
            else:
                candidates = stripe_map

            for stripe_id, stripe_sub in candidates.items():
                if stripe_id not in local_map and stripe_sub.status not in (
                    "canceled",
                    "incomplete_expired",
                ):
                    stripe_orphans += 1
                    self.stdout.write(
                        f"[STRIPE ORPHAN] id={stripe_id} | "
                        f"status={stripe_sub.status} | "
                        f"customer={stripe_sub.customer}\n"
                    )

        # ── 5. Summary ────────────────────────────────────────────────────────
        self.stdout.write("\n── Summary ──────────────────────────────────────────\n")
        self.stdout.write(f"  OK (in sync):        {ok}\n")
        self.stdout.write(f"  Mismatched:          {mismatched}\n")
        self.stdout.write(f"  Missing on Stripe:   {missing_on_stripe}\n")
        if check_stripe_orphans:
            self.stdout.write(f"  Stripe orphans:      {stripe_orphans}\n")
        self.stdout.write("─────────────────────────────────────────────────────\n")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _compare(self, sub, stripe_sub, tz):
        """Return list of (field, local_value, stripe_value) tuples for each mismatch."""
        diffs = []

        # status
        local_status = sub.stripe_status or ""
        stripe_status = stripe_sub.status or ""
        if local_status != stripe_status:
            diffs.append(("stripe_status", local_status, stripe_status))

        # cancel_at_period_end → local `cancelled`
        stripe_cape = bool(stripe_sub.cancel_at_period_end)
        if bool(sub.cancelled) != stripe_cape:
            diffs.append(("cancelled/cancel_at_period_end", sub.cancelled, stripe_cape))

        # cancel_at (date)
        stripe_cancel_at_ts = getattr(stripe_sub, "cancel_at", None)
        stripe_cancel_at = (
            datetime.fromtimestamp(stripe_cancel_at_ts, tz=dt_timezone.utc).date()
            if stripe_cancel_at_ts
            else None
        )
        if sub.cancel_at != stripe_cancel_at:
            diffs.append(("cancel_at", sub.cancel_at, stripe_cancel_at))

        # current_period_end — read from subscription items (newer API)
        items = getattr(stripe_sub, "items", None)
        stripe_cpe_ts = (
            items.data[0].current_period_end if items and items.data else None
        )
        stripe_cpe = (
            datetime.fromtimestamp(stripe_cpe_ts, tz=tz) if stripe_cpe_ts else None
        )
        local_cpe = sub.current_period_end
        if not _datetimes_match(local_cpe, stripe_cpe):
            diffs.append(("current_period_end", local_cpe, stripe_cpe))

        # quantity
        stripe_qty = items.data[0].quantity if items and items.data else None
        if stripe_qty is not None and sub.quantity != stripe_qty:
            diffs.append(("quantity", sub.quantity, stripe_qty))

        # plan stripe_id (price/plan ID on the subscription item)
        stripe_plan_id = None
        if items and items.data:
            item = items.data[0]
            # Newer API: item.price.id; older API: item.plan.id
            if hasattr(item, "price") and item.price:
                stripe_plan_id = getattr(item.price, "id", None)
            elif hasattr(item, "plan") and item.plan:
                stripe_plan_id = getattr(item.plan, "id", None)
        local_plan_id = sub.plan.stripe_id if sub.plan else None
        if stripe_plan_id != local_plan_id:
            diffs.append(("plan_stripe_id", local_plan_id, stripe_plan_id))

        return diffs
