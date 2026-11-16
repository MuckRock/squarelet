# Django
from django.utils import timezone

# Standard Library
from datetime import datetime

# Third Party
import pytest

# Squarelet
from squarelet.organizations.tests.factories import PlanFactory, PlanPriceFactory
from squarelet.statistics.revenue import revenue_report

pytestmark = [pytest.mark.django_db(), pytest.mark.freeze_time("2026-10-21 12:00")]


def ts(year, month, day):
    return int(timezone.make_aware(datetime(year, month, day, 12)).timestamp())


def stripe_sub(  # pylint: disable=too-many-arguments
    price_id,
    amount,
    started,
    *,
    interval="month",
    quantity=1,
    ended=None,
    canceled=None,
    status="active",
    cancel_at_period_end=False,
):
    """A subscription shaped as Stripe lists it, with one item."""
    return {
        "status": status,
        "start_date": ts(*started),
        "ended_at": ts(*ended) if ended else None,
        "canceled_at": ts(*canceled) if canceled else None,
        "cancel_at_period_end": cancel_at_period_end,
        "cancel_at": None,
        "items": {
            "data": [
                {
                    "quantity": quantity,
                    "price": {
                        "id": price_id,
                        "unit_amount": amount,
                        "recurring": {"interval": interval, "interval_count": 1},
                        "product": "prod_test",
                    },
                }
            ]
        },
    }


def row(report, month, segment="all"):
    return next(
        r for r in report["months"] if r["month"] == month and r["segment"] == segment
    )


@pytest.fixture(name="professional")
def fixture_professional():
    plan = PlanFactory(name="Professional", slug="professional")
    return PlanPriceFactory(plan=plan, stripe_price_id="price_pro").stripe_price_id


def test_an_annual_plan_counts_at_a_twelfth(professional):
    report = revenue_report(
        [stripe_sub(professional, 120000, (2026, 1, 15), interval="year")]
    )

    assert row(report, "2026-09")["mrr_end"] == 100


def test_quantity_multiplies_the_price(professional):
    report = revenue_report([stripe_sub(professional, 1000, (2026, 1, 15), quantity=3)])

    assert row(report, "2026-09")["mrr_end"] == 30


def test_a_subscription_whose_first_payment_failed_is_not_counted(professional):
    report = revenue_report(
        [stripe_sub(professional, 4000, (2026, 1, 15), status="incomplete_expired")]
    )

    assert row(report, "2026-09")["subs_end"] == 0


def test_a_free_subscription_is_not_counted(professional):
    report = revenue_report([stripe_sub(professional, 0, (2026, 1, 15))])

    assert row(report, "2026-09")["subs_end"] == 0


def test_a_price_outside_squarelet_plans_is_not_counted():
    report = revenue_report([stripe_sub("price_donation", 2500, (2026, 1, 15))])

    assert row(report, "2026-09")["subs_end"] == 0


def test_churn_is_dated_by_when_the_subscription_ended(professional):
    report = revenue_report(
        [
            stripe_sub(
                professional,
                4000,
                (2026, 1, 15),
                canceled=(2026, 6, 10),
                ended=(2026, 8, 15),
                status="canceled",
            )
        ]
    )

    assert row(report, "2026-06")["churned"] == 0
    assert row(report, "2026-08")["churned"] == 1
    assert row(report, "2026-08")["churned_mrr"] == 40


def test_customer_churn_divides_by_subscriptions_live_at_the_month_start(
    professional,
):
    live = [stripe_sub(professional, 4000, (2026, 1, 15)) for _ in range(3)]
    ended = stripe_sub(
        professional, 4000, (2026, 1, 15), ended=(2026, 8, 15), status="canceled"
    )
    joined = stripe_sub(professional, 4000, (2026, 8, 20))

    august = row(revenue_report([*live, ended, joined]), "2026-08")

    assert (august["subs_start"], august["new"], august["churned"]) == (4, 1, 1)
    assert august["subs_end"] == 4
    assert august["logo_churn"] == 0.25
    assert august["mrr_churn"] == 0.25


def test_the_election_cohort_counts_as_sunlight():
    plan = PlanFactory(
        name="Election Accountability Cohort", slug="election-accountability-cohort"
    )
    PlanPriceFactory(plan=plan, stripe_price_id="price_cohort")

    report = revenue_report([stripe_sub("price_cohort", 25000, (2026, 1, 15))])

    assert row(report, "2026-09", "sunlight")["subs_end"] == 1
    assert row(report, "2026-09", "other")["subs_end"] == 0


def test_a_legacy_price_finds_its_plan_by_slug():
    PlanFactory(name="Professional", slug="professional")

    report = revenue_report(
        [stripe_sub("squarelet_plan_professional", 4000, (2026, 1, 15))]
    )

    assert row(report, "2026-09", "professional")["subs_end"] == 1


def test_a_subscription_set_to_cancel_is_pending(professional):
    report = revenue_report(
        [
            stripe_sub(professional, 4000, (2026, 1, 15), cancel_at_period_end=True),
            stripe_sub(professional, 4000, (2026, 1, 15)),
        ]
    )

    pending = {p["segment"]: p for p in report["pending"]}
    assert (pending["all"]["subs"], pending["all"]["mrr"]) == (1, 40)
    assert pending["professional"]["subs"] == 1


def test_the_current_month_is_partial(professional):
    report = revenue_report([stripe_sub(professional, 4000, (2026, 10, 5))])

    assert report["months"][0]["month"] == "2025-08"
    assert row(report, "2026-10")["partial"]
    assert row(report, "2026-10")["new"] == 1
    assert not row(report, "2026-09")["partial"]
