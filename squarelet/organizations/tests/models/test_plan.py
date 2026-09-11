# Django
from django.test import override_settings

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models.payment import (
    consolidate_plan_benefits,
    format_benefits,
    sum_resources,
)
from squarelet.organizations.tests.factories import EntitlementFactory

# pylint: disable=too-many-public-methods


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

    @pytest.mark.django_db
    def test_make_stripe_plan_creates_a_price_row(
        self, professional_plan_factory, mocker
    ):
        """A new plan gets a PlanPrice, not a legacy Stripe Plan object."""
        mocker.patch(
            "squarelet.organizations.models.payment.PlanPrice.ensure_stripe_price"
        )
        # PlanFactory mutes the post_save signal, so call the method the
        # signal calls rather than relying on the wiring.
        plan = professional_plan_factory()
        plan.make_stripe_plan()

        price = plan.prices.get()

        assert price.amount == 100 * plan.base_price
        assert (price.label, price.code, price.interval) == (
            "standard",
            "",
            "monthly",
        )

    @pytest.mark.django_db
    def test_an_annual_plan_gets_an_annual_price(self, plan_factory, mocker):
        mocker.patch(
            "squarelet.organizations.models.payment.PlanPrice.ensure_stripe_price"
        )
        plan = plan_factory(name="Yearly", base_price=120, annual=True)
        plan.make_stripe_plan()

        assert plan.prices.get().interval == "annual"

    @pytest.mark.django_db
    def test_a_free_plan_still_gets_a_price(self, plan_factory, mocker):
        """Zero, and no Stripe Price behind it.

        Every plan having a price is what lets `plan_price` become non-null
        in step 3d; `ensure_stripe_price` is what declines to create a
        Stripe object for a zero amount.
        """
        ensure = mocker.patch(
            "squarelet.organizations.models.payment.PlanPrice.ensure_stripe_price"
        )
        plan = plan_factory(name="Free Tier", base_price=0, price_per_user=0)
        plan.make_stripe_plan()

        assert plan.prices.get().amount == 0
        ensure.assert_called_once()

    @pytest.mark.django_db
    def test_a_per_user_rate_is_reported(self, organization_plan_factory, mocker):
        """The consolidated model sells the extra units as a pack instead.

        A flat Price cannot express the second tier the legacy Price used,
        so dropping the rate silently would be a quiet mispricing.
        """
        mocker.patch(
            "squarelet.organizations.models.payment.PlanPrice.ensure_stripe_price"
        )
        warning = mocker.patch("squarelet.organizations.models.payment.logger.warning")

        organization_plan_factory().make_stripe_plan()

        assert warning.called


