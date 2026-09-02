# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import SubscriptionItem
from squarelet.organizations.plan_mapping import resolve_target


@pytest.fixture(name="legacy_plan")
def legacy_plan_fixture(plan_factory):
    """A plan that costs something, with no PlanPrice behind it yet."""
    return plan_factory(name="Legacy Plan", base_price=100)


@pytest.fixture(name="paid_price")
def paid_price_fixture(plan_price_factory):
    """A price with a Stripe Price behind it."""
    return plan_price_factory(amount=10_000, stripe_price_id="price_paid")


@pytest.mark.django_db()
class TestWhatIsSentToStripe:
    """Which identifier each line bills against.

    The fallback to the plan's legacy id is not a transitional convenience
    that disappears when the backfill finishes -- it covers the three
    populations that keep a null `plan_price` by design: per-user
    subscribers awaiting decomposition, deferred slugs, and every signup
    until the purchase flow records a price.
    """

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
        """The state production sits in for the whole window before 3c."""
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
        """consolidate_stripe_products can leave a paid row blank on failure."""
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


@pytest.mark.django_db()
class TestCompedLinesNeverReachStripe:
    """A comped price has no Stripe Price, so there is nothing to name."""

    def test_a_comped_line_is_omitted(
        self, subscription_item_factory, plan_price_factory, paid_price
    ):
        paid = subscription_item_factory(plan=paid_price.plan, plan_price=paid_price)
        comped_price = plan_price_factory(
            plan=paid_price.plan, label="comped", amount=0, stripe_price_id=""
        )
        subscription_item_factory(
            subscription=paid.subscription,
            plan=plan_price_factory(amount=0).plan,
            plan_price=comped_price,
        )

        specs = paid.subscription.stripe_items()

        assert specs == [{"plan": "price_paid", "quantity": paid.quantity}]

    def test_an_all_comped_subscription_is_free(
        self, subscription_item_factory, plan_price_factory
    ):
        price = plan_price_factory(label="comped", amount=0, stripe_price_id="")
        item = subscription_item_factory(plan=price.plan, plan_price=price)

        assert item.subscription.free
        assert item.subscription.stripe_items() == []

    def test_one_paid_line_makes_the_subscription_not_free(
        self, subscription_item_factory, plan_price_factory, paid_price
    ):
        """The case that would have sent a blank plan id to Stripe."""
        paid = subscription_item_factory(plan=paid_price.plan, plan_price=paid_price)
        comped = plan_price_factory(
            plan=paid_price.plan, label="comped", amount=0, stripe_price_id=""
        )
        subscription_item_factory(
            subscription=paid.subscription,
            plan=plan_price_factory(amount=0).plan,
            plan_price=comped,
        )

        assert not paid.subscription.free
        assert all(spec["plan"] for spec in paid.subscription.stripe_items())

    def test_free_still_falls_back_to_the_plan_without_a_price(
        self, subscription_item_factory, plan_factory
    ):
        item = subscription_item_factory(
            plan=plan_factory(name="Free Plan", base_price=0, price_per_user=0)
        )

        assert item.subscription.free


@pytest.mark.django_db()
class TestPurchaseResolvesAPrice:
    """What price a new subscription is sold at.

    Plan, interval and label identify exactly one active list price, so
    this is a lookup rather than a choice -- there is no UI for picking a
    price, and deliberately so.
    """

    def _resolve(self, **kwargs):
        _, price = SubscriptionItem.objects.resolve_purchase(**kwargs)
        return price

    def test_resolves_the_standard_list_price(self, plan_price_factory):
        price = plan_price_factory(interval="monthly", label="standard")

        assert self._resolve(plan=price.plan, interval="monthly") == price

    def test_nonprofit_resolves_the_nonprofit_price(self, plan_price_factory):
        """Self-reported, and the only thing the checkbox now decides."""
        plan = plan_price_factory(interval="monthly", label="standard").plan
        nonprofit = plan_price_factory(
            plan=plan, interval="monthly", label="nonprofit", amount=3_500
        )

        assert self._resolve(plan=plan, interval="monthly", nonprofit=True) == nonprofit

    def test_interval_selects_between_prices(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly").plan
        annual = plan_price_factory(plan=plan, interval="annual", amount=120_000)

        assert self._resolve(plan=plan, interval="annual") == annual

    def test_list_pricing_wins_over_a_negotiated_rate(self, plan_price_factory):
        """A deal attached to a plan is not what a stranger buying it pays.

        Reaching a negotiated rate requires being granted the private plan
        it belongs to, and that grant is the authorisation -- so `code`
        prices are not blocked outright, only never picked by default.
        """
        plan = plan_price_factory(interval="monthly", label="standard").plan
        plan_price_factory(
            plan=plan,
            interval="monthly",
            label="standard",
            code="insideclimate",
            amount=3_000,
        )

        assert self._resolve(plan=plan, interval="monthly").code == ""

    def test_a_comped_target_is_never_sold(self):
        """The mapping legitimately contains comped targets, for migrating
        subscriptions that are already comped.  Self-service must not reach
        one -- that would be handing out a free subscription."""
        assert resolve_target("beta", allow_comped=True)[2] == "comped"
        assert resolve_target("beta", allow_comped=False) is None

    def test_a_comped_price_is_unreachable(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly", label="comped", amount=0).plan

        assert self._resolve(plan=plan, interval="monthly") is None

    def test_no_price_yet_resolves_to_none(self, plan_factory):
        """Every plan, until consolidate_stripe_products has run."""
        assert self._resolve(plan=plan_factory(), interval="monthly") is None


@pytest.mark.django_db()
class TestProrationIsOptOut:
    """A genuine upgrade should prorate; an identifier swap should not."""

    def _modify(self, item, mocker, **kwargs):
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        svc = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_subscription_service.return_value
        svc.modify.return_value = None
        item.subscription.stripe_modify(**kwargs)
        return svc.modify.call_args.kwargs

    def test_default_leaves_proration_to_stripe(
        self, subscription_item_factory, mocker
    ):
        item = subscription_item_factory(subscription__subscription_id="sub_1")

        assert "proration_behavior" not in self._modify(item, mocker)

    def test_it_can_be_suppressed(self, subscription_item_factory, mocker):
        item = subscription_item_factory(subscription__subscription_id="sub_1")

        kwargs = self._modify(item, mocker, proration_behavior="none")

        assert kwargs["proration_behavior"] == "none"
