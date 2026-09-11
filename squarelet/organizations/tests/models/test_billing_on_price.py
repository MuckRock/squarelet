# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Plan, SubscriptionItem
from squarelet.organizations.payments.exceptions import SubscriptionError
from squarelet.organizations.plan_mapping import resolve_target


@pytest.fixture(name="legacy_plan")
def legacy_plan_fixture(plan_factory):
    """A plan that costs something, with no PlanPrice behind it yet."""
    return plan_factory(name="Legacy Plan", base_price=100)


@pytest.fixture(name="paid_price")
def paid_price_fixture(plan_price_factory):
    """A price with a Stripe Price behind it."""
    return plan_price_factory(amount=10_000, stripe_price_id="price_paid")


def plan_with_slug(plan_factory, name, slug, **kwargs):
    """A plan at exactly `slug`, adopting the migration-seeded row if any.

    PlanFactory get-or-creates on *name* while `slug` is an AutoSlugField,
    so asking for a slug the seeded data already uses under another name
    quietly yields `<slug>-2`.  Everything that resolves by slug then finds
    the seeded row instead, with none of the prices the test just set up -
    and the test passes or fails on whether the database had been flushed.
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
        """consolidate_stripe_products can leave a paid row blank on failure.

        Safe here because this line's `plan` is the row the customer picked,
        so its legacy id bills what it always billed.  `resolve_purchase`
        refuses to *create* this pairing against a canonical plan, where the
        legacy id would be the monthly standard one - see
        `TestAPriceWithNoStripePriceIsNotReady`.
        """
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

    def _resolve(self, plan, nonprofit=False):
        _, price = SubscriptionItem.objects.resolve_purchase(plan, nonprofit)
        return price

    def test_resolves_the_standard_list_price(self, plan_price_factory):
        price = plan_price_factory(interval="monthly", label="standard")

        assert self._resolve(plan=price.plan) == price

    def test_nonprofit_resolves_the_nonprofit_price(self, plan_price_factory):
        """Self-reported, and the only thing the checkbox now decides."""
        plan = plan_price_factory(interval="monthly", label="standard").plan
        nonprofit = plan_price_factory(
            plan=plan, interval="monthly", label="nonprofit", amount=3_500
        )

        assert self._resolve(plan=plan, nonprofit=True) == nonprofit

    def test_an_annual_plan_resolves_the_annual_price(
        self, plan_factory, plan_price_factory
    ):
        """Interval comes from the plan, not from the caller."""
        plan = plan_factory(name="Annual Tier", annual=True)
        plan_price_factory(plan=plan, interval="monthly", amount=10_000)
        annual = plan_price_factory(plan=plan, interval="annual", amount=120_000)

        assert self._resolve(plan=plan) == annual

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

        assert self._resolve(plan=plan).code == ""

    def test_a_comped_target_is_never_sold(self):
        """The mapping legitimately contains comped targets, for migrating
        subscriptions that are already comped.  Self-service must not reach
        one -- that would be handing out a free subscription."""
        assert resolve_target("beta", allow_comped=True)[2] == "comped"
        assert resolve_target("beta", allow_comped=False) is None

    def test_a_comped_price_is_unreachable(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly", label="comped", amount=0).plan

        assert self._resolve(plan=plan) is None

    def test_no_price_yet_resolves_to_none(self, plan_factory):
        """Every plan, until consolidate_stripe_products has run."""
        assert self._resolve(plan=plan_factory()) is None


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

    def test_default_is_the_subscription_own_answer(
        self, subscription_item_factory, mocker
    ):
        """Which is `always_invoice` for a card payer - it still prorates."""
        item = subscription_item_factory(subscription__subscription_id="sub_1")

        kwargs = self._modify(item, mocker)

        assert kwargs["proration_behavior"] == item.subscription.proration_behavior
        assert kwargs["proration_behavior"] != "none"

    def test_it_can_be_suppressed(self, subscription_item_factory, mocker):
        item = subscription_item_factory(subscription__subscription_id="sub_1")

        kwargs = self._modify(item, mocker, proration_behavior="none")

        assert kwargs["proration_behavior"] == "none"


@pytest.mark.django_db()
class TestEveryPurchasablePlanResolves:
    """A plan a customer can pick must map to a price.

    An unmapped slug falls back to the legacy plan silently -- correct
    while nothing is set up, but indistinguishable from a missing entry.
    These pin the slugs that were public when the mapping was written, so
    adding a purchasable plan without a price fails here rather than in
    production.
    """

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
        """The checkbox substitutes the plan; the map turns it into a label."""
        for slug, canonical, interval in self.NONPROFIT:
            target = resolve_target(slug, allow_comped=False)
            assert target is not None, f"{slug} has no mapping"
            assert target[:3] == (canonical, interval, "nonprofit"), slug

    def test_every_target_names_a_blank_code(self):
        """A purchase must never default onto someone's negotiated rate."""
        for slug, *_ in self.PURCHASABLE + [
            (s, None, None) for s, _, _ in self.NONPROFIT
        ]:
            assert resolve_target(slug, allow_comped=False)[3] == ""