class TestArchivingAPlan:
    """Stripe has no delete for a Price - only `active: false`."""

    @pytest.mark.django_db
    def test_archive_stripe_plan_deactivates_the_prices(
        self, plan_factory, plan_price_factory, mocker
    ):
        """Stripe has no delete for a Price - only `active: false`."""
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_plan_service.return_value
        plan = plan_factory(name="Retiring", base_price=0)
        plan.prices.all().delete()
        price = plan_price_factory(plan=plan, stripe_price_id="price_1")

        plan.archive_stripe_plan()

        service.archive_price.assert_called_once_with("price_1")
        price.refresh_from_db()
        assert not price.active

    @pytest.mark.django_db
    def test_the_product_survives_while_a_price_remains(
        self, plan_factory, plan_price_factory, mocker
    ):
        """Other variants still hang off it."""
        service = mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_plan_service.return_value
        plan = plan_factory(name="Still Priced", base_price=0)
        plan.prices.all().delete()
        plan.stripe_product_id = "prod_1"
        plan.save()
        plan_price_factory(plan=plan, stripe_price_id="price_1")

        plan.archive_stripe_plan()

        service.archive_product.assert_not_called()

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
        self, plan_factory, subscription_item_factory
    ):
        """Sunlight wix plan under limit has available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 10 active subscriptions (under limit of 15)
        subscription_item_factory.create_batch(
            10, plan=sunlight_plan, subscription__cancelled=False
        )

        assert sunlight_plan.has_available_slots() is True

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_at_limit(
        self, plan_factory, subscription_item_factory
    ):
        """Sunlight wix plan at limit has no available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 15 active subscriptions (at limit)
        subscription_item_factory.create_batch(
            15, plan=sunlight_plan, subscription__cancelled=False
        )

        assert sunlight_plan.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_sunlight_over_limit(
        self, plan_factory, subscription_item_factory
    ):
        """Sunlight wix plan over limit has no available slots"""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 20 active subscriptions (over limit)
        subscription_item_factory.create_batch(
            20, plan=sunlight_plan, subscription__cancelled=False
        )

        assert sunlight_plan.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_counts_all_sunlight_variants(
        self, plan_factory, subscription_item_factory
    ):
        """Limit is shared across all Sunlight plan variants"""
        sunlight_basic = plan_factory(slug="sunlight-essential-monthly", wix=True)
        sunlight_premium = plan_factory(slug="sunlight-enhanced-annual", wix=True)

        # Create 10 subscriptions for basic, 5 for premium (total 15)
        for _ in range(10):
            subscription_item_factory(
                plan=sunlight_basic, subscription__cancelled=False
            )
        for _ in range(5):
            subscription_item_factory(
                plan=sunlight_premium, subscription__cancelled=False
            )

        # Both plans should show no slots available
        assert sunlight_basic.has_available_slots() is False
        assert sunlight_premium.has_available_slots() is False

    @override_settings(MAX_SUNLIGHT_SUBSCRIPTIONS=15)
    @pytest.mark.django_db
    def test_has_available_slots_includes_cancelled(
        self, plan_factory, subscription_item_factory
    ):
        """cancelled=True means pending cancellation — counts toward limit."""
        sunlight_plan = plan_factory(slug="sunlight-essential-monthly", wix=True)

        # Create 10 active and 5 pending-cancellation subscriptions (total 15 = limit)
        for _ in range(10):
            subscription_item_factory(plan=sunlight_plan, subscription__cancelled=False)
        for _ in range(5):
            subscription_item_factory(plan=sunlight_plan, subscription__cancelled=True)

        # 15 total subscriptions = at the limit, no slots available
        assert sunlight_plan.has_available_slots() is False

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

    @pytest.mark.django_db()
    def test_get_benefits_no_entitlements(self, plan_factory):
        """Falls back to the plan's own benefits when it has no entitlements"""
        plan = plan_factory(benefits=["Plan benefit A", "Plan benefit B"])
        assert plan.get_benefits() == ["Plan benefit A", "Plan benefit B"]

    @pytest.mark.django_db()
    def test_get_benefits_entitlements_without_benefits(self, plan_factory):
        """Entitlements with empty benefits don't override the plan's benefits"""
        plan = plan_factory(benefits=["Plan benefit"])
        plan.entitlements.set([EntitlementFactory(benefits=[])])
        assert plan.get_benefits() == ["Plan benefit"]

    @pytest.mark.django_db()
    def test_get_benefits_entitlement_overrides_plan(self, plan_factory):
        """A single entitlement's benefits override the plan's own benefits"""
        plan = plan_factory(benefits=["Plan benefit"])
        plan.entitlements.set([EntitlementFactory(benefits=["Entitlement benefit"])])
        assert plan.get_benefits() == ["Entitlement benefit"]

    @pytest.mark.django_db()
    def test_get_benefits_dedupes_across_entitlements(self, plan_factory):
        """The union of entitlement benefits is deduplicated, preserving order"""
        plan = plan_factory(benefits=["Plan benefit"])
        # Names control slug ordering (Entitlement.Meta.ordering = ("slug",))
        plan.entitlements.set(
            [
                EntitlementFactory(name="A benefit", benefits=["Shared", "First only"]),
                EntitlementFactory(
                    name="B benefit", benefits=["Shared", "Second only"]
                ),
            ]
        )
        assert plan.get_benefits() == ["Shared", "First only", "Second only"]

    @pytest.mark.django_db()
    def test_get_resources_sums_across_entitlements(self, plan_factory):
        """A plan's resources are the aggregate of its entitlements' resources"""
        plan = plan_factory()
        plan.entitlements.set(
            [
                EntitlementFactory(
                    name="A", resources={"base_requests": 20, "feature_level": 1}
                ),
                EntitlementFactory(
                    name="B", resources={"base_requests": 50, "feature_level": 2}
                ),
            ]
        )
        assert plan.get_resources() == {"base_requests": 70, "feature_level": 2}

    @pytest.mark.django_db()
    def test_get_benefits_fills_in_quantities(self, plan_factory):
        """Benefit strings are formatted with the plan's aggregated resources"""
        plan = plan_factory()
        plan.entitlements.set(
            [
                EntitlementFactory(
                    name="A",
                    benefits=["{base_requests} free requests each month"],
                    resources={"base_requests": 20},
                ),
                EntitlementFactory(
                    name="B",
                    benefits=["{base_requests} free requests each month"],
                    resources={"base_requests": 50},
                ),
            ]
        )
        assert plan.get_benefits() == ["70 free requests each month"]

    @pytest.mark.django_db()
    def test_get_benefit_templates_are_unformatted(self, plan_factory):
        """Templates are returned as authored, for callers that format later"""
        plan = plan_factory()
        plan.entitlements.set(
            [
                EntitlementFactory(
                    benefits=["{base_requests} free requests each month"],
                    resources={"base_requests": 20},
                )
            ]
        )
        assert plan.get_benefit_templates() == [
            "{base_requests} free requests each month"
        ]


