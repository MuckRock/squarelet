# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Subscription


@pytest.fixture(name="legacy_plan")
def legacy_plan_fixture(plan_factory):
    """A plan that costs something, with no PlanPrice behind it yet."""
    return plan_factory(name="Legacy Plan", base_price=100)


@pytest.fixture(name="paid_price")
def paid_price_fixture(plan_price_factory):
    return plan_price_factory(amount=10_000, stripe_price_id="price_paid")


@pytest.mark.django_db()
class TestWhatIsSentToStripe:
    """A line bills its price once it has one, and its plan until then."""

    def test_a_line_with_a_price_bills_against_it(
        self, subscription_item_factory, paid_price
    ):
        item = subscription_item_factory(plan=paid_price.plan, plan_price=paid_price)

        assert item.subscription.stripe_items() == [
            {"plan": "price_paid", "quantity": item.quantity}
        ]

    def test_a_line_without_a_price_falls_back_to_the_plan(
        self, subscription_item_factory, legacy_plan
    ):
        item = subscription_item_factory(plan=legacy_plan)

        assert item.subscription.stripe_items() == [
            {"plan": item.plan.stripe_id, "quantity": item.quantity}
        ]

    def test_a_mixed_subscription_sends_the_right_thing_per_line(
        self, subscription_item_factory, paid_price, legacy_plan
    ):
        """Production looks like this until every line is migrated."""
        migrated = subscription_item_factory(
            plan=paid_price.plan, plan_price=paid_price
        )
        legacy = subscription_item_factory(
            subscription=migrated.subscription, plan=legacy_plan
        )

        specs = migrated.subscription.stripe_items()

        assert {s["plan"] for s in specs} == {"price_paid", legacy.plan.stripe_id}

    def test_a_price_with_no_stripe_price_yet_falls_back(
        self, subscription_item_factory, plan_price_factory, plan_factory
    ):
        """A failed `consolidate_stripe_products` can leave a paid price blank."""
        price = plan_price_factory(
            plan=plan_factory(name="Unready Plan", base_price=100),
            amount=10_000,
            stripe_price_id="",
        )
        item = subscription_item_factory(plan=price.plan, plan_price=price)

        assert item.subscription.stripe_items() == [
            {"plan": item.plan.stripe_id, "quantity": item.quantity}
        ]

    def test_include_ids_still_carries_the_item_id(
        self, subscription_item_factory, paid_price
    ):
        item = subscription_item_factory(
            plan=paid_price.plan, plan_price=paid_price, stripe_item_id="si_1"
        )

        specs = item.subscription.stripe_items(include_ids=True)

        assert specs == [
            {"plan": "price_paid", "quantity": item.quantity, "id": "si_1"}
        ]

    def test_item_ids_are_matched_on_the_price_sent(
        self, subscription_item_factory, paid_price
    ):
        item = subscription_item_factory(plan=paid_price.plan, plan_price=paid_price)
        stripe_sub = {
            "items": {"data": [{"id": "si_new", "price": {"id": "price_paid"}}]}
        }

        item.subscription.sync_stripe_item_ids(stripe_sub)

        item.refresh_from_db()
        assert item.stripe_item_id == "si_new"

    def test_a_newly_priced_line_is_matched_on_its_legacy_id(
        self, subscription_item_factory, paid_price
    ):
        """Unmatched, it is sent with no id and Stripe bills it twice."""
        item = subscription_item_factory(plan=paid_price.plan, plan_price=paid_price)
        stripe_sub = {
            "items": {"data": [{"id": "si_old", "price": {"id": item.plan.stripe_id}}]}
        }

        item.subscription.sync_stripe_item_ids(stripe_sub)

        item.refresh_from_db()
        assert item.stripe_item_id == "si_old"


@pytest.mark.django_db()
class TestAZeroPriceIsFree:
    """A comped price on a paid plan costs nothing and never reaches Stripe."""

    def test_the_line_and_subscription_are_free(
        self, subscription_item_factory, plan_price_factory
    ):
        price = plan_price_factory(label="comped", amount=0)
        item = subscription_item_factory(plan=price.plan, plan_price=price)

        assert item.is_free
        assert item.subscription.free
        assert item.subscription.stripe_items() == []

    def test_it_belongs_on_the_free_subscription(
        self, plan_factory, plan_price_factory
    ):
        price = plan_price_factory(
            plan=plan_factory(name="Paid Plan", base_price=100),
            label="comped",
            amount=0,
        )

        assert not price.plan.free
        assert Subscription.kind_for(price.plan, price) == "free"

    def test_a_paid_price_on_a_free_plan_is_not(self, plan_factory, plan_price_factory):
        plan = plan_factory(name="Free Plan", base_price=0, price_per_user=0)
        price = plan_price_factory(plan=plan, amount=10_000)

        assert Subscription.kind_for(plan, price) == "renewing"

    def test_without_a_price_the_plan_decides(
        self, subscription_item_factory, plan_factory
    ):
        item = subscription_item_factory(
            plan=plan_factory(name="Free Plan", base_price=0, price_per_user=0)
        )

        assert item.is_free
        assert Subscription.kind_for(item.plan) == "free"


@pytest.mark.django_db()
class TestNonprofitLines:
    def test_a_nonprofit_price_makes_a_nonprofit_line(
        self, subscription_item_factory, plan_price_factory
    ):
        price = plan_price_factory(label="nonprofit")

        assert subscription_item_factory(plan=price.plan, plan_price=price).is_nonprofit

    def test_a_standard_or_missing_price_does_not(
        self, subscription_item_factory, paid_price, legacy_plan
    ):
        assert not subscription_item_factory(
            plan=paid_price.plan, plan_price=paid_price
        ).is_nonprofit
        assert not subscription_item_factory(plan=legacy_plan).is_nonprofit
