# Django
from django.test import override_settings

# Third Party
import pytest


class TestPlan:
    """Unit tests for Plan model"""

    def test_str(self, plan_factory):
        plan = plan_factory.build()
        assert str(plan) == plan.name

    def test_free(self, plan_factory):
        plan = plan_factory.build()
        assert plan.free

    def test_not_free(self, professional_plan_factory):
        plan = professional_plan_factory.build()
        assert not plan.free

    @pytest.mark.parametrize(
        "users,cost", [(0, 100), (1, 100), (5, 100), (7, 120), (10, 150)]
    )
    def test_cost(self, organization_plan_factory, users, cost):
        plan = organization_plan_factory.build()
        assert plan.cost(users) == cost

    def test_stripe_id(self, plan_factory):
        plan = plan_factory.build()
        assert plan.stripe_id == f"squarelet_plan_{plan.slug}"

    def test_make_stripe_plan_individual(self, professional_plan_factory, mocker):
        mocked = mocker.patch("stripe.Plan.create")
        plan = professional_plan_factory.build()
        plan.make_stripe_plan()
        mocked.assert_called_with(
            id=plan.stripe_id,
            currency="usd",
            interval="month",
            product={"name": plan.name, "unit_label": "Seats"},
            billing_scheme="per_unit",
            amount=100 * plan.base_price,
        )

    def test_make_stripe_plan_group(self, organization_plan_factory, mocker):
        mocked = mocker.patch("stripe.Plan.create")
        plan = organization_plan_factory.build()
        plan.make_stripe_plan()
        mocked.assert_called_with(
            id=plan.stripe_id,
            currency="usd",
            interval="month",
            product={"name": plan.name, "unit_label": "Seats"},
            billing_scheme="tiered",
            tiers=[
                {"flat_amount": 100 * plan.base_price, "up_to": plan.minimum_users},
                {"unit_amount": 100 * plan.price_per_user, "up_to": "inf"},
            ],
            tiers_mode="graduated",
        )

    @pytest.mark.django_db
    def test_has_available_slots_non_sunlight_plan(self, plan_factory):
        """Non-Sunlight plans always have available slots"""
        plan = plan_factory(slug="professional", wix=False)
        assert plan.has_available_slots() is True

    @pytest.mark.django_db
    def test_has_available_slots_sunlight_no_wix(self, plan_factory):
        """Sunlight plans with wix=False have no limit"""
        plan = plan_factory(slug="sunlight-essential", wix=False)
        assert plan.has_available_slots() is True

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_under_limit(
        self, plan_factory, subscription_factory
    ):
        """Sunlight wix plan under limit has available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 10 active subscriptions (under limit of 15)
        subscription_factory.create_batch(10, plan=sunlight_plan, cancelled=False)

        assert sunlight_plan.has_available_slots() is True

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_at_limit(
        self, plan_factory, subscription_factory
    ):
        """Sunlight wix plan at limit has no available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 15 active subscriptions (at limit)
        subscription_factory.create_batch(15, plan=sunlight_plan, cancelled=False)

        assert sunlight_plan.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_over_limit(
        self, plan_factory, subscription_factory
    ):
        """Sunlight wix plan over limit has no available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 20 active subscriptions (over limit)
        subscription_factory.create_batch(20, plan=sunlight_plan, cancelled=False)

        assert sunlight_plan.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_counts_all_sunlight_variants(
        self, plan_factory, subscription_factory
    ):
        """Limit is shared across all Sunlight plan variants"""
        sunlight_basic = plan_factory(slug="sunlight-essential-monthly", wix=True)
        sunlight_premium = plan_factory(slug="sunlight-enhanced-annual", wix=True)

        # Create 10 subscriptions for basic, 5 for premium (total 15)
        for _ in range(10):
            subscription_factory(plan=sunlight_basic, cancelled=False)
        for _ in range(5):
            subscription_factory(plan=sunlight_premium, cancelled=False)

        # Both plans should show no slots available
        assert sunlight_basic.has_available_slots() is False
        assert sunlight_premium.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_excludes_cancelled(
        self, plan_factory, subscription_factory
    ):
        """Cancelled subscriptions don't count toward limit"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 14 active and 10 cancelled subscriptions
        for _ in range(14):
            subscription_factory(plan=sunlight_plan, cancelled=False)
        for _ in range(10):
            subscription_factory(plan=sunlight_plan, cancelled=True)

        # Should still have slots available (14 < 15)
        assert sunlight_plan.has_available_slots() is True

    def test_is_sunlight_plan_for_regular_sunlight(self, plan_factory):
        """Regular Sunlight plans should be identified as Sunlight plans"""
        plan = plan_factory.build(slug="sunlight-essential")
        assert plan.is_sunlight_plan is True

        plan = plan_factory.build(slug="sunlight-enhanced-annual")
        assert plan.is_sunlight_plan is True

        plan = plan_factory.build(slug="sunlight-enterprise")
        assert plan.is_sunlight_plan is True

    def test_is_sunlight_plan_for_nonprofit_sunlight(self, plan_factory):
        """Nonprofit Sunlight plans should be identified as Sunlight plans"""
        plan = plan_factory.build(slug="sunlight-nonprofit-essential")
        assert plan.is_sunlight_plan is True

        plan = plan_factory.build(slug="sunlight-nonprofit-enhanced-annual")
        assert plan.is_sunlight_plan is True

    def test_is_sunlight_plan_for_non_sunlight(self, plan_factory):
        """Non-Sunlight plans should not be identified as Sunlight plans"""
        plan = plan_factory.build(slug="professional")
        assert plan.is_sunlight_plan is False

        plan = plan_factory.build(slug="organization")
        assert plan.is_sunlight_plan is False

        plan = plan_factory.build(slug="free")
        assert plan.is_sunlight_plan is False

    def test_nonprofit_variant_slug_for_regular_sunlight(self, plan_factory):
        """Regular Sunlight plans should return nonprofit variant slug"""
        plan = plan_factory.build(slug="sunlight-essential")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-essential"

        plan = plan_factory.build(slug="sunlight-enhanced-annual")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-enhanced-annual"

        plan = plan_factory.build(slug="sunlight-enterprise")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-enterprise"

    def test_nonprofit_variant_slug_for_nonprofit_sunlight(self, plan_factory):
        """Nonprofit Sunlight plans should return their own slug"""
        plan = plan_factory.build(slug="sunlight-nonprofit-essential")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-essential"

        plan = plan_factory.build(slug="sunlight-nonprofit-enhanced-annual")
        assert plan.nonprofit_variant_slug == "sunlight-nonprofit-enhanced-annual"

    def test_nonprofit_variant_slug_for_non_sunlight(self, plan_factory):
        """Non-Sunlight plans should return None"""
        plan = plan_factory.build(slug="professional")
        assert plan.nonprofit_variant_slug is None

        plan = plan_factory.build(slug="organization")
        assert plan.nonprofit_variant_slug is None

        plan = plan_factory.build(slug="free")
        assert plan.nonprofit_variant_slug is None
