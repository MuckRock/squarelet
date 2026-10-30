# The audit's internals are the unit under test here.
# pylint: disable=protected-access

# Standard Library
from datetime import datetime, timezone
from unittest.mock import Mock

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.management.commands.audit_subscriptions import Command


def _stripe_item(item_id, price_id, quantity):
    """A Stripe subscription item as the newer API returns it."""
    return Mock(id=item_id, price=Mock(id=price_id), quantity=quantity)


def _items(*data):
    return Mock(data=list(data))


@pytest.mark.django_db()
class TestCompareItems:
    """The per-line half of the audit, which is what the split changed."""

    def test_matching_lines_report_nothing(self, subscription_item_factory):
        line = subscription_item_factory(stripe_item_id="si_1", quantity=3)
        stripe_items = _items(_stripe_item("si_1", line.plan.stripe_id, 3))

        assert not Command()._compare_items(line.subscription, stripe_items)

    def test_a_line_on_its_price_is_compared_against_the_price(
        self, subscription_item_factory, plan_price_factory
    ):
        price = plan_price_factory(stripe_price_id="price_new")
        line = subscription_item_factory(
            plan=price.plan, plan_price=price, stripe_item_id="si_1", quantity=1
        )
        stripe_items = _items(_stripe_item("si_1", "price_new", 1))

        assert not Command()._compare_items(line.subscription, stripe_items)

    def test_quantity_drift_is_reported_per_line(self, subscription_item_factory):
        line = subscription_item_factory(stripe_item_id="si_1", quantity=3)
        stripe_items = _items(_stripe_item("si_1", line.plan.stripe_id, 7))

        diffs = Command()._compare_items(line.subscription, stripe_items)

        assert diffs == [(f"item[{line.plan.slug}] quantity", 3, 7)]

    def test_a_free_line_is_not_reported_missing(
        self, subscription_item_factory, plan_factory
    ):
        """A free line has no Stripe counterpart to be missing from.

        `stripe_items()` drops free lines before describing the subscription
        to Stripe, so auditing one against Stripe reported it missing on
        every run - on every subscription carrying one, for good.
        """
        paid = subscription_item_factory(stripe_item_id="si_1", quantity=1)
        subscription_item_factory(
            subscription=paid.subscription,
            plan=plan_factory(name="Free Tier", base_price=0, price_per_user=0),
            stripe_item_id="",
        )
        stripe_items = _items(_stripe_item("si_1", paid.plan.stripe_id, 1))

        assert not Command()._compare_items(paid.subscription, stripe_items)

    def test_each_line_is_matched_by_its_own_stripe_item(
        self, subscription_item_factory, plan_factory
    ):
        """Two lines on one subscription must not be compared positionally."""
        first = subscription_item_factory(stripe_item_id="si_1", quantity=1)
        second = subscription_item_factory(
            subscription=first.subscription,
            plan=plan_factory(name="Pack Plan"),
            stripe_item_id="si_2",
            quantity=5,
        )
        # Deliberately out of order relative to the local rows
        stripe_items = _items(
            _stripe_item("si_2", second.plan.stripe_id, 5),
            _stripe_item("si_1", first.plan.stripe_id, 1),
        )

        assert not Command()._compare_items(first.subscription, stripe_items)

    def test_line_absent_from_stripe_is_reported(self, subscription_item_factory):
        line = subscription_item_factory(stripe_item_id="si_gone", quantity=1)
        stripe_items = _items()

        diffs = Command()._compare_items(line.subscription, stripe_items)

        assert diffs == [(f"item[{line.plan.slug}] missing on stripe", "si_gone", None)]

    def test_stripe_item_we_do_not_track_is_reported(self, subscription_item_factory):
        """The one that costs money: Stripe bills a line we have no record of."""
        line = subscription_item_factory(stripe_item_id="si_1", quantity=1)
        stripe_items = _items(
            _stripe_item("si_1", line.plan.stripe_id, 1),
            _stripe_item("si_rogue", "price_rogue", 2),
        )

        diffs = Command()._compare_items(line.subscription, stripe_items)

        assert diffs == [("untracked stripe item", None, "si_rogue (price_rogue)")]


@pytest.mark.django_db()
class TestLoadLocalSubs:
    """The loader walks subscriptions, not lines."""

    def test_skips_subscriptions_with_no_stripe_id(self, subscription_item_factory):
        subscription_item_factory(subscription__subscription_id="sub_real")
        subscription_item_factory(
            subscription__organization__name="No Stripe Org",
            subscription__subscription_id="",
        )

        subs, by_id = Command()._load_local_subs(None)

        assert [s.subscription_id for s in subs] == ["sub_real"]
        assert set(by_id) == {"sub_real"}

    def test_one_row_per_subscription_not_per_line(
        self, subscription_item_factory, plan_factory
    ):
        line = subscription_item_factory(subscription__subscription_id="sub_multi")
        subscription_item_factory(
            subscription=line.subscription, plan=plan_factory(name="Second Plan")
        )

        subs, _ = Command()._load_local_subs(None)

        assert len(subs) == 1


@pytest.mark.django_db()
class TestNoStripeId:
    def test_a_comp_on_the_free_subscription_is_not_reported(
        self, subscription_item_factory, plan_factory
    ):
        """Free subscriptions never reach Stripe, whatever plan the line is on."""
        subscription_item_factory(
            plan=plan_factory(name="Priced Tier", base_price=100),
            subscription__subscription_id="",
            subscription__kind="free",
        )

        assert Command()._report_no_stripe_id(None) == 0

    def test_a_paid_subscription_without_one_is(
        self, subscription_item_factory, plan_factory
    ):
        subscription_item_factory(
            plan=plan_factory(name="Priced Tier", base_price=100),
            subscription__subscription_id="",
        )

        assert Command()._report_no_stripe_id(None) == 1


@pytest.mark.django_db()
class TestCancellation:
    ENDS = datetime(2027, 8, 9, 16, tzinfo=timezone.utc)

    def _stripe(self, **fields):
        values = {"status": "active", "cancel_at_period_end": False}
        values.update(fields, items={"data": []}, discounts=[])
        return stripe.Subscription.construct_from(values, "sk_test")

    def _diff(self, sub, stripe_sub):
        return [
            diff
            for diff in Command()._compare(sub, stripe_sub, timezone.utc)
            if diff[0] == "cancelled/cancel_at_period_end"
        ]

    def test_a_dated_cancellation_counts_as_cancelling(self, subscription_factory):
        """A `cancel_at` or a schedule that cancels, not only period end."""
        sub = subscription_factory(cancelled=True, cancel_at=self.ENDS.date())
        stripe_sub = self._stripe(cancel_at=int(self.ENDS.timestamp()))

        assert not self._diff(sub, stripe_sub)

    def test_one_side_not_cancelling_is_still_reported(self, subscription_factory):
        sub = subscription_factory(cancelled=False, cancel_at=None)
        stripe_sub = self._stripe(cancel_at=int(self.ENDS.timestamp()))

        assert self._diff(sub, stripe_sub)
