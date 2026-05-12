# Standard Library
from datetime import date, timedelta
from unittest.mock import patch

# Third Party
import pytest

# Squarelet
from squarelet.organizations.serializers import OrganizationDetailSerializer
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    PlanFactory,
    SubscriptionFactory,
)


class TestGetEntitlements:
    """Tests for OrganizationDetailSerializer.get_entitlements()"""

    @pytest.mark.django_db
    def test_single_plan_returns_one_row(self, organization_factory, client):
        """Single plan with one entitlement returns exactly one row."""
        org = organization_factory()
        entitlement = EntitlementFactory(client=client)
        plan = PlanFactory()
        plan.entitlements.add(entitlement)
        update_date = date.today()
        SubscriptionFactory(organization=org, plan=plan, update_on=update_date)

        with patch(
            "squarelet.organizations.serializers.OrganizationDetailSerializer"
            ".get_card",
            return_value="",
        ):
            serializer = OrganizationDetailSerializer(
                org, context={"client": client}
            )
            entitlements = serializer.data["entitlements"]

        assert len(entitlements) == 1
        assert entitlements[0]["slug"] == entitlement.slug
        assert entitlements[0]["update_on"] == update_date

    @pytest.mark.django_db
    def test_two_plans_same_entitlement_one_row_earliest_date(
        self, organization_factory, client
    ):
        """Two plans granting the same entitlement produce one row with the
        earliest update_on date."""
        org = organization_factory()
        entitlement = EntitlementFactory(client=client)
        plan_a = PlanFactory()
        plan_b = PlanFactory()
        plan_a.entitlements.add(entitlement)
        plan_b.entitlements.add(entitlement)

        earlier = date.today() - timedelta(days=5)
        later = date.today()
        SubscriptionFactory(organization=org, plan=plan_a, update_on=earlier)
        SubscriptionFactory(organization=org, plan=plan_b, update_on=later)

        with patch(
            "squarelet.organizations.serializers.OrganizationDetailSerializer"
            ".get_card",
            return_value="",
        ):
            serializer = OrganizationDetailSerializer(
                org, context={"client": client}
            )
            entitlements = serializer.data["entitlements"]

        assert len(entitlements) == 1
        assert entitlements[0]["update_on"] == earlier

    @pytest.mark.django_db
    def test_two_plans_different_entitlements_two_rows(
        self, organization_factory, client
    ):
        """Two plans granting different entitlements produce two distinct rows."""
        org = organization_factory()
        entitlement_a = EntitlementFactory(client=client)
        entitlement_b = EntitlementFactory(client=client)
        plan_a = PlanFactory()
        plan_b = PlanFactory()
        plan_a.entitlements.add(entitlement_a)
        plan_b.entitlements.add(entitlement_b)

        SubscriptionFactory(organization=org, plan=plan_a)
        SubscriptionFactory(organization=org, plan=plan_b)

        with patch(
            "squarelet.organizations.serializers.OrganizationDetailSerializer"
            ".get_card",
            return_value="",
        ):
            serializer = OrganizationDetailSerializer(
                org, context={"client": client}
            )
            entitlements = serializer.data["entitlements"]

        slugs = {e["slug"] for e in entitlements}
        assert len(entitlements) == 2
        assert entitlement_a.slug in slugs
        assert entitlement_b.slug in slugs

    @pytest.mark.django_db
    def test_no_client_returns_empty(self, organization_factory):
        """Without a client in context, entitlements is empty."""
        org = organization_factory()
        with patch(
            "squarelet.organizations.serializers.OrganizationDetailSerializer"
            ".get_card",
            return_value="",
        ):
            serializer = OrganizationDetailSerializer(org, context={})
            assert serializer.data["entitlements"] == []

    @pytest.mark.django_db
    def test_cancelled_subscription_excluded_from_update_on(
        self, organization_factory, client
    ):
        """Cancelled subscriptions are excluded from the update_on subquery."""
        org = organization_factory()
        entitlement = EntitlementFactory(client=client)
        plan = PlanFactory()
        plan.entitlements.add(entitlement)
        SubscriptionFactory(
            organization=org, plan=plan, update_on=date.today(), cancelled=True
        )

        with patch(
            "squarelet.organizations.serializers.OrganizationDetailSerializer"
            ".get_card",
            return_value="",
        ):
            serializer = OrganizationDetailSerializer(
                org, context={"client": client}
            )
            entitlements = serializer.data["entitlements"]

        # The subscription exists but is cancelled; update_on subquery should
        # return None (no active subscription) while the entitlement row still
        # appears because the plan is linked to the org via the cancelled sub.
        # (Cancelled subs remain in the M2M until restore_organization deletes
        # them, so the entitlement is still visible with update_on=None.)
        assert len(entitlements) == 1
        assert entitlements[0]["update_on"] is None
