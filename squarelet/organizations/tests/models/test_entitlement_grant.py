# Django
from django.db.models import QuerySet

# Third Party
import pytest

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory
from squarelet.organizations.models import Entitlement
from squarelet.organizations.tests.factories import (
    EntitlementFactory,
    EntitlementGrantFactory,
    OrganizationFactory,
    PlanFactory,
    SubscriptionFactory,
)


class TestEntitlementGrant:
    """Unit tests for EntitlementGrant.matches"""

    @pytest.mark.django_db()
    def test_grant_matches_explicit_org(self):
        """
        Entitlements may be granted to individual orgs.
        """
        org = OrganizationFactory()
        other_org = OrganizationFactory()
        grant = EntitlementGrantFactory(organizations=[org])
        assert grant.matches(org) is True
        assert grant.matches(other_org) is False

    @pytest.mark.django_db()
    def test_grant_no_criteria_no_explicit_does_not_match(self):
        """
        We need to be precise with our entitlement grants.
        We don't do broad entitlement grants—orgs _must_ meet the criteria.
        """
        org = OrganizationFactory()
        grant = EntitlementGrantFactory()
        assert grant.matches(org) is False

    @pytest.mark.django_db()
    def test_grant_matches_verified_org(self):
        """
        We can give entitlements to all verified organizations.
        """
        verified = OrganizationFactory(verified_journalist=True)
        unverified = OrganizationFactory(verified_journalist=False)
        grant = EntitlementGrantFactory(require_verified=True)
        assert grant.matches(verified) is True
        assert grant.matches(unverified) is False

    @pytest.mark.django_db()
    def test_grant_matches_active_subscription_org(self):
        """
        We can grant entitlements to our active subscribers.
        """
        subscribed = OrganizationFactory()
        SubscriptionFactory(organization=subscribed)
        unsubscribed = OrganizationFactory()
        grant = EntitlementGrantFactory(require_active_subscription=True)
        assert grant.matches(subscribed) is True
        assert grant.matches(unsubscribed) is False

    @pytest.mark.django_db()
    def test_grant_requires_all_checked_criteria(self):
        """
        Grant rules are combined with "AND" logic.
        """
        verified_and_sub = OrganizationFactory(verified_journalist=True)
        SubscriptionFactory(organization=verified_and_sub)
        verified_only = OrganizationFactory(verified_journalist=True)
        sub_only = OrganizationFactory(verified_journalist=False)
        SubscriptionFactory(organization=sub_only)

        grant = EntitlementGrantFactory(
            require_verified=True, require_active_subscription=True
        )
        assert grant.matches(verified_and_sub) is True
        assert grant.matches(verified_only) is False
        assert grant.matches(sub_only) is False

    @pytest.mark.django_db()
    def test_grant_explicit_overrides_criteria(self):
        """
        Granting an entitlement to an org ignores our rules.
        """
        unverified = OrganizationFactory(verified_journalist=False)
        grant = EntitlementGrantFactory(
            organizations=[unverified], require_verified=True
        )
        assert grant.matches(unverified) is True

    @pytest.mark.django_db()
    def test_inactive_grant_does_not_match(self):
        """
        When a grant is inactive, nobody gets it.
        """
        org = OrganizationFactory(verified_journalist=True)
        grant = EntitlementGrantFactory(
            organizations=[org], require_verified=True, active=False
        )
        assert grant.matches(org) is False

    @pytest.mark.django_db()
    def test_grant_for_individuals_only(self):
        """
        Entitlements may just be granted to individuals.
        """
        individual = OrganizationFactory(individual=True, verified_journalist=True)
        group = OrganizationFactory(individual=False, verified_journalist=True)
        grant = EntitlementGrantFactory(
            require_verified=True, for_individuals=True, for_groups=False
        )
        assert grant.matches(individual) is True
        assert grant.matches(group) is False

    @pytest.mark.django_db()
    def test_grant_for_groups_only(self):
        """
        Entitlements may also be granted to groups.
        """
        individual = OrganizationFactory(individual=True, verified_journalist=True)
        group = OrganizationFactory(individual=False, verified_journalist=True)
        grant = EntitlementGrantFactory(
            require_verified=True, for_individuals=False, for_groups=True
        )
        assert grant.matches(individual) is False
        assert grant.matches(group) is True

    @pytest.mark.django_db()
    def test_grant_for_both_by_default(self):
        """
        Entitlements may be granted to individuals _and_ groups.
        """
        individual = OrganizationFactory(individual=True, verified_journalist=True)
        group = OrganizationFactory(individual=False, verified_journalist=True)
        grant = EntitlementGrantFactory(require_verified=True)
        assert grant.matches(individual) is True
        assert grant.matches(group) is True

    @pytest.mark.django_db()
    def test_org_type_filter_applies_to_explicit_grants(self):
        """An individual explicitly listed on a groups-only grant is still excluded."""
        individual = OrganizationFactory(individual=True)
        grant = EntitlementGrantFactory(
            organizations=[individual], for_individuals=False, for_groups=True
        )
        assert grant.matches(individual) is False