@pytest.mark.django_db()
class TestBillingShapeFollowsThePrice:
    """The subscription's interval comes from the resolved price.

    `plan.annual` is not enough: annual is a separate Plan row today, and
    the row a customer picks is not always the row they end up on -- the
    nonprofit variants are substituted in by the form.  If the flag and the
    price disagreed, an annual price would land on a subscription recorded
    as monthly, grouping it onto the wrong invoice.
    """

    def test_an_annual_price_makes_an_annual_subscription(
        self, organization_factory, plan_factory, plan_price_factory, mocker
    ):
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        plan_price_factory(
            plan=canonical,
            interval="annual",
            label="nonprofit",
            amount=400_000,
            stripe_price_id="price_np_annual",
        )
        # The row the form substitutes in, with the flag deliberately wrong
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Nonprofit Essential Annual",
            "sunlight-nonprofit-essential-annual",
            annual=False,
        )
        mocker.patch("squarelet.organizations.models.Subscription.start")
        mocker.patch(
            "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
        )

        item, _ = SubscriptionItem.objects.start(
            organization=organization_factory(), plan=picked, quantity=1
        )

        assert item.subscription.interval == "annual"
        assert item.plan == canonical
        assert item.plan_price.stripe_price_id == "price_np_annual"


@pytest.mark.django_db()
class TestAPriceWithNoStripePriceIsNotReady:
    """A paid price Stripe has never heard of cannot be sold against.

    `consolidate_stripe_products` can fail part-way and leave a paid row
    with a blank `stripe_price_id`.  Resolving to it anyway would record
    the line against the canonical plan and take the interval from the
    price, while the Stripe id fell back to the canonical plan's legacy
    row - the *monthly standard* one.  An annual nonprofit would bill the
    monthly standard amount on a subscription recorded as annual.
    """

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
        price = plan_price_factory(
            plan=picked, interval="monthly", amount=10_000, stripe_price_id="price_ok"
        )

        assert self._resolve(plan=picked) == (price.plan, price)

    def test_a_free_price_is_not_treated_as_unready(
        self, plan_factory, plan_price_factory
    ):
        """$0 has no Stripe Price and never will - finished, not part-way."""
        picked = plan_factory(name="Free Tier")
        free = plan_price_factory(
            plan=picked, interval="monthly", amount=0, stripe_price_id=""
        )

        assert self._resolve(plan=picked) == (free.plan, free)


@pytest.mark.django_db()
class TestDuplicatePurchaseIsRefusedPolitely:
    """The guard has to ask about the row the line will be stored under.

    `start` records the resolved plan, so asking about the picked one found
    nothing for anyone buying an annual or nonprofit variant.  The purchase
    then ran the whole way - card, Stripe customer, subscription - before
    the insert hit `unique_together(subscription, plan)` inside
    `transaction.atomic()`: a 500, with whatever Stripe had already been
    told, in place of the polite error this check exists to raise.
    """

    def test_the_canonical_plan_is_what_gets_asked_about(
        self, plan_factory, plan_price_factory
    ):
        canonical = plan_factory(name="Sunlight Essential")
        price = plan_price_factory(
            plan=canonical, interval="monthly", label="standard", amount=68_000
        )

        assert SubscriptionItem.objects.canonical_plan(canonical) == price.plan

    def test_a_nonprofit_buyer_is_asked_about_the_same_row(
        self, plan_factory, plan_price_factory
    ):
        canonical = plan_factory(name="Sunlight Essential")
        plan_price_factory(
            plan=canonical, interval="monthly", label="standard", amount=68_000
        )
        plan_price_factory(
            plan=canonical, interval="monthly", label="nonprofit", amount=35_000
        )

        assert SubscriptionItem.objects.canonical_plan(
            canonical, nonprofit=True
        ) == SubscriptionItem.objects.canonical_plan(canonical)

    def test_buying_a_variant_a_second_time_is_refused(
        self, organization_factory, plan_factory, plan_price_factory, mocker
    ):
        """Refused here, before any of it happens.

        The picked row and the stored row differ here, which is the whole
        point: guarding on the picked one finds nothing, so the purchase
        carries on - saving a card, reaching Stripe, creating a customer -
        and only falls over at the insert, on `unique_together`.  That is a
        500 with Stripe-side leftovers where this is a clean refusal.
        """
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        plan_price_factory(
            plan=canonical,
            interval="annual",
            label="nonprofit",
            amount=400_000,
            stripe_price_id="price_np_annual",
        )
        picked = plan_with_slug(
            plan_factory,
            "Sunlight Nonprofit Essential Annual",
            "sunlight-nonprofit-essential-annual",
            annual=True,
        )
        mocker.patch("squarelet.organizations.models.Subscription.start")
        mocker.patch(
            "squarelet.organizations.models.payment.SubscriptionItem.notify_started"
        )
        organization = organization_factory()
        held, _ = SubscriptionItem.objects.start(
            organization=organization, plan=picked, nonprofit=True
        )
        assert held.plan == canonical, "the line is stored under the resolved plan"

        with pytest.raises(SubscriptionError, match="already has an active"):
            organization.add_subscription(picked, 5, None, nonprofit=True)


