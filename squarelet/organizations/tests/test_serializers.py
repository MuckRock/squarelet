# Django
from django.utils import timezone

# Standard Library
from datetime import timedelta

# Third Party
import pytest

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory
from squarelet.organizations.serializers import OrganizationDetailSerializer
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
    def test_serializer_returns_grant_update_on_when_no_subscription(self):
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        org = OrganizationFactory()
        update_on = timezone.now().date() + timedelta(days=14)
        EntitlementGrantFactory(
            organizations=[org], entitlements=[entitlement], update_on=update_on
        )

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = [
            e for e in serializer.get_entitlements(org) if e["slug"] == entitlement.slug
        ]
        assert len(rows) == 1
        assert rows[0]["update_on"] == update_on

    @pytest.mark.django_db()
    def test_serializer_picks_soonest_grant_update_on(self):
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        org = OrganizationFactory()
        sooner = timezone.now().date() + timedelta(days=7)
        later = timezone.now().date() + timedelta(days=30)
        EntitlementGrantFactory(
            organizations=[org], entitlements=[entitlement], update_on=later
        )
        EntitlementGrantFactory(
            organizations=[org], entitlements=[entitlement], update_on=sooner
        )

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = [
            e for e in serializer.get_entitlements(org) if e["slug"] == entitlement.slug
        ]
        assert len(rows) == 1
        assert rows[0]["update_on"] == sooner

    @pytest.mark.django_db()
    def test_serializer_update_on_uses_subscription(self):
        client = ClientFactory()
        entitlement = EntitlementFactory(client=client)
        plan = PlanFactory()
        entitlement.plans.set([plan])
        org = OrganizationFactory()
        sub_update_on = timezone.now().date() + timedelta(days=7)
        SubscriptionFactory(organization=org, plan=plan, update_on=sub_update_on)

        serializer = OrganizationDetailSerializer(org, context={"client": client})
        rows = [
            e for e in serializer.get_entitlements(org) if e["slug"] == entitlement.slug
        ]
        assert len(rows) == 1
        assert rows[0]["update_on"] == sub_update_on

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
