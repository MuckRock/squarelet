# Django
from django.core.cache import cache
from django.utils import timezone

# Standard Library
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone

# Squarelet
from squarelet.organizations.models import Plan, PlanPrice
from squarelet.organizations.payments.factory import get_payment_provider
from squarelet.organizations.plan_mapping import tier_of
from squarelet.statistics.kpis import _add_months

# Twelve full months to show, two more for the 3-month trailing churn, and the
# current partial month.
MONTHS = 15
CACHE_KEY = "statistics:revenue"

ALL = "all"
SEGMENTS = [
    ("professional", "Professional"),
    ("organization", "Organization"),
    ("sunlight", "Sunlight"),
    ("other", "Other plans"),
]
OTHER = "other"

# A subscription whose first payment never went through.
UNPAID_STATUSES = {"incomplete", "incomplete_expired"}
LIVE_STATUSES = {"active", "past_due", "trialing", "unpaid"}
MONTHS_PER_INTERVAL = {"day": 12 / 365, "week": 12 / 52, "month": 1, "year": 12}


def segment_of(plan):
    """The dashboard segment a plan's revenue is reported under."""
    if plan.is_sunlight_plan:
        return "sunlight"
    tier = tier_of(plan.slug)
    if tier in ("professional", "organization"):
        return tier
    return OTHER


def _field(obj, key):
    # Stripe objects raise KeyError for absent fields and shadow some names
    # (`items`) with methods, so only bracket access is safe.
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None


class PlanIndex:
    """Finds the local plan behind a Stripe price, without a query per item."""

    def __init__(self):
        plans = list(Plan.objects.all())
        self.by_price = {plan.stripe_id: plan for plan in plans}
        self.by_price.update(
            (price.stripe_price_id, price.plan)
            for price in PlanPrice.objects.exclude(stripe_price_id="").select_related(
                "plan"
            )
        )
        self.by_product = {
            plan.stripe_product_id: plan for plan in plans if plan.stripe_product_id
        }

    def find(self, price):
        plan = self.by_price.get(_field(price, "id"))
        if plan is None:
            product = _field(price, "product")
            product_id = product if isinstance(product, str) else _field(product, "id")
            plan = self.by_product.get(product_id)
        return plan


def item_mrr(item, plan):
    """Monthly revenue from one subscription item, in dollars."""
    price = _field(item, "price")
    quantity = _field(item, "quantity") or 1
    amount = _field(price, "unit_amount")
    if amount is None:
        # Tiered prices carry no unit amount, and a list call cannot expand
        # their tiers; the plan's own pricing mirrors them.
        return float(plan.cost(quantity))
    recurring = _field(price, "recurring")
    months = MONTHS_PER_INTERVAL.get(_field(recurring, "interval"), 1) * (
        _field(recurring, "interval_count") or 1
    )
    return amount * quantity / 100 / months


def _timestamp(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=dt_timezone.utc)


def subscription_rows(stripe_subs, plans):
    """Normalise Stripe subscriptions to the paid ones the dashboard counts.

    Each row is `{segment, mrr, started, ended, pending}`.  A subscription
    spanning segments counts once, under the plan earning it the most.
    """
    rows = []
    for sub in stripe_subs:
        if _field(sub, "status") in UNPAID_STATUSES:
            continue
        items = _field(_field(sub, "items"), "data") or []
        lines = []
        for item in items:
            plan = plans.find(_field(item, "price"))
            if plan is not None:
                lines.append((segment_of(plan), item_mrr(item, plan)))
        mrr = sum(amount for _, amount in lines)
        if mrr <= 0:
            continue
        named = [line for line in lines if line[0] != OTHER] or lines
        segment = max(named, key=lambda line: line[1])[0]
        ended = _timestamp(_field(sub, "ended_at"))
        rows.append(
            {
                "segment": segment,
                "mrr": mrr,
                "started": _timestamp(_field(sub, "start_date")),
                "ended": ended,
                "pending": ended is None
                and _field(sub, "status") in LIVE_STATUSES
                and bool(
                    _field(sub, "cancel_at_period_end") or _field(sub, "cancel_at")
                ),
            }
        )
    return rows


def _month_row(subs, start, end):
    def live_at(moment):
        return [
            s
            for s in subs
            if s["started"] < moment and (s["ended"] is None or s["ended"] >= moment)
        ]

    live = live_at(start)
    new = [s for s in subs if start <= s["started"] < end]
    churned = [s for s in subs if s["ended"] is not None and start <= s["ended"] < end]
    mrr_start = sum(s["mrr"] for s in live)
    new_mrr = sum(s["mrr"] for s in new)
    churned_mrr = sum(s["mrr"] for s in churned)
    return {
        "subs_start": len(live),
        "new": len(new),
        "churned": len(churned),
        "subs_end": len(live) + len(new) - len(churned),
        "mrr_start": round(mrr_start, 2),
        "new_mrr": round(new_mrr, 2),
        "churned_mrr": round(churned_mrr, 2),
        "mrr_end": round(mrr_start + new_mrr - churned_mrr, 2),
        "logo_churn": len(churned) / len(live) if live else None,
        "mrr_churn": churned_mrr / mrr_start if mrr_start else None,
    }


def _month_start(month):
    return timezone.make_aware(datetime(month.year, month.month, 1))


def _groups(subs):
    """`(key, label, subs)` for all plans, then each segment."""
    by_segment = defaultdict(list)
    for sub in subs:
        by_segment[sub["segment"]].append(sub)
    return [(ALL, "All plans", subs)] + [
        (key, label, by_segment[key]) for key, label in SEGMENTS
    ]


def _segment_months(subs, calendar, now):
    """A row per month of `calendar`; its last month is partial and runs to now."""
    rows = []
    for month in calendar:
        partial = month == calendar[-1]
        end = now if partial else _month_start(_add_months(month, 1))
        rows.append(
            {
                "month": f"{month:%Y-%m}",
                "partial": partial,
                **_month_row(subs, _month_start(month), end),
            }
        )
    return rows


def _pending(subs):
    pending = [s for s in subs if s["pending"]]
    return {
        "subs": len(pending),
        "mrr": round(sum(s["mrr"] for s in pending), 2),
    }


def revenue_report(stripe_subs, months=MONTHS):
    """Monthly growth and churn, overall and per segment, from Stripe subscriptions.

    Months run oldest first and end with the current, partial month, which
    runs to now.  MRR uses each subscription's current price and quantity for
    every month.
    """
    now = timezone.now()
    current = timezone.localdate().replace(day=1)
    calendar = [_add_months(current, i + 1 - months) for i in range(months)]

    rows, pending = [], []
    for key, label, group in _groups(subscription_rows(stripe_subs, PlanIndex())):
        labels = {"segment": key, "segment_label": label}
        rows.extend({**labels, **row} for row in _segment_months(group, calendar, now))
        pending.append({**labels, **_pending(group)})
    return {
        "generated_at": now.isoformat(),
        "current_month": f"{current:%Y-%m}",
        "segments": [list(segment) for segment in SEGMENTS],
        "months": rows,
        "pending": pending,
    }


def refresh_revenue_report():
    """Rebuild the report from every Stripe subscription and cache it.

    Pages through the whole Stripe account, so run it from a task, never a
    request.
    """
    service = get_payment_provider().get_subscription_service()
    report = revenue_report(service.list(status="all", limit=100))
    cache.set(CACHE_KEY, report, None)
    return report


def cached_revenue_report():
    """The last report `refresh_revenue_report` stored, or None."""
    return cache.get(CACHE_KEY)
