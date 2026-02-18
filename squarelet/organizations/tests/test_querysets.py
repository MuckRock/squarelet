# Django
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.utils import timezone

# Standard Library
from datetime import timedelta
from uuid import uuid4

# Third Party
import pytest

# Squarelet
from squarelet.organizations.choices import ChangeLogReason
from squarelet.organizations.models import (
    Invitation,
    Invoice,
    Membership,
    Organization,
    Subscription,
)
from squarelet.organizations.tests.factories import (
    ChargeFactory,
    InvitationFactory,
    InvitationRequestFactory,
    InvoiceFactory,
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
    def test_get_viewable_authenticated_user_public_with_paid_invoices(self):
        """Authenticated users can view public orgs with paid invoices"""
        user = UserFactory()
        public_org_with_paid_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_paid_invoice, status="paid")
        public_org_with_open_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_open_invoice, status="open")
        public_org_without_invoices = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_paid_invoice in viewable
        assert public_org_with_open_invoice not in viewable
        assert public_org_without_invoices not in viewable

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
    def test_get_viewable_anonymous_user_public_with_paid_invoices(self):
        """Anonymous users can view public orgs with paid invoices"""
        user = AnonymousUser()
        public_org_with_paid_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_paid_invoice, status="paid")
        public_org_with_open_invoice = OrganizationFactory(
            private=False, verified_journalist=False
        )
        InvoiceFactory(organization=public_org_with_open_invoice, status="open")
        public_org_without_invoices = OrganizationFactory(
            private=False, verified_journalist=False
        )

        viewable = Organization.objects.get_viewable(user)
        assert public_org_with_paid_invoice in viewable
        assert public_org_with_open_invoice not in viewable
        assert public_org_without_invoices not in viewable

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


@pytest.mark.django_db(transaction=True)
def test_membership_create_with_wix_plan_triggers_sync(mocker):
    """Test that creating a membership with a Wix plan triggers sync"""
    mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")

    user = UserFactory()
    wix_plan = PlanFactory(wix=True)
    org = OrganizationFactory()
    SubscriptionFactory(organization=org, plan=wix_plan)

    # Create membership
    membership = Membership.objects.create(user=user, organization=org)

    # Verify membership was created
    assert membership.user == user
    assert membership.organization == org

    # Verify sync_wix.delay was called with correct parameters
    mock_sync.assert_called_once_with(org.pk, wix_plan.pk, user.pk)


