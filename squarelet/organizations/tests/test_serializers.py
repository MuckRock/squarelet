# Standard Library
from datetime import date, timedelta

# Third Party
import pytest
from freezegun import freeze_time

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory
from squarelet.organizations.serializers import (
    OrganizationDetailSerializer,
    _default_update_on,
)
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    EntitlementGrantFactory,
    OrganizationFactory,
    PlanFactory,
    SubscriptionFactory,
)


class TestSerializerEntitlements:
    """Integration tests for OrganizationDetailSerializer.get_entitlements"""

    @pytest.mark.django_db()
    def test_serializer_returns_grant_entitlements(self):
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        org = OrganizationFactory()
        EntitlementGrantFactory(organizations=[org], entitlements=[entitlement])

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = serializer.get_entitlements(org)
        slugs = [e["slug"] for e in rows]
        assert entitlement.slug in slugs

    @pytest.mark.django_db()
    @freeze_time("2026-06-23")
    def test_grant_only_org_uses_first_of_next_month(self):
        """Grant entitlement on org with no subscription uses first-of-next-month."""
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        org = OrganizationFactory()  # update_on=None
        EntitlementGrantFactory(organizations=[org], entitlements=[entitlement])

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = [
            e for e in serializer.get_entitlements(org) if e["slug"] == entitlement.slug
        ]
        assert len(rows) == 1
        assert rows[0]["update_on"] == date(2026, 7, 1)

    @pytest.mark.django_db()
    @freeze_time("2026-06-23")
    def test_grant_only_org_top_level_update_on_is_first_of_next_month(self):
        """Top-level update_on for grant-only org is first of next month."""
        org = OrganizationFactory()  # update_on=None
        EntitlementGrantFactory(organizations=[org])

        serializer = OrganizationDetailSerializer(org, context={})
        assert serializer.get_update_on(org) == date(2026, 7, 1)

    @pytest.mark.django_db()
    def test_grant_and_subscription_org_uses_org_update_on(self):
        """When org has both a grant and a subscription, org.update_on is used."""
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        org_update_on = date(2026, 8, 15)
        org = OrganizationFactory(update_on=org_update_on)
        EntitlementGrantFactory(organizations=[org], entitlements=[entitlement])

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = [
            e for e in serializer.get_entitlements(org) if e["slug"] == entitlement.slug
        ]
        assert len(rows) == 1
        assert rows[0]["update_on"] == org_update_on

    @pytest.mark.django_db()
    def test_serializer_update_on_uses_org_anchor(self):
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        plan = PlanFactory()
        entitlement.plans.set([plan])
        org_update_on = date.today() + timedelta(days=7)
        org = OrganizationFactory(update_on=org_update_on)
        SubscriptionFactory(organization=org, plan=plan)

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = [
            e for e in serializer.get_entitlements(org) if e["slug"] == entitlement.slug
        ]
        assert len(rows) == 1
        assert rows[0]["update_on"] == org_update_on

    @pytest.mark.django_db()
    def test_serializer_returns_empty_without_client(self):
        org = OrganizationFactory()
        serializer = OrganizationDetailSerializer(org, context={})
        assert not serializer.get_entitlements(org)


class TestSerializerProfile:
    """Tests for url and location fields on OrganizationDetailSerializer"""

    @pytest.fixture(autouse=True)
    def _mock_card(self, mocker):
        # Avoid hitting Stripe when serializing the card field
        mocker.patch(
            "squarelet.organizations.models.payment.Customer.card_display",
            new_callable=mocker.PropertyMock,
            return_value=None,
        )

    @pytest.mark.django_db()
    def test_serializer_includes_urls(self):
        org = OrganizationFactory()
        org.urls.create(url="https://example.org")
        org.urls.create(url="https://example.org/blog")

        data = OrganizationDetailSerializer(org, context={}).data
        assert sorted(data["urls"]) == [
            "https://example.org",
            "https://example.org/blog",
        ]

    @pytest.mark.django_db()
    def test_serializer_urls_empty_when_none(self):
        org = OrganizationFactory()
        data = OrganizationDetailSerializer(org, context={}).data
        assert data["urls"] == []

    @pytest.mark.django_db()
    def test_serializer_includes_location(self):
        org = OrganizationFactory(city="Boston", state="MA", country="US")
        data = OrganizationDetailSerializer(org, context={}).data
        assert data["location"] == {
            "city": "Boston",
            "state": "MA",
            "country": "US",
        }

    @pytest.mark.django_db()
    def test_serializer_location_null_when_unset(self):
        org = OrganizationFactory()
        data = OrganizationDetailSerializer(org, context={}).data
        assert data["location"] is None

    @pytest.mark.django_db()
    def test_serializer_location_partial(self):
        org = OrganizationFactory(country="US")
        data = OrganizationDetailSerializer(org, context={}).data
        assert data["location"] == {"city": "", "state": "", "country": "US"}


class TestDefaultUpdateOn:
    @freeze_time("2026-06-23")
    def test_returns_first_of_next_month(self):
        assert _default_update_on() == date(2026, 7, 1)

    @freeze_time("2026-12-15")
    def test_wraps_december_to_january(self):
        assert _default_update_on() == date(2027, 1, 1)
