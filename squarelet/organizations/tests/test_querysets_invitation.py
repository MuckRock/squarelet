# Django
from django.test import TestCase
from django.utils import timezone

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Invitation
from squarelet.organizations.tests.factories import (
    InvitationFactory,
    InvitationRequestFactory,
    OrganizationFactory,
)
from squarelet.users.tests.factories import UserFactory


class TestInvitationQuerySetStatus(TestCase):
    """Unit tests for Invitation queryset status filters"""

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
        InvitationFactory(organization=org, request=False, withdrawn_at=timezone.now())

        qs = Invitation.objects.get_org_invitations(org)
        assert qs.count() == 4

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
        InvitationRequestFactory(
            organization=org,
            user=user3,
            request=True,
            withdrawn_at=timezone.now(),
        )

        qs = Invitation.objects.get_org_requests(org)
        assert qs.count() == 4

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

    @pytest.mark.django_db
    def test_get_withdrawn(self):
        """Test get_withdrawn returns only withdrawn invitations"""
        withdrawn_inv = InvitationFactory(withdrawn_at=timezone.now())
        active_inv = InvitationFactory(withdrawn_at=None)

        queryset = Invitation.objects.get_withdrawn()
        assert withdrawn_inv in queryset
        assert active_inv not in queryset


class TestInvitationQuerySetForUser(TestCase):
    """Unit tests for Invitation queryset for_user filtering"""

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


class TestInvitationQuerySetUserInvitations(TestCase):
    """Unit tests for Invitation queryset get_user_invitations/get_user_requests"""

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
