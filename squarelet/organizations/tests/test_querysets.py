# Django
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

# Standard Library
from uuid import uuid4

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import Membership, Organization, Subscription
from squarelet.organizations.tests.factories import (
    ChargeFactory,
    MembershipFactory,
    OrganizationFactory,
    PlanFactory,
    SubscriptionFactory,
)
from squarelet.users.tests.factories import UserFactory


class TestOrganizationQuerySet(TestCase):
    """Unit tests for Organization queryset"""

    @pytest.mark.django_db
    def test_get_viewable_staff_user(self):
        """Staff users can view all organizations"""
        staff_user = UserFactory(is_staff=True)
        private_org = OrganizationFactory(private=True, verified_journalist=False)
        public_org = OrganizationFactory(private=False, verified_journalist=True)

        viewable = Organization.objects.get_viewable(staff_user)
        assert private_org in viewable
        assert public_org in viewable
        assert viewable.count() >= 2

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_public_verified(self):
        """Authenticated users can view public, verified orgs"""
        user = UserFactory()
        public_verified_org = OrganizationFactory(
            private=False, verified_journalist=True
        )
        private_org = OrganizationFactory(private=True, verified_journalist=True)
        public_unverified_org = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_verified_org in viewable
        assert private_org not in viewable
        assert public_unverified_org not in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_public_with_charges(self):
        """Authenticated users can view public orgs with charges"""
        user = UserFactory()
        public_org_with_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )
        ChargeFactory(organization=public_org_with_charges)
        public_org_without_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_charges in viewable
        assert public_org_without_charges not in viewable

    @pytest.mark.django_db
    def test_get_viewable_authenticated_user_member_of_private_org(self):
        """Authenticated users can view private orgs they are members of"""
        user = UserFactory()
        private_org = OrganizationFactory(private=True, verified_journalist=False)
        MembershipFactory(user=user, organization=private_org)
        other_private_org = OrganizationFactory(private=True, verified_journalist=False)

        viewable = Organization.objects.get_viewable(user)
        assert private_org in viewable
        assert other_private_org not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous_user_public_verified(self):
        """Anonymous users can only view public verified journalist orgs"""
        user = AnonymousUser()
        public_verified_org = OrganizationFactory(
            private=False, verified_journalist=True
        )
        private_verified_org = OrganizationFactory(
            private=True, verified_journalist=True
        )
        public_unverified_org = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_verified_org in viewable
        assert private_verified_org not in viewable
        assert public_unverified_org not in viewable

    @pytest.mark.django_db
    def test_get_viewable_anonymous_user_public_with_charges(self):
        """Anonymous users can view public orgs with charges"""
        user = AnonymousUser()
        public_org_with_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )
        ChargeFactory(organization=public_org_with_charges)
        public_org_without_charges = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_charges in viewable
        assert public_org_without_charges not in viewable

    @pytest.mark.django_db
    def test_get_viewable_distinct_results(self):
        """Ensure queryset returns distinct results"""
        user = UserFactory()
        org = OrganizationFactory(private=False, verified_journalist=True)
        # Create a charge and membership to potentially cause duplicates
        ChargeFactory(organization=org)
        MembershipFactory(user=user, organization=org)

        viewable = Organization.objects.get_viewable(user)
        # Should only appear once despite meeting multiple criteria
        assert viewable.filter(id=org.id).count() == 1

    @pytest.mark.django_db
    def test_create_individual_basic(self):
        """Test creating an individual organization for a user"""
        user = UserFactory.build()  # build() creates unsaved instance
        assert user.pk is None  # Ensure user is unsaved as required

        org = Organization.objects.create_individual(user)

        # Verify organization properties
        assert org.name == user.username
        assert org.individual is True
        assert org.private is True
        assert org.max_users == 1

        # Verify user is saved and linked
        assert user.pk is not None
        assert user.individual_organization == org

        # Verify creator membership exists
        assert org.memberships.filter(user=user, admin=True).exists()

        # Verify change log was created
        assert org.change_logs.filter(
            reason=ChangeLogReason.created, user=user, to_plan=org.plan, to_max_users=1
        ).exists()

    @pytest.mark.django_db
    def test_create_individual_with_uuid(self):
        """Test creating an individual organization with custom UUID"""
        user = UserFactory.build()
        custom_uuid = uuid4()

        org = Organization.objects.create_individual(user, uuid=custom_uuid)

        assert org.uuid == custom_uuid
        assert org.name == user.username
        assert org.individual is True

    @pytest.mark.django_db
    def test_create_individual_returns_organization(self):
        """Test that create_individual returns the created organization"""
        user = UserFactory.build()

        org = Organization.objects.create_individual(user)

        assert isinstance(org, Organization)
        assert org == user.individual_organization


class TestMembershipQuerySet(TestCase):
    """Unit tests for Membership queryset"""

    @pytest.mark.django_db
    def test_get_viewable(self):
        admin, member, user = UserFactory.create_batch(3)
        private_org = OrganizationFactory(admins=[admin], private=True)
        MembershipFactory(organization=private_org, user=member)

        assert Membership.objects.get_viewable(member).count() == 3
        assert Membership.objects.get_viewable(user).count() == 1

        another_user = UserFactory()
        assert member.memberships.get_viewable(another_user).count() == 0


class TestSubscriptionQuerySet(TestCase):
    """Unit tests for Subscription queryset"""

    @pytest.mark.django_db
    def test_sunlight_active_count_zero(self):
        """Test count returns zero when no Sunlight subscriptions exist"""
        # Create some non-Sunlight subscriptions
        regular_plan = PlanFactory(slug="professional", wix=False)
        SubscriptionFactory(plan=regular_plan, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 0

    @pytest.mark.django_db
    def test_sunlight_active_count_basic(self):
        """Test count returns correct number of active Sunlight subscriptions"""
        # Create Sunlight plans
        sunlight_plan1 = PlanFactory(slug="sunlight-basic-monthly", wix=True)
        sunlight_plan2 = PlanFactory(slug="sunlight-premium-annual", wix=True)

        # Create active subscriptions
        SubscriptionFactory(plan=sunlight_plan1, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan1, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan2, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 3

    @pytest.mark.django_db
    def test_sunlight_active_count_excludes_cancelled(self):
        """Test count excludes cancelled Sunlight subscriptions"""
        sunlight_plan = PlanFactory(slug="sunlight-basic-monthly", wix=True)

        # Create active and cancelled subscriptions
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=True)
        SubscriptionFactory(plan=sunlight_plan, cancelled=True)

        count = Subscription.objects.sunlight_active_count()
        assert count == 2

    @pytest.mark.django_db
    def test_sunlight_active_count_excludes_non_wix(self):
        """Test count excludes Sunlight plans with wix=False"""
        sunlight_wix = PlanFactory(slug="sunlight-basic-monthly", wix=True)
        sunlight_no_wix = PlanFactory(slug="sunlight-premium-annual", wix=False)

        SubscriptionFactory(plan=sunlight_wix, cancelled=False)
        SubscriptionFactory(plan=sunlight_no_wix, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 1

    @pytest.mark.django_db
    def test_sunlight_active_count_mixed_subscriptions(self):
        """Test count with mix of Sunlight and non-Sunlight subscriptions"""
        sunlight_plan = PlanFactory(slug="sunlight-basic-monthly", wix=True)
        regular_plan = PlanFactory(slug="professional", wix=False)

        # Create mix of subscriptions
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan, cancelled=True)
        SubscriptionFactory(plan=regular_plan, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 2