@pytest.mark.django_db()
class TestNonprofitSurvivesTheMapping:
    """The checkbox has to work once the nonprofit Plan rows are gone.

    Today the form substitutes a `sunlight-nonprofit-*` row in, so the slug
    carries the nonprofit-ness and `resolve_target` reads it off the slug.
    #806 removes those rows.  After that the flag is the only thing that
    knows, and ignoring it would show a nonprofit the nonprofit rate and
    bill them the standard one.
    """

    def _resolve(self, plan, nonprofit=False):
        _, price = SubscriptionItem.objects.resolve_purchase(plan, nonprofit)
        return price

    def test_a_mapped_slug_still_honours_the_flag(
        self, plan_factory, plan_price_factory
    ):
        """The case that breaks the moment the variant rows are deleted."""
        canonical = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        standard = plan_price_factory(
            plan=canonical, interval="annual", label="standard", amount=800_000
        )
        nonprofit = plan_price_factory(
            plan=canonical, interval="annual", label="nonprofit", amount=400_000
        )
        # The row the customer picks once the nonprofit variants are gone.
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
        """Preferred, not forced - matching nothing would be worse."""
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
class TestChangingTierRepricesTheLine:
    """`modify` moves the plan, so it has to move the price with it.

    The line bills against `plan_price` now.  Leaving the old one behind
    moved the customer on paper and charged them the tier they left, and
    `is_free` answered about that tier too.
    """

    def _modify(self, item, plan, mocker):
        mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription",
            None,
        )
        mocker.patch("squarelet.organizations.models.Subscription.sync_to_stripe")
        item.modify(plan)
        item.refresh_from_db()
        return item

    def test_the_price_moves_with_the_plan(
        self, subscription_item_factory, plan_factory, plan_price_factory, mocker
    ):
        essential = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        from_price = plan_price_factory(
            plan=essential, interval="monthly", label="standard", amount=68_000
        )
        enhanced = plan_with_slug(
            plan_factory, "Sunlight Enhanced", "sunlight-enhanced"
        )
        to_price = plan_price_factory(
            plan=enhanced, interval="monthly", label="standard", amount=138_000
        )
        item = subscription_item_factory(plan=essential, plan_price=from_price)

        self._modify(item, enhanced, mocker)

        assert item.plan == enhanced
        assert item.plan_price == to_price
        assert item.stripe_price_id == to_price.stripe_price_id

    def test_a_nonprofit_stays_a_nonprofit(
        self, subscription_item_factory, plan_factory, plan_price_factory, mocker
    ):
        essential = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential"
        )
        from_price = plan_price_factory(
            plan=essential, interval="monthly", label="nonprofit", amount=35_000
        )
        enhanced = plan_with_slug(
            plan_factory, "Sunlight Enhanced", "sunlight-enhanced"
        )
        plan_price_factory(
            plan=enhanced, interval="monthly", label="standard", amount=138_000
        )
        to_nonprofit = plan_price_factory(
            plan=enhanced, interval="monthly", label="nonprofit", amount=68_000
        )
        item = subscription_item_factory(plan=essential, plan_price=from_price)

        self._modify(item, enhanced, mocker)

        assert item.plan_price == to_nonprofit
