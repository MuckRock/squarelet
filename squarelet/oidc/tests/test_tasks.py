"""
Tests for OIDC tasks
"""

# send_cache_invalidation is a bind=True task, so calling it directly passes
# `self` implicitly - pylint reads every call here as missing its first argument
# pylint: disable=no-value-for-parameter

# Django
from celery.exceptions import Retry
from django.utils import timezone

# Standard Library
import logging
from datetime import timedelta
from uuid import uuid4

# Third Party
import pytest
import requests
from oidc_provider.models import UserConsent

# Squarelet
from squarelet.oidc.models import ClientProfile
from squarelet.oidc.tasks import (
    MAX_RETRIES,
    RETRY_BACKOFF,
    RETRY_JITTER,
    retry_countdown,
    send_cache_invalidation,
)
from squarelet.oidc.tests.factories import ClientFactory, ClientProfileFactory
from squarelet.organizations.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
)
from squarelet.users.tests.factories import UserFactory


@pytest.fixture(name="client_profile")
def client_profile_fixture():
    """A client profile that sends unconditionally

    require_consent defaults to True on oidc_provider.Client, which would
    otherwise filter every uuid out before the send is attempted.
    """
    return ClientProfileFactory(client=ClientFactory(require_consent=False))


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
        # pylint: disable=too-many-locals
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


@pytest.mark.django_db()
class TestSendCacheInvalidationObservability:
    """Test that every non-sending branch of the task leaves a trace"""

    def test_missing_client_profile_still_propagates(self):
        """A deleted client profile fails the task, as it did before"""
        with pytest.raises(ClientProfile.DoesNotExist):
            send_cache_invalidation(999999, "user", [str(uuid4())])

    def test_consent_filtered_to_empty_logs_reason(self, caplog, mocker):
        """A consent-filtered drop is distinguishable from a send"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.tasks")
        client_profile = ClientProfileFactory(
            client=ClientFactory(require_consent=True)
        )
        user = UserFactory()  # no consent granted
        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        send_cache_invalidation(
            client_profile.pk, "user", [str(user.individual_organization_id)]
        )

        mock_send.assert_not_called()
        assert "reason=consent-filtered" in caplog.text
        assert "original_count=1" in caplog.text

    def test_empty_input_logs_distinct_reason(self, caplog, mocker, client_profile):
        """An empty uuid list from the caller is reported as such"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.tasks")
        mocker.patch("squarelet.oidc.models.ClientProfile.send_cache_invalidation")

        send_cache_invalidation(client_profile.pk, "user", [])

        assert "reason=empty-input" in caplog.text

    def test_partial_consent_reduction_logs_no_extra_line(self, caplog, mocker):
        """A partial reduction sends the reduced list and stays quiet

        The Dispatching and Sent lines already carry both counts under a shared
        invalidation_id, so a third line per client per broadcast is wasted
        log volume.
        """
        caplog.set_level(logging.INFO, logger="squarelet.oidc.tasks")
        client = ClientFactory(require_consent=True)
        client_profile = ClientProfileFactory(client=client)
        consenting = UserFactory()
        UserConsent.objects.create(
            user=consenting,
            client=client,
            expires_at=timezone.now() + timedelta(days=1),
            date_given=timezone.now(),
        )
        other = UserFactory()
        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        send_cache_invalidation(
            client_profile.pk,
            "user",
            [
                str(consenting.individual_organization_id),
                str(other.individual_organization_id),
            ],
        )

        mock_send.assert_called_once()
        assert mock_send.call_args[0][1] == [str(consenting.individual_organization_id)]
        assert caplog.text == ""

    def test_callable_without_invalidation_id(self, mocker, client_profile):
        """Messages queued before deploy still deserialize"""
        mock_send = mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation"
        )

        send_cache_invalidation(client_profile.pk, "user", [str(uuid4())])

        mock_send.assert_called_once()


