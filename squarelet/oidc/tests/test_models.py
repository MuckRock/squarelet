"""
Tests for OIDC models

These cover the actual webhook HTTP send, which was previously untested - every
test in test_tasks.py mocks `ClientProfile.send_cache_invalidation` away.
"""

# Standard Library
import hashlib
import hmac
import logging
from urllib.parse import parse_qs
from uuid import uuid4

# Third Party
import pytest
import requests

# Squarelet
from squarelet.oidc.models import ERROR_BODY_CHARS, UUID_LOG_SAMPLE, UUID_LOG_THRESHOLD
from squarelet.oidc.tests.factories import ClientProfileFactory


@pytest.mark.django_db()
class TestSendCacheInvalidation:
    """Test ClientProfile.send_cache_invalidation"""

    def test_success_posts_expected_payload(self, requests_mock):
        """A successful send posts the documented form payload"""
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)
        uuids = [str(uuid4()) for _ in range(3)]

        client_profile.send_cache_invalidation("user", uuids)

        posted = parse_qs(requests_mock.last_request.text)
        assert posted["type"] == ["user"]
        assert posted["uuids"] == uuids
        assert len(posted["timestamp"]) == 1
        assert len(posted["signature"]) == 1

    def test_signature_is_correct_hmac(self, requests_mock):
        """The signature is an HMAC-SHA256 over timestamp + model + joined uuids

        Regression guard on the wire contract: MuckRock and DocumentCloud both
        verify this signature, so a change here breaks them simultaneously.
        """
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)
        uuids = [str(uuid4()) for _ in range(3)]

        client_profile.send_cache_invalidation("organization", uuids)

        posted = parse_qs(requests_mock.last_request.text)
        uuid_str = "".join(posted["uuids"])
        expected = hmac.new(
            key=client_profile.client.client_secret.encode("utf8"),
            msg=f"{posted['timestamp'][0]}organization{uuid_str}".encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        assert posted["signature"] == [expected]

    def test_success_returns_response_and_logs_info(self, requests_mock, caplog):
        """A 2xx response is returned and logged with context"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)
        uuids = [str(uuid4()) for _ in range(3)]

        response = client_profile.send_cache_invalidation("user", uuids)

        assert response.status_code == 200
        assert "[CACHE-INVALIDATION] Sent" in caplog.text
        assert f"client={client_profile.client.name}" in caplog.text
        assert "model=user" in caplog.text
        assert "count=3" in caplog.text
        assert "status=200" in caplog.text

    @pytest.mark.parametrize("status_code", [400, 404, 413, 500, 502])
    def test_non_2xx_raises_and_logs_warning(self, requests_mock, caplog, status_code):
        """A non-2xx response raises HTTPError instead of passing silently"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=status_code)

        with pytest.raises(requests.HTTPError):
            client_profile.send_cache_invalidation("user", [str(uuid4())])

        assert "[CACHE-INVALIDATION] Rejected" in caplog.text
        assert f"status={status_code}" in caplog.text

    def test_network_error_raises_and_logs_warning(self, requests_mock, caplog):
        """A connection failure propagates and is logged"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(
            client_profile.webhook_url, exc=requests.exceptions.ConnectTimeout
        )

        with pytest.raises(requests.exceptions.ConnectTimeout):
            client_profile.send_cache_invalidation("user", [str(uuid4())])

        assert "[CACHE-INVALIDATION] Network failure" in caplog.text

    def test_error_response_body_is_truncated(self, requests_mock, caplog):
        """A client's debug HTML error page does not flood the log"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=500, text="x" * 5000)

        with pytest.raises(requests.HTTPError):
            client_profile.send_cache_invalidation("user", [str(uuid4())])

        assert "x" * ERROR_BODY_CHARS in caplog.text
        assert "x" * (ERROR_BODY_CHARS + 1) not in caplog.text

    def test_logs_every_uuid_at_threshold(self, requests_mock, caplog):
        """An interactive-sized batch logs every uuid, so it can be traced"""
        caplog.set_level(logging.INFO, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)
        uuids = [str(uuid4()) for _ in range(UUID_LOG_THRESHOLD)]

        client_profile.send_cache_invalidation("organization", uuids)

        assert f"count={UUID_LOG_THRESHOLD}" in caplog.text
        for uuid in uuids:
            assert uuid in caplog.text
        assert "more" not in caplog.text

    def test_bulk_batch_is_abbreviated(self, requests_mock, caplog):
        """A bulk batch logs a sample and a remainder, not thousands of uuids

        restore_organization sends every due org in one batch. The full list
        would exceed Heroku's 10KB per-line limit and be truncated by the log
        drain anyway.
        """
        caplog.set_level(logging.INFO, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)
        uuids = [str(uuid4()) for _ in range(500)]

        client_profile.send_cache_invalidation("organization", uuids)

        assert "count=500" in caplog.text
        assert f"+{500 - UUID_LOG_SAMPLE} more" in caplog.text
        for uuid in uuids[:UUID_LOG_SAMPLE]:
            assert uuid in caplog.text
        assert uuids[UUID_LOG_SAMPLE] not in caplog.text
        # the whole line stays well inside the log drain's per-line limit
        assert len(caplog.text) < 1024

    def test_failure_logs_every_uuid(self, requests_mock, caplog):
        """A rejected delivery names every uuid the client did not receive"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=502)
        uuids = [str(uuid4()) for _ in range(5)]

        with pytest.raises(requests.HTTPError):
            client_profile.send_cache_invalidation("organization", uuids)

        for uuid in uuids:
            assert uuid in caplog.text

    def test_bulk_failure_is_abbreviated(self, requests_mock, caplog):
        """A failed bulk delivery reports its size without the full list"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=502)
        uuids = [str(uuid4()) for _ in range(500)]

        with pytest.raises(requests.HTTPError):
            client_profile.send_cache_invalidation("organization", uuids)

        assert f"+{500 - UUID_LOG_SAMPLE} more" in caplog.text
        assert uuids[UUID_LOG_SAMPLE] not in caplog.text

    def test_success_logs_webhook_url_and_id(self, requests_mock, caplog):
        """A send names the endpoint it reached and the broadcast it belongs to

        With several clients configured, the client name alone does not say
        which URL a delivery went to after a webhook_url is changed.
        """
        caplog.set_level(logging.INFO, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)

        client_profile.send_cache_invalidation(
            "user", [str(uuid4())], invalidation_id="abc12345"
        )

        assert f"url={client_profile.webhook_url}" in caplog.text
        assert "id=abc12345" in caplog.text

    def test_rejection_logs_webhook_url_and_id(self, requests_mock, caplog):
        """A rejected delivery names the endpoint that rejected it"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=502)

        with pytest.raises(requests.HTTPError):
            client_profile.send_cache_invalidation(
                "user", [str(uuid4())], invalidation_id="abc12345"
            )

        assert f"url={client_profile.webhook_url}" in caplog.text
        assert "id=abc12345" in caplog.text

    def test_network_failure_logs_webhook_url_and_id(self, requests_mock, caplog):
        """A network failure names the endpoint that could not be reached"""
        caplog.set_level(logging.WARNING, logger="squarelet.oidc.models")
        client_profile = ClientProfileFactory()
        requests_mock.post(
            client_profile.webhook_url, exc=requests.exceptions.ConnectTimeout
        )

        with pytest.raises(requests.exceptions.ConnectTimeout):
            client_profile.send_cache_invalidation(
                "user", [str(uuid4())], invalidation_id="abc12345"
            )

        assert f"url={client_profile.webhook_url}" in caplog.text
        assert "id=abc12345" in caplog.text

    def test_timeout_is_connect_read_tuple(self, requests_mock):
        """A stuck handshake must not pin a worker for the full read timeout"""
        client_profile = ClientProfileFactory()
        requests_mock.post(client_profile.webhook_url, status_code=200)

        client_profile.send_cache_invalidation("user", [str(uuid4())])

        assert requests_mock.last_request.timeout == (5, 30)
