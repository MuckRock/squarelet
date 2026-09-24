# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Plan, Subscription, SubscriptionItem
from squarelet.organizations.payments.exceptions import SubscriptionError
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

    def test_a_free_price_resolves(self, plan_price_factory):
        price = plan_price_factory(amount=0)

        assert self._resolve(plan=price.plan) == price

    def test_no_price_yet_bills_the_plan_picked(self, plan_factory):
        plan = plan_factory()

        assert SubscriptionItem.objects.resolve_purchase(plan) == (plan, None)


@pytest.mark.django_db()
class TestACompedTargetIsNeverSold:
    """The mapping lands some legacy plans on comped; a purchase must not."""

    def test_buying_beta_does_not_get_it_free(self, plan_factory, plan_price_factory):
        professional = plan_with_slug(
            plan_factory, "Professional", "professional", base_price=40
        )
        plan_price_factory(plan=professional, label="comped", amount=0)
        beta = plan_with_slug(plan_factory, "Beta", "beta")

        _, price = SubscriptionItem.objects.resolve_purchase(beta)

        assert price is None


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
            target = resolve_target(slug)
            assert target is not None, f"{slug} has no mapping"
            assert target[:3] == (canonical, interval, label), slug

    def test_each_nonprofit_variant_maps_to_the_nonprofit_price(self):
        for slug, canonical, interval in self.NONPROFIT:
            target = resolve_target(slug)
            assert target is not None, f"{slug} has no mapping"
            assert target[:3] == (canonical, interval, "nonprofit"), slug

    def test_every_target_names_a_blank_code(self):
        """A purchase must never land on someone's negotiated rate."""
        slugs = [slug for slug, *_ in self.PURCHASABLE + self.NONPROFIT]
        for slug in slugs:
            assert resolve_target(slug)[3] == "", slug


@pytest.mark.django_db()
class TestTheNonprofitFlag:
    """The checkbox must pick the price once the variant rows are gone."""

    def test_a_mapped_slug_honours_the_flag(self, plan_factory, plan_price_factory):
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

        assert SubscriptionItem.objects.resolve_purchase(picked, nonprofit=True) == (
            canonical,
            nonprofit,
        )
        assert SubscriptionItem.objects.resolve_purchase(picked) == (
            canonical,
            standard,
        )


@pytest.mark.django_db()
class TestWhereAPurchaseIsStored:
    """What "already subscribed?" has to ask about."""

    def test_a_variant_may_be_under_its_tier_or_itself(self, plan_factory):
        tier = plan_with_slug(plan_factory, "Sunlight Essential", "sunlight-essential")
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Nonprofit Essential Annual",
            "sunlight-nonprofit-essential-annual",
            annual=True,
        )

        assert SubscriptionItem.objects.stored_under(picked) >= {picked, tier}

    def test_every_schedule_and_rate_of_a_tier_counts(self, plan_factory):
        """Holding Essential monthly, annual Essential is the same tier."""
        rows = {
            plan_with_slug(plan_factory, name, slug)
            for name, slug in [
                ("Sunlight Essential", "sunlight-essential"),
                ("Sunlight Essential (Annual)", "sunlight-essential-annual"),
                ("Sunlight Nonprofit Essential", "sunlight-nonprofit-essential"),
                (
                    "Sunlight Nonprofit Essential (Annual)",
                    "sunlight-nonprofit-essential-annual",
                ),
            ]
        }
        enhanced = plan_with_slug(
            plan_factory, "Sunlight Enhanced", "sunlight-enhanced"
        )

        for row in rows:
            held = SubscriptionItem.objects.stored_under(row)
            assert held >= rows, row.slug
            assert enhanced not in held

    def test_an_unmapped_plan_is_only_itself(self, plan_factory):
        plan = plan_factory(name="Unmapped Plan")

        assert SubscriptionItem.objects.stored_under(plan) == {plan}


@pytest.fixture(name="no_stripe")
def no_stripe_fixture(mocker):
    mocker.patch("squarelet.organizations.models.Subscription.start")
    mocker.patch(
        "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
    )