@pytest.mark.django_db()
class TestSendCacheInvalidationRetries:
    """Test that a failed delivery is retried before it is abandoned

    A client restart or deploy used to drop every invalidation in flight, with
    no reattempt and no error - the client's cache stayed stale until the next
    write to the same record.
    """

    @pytest.mark.parametrize(
        "exc",
        [
            requests.exceptions.ConnectTimeout("unreachable"),
            requests.exceptions.HTTPError("502 Bad Gateway"),
        ],
    )
    def test_failed_delivery_is_retried(self, mocker, caplog, client_profile, exc):
        """Both a network failure and a rejection schedule another attempt"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.tasks")
        mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation",
            side_effect=exc,
        )
        mock_retry = mocker.patch.object(
            send_cache_invalidation, "retry", side_effect=Retry
        )

        with pytest.raises(Retry):
            send_cache_invalidation(client_profile.pk, "user", [str(uuid4())])

        mock_retry.assert_called_once()
        assert mock_retry.call_args.kwargs["exc"] is exc
        assert mock_retry.call_args.kwargs["countdown"] >= RETRY_BACKOFF
        assert "[CACHE-INVALIDATION] Retrying" in caplog.text
        assert f"url={client_profile.webhook_url}" in caplog.text

    def test_retries_exhausted_logs_one_error(self, mocker, caplog, client_profile):
        """The last attempt reports the lost delivery exactly once

        The model logs each attempt at warning level, so this error is the only
        Sentry event for a broadcast that never landed.
        """
        caplog.set_level(logging.INFO, logger="squarelet.oidc.tasks")
        mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation",
            side_effect=requests.exceptions.HTTPError("502 Bad Gateway"),
        )
        mock_retry = mocker.patch.object(send_cache_invalidation, "retry")
        uuids = [str(uuid4())]

        result = send_cache_invalidation.apply(
            args=(client_profile.pk, "user", uuids, "abc12345"),
            retries=MAX_RETRIES,
        )

        # the task itself succeeds: a stale client cache is not worth a task
        # left in a failed state, and the error above is the alarm
        assert result.successful()
        mock_retry.assert_not_called()
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "[CACHE-INVALIDATION] Retries exceeded, giving up!" in caplog.text
        assert "id=abc12345" in caplog.text
        assert f"url={client_profile.webhook_url}" in caplog.text
        assert f"attempts={MAX_RETRIES + 1}" in caplog.text
        assert uuids[0] in caplog.text
        # exc_info is what carries the traceback into Sentry
        assert errors[0].exc_info is not None

    def test_successful_delivery_does_not_retry(self, mocker, client_profile):
        """A delivered invalidation is not reattempted"""
        mocker.patch("squarelet.oidc.models.ClientProfile.send_cache_invalidation")
        mock_retry = mocker.patch.object(send_cache_invalidation, "retry")

        send_cache_invalidation(client_profile.pk, "user", [str(uuid4())])

        mock_retry.assert_not_called()

    def test_non_request_errors_still_propagate(self, mocker, client_profile):
        """A bug in the send path fails the task instead of being retried"""
        mocker.patch(
            "squarelet.oidc.models.ClientProfile.send_cache_invalidation",
            side_effect=ValueError("bug"),
        )
        mock_retry = mocker.patch.object(send_cache_invalidation, "retry")

        with pytest.raises(ValueError):
            send_cache_invalidation(client_profile.pk, "user", [str(uuid4())])

        mock_retry.assert_not_called()


class TestRetryCountdown:
    """Test the retry backoff schedule"""

    def test_backoff_is_exponential_with_jitter(self):
        """Each attempt waits longer, and clients do not see a thundering herd"""
        for retries in range(MAX_RETRIES):
            countdown = retry_countdown(retries)
            assert 2**retries * RETRY_BACKOFF <= countdown
            assert countdown <= 2**retries * RETRY_BACKOFF + RETRY_JITTER
