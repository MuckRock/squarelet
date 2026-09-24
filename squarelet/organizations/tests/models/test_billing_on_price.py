# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Plan, Subscription, SubscriptionItem
from squarelet.organizations.plan_mapping import resolve_target


@pytest.fixture(name="legacy_plan")
def legacy_plan_fixture(plan_factory):
    """A plan that costs something, with no PlanPrice behind it yet."""
    return plan_factory(name="Legacy Plan", base_price=100)


@pytest.fixture(name="paid_price")
def paid_price_fixture(plan_price_factory):
    return plan_price_factory(amount=10_000, stripe_price_id="price_paid")


def plan_with_slug(plan_factory, name, slug, **kwargs):
    """A plan at exactly `slug`, adopting the migration-seeded row if any.

    PlanFactory gets-or-creates on name, so a seeded slug would come back as
    `<slug>-2` and the test would depend on whether the database was flushed.
    """
    plan = Plan.objects.filter(slug=slug).first()
    if plan is None:
        return plan_factory(name=name, slug=slug, **kwargs)
    for field, value in kwargs.items():
        setattr(plan, field, value)
    plan.save()
    plan.prices.all().delete()
    return plan


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

    def test_a_mixed_subscription_sends_the_right_thing_per_line(
        self, subscription_item_factory, paid_price, legacy_plan, plan_price_factory
    ):
        """Production looks like this until every line is migrated."""
        migrated = subscription_item_factory(
            plan=paid_price.plan, plan_price=paid_price
        )
        legacy = subscription_item_factory(
            subscription=migrated.subscription, plan=legacy_plan
        )
        # A failed `consolidate_stripe_products` can leave a paid price blank.
        unready_price = plan_price_factory(
            plan__name="Unready Plan", plan__base_price=100, stripe_price_id=""
        )
        unready = subscription_item_factory(
            subscription=migrated.subscription,
            plan=unready_price.plan,
            plan_price=unready_price,
        )

        specs = migrated.subscription.stripe_items()

        assert {s["plan"] for s in specs} == {
            "price_paid",
            legacy.plan.stripe_id,
            unready.plan.stripe_id,
        }

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
        self, subscription_item_factory, plan_factory, plan_price_factory
    ):
        price = plan_price_factory(
            plan=plan_factory(name="Paid Plan", base_price=100),
            label="comped",
            amount=0,
        )
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


