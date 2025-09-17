# Django
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Membership, Organization
from squarelet.organizations.tests.factories import (
    ChargeFactory,
    MembershipFactory,
    OrganizationFactory,
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
