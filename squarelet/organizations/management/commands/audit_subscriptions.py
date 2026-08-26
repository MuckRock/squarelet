# Django
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import get_current_timezone

# Standard Library
import logging
import time
from datetime import datetime

# Third Party
import stripe

# Squarelet
from squarelet.organizations.models.payment import Customer, SubscriptionItem

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

# How close (in seconds) current_period_end timestamps can be
# and still count as matching
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
    """Compare local SubscriptionItem records against Stripe and report mismatches.

    Checks for:
      - Local subscriptions with no subscription_id
      - Local subscriptions canceled on Stripe but not yet deleted locally
      - Local subscriptions whose subscription_id doesn't exist on Stripe
      - Stripe subscriptions that have no matching local record (--stripe-orphans)
      - Field mismatches: status, cancel_at_period_end, cancel_at,
        current_period_end, quantity, plan stripe_id
    """

    help = (
        "Audit subscriptions: compare local records against Stripe"
        " and report mismatches"
    )

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

        # ── 0. Subscriptions with no Stripe ID ────────────────────────────────
        no_id_count = self._report_no_stripe_id(org_filter)

        # ── 1. Load local subscriptions ──────────────────────────────────────
        local_subs, local_map = self._load_local_subs(org_filter)

        # ── 2. Fetch Stripe subscriptions ─────────────────────────────────────
        stripe_map = self._fetch_stripe_map(
            local_subs, local_map, org_filter, check_stripe_orphans
        )

        # ── 3. Compare local vs Stripe ────────────────────────────────────────
        ok, mismatched, missing, should_delete = self._audit_local(
            local_subs, stripe_map, tz, show_ok
        )

        # ── 4 + 5. Stripe orphans + Summary ──────────────────────────────────
        self.stdout.write("\n── Summary ──────────────────────────────────────────\n")
        self.stdout.write(f"  No Stripe ID:        {no_id_count}\n")
        self.stdout.write(f"  Should delete:       {should_delete}\n")
        self.stdout.write(f"  Missing on Stripe:   {missing}\n")
        self.stdout.write(f"  Mismatched:          {mismatched}\n")
        self.stdout.write(f"  OK (in sync):        {ok}\n")
        if check_stripe_orphans:
            self.stdout.write(
                f"  Stripe orphans:      "
                f"{self._find_orphans(stripe_map, local_map, org_filter)}\n"
            )
        self.stdout.write("─────────────────────────────────────────────────────\n")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_local_subs(self, org_filter):
        """Return (local_subs, id→sub map) for subscriptions with a Stripe ID."""
        qs = SubscriptionItem.objects.select_related("plan", "organization").exclude(
            subscription_id=None
        )
        if org_filter:
            qs = qs.filter(organization__slug=org_filter)
        subs = list(qs.iterator())
        self.stdout.write(
            f"Loaded {len(subs)} local subscription(s) with a Stripe ID.\n"
        )
        return subs, {s.subscription_id: s for s in subs}

    def _report_no_stripe_id(self, org_filter):
        """Print paid subscriptions with no subscription_id; return count."""
        qs = SubscriptionItem.objects.select_related("plan", "organization").filter(
            subscription_id=None, plan__base_price__gt=0
        )
        if org_filter:
            qs = qs.filter(organization__slug=org_filter)
        subs = list(qs.iterator())
        if subs:
            self.stdout.write(
                f"[NO STRIPE ID] {len(subs)} paid subscription(s) have no"
                " subscription_id:\n"
            )
            for sub in subs:
                plan = sub.plan
                self.stdout.write(
                    f"  {sub.organization.name!r} (org {sub.organization.pk}) |"
                    f" plan={plan.slug if plan else 'None'!r}\n"
                )
            self.stdout.write("\n")
        return len(subs)

    def _fetch_stripe_map(
        self, local_subs, local_map, org_filter, check_stripe_orphans
    ):
        """Fetch relevant Stripe subscriptions; return a {id: stripe_sub} map."""
        start = time.monotonic()
        stripe_map = {}

        if org_filter and not check_stripe_orphans:
            # Targeted: only retrieve the specific IDs we need to compare.
            # A full list() would scan the entire Stripe account unnecessarily.
            self.stdout.write(
                f"Fetching {len(local_subs)} Stripe subscription(s) by ID...\n"
            )
            for sub in local_subs:
                try:
                    stripe_sub = stripe.Subscription.retrieve(sub.subscription_id)
                    stripe_map[stripe_sub.id] = stripe_sub
                except stripe.InvalidRequestError:
                    pass  # reported as missing in _audit_local
            fetched = len(stripe_map)
        else:
            # Bulk fetch: needed for orphan detection or a full-account audit.
            # Only retain objects that match a local record (or everything when
            # checking orphans) to avoid holding the full dataset in RAM.
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
        return stripe_map

    def _audit_local(self, local_subs, stripe_map, tz, show_ok):
        """Compare local subscriptions; return (ok, mismatched, missing, to_delete)."""
        ok = mismatched = missing = should_delete = 0
        for sub in local_subs:
            stripe_sub = stripe_map.get(sub.subscription_id)
            if stripe_sub is None:
                missing += 1
                self.stdout.write(
                    f"[MISSING ON STRIPE] {sub.organization.name!r} "
                    f"(org {sub.organization.pk}) | "
                    f"plan={sub.plan.slug!r} | "
                    f"subscription_id={sub.subscription_id}\n"
                )
                continue
            # Stripe fully canceled → local record should have been deleted
            if stripe_sub.status == "canceled":
                should_delete += 1
                self.stdout.write(
                    f"[SHOULD DELETE] {sub.organization.name!r} "
                    f"(org {sub.organization.pk}) | "
                    f"plan={sub.plan.slug!r} | "
                    f"id={sub.subscription_id} | "
                    f"local_cancelled={sub.cancelled}"
                    f" local_stripe_status={sub.stripe_status!r}\n"
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
                        f"  {field}: local={_fmt(local_val)}"
                        f"  stripe={_fmt(stripe_val)}\n"
                    )
            else:
                ok += 1
                if show_ok:
                    self.stdout.write(
                        f"[OK] {sub.organization.name!r} | "
                        f"plan={sub.plan.slug!r} | "
                        f"id={sub.subscription_id}\n"
                    )
        return ok, mismatched, missing, should_delete

    def _find_orphans(self, stripe_map, local_map, org_filter):
        """Report active Stripe subscriptions with no local record; return count."""
        if org_filter:
            # Scope to the filtered org's Stripe customer(s) to avoid flagging
            # every other org's subscriptions as orphans.
            org_customer_ids = set(
                Customer.objects.filter(organization__slug=org_filter)
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

        count = 0
        for stripe_id, stripe_sub in candidates.items():
            if stripe_id not in local_map and stripe_sub.status not in (
                "canceled",
                "incomplete_expired",
            ):
                count += 1
                self.stdout.write(
                    f"[STRIPE ORPHAN] id={stripe_id} | "
                    f"status={stripe_sub.status} | "
                    f"customer={stripe_sub.customer}\n"
                )
        return count

    def _compare(self, sub, stripe_sub, tz):
        """Return (field, local, stripe) diff tuples for each mismatch."""
        diffs = []

        # status
        if (sub.stripe_status or "") != (stripe_sub.status or ""):
            diffs.append(
                (
                    "stripe_status",
                    sub.stripe_status or "",
                    stripe_sub.status or "",
                )
            )

        # cancel_at_period_end → local `cancelled`
        if bool(sub.cancelled) != bool(stripe_sub.cancel_at_period_end):
            diffs.append(
                (
                    "cancelled/cancel_at_period_end",
                    sub.cancelled,
                    bool(stripe_sub.cancel_at_period_end),
                )
            )

        # cancel_at (date) — use local tz to match how sub.cancel_at is derived
        # (cancel_at = current_period_end.date(), which is in the local tz)
        cancel_at_ts = getattr(stripe_sub, "cancel_at", None)
        stripe_cancel_at = (
            datetime.fromtimestamp(cancel_at_ts, tz=tz).date() if cancel_at_ts else None
        )
        if sub.cancel_at != stripe_cancel_at:
            diffs.append(("cancel_at", sub.cancel_at, stripe_cancel_at))

        # current_period_end — read from subscription items (newer API).
        # Use bracket notation: getattr() shadows the field with the built-in
        # items() method on StripeObject.
        try:
            items = stripe_sub["items"]
        except (KeyError, TypeError):
            items = None
        cpe_ts = items.data[0].current_period_end if items and items.data else None
        stripe_cpe = datetime.fromtimestamp(cpe_ts, tz=tz) if cpe_ts else None
        if not _datetimes_match(sub.current_period_end, stripe_cpe):
            diffs.append(("current_period_end", sub.current_period_end, stripe_cpe))

        # quantity
        if items and items.data and sub.quantity != items.data[0].quantity:
            diffs.append(("quantity", sub.quantity, items.data[0].quantity))

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

        # discounts / coupons applied to this subscription
        # Check newer list field first, fall back to legacy single-discount field.
        discounts = getattr(stripe_sub, "discounts", None) or (
            [stripe_sub.discount] if getattr(stripe_sub, "discount", None) else []
        )
        if discounts:
            coupon_ids = ", ".join(
                getattr(getattr(d, "coupon", None), "id", None) or "unknown"
                for d in discounts
            )
            diffs.append(("unexpected_discount", None, coupon_ids))

        return diffs