@pytest.mark.django_db(transaction=True)
def test_membership_create_without_wix_plan_no_sync(mocker):
    """Test that creating a membership without Wix plan does not trigger sync"""
    mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")

    user = UserFactory()
    non_wix_plan = PlanFactory(wix=False)
    org = OrganizationFactory()
    SubscriptionFactory(organization=org, plan=non_wix_plan)

    # Create membership
    membership = Membership.objects.create(user=user, organization=org)

    # Verify membership was created
    assert membership.user == user
    assert membership.organization == org

    # Verify sync_wix.delay was NOT called
    mock_sync.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_membership_create_without_plan_no_sync(mocker):
    """Test that creating a membership for an org with no plan does not trigger sync"""
    mock_sync = mocker.patch("squarelet.organizations.tasks.sync_wix.delay")

    user = UserFactory()
    org = OrganizationFactory()

    # Create membership (org has no plan)
    membership = Membership.objects.create(user=user, organization=org)

    # Verify membership was created
    assert membership.user == user
    assert membership.organization == org

    # Verify sync_wix.delay was NOT called
    mock_sync.assert_not_called()


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
        sunlight_plan1 = PlanFactory(slug="sunlight-essential-monthly", wix=True)
        sunlight_plan2 = PlanFactory(slug="sunlight-enhanced-annual", wix=True)

        # Create active subscriptions
        SubscriptionFactory(plan=sunlight_plan1, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan1, cancelled=False)
        SubscriptionFactory(plan=sunlight_plan2, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 3

    @pytest.mark.django_db
    def test_sunlight_active_count_excludes_cancelled(self):
        """Test count excludes cancelled Sunlight subscriptions"""
        sunlight_plan = PlanFactory(slug="sunlight-essential-monthly", wix=True)

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
        sunlight_wix = PlanFactory(slug="sunlight-essential-monthly", wix=True)
        sunlight_no_wix = PlanFactory(slug="sunlight-enhanced-annual", wix=False)

        SubscriptionFactory(plan=sunlight_wix, cancelled=False)
        SubscriptionFactory(plan=sunlight_no_wix, cancelled=False)

        count = Subscription.objects.sunlight_active_count()
        assert count == 1

    @pytest.mark.django_db
    def test_sunlight_active_count_mixed_subscriptions(self):
        """Test count with mix of Sunlight and non-Sunlight subscriptions"""
        sunlight_plan = PlanFactory(slug="sunlight-essential-monthly", wix=True)
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
    # pylint: disable=too-many-public-methods

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

    def test_for_user_with_verified_email(self):
        """Test for_user() filters by user's verified email"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create invitation to user's verified email
        invitation = InvitationFactory(email="user@example.com", organization=org)

        # Create invitation to different email (should not appear)
        InvitationFactory(email="other@example.com", organization=org)

        queryset = Invitation.objects.for_user(user)
        assert invitation in queryset
        assert queryset.count() == 1

    @pytest.mark.django_db
    def test_for_user_with_user_field(self):
        """Test for_user() includes invitations via user field"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create invitation via user field
        invitation = InvitationFactory(user=user, organization=org, request=True)

        queryset = Invitation.objects.for_user(user)
        assert invitation in queryset
        assert queryset.count() == 1

    @pytest.mark.django_db
    def test_for_user_combines_email_and_user_field(self):
        """Test for_user() returns both email and user field matches"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create invitation to email
        email_invitation = InvitationFactory(email="user@example.com", organization=org)

        # Create invitation via user field
        user_invitation = InvitationFactory(user=user, organization=org, request=True)

        queryset = Invitation.objects.for_user(user)
        assert email_invitation in queryset
        assert user_invitation in queryset
        assert queryset.count() == 2

    @pytest.mark.django_db
    def test_for_user_no_verified_emails(self):
        """Test for_user() returns empty queryset when user has no verified emails"""
        user = UserFactory(email="user@example.com", email_verified=False)
        org = OrganizationFactory()

        # Create invitation that would match if email was verified
        InvitationFactory(email="user@example.com", organization=org)

        queryset = Invitation.objects.for_user(user)
        assert queryset.count() == 0

    @pytest.mark.django_db
    def test_for_user_multiple_verified_emails(self):
        """Test for_user() matches any of user's verified emails"""
        user = UserFactory(email="primary@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create invitations to different verified emails
        invitation1 = InvitationFactory(email="primary@example.com", organization=org)
        InvitationFactory(email="secondary@example.com", organization=org)

        # Mock get_verified_emails to return multiple emails
        # In real code, this would involve creating EmailAddress records
        # For now, we'll just test the primary email case
        queryset = Invitation.objects.for_user(user)
        assert invitation1 in queryset
        # invitation2 won't be included unless secondary email is verified
        assert queryset.count() == 1

    @pytest.mark.django_db
    def test_get_user_invitations_filters_by_request_false(self):
        """Test get_user_invitations() returns only invitations, not requests"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create invitation (request=False)
        invitation = InvitationFactory(
            email="user@example.com", organization=org, request=False
        )

        # Create request (request=True) - should not appear
        InvitationRequestFactory(user=user, organization=org, request=True)

        queryset = Invitation.objects.get_user_invitations(user)
        assert invitation in queryset
        assert queryset.count() == 1
        assert all(not inv.request for inv in queryset)

    @pytest.mark.django_db
    def test_get_user_invitations_includes_select_related(self):
        """Test get_user_invitations() includes organization via select_related"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        InvitationFactory(email="user@example.com", organization=org)

        # Execute the query to load data
        queryset = list(Invitation.objects.get_user_invitations(user))

        # Check that organization is prefetched (no additional query needed)
        with self.assertNumQueries(0):
            # This should not trigger a query if select_related worked
            _ = queryset[0].organization.name

    @pytest.mark.django_db
    def test_get_user_invitations_ordered_by_created_at_desc(self):
        """Test get_user_invitations() orders by created_at descending"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create invitations in sequence
        invitation1 = InvitationFactory(email="user@example.com", organization=org)
        invitation2 = InvitationFactory(email="user@example.com", organization=org)
        invitation3 = InvitationFactory(email="user@example.com", organization=org)

        queryset = list(Invitation.objects.get_user_invitations(user))

        # Most recent should be first
        assert queryset[0] == invitation3
        assert queryset[1] == invitation2
        assert queryset[2] == invitation1

    @pytest.mark.django_db
    def test_get_user_requests_filters_by_request_true(self):
        """Test get_user_requests() returns only requests, not invitations"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create request (request=True)
        request = InvitationRequestFactory(user=user, organization=org, request=True)

        # Create invitation (request=False) - should not appear
        InvitationFactory(email="user@example.com", organization=org, request=False)

        queryset = Invitation.objects.get_user_requests(user)
        assert request in queryset
        assert queryset.count() == 1
        assert all(inv.request for inv in queryset)

    @pytest.mark.django_db
    def test_get_user_requests_includes_select_related(self):
        """Test get_user_requests() includes organization via select_related"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        InvitationRequestFactory(user=user, organization=org)

        # Execute the query to load data
        queryset = list(Invitation.objects.get_user_requests(user))

        # Check that organization is prefetched (no additional query needed)
        with self.assertNumQueries(0):
            # This should not trigger a query if select_related worked
            _ = queryset[0].organization.name

    @pytest.mark.django_db
    def test_get_user_requests_ordered_by_created_at_desc(self):
        """Test get_user_requests() orders by created_at descending"""
        user = UserFactory(email="user@example.com", email_verified=True)
        org = OrganizationFactory()

        # Create requests in sequence
        request1 = InvitationRequestFactory(user=user, organization=org)
        request2 = InvitationRequestFactory(user=user, organization=org)
        request3 = InvitationRequestFactory(user=user, organization=org)

        queryset = list(Invitation.objects.get_user_requests(user))

        # Most recent should be first
        assert queryset[0] == request3
        assert queryset[1] == request2
        assert queryset[2] == request1

    @pytest.mark.django_db
    def test_get_user_invitations_no_verified_emails(self):
        """Test get_user_invitations() returns empty when no verified emails"""
        user = UserFactory(email="user@example.com", email_verified=False)
        org = OrganizationFactory()

        # Create invitation that would match if verified
        InvitationFactory(email="user@example.com", organization=org)

        queryset = Invitation.objects.get_user_invitations(user)
        assert queryset.count() == 0

    @pytest.mark.django_db
    def test_get_user_requests_no_verified_emails(self):
        """Test get_user_requests() returns empty when no verified emails"""
        user = UserFactory(email="user@example.com", email_verified=False)
        org = OrganizationFactory()

        # Create request that would match if verified
        InvitationRequestFactory(user=user, organization=org)

        queryset = Invitation.objects.get_user_requests(user)
        assert queryset.count() == 0

    @pytest.mark.django_db
    def test_get_org_invitations_filters_by_request_false(self):
        """get_org_invitations returns only invitations (request=False) for an org"""
        org = OrganizationFactory()
        invitation = InvitationFactory(organization=org, request=False)
        InvitationFactory(organization=org, request=True)  # request, not invitation

        qs = Invitation.objects.get_org_invitations(org)
        assert qs.count() == 1
        assert invitation in qs

    @pytest.mark.django_db
    def test_get_org_invitations_includes_all_statuses(self):
        """get_org_invitations returns pending, accepted, and rejected invitations"""
        org = OrganizationFactory()
        InvitationFactory(organization=org, request=False)  # pending
        InvitationFactory(organization=org, request=False, accepted_at=timezone.now())
        InvitationFactory(organization=org, request=False, rejected_at=timezone.now())
        # TODO: Add withdrawn status (#588)

        qs = Invitation.objects.get_org_invitations(org)
        assert qs.count() == 3

    @pytest.mark.django_db
    def test_get_org_invitations_scoped_to_org(self):
        """get_org_invitations only returns invitations for the specified org"""
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        invite1 = InvitationFactory(organization=org1, request=False)
        InvitationFactory(organization=org2, request=False)

        qs = Invitation.objects.get_org_invitations(org1)
        assert qs.count() == 1
        assert invite1 in qs

    @pytest.mark.django_db
    def test_get_org_invitations_ordered_by_created_at_desc(self):
        """get_org_invitations orders by created_at descending"""
        org = OrganizationFactory()
        inv1 = InvitationFactory(organization=org, request=False)
        inv2 = InvitationFactory(organization=org, request=False)
        inv3 = InvitationFactory(organization=org, request=False)

        qs = list(Invitation.objects.get_org_invitations(org))
        assert qs[0] == inv3
        assert qs[1] == inv2
        assert qs[2] == inv1

    @pytest.mark.django_db
    def test_get_org_requests_filters_by_request_true(self):
        """get_org_requests returns only requests (request=True) for an org"""
        org = OrganizationFactory()
        user = UserFactory()
        request = InvitationRequestFactory(organization=org, user=user, request=True)
        InvitationFactory(organization=org, request=False)  # invitation, not request

        qs = Invitation.objects.get_org_requests(org)
        assert qs.count() == 1
        assert request in qs

    @pytest.mark.django_db
    def test_get_org_requests_includes_all_statuses(self):
        """get_org_requests returns pending, accepted, and rejected requests"""
        org = OrganizationFactory()
        user1 = UserFactory()
        user2 = UserFactory()
        user3 = UserFactory()
        InvitationRequestFactory(organization=org, user=user1, request=True)
        InvitationRequestFactory(
            organization=org,
            user=user2,
            request=True,
            accepted_at=timezone.now(),
        )
        InvitationRequestFactory(
            organization=org,
            user=user3,
            request=True,
            rejected_at=timezone.now(),
        )
        # TODO: Add withdrawn status (#588)

        qs = Invitation.objects.get_org_requests(org)
        assert qs.count() == 3

    @pytest.mark.django_db
    def test_get_org_requests_scoped_to_org(self):
        """get_org_requests only returns requests for the specified org"""
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        user1 = UserFactory()
        user2 = UserFactory()
        invite1 = InvitationRequestFactory(organization=org1, user=user1, request=True)
        InvitationRequestFactory(organization=org2, user=user2, request=True)

        qs = Invitation.objects.get_org_requests(org1)
        assert qs.count() == 1
        assert invite1 in qs


class TestInvoiceQuerySet(TestCase):
    """Unit tests for Invoice queryset"""

    @pytest.mark.django_db
    def test_overdue_empty_when_no_invoices(self):
        """Overdue returns empty queryset when no invoices exist"""
        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 0

    @pytest.mark.django_db
    def test_overdue_finds_past_due_invoices(self):
        """Verify overdue finds invoices past their due date"""
        # Create invoice that's 35 days overdue
        old_due_date = timezone.now().date() - timedelta(days=35)
        InvoiceFactory(status="open", due_date=old_due_date)

        # Create invoice that's overdue within grace period
        recent_due_date = timezone.now().date() - timedelta(days=10)
        InvoiceFactory(status="open", due_date=recent_due_date)

        # Query with 30-day grace period
        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 1

    @pytest.mark.django_db
    def test_overdue_excludes_paid_invoices(self):
        """Test overdue excludes paid invoices even if past due date"""
        old_due_date = timezone.now().date() - timedelta(days=35)

        # Create overdue but paid invoice
        InvoiceFactory(status="paid", due_date=old_due_date)

        # Create overdue open invoice
        InvoiceFactory(status="open", due_date=old_due_date)

        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 1

    @pytest.mark.django_db
    def test_overdue_excludes_other_statuses(self):
        """Test overdue only includes open status invoices"""
        old_due_date = timezone.now().date() - timedelta(days=35)

        # Create invoices with various statuses
        InvoiceFactory(status="open", due_date=old_due_date)
        InvoiceFactory(status="void", due_date=old_due_date)
        InvoiceFactory(status="uncollectible", due_date=old_due_date)
        InvoiceFactory(status="draft", due_date=old_due_date)

        overdue = Invoice.objects.overdue(grace_period_days=30)
        assert overdue.count() == 1

    @pytest.mark.django_db
    def test_overdue_respects_grace_period(self):
        """Test overdue respects the grace period parameter"""
        # Create invoices at different overdue levels
        InvoiceFactory.create_batch(
            3,
            status="open",
            due_date=timezone.now().date() - timedelta(days=70),
        )
        InvoiceFactory.create_batch(
            2,
            status="open",
            due_date=timezone.now().date() - timedelta(days=45),
        )
        InvoiceFactory.create_batch(
            4,
            status="open",
            due_date=timezone.now().date() - timedelta(days=20),
        )

        # 30-day grace period should find 5 invoices (70 and 45 days old)
        assert Invoice.objects.overdue(grace_period_days=30).count() == 5

        # 60-day grace period should find 3 invoices (only 70 days old)
        assert Invoice.objects.overdue(grace_period_days=60).count() == 3

        # 15-day grace period should find all 9 invoices
        assert Invoice.objects.overdue(grace_period_days=15).count() == 9