class TestMatchingOrganizations:
    """Tests for EntitlementGrant.matching_organizations"""

    @pytest.mark.django_db()
    def test_explicit_membership_only(self):
        org = OrganizationFactory()
        other = OrganizationFactory()
        grant = EntitlementGrantFactory(organizations=[org])
        matched = list(grant.matching_organizations())
        assert org in matched
        assert other not in matched

    @pytest.mark.django_db()
    def test_verified_rule(self):
        verified = OrganizationFactory(verified_journalist=True)
        unverified = OrganizationFactory(verified_journalist=False)
        grant = EntitlementGrantFactory(require_verified=True)
        matched = list(grant.matching_organizations())
        assert verified in matched
        assert unverified not in matched

    @pytest.mark.django_db()
    def test_active_subscription_rule(self):
        subscribed = OrganizationFactory()
        SubscriptionFactory(organization=subscribed)
        unsubscribed = OrganizationFactory()
        grant = EntitlementGrantFactory(require_active_subscription=True)
        matched = list(grant.matching_organizations())
        assert subscribed in matched
        assert unsubscribed not in matched

    @pytest.mark.django_db()
    def test_org_type_filter(self):
        individual = OrganizationFactory(individual=True, verified_journalist=True)
        group = OrganizationFactory(individual=False, verified_journalist=True)
        grant = EntitlementGrantFactory(
            require_verified=True, for_individuals=False, for_groups=True
        )
        matched = list(grant.matching_organizations())
        assert group in matched
        assert individual not in matched

    @pytest.mark.django_db()
    def test_inactive_grant_matches_nobody(self):
        org = OrganizationFactory(verified_journalist=True)
        grant = EntitlementGrantFactory(
            organizations=[org], require_verified=True, active=False
        )
        assert not list(grant.matching_organizations())

    @pytest.mark.django_db()
    def test_explicit_membership_respects_org_type_filter(self):
        """An individual explicitly listed on a groups-only grant should not match."""
        individual = OrganizationFactory(individual=True)
        grant = EntitlementGrantFactory(
            organizations=[individual], for_individuals=False, for_groups=True
        )
        assert individual not in grant.matching_organizations()

    @pytest.mark.django_db()
    def test_both_rules_and_logic(self):
        verified_and_sub = OrganizationFactory(verified_journalist=True)
        SubscriptionFactory(organization=verified_and_sub)
        verified_only = OrganizationFactory(verified_journalist=True)
        grant = EntitlementGrantFactory(
            require_verified=True, require_active_subscription=True
        )
        matched = list(grant.matching_organizations())
        assert verified_and_sub in matched
        assert verified_only not in matched


