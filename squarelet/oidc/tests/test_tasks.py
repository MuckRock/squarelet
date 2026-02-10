"""
Tests for OIDC tasks
"""

# Django
from django.utils import timezone

# Standard Library
from datetime import timedelta

# Third Party
import pytest
from oidc_provider.models import UserConsent

# Squarelet
from squarelet.oidc.tasks import send_cache_invalidation
from squarelet.oidc.tests.factories import ClientFactory, ClientProfileFactory
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
)
from squarelet.users.tests.factories import UserFactory


@pytest.mark.django_db()
class TestSendCacheInvalidation:
    """Test the send_cache_invalidation task with consent filtering"""

    # ==================== User Tests ====================

    def test_user_no_consent_required(self, mocker):
        """Client with require_consent=False should receive all user
        invalidations
        """
        # Setup
        client = ClientFactory(require_consent=False)
        client_profile = ClientProfileFactory(client=client)
        user1 = UserFactory()
        user2 = UserFactory()
        user3 = UserFactory()

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [
            str(user1.individual_organization_id),
            str(user2.individual_organization_id),
            str(user3.individual_organization_id),
        ]
        send_cache_invalidation(client_profile.pk, "user", uuids)

        # Verify - all UUIDs should be sent
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "user"
        assert set(mock_send.call_args[0][1]) == set(uuids)

    def test_user_consent_required_single_user_with_consent(self, mocker):
        """Client with require_consent=True should receive invalidation for
        user with valid consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        user = UserFactory()

        # Create valid consent
        UserConsent.objects.create(
            user=user,
            client=client,
            expires_at=timezone.now() + timedelta(days=30),
            date_given=timezone.now(),
            scope=["openid"],
        )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(user.individual_organization_id)]
        send_cache_invalidation(client_profile.pk, "user", uuids)

        # Verify - UUID should be sent since user has consent
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "user"
        assert mock_send.call_args[0][1] == uuids

    def test_user_consent_required_single_user_no_consent(self, mocker):
        """Client with require_consent=True should not receive invalidation
        for user without consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        user = UserFactory()

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(user.individual_organization_id)]
        send_cache_invalidation(client_profile.pk, "user", uuids)

        # Verify - function should not be called since user has no consent
        mock_send.assert_not_called()

    def test_user_consent_required_expired_consent(self, mocker):
        """Client with require_consent=True should not receive invalidation
        for user with expired consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        user = UserFactory()

        # Create expired consent
        UserConsent.objects.create(
            user=user,
            client=client,
            expires_at=timezone.now() - timedelta(days=1),
            date_given=timezone.now() - timedelta(days=31),
            scope=["openid"],
        )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(user.individual_organization_id)]
        send_cache_invalidation(client_profile.pk, "user", uuids)

        # Verify - function should not be called since consent is expired
        mock_send.assert_not_called()

    def test_user_consent_required_mixed_consent_status(self, mocker):
        """Client with require_consent=True should only receive
        invalidations for users with valid consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)

        user_with_consent = UserFactory()
        user_no_consent = UserFactory()
        user_expired_consent = UserFactory()
        user_with_consent_2 = UserFactory()

        # Create valid consent for user 1
        UserConsent.objects.create(
            user=user_with_consent,
            client=client,
            expires_at=timezone.now() + timedelta(days=30),
            date_given=timezone.now(),
            scope=["openid"],
        )

        # User 2 has no consent record

        # Create expired consent for user 3
        UserConsent.objects.create(
            user=user_expired_consent,
            client=client,
            expires_at=timezone.now() - timedelta(days=1),
            date_given=timezone.now() - timedelta(days=31),
            scope=["openid"],
        )

        # Create valid consent for user 4
        UserConsent.objects.create(
            user=user_with_consent_2,
            client=client,
            expires_at=timezone.now() + timedelta(days=60),
            date_given=timezone.now(),
            scope=["openid"],
        )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [
            str(user_with_consent.individual_organization_id),
            str(user_no_consent.individual_organization_id),
            str(user_expired_consent.individual_organization_id),
            str(user_with_consent_2.individual_organization_id),
        ]
        send_cache_invalidation(client_profile.pk, "user", uuids)

        # Verify - only users with valid consent should be included
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "user"
        sent_uuids = set(mock_send.call_args[0][1])
        expected_uuids = {
            str(user_with_consent.individual_organization_id),
            str(user_with_consent_2.individual_organization_id),
        }
        assert sent_uuids == expected_uuids

    # ==================== Organization Tests ====================

    def test_organization_no_consent_required(self, mocker):
        """Client with require_consent=False should receive all organization
        invalidations
        """
        # Setup
        client = ClientFactory(require_consent=False)
        client_profile = ClientProfileFactory(client=client)
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        org3 = OrganizationFactory()

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(org1.uuid), str(org2.uuid), str(org3.uuid)]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - all UUIDs should be sent
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "organization"
        assert set(mock_send.call_args[0][1]) == set(uuids)

    def test_organization_consent_required_single_org_with_consent(self, mocker):
        """Client with require_consent=True should receive invalidation for
        organization with at least one user with valid consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        org = OrganizationFactory()
        user = UserFactory()

        # Add user to organization
        MembershipFactory(user=user, organization=org)

        # Create valid consent for user
        UserConsent.objects.create(
            user=user,
            client=client,
            expires_at=timezone.now() + timedelta(days=30),
            date_given=timezone.now(),
            scope=["openid"],
        )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(org.uuid)]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - UUID should be sent since org has user with consent
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "organization"
        assert mock_send.call_args[0][1] == uuids

    def test_organization_consent_required_single_org_no_consent(self, mocker):
        """Client with require_consent=True should not receive invalidation
        for organization with no users with consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        org = OrganizationFactory()
        user = UserFactory()

        # Add user to organization but don't create consent
        MembershipFactory(user=user, organization=org)

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(org.uuid)]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - function should not be called since org has no consent
        mock_send.assert_not_called()

    def test_organization_consent_required_org_with_expired_consent(self, mocker):
        """Client with require_consent=True should not receive invalidation
        for organization where all users have expired consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        org = OrganizationFactory()
        user = UserFactory()

        # Add user to organization
        MembershipFactory(user=user, organization=org)

        # Create expired consent
        UserConsent.objects.create(
            user=user,
            client=client,
            expires_at=timezone.now() - timedelta(days=1),
            date_given=timezone.now() - timedelta(days=31),
            scope=["openid"],
        )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(org.uuid)]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - function should not be called since consent is expired
        mock_send.assert_not_called()

    def test_organization_consent_required_mixed_consent_status(self, mocker):
        """Client with require_consent=True should only receive
        invalidations for organizations with at least one user with valid
        consent
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)

        # Org 1: Has user with valid consent
        org_with_consent = OrganizationFactory()
        user1 = UserFactory()
        MembershipFactory(user=user1, organization=org_with_consent)
        UserConsent.objects.create(
            user=user1,
            client=client,
            expires_at=timezone.now() + timedelta(days=30),
            date_given=timezone.now(),
            scope=["openid"],
        )

        # Org 2: Has no users with consent
        org_no_consent = OrganizationFactory()
        user2 = UserFactory()
        MembershipFactory(user=user2, organization=org_no_consent)

        # Org 3: Has user with expired consent
        org_expired_consent = OrganizationFactory()
        user3 = UserFactory()
        MembershipFactory(user=user3, organization=org_expired_consent)
        UserConsent.objects.create(
            user=user3,
            client=client,
            expires_at=timezone.now() - timedelta(days=1),
            date_given=timezone.now() - timedelta(days=31),
            scope=["openid"],
        )

        # Org 4: Has multiple users, one with valid consent
        org_mixed = OrganizationFactory()
        user4_no_consent = UserFactory()
        user4_with_consent = UserFactory()
        MembershipFactory(user=user4_no_consent, organization=org_mixed)
        MembershipFactory(user=user4_with_consent, organization=org_mixed)
        UserConsent.objects.create(
            user=user4_with_consent,
            client=client,
            expires_at=timezone.now() + timedelta(days=60),
            date_given=timezone.now(),
            scope=["openid"],
        )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [
            str(org_with_consent.uuid),
            str(org_no_consent.uuid),
            str(org_expired_consent.uuid),
            str(org_mixed.uuid),
        ]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - only orgs with at least one user with valid consent
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "organization"
        sent_uuids = set(mock_send.call_args[0][1])
        expected_uuids = {
            str(org_with_consent.uuid),
            str(org_mixed.uuid),
        }
        assert sent_uuids == expected_uuids

    def test_organization_consent_required_multiple_users_with_consent(self, mocker):
        """Organization with multiple users having valid consent should still
        only be sent once
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        org = OrganizationFactory()

        # Add multiple users with consent
        user1 = UserFactory()
        user2 = UserFactory()
        user3 = UserFactory()

        MembershipFactory(user=user1, organization=org)
        MembershipFactory(user=user2, organization=org)
        MembershipFactory(user=user3, organization=org)

        for user in [user1, user2, user3]:
            UserConsent.objects.create(
                user=user,
                client=client,
                expires_at=timezone.now() + timedelta(days=30),
                date_given=timezone.now(),
                scope=["openid"],
            )

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(org.uuid)]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - org should be sent once (no duplicates)
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "organization"
        assert mock_send.call_args[0][1] == [str(org.uuid)]

    def test_empty_uuid_list(self, mocker):
        """Task should handle empty UUID list gracefully"""
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute with empty list
        send_cache_invalidation(client_profile.pk, "user", [])

        # Verify - function should not be called for empty list
        mock_send.assert_not_called()

    def test_organization_no_users(self, mocker):
        """Organization with no users should not be sent when consent is
        required
        """
        # Setup
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        org = OrganizationFactory()  # No users added

        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        # Execute
        uuids = [str(org.uuid)]
        send_cache_invalidation(client_profile.pk, "organization", uuids)

        # Verify - function should not be called since org has no users
        mock_send.assert_not_called()