@pytest.mark.django_db()
@pytest.mark.usefixtures("no_stripe")
class TestSellingAgainstThePrice:
    def test_the_line_is_stored_under_the_tier_and_its_price(
        self, organization_factory, plan_factory, plan_price_factory
    ):
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        price = plan_price_factory(
            plan=canonical, interval="annual", label="nonprofit", amount=400_000
        )
        # The row the form substitutes in, with its annual flag wrong.
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Nonprofit Essential Annual",
            "sunlight-nonprofit-essential-annual",
            annual=False,
        )

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=picked
        )

        assert item.plan == canonical
        assert item.plan_price == price
        assert item.subscription.interval == "annual"

    def test_a_tier_is_one_unit_of_its_price(
        self, organization_factory, plan_price_factory
    ):
        price = plan_price_factory(amount=10_000)
        price.plan.minimum_users = 5
        price.plan.save()

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=price.plan
        )

        assert item.quantity == 1

    def test_a_legacy_plan_still_takes_its_minimum(
        self, organization_factory, legacy_plan
    ):
        """A legacy tiered Stripe Plan prices its minimum as the base."""
        legacy_plan.minimum_users = 5
        legacy_plan.save()

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=legacy_plan
        )

        assert item.quantity == 5

    def test_an_explicit_quantity_is_kept(
        self, organization_factory, plan_price_factory
    ):
        price = plan_price_factory(amount=1_000)

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=price.plan, quantity=3
        )

        assert item.quantity == 3

    def test_a_zero_price_goes_on_the_free_subscription(
        self, organization_factory, plan_factory, plan_price_factory
    ):
        plan = plan_with_slug(
            plan_factory, "Organization", "organization", base_price=100
        )
        plan_price_factory(plan=plan, amount=0)

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=plan
        )

        assert item.subscription.kind == "free"

    def test_buying_a_variant_a_second_time_is_refused(
        self, organization_factory, plan_factory, plan_price_factory
    ):
        """Refused before any card or Stripe work, not at the insert."""
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
        organization = organization_factory()
        SubscriptionItem.objects.start(
            organization=organization, plan=picked, nonprofit=True
        )

        with pytest.raises(SubscriptionError, match="already has an active"):
            organization.add_subscription(picked, None, None, nonprofit=True)

    def test_a_line_bought_before_prices_existed_still_counts(
        self, organization_factory, plan_factory, plan_price_factory
    ):
        """Held under the plan picked, not yet under its tier."""
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Essential (Annual)",
            "sunlight-essential-annual",
            annual=True,
        )
        organization = organization_factory()
        held, _ = SubscriptionItem.objects.start(organization=organization, plan=picked)
        assert held.plan == picked
        plan_price_factory(plan=canonical, interval="annual")

        with pytest.raises(SubscriptionError, match="already has an active"):
            organization.add_subscription(picked, None, None)

    def test_the_tier_counts_as_held_on_any_schedule(
        self, organization_factory, plan_factory
    ):
        monthly = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential", base_price=680
        )
        annual = plan_with_slug(
            plan_factory,
            "Sunlight Essential (Annual)",
            "sunlight-essential-annual",
            annual=True,
        )
        organization = organization_factory()
        held, _ = SubscriptionItem.objects.start(
            organization=organization, plan=monthly
        )

        assert organization.has_active_subscription(annual)
        assert organization.line_holding(annual) == held

    def test_the_log_names_the_plan_held(
        self, organization_factory, plan_factory, plan_price_factory, mocker
    ):
        """So the addition pairs with the removal, which logs the line's plan."""
        mocker.patch("squarelet.organizations.models.Organization.customer")
        tier = plan_with_slug(plan_factory, "Sunlight Essential", "sunlight-essential")
        plan_price_factory(plan=tier, interval="annual")
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Essential (Annual)",
            "sunlight-essential-annual",
            annual=True,
        )
        organization = organization_factory()

        organization.add_subscription(picked, None, None, payment_method="card")

        assert organization.change_logs.get().to_plan == tier


@pytest.mark.django_db()
class TestChangingTierRepricesTheLine:
    """Leaving the old price behind would bill the tier the customer left."""

    def _modify(self, item, plan, mocker):
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription", None
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        item.modify(plan)
        item.refresh_from_db()
        return item

    @pytest.fixture
    def tiers(self, plan_factory):
        return (
            plan_with_slug(plan_factory, "Sunlight Essential", "sunlight-essential"),
            plan_with_slug(plan_factory, "Sunlight Enhanced", "sunlight-enhanced"),
        )

    def test_the_price_moves_with_the_plan(
        self, subscription_item_factory, plan_price_factory, tiers, mocker
    ):
        essential, enhanced = tiers
        from_price = plan_price_factory(plan=essential, amount=68_000)
        to_price = plan_price_factory(plan=enhanced, amount=138_000)
        item = subscription_item_factory(plan=essential, plan_price=from_price)

        self._modify(item, enhanced, mocker)

        assert item.plan == enhanced
        assert item.plan_price == to_price

    def test_a_nonprofit_stays_a_nonprofit(
        self, subscription_item_factory, plan_price_factory, tiers, mocker
    ):
        essential, enhanced = tiers
        from_price = plan_price_factory(
            plan=essential, label="nonprofit", amount=35_000
        )
        plan_price_factory(plan=enhanced, label="standard", amount=138_000)
        to_nonprofit = plan_price_factory(
            plan=enhanced, label="nonprofit", amount=68_000
        )
        item = subscription_item_factory(plan=essential, plan_price=from_price)

        self._modify(item, enhanced, mocker)

        assert item.plan_price == to_nonprofit

    def test_a_move_onto_a_zero_price_is_refused(
        self, subscription_item_factory, plan_price_factory, tiers, mocker
    ):
        """A $0 price belongs on the free subscription."""
        essential, enhanced = tiers
        from_price = plan_price_factory(plan=essential, amount=68_000)
        plan_price_factory(plan=enhanced, amount=0)
        item = subscription_item_factory(plan=essential, plan_price=from_price)

        with pytest.raises(SubscriptionError, match="never share a subscription"):
            self._modify(item, enhanced, mocker)