class TestEntitlementForOrganization:
    """Tests for Entitlement.objects.for_organization manager method"""

    @pytest.mark.django_db()
    def test_includes_plan_entitlements(self):
        plan = PlanFactory()
        entitlement = EntitlementFactory()
        entitlement.plans.set([plan])
        org = OrganizationFactory(plans=[plan])
        assert entitlement in Entitlement.objects.for_organization(org)

    @pytest.mark.django_db()
    def test_includes_explicit_grant_entitlements(self):
        org = OrganizationFactory()
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(organizations=[org], entitlements=[entitlement])
        assert entitlement in Entitlement.objects.for_organization(org)

    @pytest.mark.django_db()
    def test_dedupes_plan_and_grant(self):
        plan = PlanFactory()
        entitlement = EntitlementFactory()
        entitlement.plans.set([plan])
        org = OrganizationFactory(plans=[plan])
        EntitlementGrantFactory(organizations=[org], entitlements=[entitlement])
        qs = Entitlement.objects.for_organization(org)
        assert qs.filter(pk=entitlement.pk).count() == 1

    @pytest.mark.django_db()
    def test_filters_by_client(self):
        client1 = ClientFactory()
        client2 = ClientFactory()
        e1 = EntitlementFactory(client=client1)
        e2 = EntitlementFactory(client=client2)
        org = OrganizationFactory()
        EntitlementGrantFactory(organizations=[org], entitlements=[e1, e2])

        result = Entitlement.objects.for_organization(org, client=client1)
        assert e1 in result
        assert e2 not in result

    @pytest.mark.django_db()
    def test_verified_rule_matches(self):
        verified = OrganizationFactory(verified_journalist=True)
        unverified = OrganizationFactory(verified_journalist=False)
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(require_verified=True, entitlements=[entitlement])
        assert entitlement in Entitlement.objects.for_organization(verified)
        assert entitlement not in Entitlement.objects.for_organization(unverified)

    @pytest.mark.django_db()
    def test_active_subscription_rule_matches(self):
        subscribed = OrganizationFactory()
        SubscriptionFactory(organization=subscribed)
        unsubscribed = OrganizationFactory()
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(
            require_active_subscription=True, entitlements=[entitlement]
        )
        assert entitlement in Entitlement.objects.for_organization(subscribed)
        assert entitlement not in Entitlement.objects.for_organization(unsubscribed)

    @pytest.mark.django_db()
    def test_both_rules_require_both_at_db_level(self):
        verified_and_sub = OrganizationFactory(verified_journalist=True)
        SubscriptionFactory(organization=verified_and_sub)
        verified_only = OrganizationFactory(verified_journalist=True)
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(
            require_verified=True,
            require_active_subscription=True,
            entitlements=[entitlement],
        )
        assert entitlement in Entitlement.objects.for_organization(verified_and_sub)
        assert entitlement not in Entitlement.objects.for_organization(verified_only)

    @pytest.mark.django_db()
    def test_explicit_membership_bypasses_criteria_at_db_level(self):
        unverified = OrganizationFactory(verified_journalist=False)
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(
            organizations=[unverified],
            require_verified=True,
            entitlements=[entitlement],
        )
        assert entitlement in Entitlement.objects.for_organization(unverified)

    @pytest.mark.django_db()
    def test_excludes_inactive_grants(self):
        org = OrganizationFactory()
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(
            organizations=[org], entitlements=[entitlement], active=False
        )
        assert entitlement not in Entitlement.objects.for_organization(org)

    @pytest.mark.django_db()
    def test_excludes_grants_for_wrong_org_type_at_db_level(self):
        individual = OrganizationFactory(individual=True, verified_journalist=True)
        group = OrganizationFactory(individual=False, verified_journalist=True)
        entitlement = EntitlementFactory()
        EntitlementGrantFactory(
            require_verified=True,
            for_individuals=False,
            for_groups=True,
            entitlements=[entitlement],
        )
        assert entitlement in Entitlement.objects.for_organization(group)
        assert entitlement not in Entitlement.objects.for_organization(individual)

    @pytest.mark.django_db()
    def test_returns_queryset_instance(self):
        org = OrganizationFactory()
        result = Entitlement.objects.for_organization(org)
        assert isinstance(result, QuerySet)
        # Chainable
        assert not list(result.values_list("pk", flat=True))
