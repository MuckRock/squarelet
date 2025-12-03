# Django
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

# Standard Library
from uuid import uuid4

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import (
    Invitation,
    Membership,
    Organization,
    Subscription,
)
from squarelet.organizations.tests.factories import (
    ChargeFactory,
    InvitationFactory,
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


class TestInvitationQuerySet(TestCase):
    """Unit tests for Invitation queryset"""

    @pytest.mark.django_db
    def test_get_open(self):
        """get_open returns only invitations with no accepted_at/rejected_at"""
        inv_open = InvitationFactory(accepted_at=None, rejected_at=None)
        InvitationFactory(accepted_at=None, rejected_at="2024-01-01")  # rejected
        InvitationFactory(accepted_at="2024-01-01", rejected_at=None)  # accepted

        qs = Invitation.objects.get_open()
        assert qs.count() == 1
        assert inv_open in qs

    @pytest.mark.django_db
    def test_get_pending(self):
        """get_pending returns only open invitations, alias for open"""
        open_inv = InvitationFactory(accepted_at=None, rejected_at=None)
        # non-open invitations
        InvitationFactory(accepted_at="2024-01-01", rejected_at=None)  # accepted
        InvitationFactory(accepted_at=None, rejected_at="2024-01-01")  # rejected

        qs = Invitation.objects.get_pending()
        assert qs.count() == 1
        assert open_inv in qs

    @pytest.mark.django_db
    def test_get_pending_invitations(self):
        """get_pending_invitations returns open invitations where request=False"""
        normal_inv = InvitationFactory(
            request=False, accepted_at=None, rejected_at=None
        )
        InvitationFactory(request=True, accepted_at=None, rejected_at=None)  # request
        InvitationFactory(request=False, accepted_at="2024-01-01")  # accepted

        qs = Invitation.objects.get_pending_invitations()
        assert qs.count() == 1
        assert normal_inv in qs

    @pytest.mark.django_db
    def test_get_pending_requests(self):
        """get_pending_requests returns open invitations where request=True"""
        req_inv = InvitationFactory(request=True, accepted_at=None, rejected_at=None)
        InvitationFactory(request=False, accepted_at=None, rejected_at=None)
        InvitationFactory(request=True, rejected_at="2024-01-01")  # rejected

        qs = Invitation.objects.get_pending_requests()
        assert qs.count() == 1
        assert req_inv in qs

    @pytest.mark.django_db
    def test_get_rejected_requests(self):
        """get_rejected_requests returns request=True and rejected_at is not null"""
        rejected_req = InvitationFactory(request=True, rejected_at="2024-01-01")
        InvitationFactory(request=True, rejected_at=None)  # still open
        InvitationFactory(request=False, rejected_at="2024-01-01")  # not a request

        qs = Invitation.objects.get_rejected_requests()
        assert qs.count() == 1
        assert rejected_req in qs

    @pytest.mark.django_db
    def test_get_accepted(self):
        """get_accepted returns invitations where accepted_at is set"""
        accepted = InvitationFactory(accepted_at="2024-01-01")
        InvitationFactory(accepted_at=None)
        InvitationFactory(accepted_at=None, rejected_at="2024-01-01")

        qs = Invitation.objects.get_accepted()
        assert qs.count() == 1
        assert accepted in qs

    @pytest.mark.django_db
    def test_get_rejected(self):
        """get_rejected returns invitations where rejected_at is set"""
        rejected = InvitationFactory(rejected_at="2024-01-01")
        InvitationFactory(rejected_at=None)
        InvitationFactory(accepted_at="2024-01-01", rejected_at=None)

        qs = Invitation.objects.get_rejected()
        assert qs.count() == 1
        assert rejected in qs