class TestConsolidatePlanBenefits:
    """Unit tests for consolidate_plan_benefits"""

    def test_empty(self):
        """No plans yields no benefits"""
        assert not consolidate_plan_benefits([])

    @pytest.mark.django_db()
    def test_dedupes_benefits(self, plan_factory):
        """Benefit copy shared by two plans is only listed once"""
        plan_a = plan_factory(name="Plan A", benefits=["Shared", "A only"])
        plan_b = plan_factory(name="Plan B", benefits=["Shared", "B only"])

        assert consolidate_plan_benefits([plan_a, plan_b]) == [
            "Shared",
            "A only",
            "B only",
        ]

    @pytest.mark.django_db()
    def test_reflects_entitlement_override(self, plan_factory):
        """Entitlement benefits override plan benefits in the consolidated list"""
        plan = plan_factory(benefits=["Plan benefit"])
        plan.entitlements.set([EntitlementFactory(benefits=["Entitlement benefit"])])

        assert consolidate_plan_benefits([plan]) == ["Entitlement benefit"]

    @pytest.mark.django_db()
    def test_sums_quantities(self, plan_factory):
        """Two plans granting the same benefit show the combined quantity"""
        benefits = ["{base_requests} free requests each month"]
        plan_a = plan_factory(name="Plan A")
        plan_a.entitlements.set(
            [
                EntitlementFactory(
                    name="A", benefits=benefits, resources={"base_requests": 50}
                )
            ]
        )
        plan_b = plan_factory(name="Plan B")
        plan_b.entitlements.set(
            [
                EntitlementFactory(
                    name="B", benefits=benefits, resources={"base_requests": 10}
                )
            ]
        )

        assert consolidate_plan_benefits([plan_a, plan_b]) == [
            "60 free requests each month"
        ]


class TestSumResources:
    """Unit tests for sum_resources"""

    def test_empty(self):
        assert not sum_resources([])

    def test_sums_quantities(self):
        assert sum_resources([{"requests": 20}, {"requests": 50}]) == {"requests": 70}

    def test_unions_keys(self):
        assert sum_resources([{"a": 1}, {"b": 2}]) == {"a": 1, "b": 2}

    def test_ors_flags(self):
        assert sum_resources([{"proxy": False}, {"proxy": True}]) == {"proxy": True}

    def test_takes_max_of_tiers(self):
        """Tier and threshold values describe a level, not a quantity"""
        assert sum_resources(
            [
                {"feature_level": 2, "minimum_users": 5},
                {"feature_level": 1, "minimum_users": 1},
            ]
        ) == {"feature_level": 2, "minimum_users": 5}

    def test_keeps_first_of_incompatible_values(self):
        assert sum_resources([{"tier": "pro"}, {"tier": "basic"}]) == {"tier": "pro"}

    def test_ignores_empty_resources(self):
        assert sum_resources([{}, None, {"requests": 5}]) == {"requests": 5}


class TestFormatBenefits:
    """Unit tests for format_benefits"""

    def test_fills_in_named_arguments(self):
        assert format_benefits(
            ["{requests} requests, {pages} pages"], {"requests": 50, "pages": 10}
        ) == ["50 requests, 10 pages"]

    def test_supports_format_specs(self):
        """Format specs let benefit copy control number presentation"""
        assert format_benefits(["{pages:,} pages"], {"pages": 12000}) == [
            "12,000 pages"
        ]

    def test_leaves_plain_strings_alone(self):
        assert format_benefits(["Access to Slack community"], {}) == [
            "Access to Slack community"
        ]

    def test_falls_back_when_resource_is_missing(self):
        """An unresolvable placeholder shouldn't blow up the page"""
        assert format_benefits(["{requests} requests"], {}) == ["{requests} requests"]

    def test_falls_back_on_malformed_template(self):
        assert format_benefits(["100% of {"], {}) == ["100% of {"]
