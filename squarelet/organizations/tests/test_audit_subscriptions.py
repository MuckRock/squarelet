# The audit's internals are the unit under test here.
# pylint: disable=protected-access

# Standard Library
from unittest.mock import Mock

# Third Party
import pytest

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

    def test_quantity_drift_is_reported_per_line(self, subscription_item_factory):
        line = subscription_item_factory(stripe_item_id="si_1", quantity=3)
        stripe_items = _items(_stripe_item("si_1", line.plan.stripe_id, 7))

        diffs = Command()._compare_items(line.subscription, stripe_items)

        assert diffs == [(f"item[{line.plan.slug}] quantity", 3, 7)]

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