@pytest.mark.django_db()
class TestPurchaseResolvesAPrice:
    """Plan, interval and label pick exactly one active list price."""

    def _resolve(self, plan, nonprofit=False):
        _, price = SubscriptionItem.objects.resolve_purchase(plan, nonprofit)
        return price

    def test_resolves_the_standard_list_price(self, plan_price_factory):
        price = plan_price_factory(interval="monthly", label="standard")

        assert self._resolve(plan=price.plan) == price

    def test_nonprofit_resolves_the_nonprofit_price(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly", label="standard").plan
        nonprofit = plan_price_factory(
            plan=plan, interval="monthly", label="nonprofit", amount=3_500
        )

        assert self._resolve(plan=plan, nonprofit=True) == nonprofit

    def test_an_annual_plan_resolves_the_annual_price(
        self, plan_factory, plan_price_factory
    ):
        plan = plan_factory(name="Annual Tier", annual=True)
        plan_price_factory(plan=plan, interval="monthly", amount=10_000)
        annual = plan_price_factory(plan=plan, interval="annual", amount=120_000)

        assert self._resolve(plan=plan) == annual

    def test_list_pricing_wins_over_a_negotiated_rate(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly", label="standard").plan
        plan_price_factory(
            plan=plan,
            interval="monthly",
            label="standard",
            code="insideclimate",
            amount=3_000,
        )

        assert self._resolve(plan=plan).code == ""

    def test_a_comped_target_is_never_sold(self):
        """The migration may land on comped; a purchase must not."""
        assert resolve_target("beta", allow_comped=True)[2] == "comped"
        assert resolve_target("beta", allow_comped=False) is None

    def test_a_comped_price_is_unreachable(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly", label="comped", amount=0).plan

        assert self._resolve(plan=plan) is None

    def test_no_price_yet_resolves_to_none(self, plan_factory):
        assert self._resolve(plan=plan_factory()) is None


@pytest.mark.django_db()
class TestEveryPurchasablePlanResolves:
    """An unmapped slug silently bills its legacy plan, so pin the public ones."""

    PURCHASABLE = [
        ("organization", "organization", "monthly", "standard"),
        ("sunlight-essential", "sunlight-essential", "monthly", "standard"),
        ("sunlight-essential-annual", "sunlight-essential", "annual", "standard"),
        ("sunlight-enhanced", "sunlight-enhanced", "monthly", "standard"),
        ("sunlight-enhanced-annual", "sunlight-enhanced", "annual", "standard"),
        ("professional", "professional", "monthly", "standard"),
    ]

    NONPROFIT = [
        ("sunlight-nonprofit-essential", "sunlight-essential", "monthly"),
        ("sunlight-nonprofit-essential-annual", "sunlight-essential", "annual"),
        ("sunlight-nonprofit-enhanced", "sunlight-enhanced", "monthly"),
        ("sunlight-nonprofit-enhanced-annual", "sunlight-enhanced", "annual"),
    ]

    def test_each_public_plan_maps_to_a_canonical_target(self):
        for slug, canonical, interval, label in self.PURCHASABLE:
            target = resolve_target(slug, allow_comped=False)
            assert target is not None, f"{slug} has no mapping"
            assert target[:3] == (canonical, interval, label), slug

    def test_each_nonprofit_variant_maps_to_the_nonprofit_price(self):
        for slug, canonical, interval in self.NONPROFIT:
            target = resolve_target(slug, allow_comped=False)
            assert target is not None, f"{slug} has no mapping"
            assert target[:3] == (canonical, interval, "nonprofit"), slug

    def test_every_target_names_a_blank_code(self):
        """A purchase must never land on someone's negotiated rate."""
        slugs = [slug for slug, *_ in self.PURCHASABLE + self.NONPROFIT]
        for slug in slugs:
            assert resolve_target(slug, allow_comped=False)[3] == "", slug


@pytest.mark.django_db()
class TestAPriceWithNoStripePriceIsNotReady:
    """Selling on it would bill the canonical plan's monthly standard id."""

    def _resolve(self, plan, nonprofit=False):
        return SubscriptionItem.objects.resolve_purchase(plan, nonprofit)

    def test_it_stays_on_the_plan_the_customer_picked(
        self, plan_factory, plan_price_factory
    ):
        picked = plan_factory(name="Annual Nonprofit Tier", annual=True)
        plan_price_factory(
            plan=picked, interval="annual", amount=400_000, stripe_price_id=""
        )

        assert self._resolve(plan=picked) == (picked, None)

    def test_a_ready_price_still_resolves(self, plan_factory, plan_price_factory):
        picked = plan_factory(name="Ready Tier")
        price = plan_price_factory(plan=picked, interval="monthly", amount=10_000)

        assert self._resolve(plan=picked) == (price.plan, price)

    def test_a_free_price_is_not_treated_as_unready(
        self, plan_factory, plan_price_factory
    ):
        """A $0 price never gets a Stripe Price."""
        picked = plan_factory(name="Free Tier")
        free = plan_price_factory(plan=picked, interval="monthly", amount=0)

        assert self._resolve(plan=picked) == (free.plan, free)


@pytest.mark.django_db()
class TestNonprofitSurvivesTheMapping:
    """The checkbox must still pick the price once the variant rows are gone."""

    def _resolve(self, plan, nonprofit=False):
        _, price = SubscriptionItem.objects.resolve_purchase(plan, nonprofit)
        return price

    def test_a_mapped_slug_still_honours_the_flag(
        self, plan_factory, plan_price_factory
    ):
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        standard = plan_price_factory(
            plan=canonical, interval="annual", label="standard", amount=800_000
        )
        nonprofit = plan_price_factory(
            plan=canonical, interval="annual", label="nonprofit", amount=400_000
        )
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Essential (Annual)",
            "sunlight-essential-annual",
            annual=True,
        )

        assert self._resolve(picked, nonprofit=True) == nonprofit
        assert self._resolve(picked) == standard

    def test_a_tier_with_no_nonprofit_price_sells_at_its_list_price(
        self, plan_factory, plan_price_factory
    ):
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        standard = plan_price_factory(
            plan=canonical, interval="annual", label="standard", amount=800_000
        )
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Essential (Annual)",
            "sunlight-essential-annual",
            annual=True,
        )

        assert self._resolve(picked, nonprofit=True) == standard


@pytest.mark.django_db()
class TestTheCanonicalPlan:
    def test_a_variant_is_stored_under_its_tier(self, plan_factory, plan_price_factory):
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        plan_price_factory(plan=canonical, interval="annual", label="nonprofit")
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Nonprofit Essential Annual",
            "sunlight-nonprofit-essential-annual",
            annual=True,
        )

        assert SubscriptionItem.objects.canonical_plan(picked) == canonical

    def test_a_nonprofit_buyer_is_asked_about_the_same_row(
        self, plan_factory, plan_price_factory
    ):
        canonical = plan_factory(name="Sunlight Essential")
        plan_price_factory(plan=canonical, label="standard", amount=68_000)
        plan_price_factory(plan=canonical, label="nonprofit", amount=35_000)

        assert SubscriptionItem.objects.canonical_plan(
            canonical, nonprofit=True
        ) == SubscriptionItem.objects.canonical_plan(canonical)
