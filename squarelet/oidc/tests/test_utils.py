"""
Tests for OIDC utils
"""

# Django
from django.test import override_settings

# Standard Library
import logging
from uuid import uuid4

# Third Party
import pytest

# Squarelet
from squarelet.oidc.models import UUID_LOG_SAMPLE, UUID_LOG_THRESHOLD
from squarelet.oidc.tests.factories import ClientProfileFactory
from squarelet.oidc.utils import send_cache_invalidations


@pytest.mark.django_db()
class TestSendCacheInvalidations:
    """Test the fan-out of a cache invalidation broadcast to every client"""

    @override_settings(ENABLE_SEND_CACHE_INVALIDATIONS=False)
    def test_disabled_flag_logs_and_enqueues_nothing(self, caplog, mocker):
        """The feature flag being off is no longer a silent no-op"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.utils")
        ClientProfileFactory()
        mock_delay = mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")

        send_cache_invalidations("user", [str(uuid4())])

        mock_delay.assert_not_called()
        assert "Disabled by ENABLE_SEND_CACHE_INVALIDATIONS" in caplog.text

    def test_no_clients_with_webhook_url_is_logged(self, caplog, mocker):
        """A client set with no webhook URLs is a misconfiguration, not silence"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.utils")
        ClientProfileFactory(webhook_url="")
        mock_delay = mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")

        send_cache_invalidations("user", [str(uuid4())])

        mock_delay.assert_not_called()
        assert "No client has a webhook_url configured" in caplog.text

    def test_dispatch_logs_client_names_and_count(self, caplog, mocker):
        """The dispatch line names every client it fanned out to"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.utils")
        profiles = ClientProfileFactory.create_batch(2)
        mock_delay = mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")

        send_cache_invalidations("organization", [str(uuid4()), str(uuid4())])

        assert mock_delay.call_count == 2
        assert "Dispatching id=" in caplog.text
        assert "count=2" in caplog.text
        for profile in profiles:
            assert profile.client.name in caplog.text

    def test_all_clients_share_one_invalidation_id(self, mocker):
        """One broadcast is greppable across every client's task"""
        ClientProfileFactory.create_batch(3)
        mock_delay = mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")

        send_cache_invalidations("user", [str(uuid4())])

        ids = {call.kwargs["invalidation_id"] for call in mock_delay.call_args_list}
        assert len(ids) == 1
        assert len(ids.pop()) == 8

    def test_blank_webhook_url_is_excluded(self, mocker):
        """Clients without a webhook URL are not dispatched to"""
        configured = ClientProfileFactory()
        ClientProfileFactory(webhook_url="")
        mock_delay = mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")

        send_cache_invalidations("user", [str(uuid4())])

        mock_delay.assert_called_once()
        assert mock_delay.call_args[0][0] == configured.pk

    def test_dispatch_logs_every_uuid(self, caplog, mocker):
        """An interactive-sized broadcast names every uuid it dispatched"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.utils")
        ClientProfileFactory()
        mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")
        uuids = [str(uuid4()) for _ in range(UUID_LOG_THRESHOLD)]

        send_cache_invalidations("organization", uuids)

        assert f"count={UUID_LOG_THRESHOLD}" in caplog.text
        for uuid in uuids:
            assert uuid in caplog.text

    def test_bulk_dispatch_is_abbreviated(self, caplog, mocker):
        """A bulk broadcast logs a sample and a remainder, not the full list"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.utils")
        ClientProfileFactory()
        mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")
        uuids = [str(uuid4()) for _ in range(500)]

        send_cache_invalidations("organization", uuids)

        assert "count=500" in caplog.text
        assert f"+{500 - UUID_LOG_SAMPLE} more" in caplog.text
        assert uuids[UUID_LOG_SAMPLE] not in caplog.text

    def test_full_uuid_list_still_reaches_the_task(self, mocker):
        """Abbreviating the log must not abbreviate what actually gets sent"""
        ClientProfileFactory()
        mock_delay = mocker.patch("squarelet.oidc.tasks.send_cache_invalidation.delay")
        uuids = [str(uuid4()) for _ in range(500)]

        send_cache_invalidations("organization", uuids)

        assert mock_delay.call_args[0][2] == uuids
