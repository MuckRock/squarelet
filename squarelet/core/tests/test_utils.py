# Django
from django.conf import settings
from django.test import TestCase, override_settings

# Standard Library
import hashlib
from unittest.mock import MagicMock, patch

# Third Party
import requests

# Squarelet
from squarelet.core.utils import file_path, mailchimp_journey


def test_file_path_normal():
    """File path just appends base and filename if under the limit"""
    assert file_path("base", None, "filename.ext") == "base/filename.ext"


def test_file_path_long():
    """File path truncates the file name if necessary"""
    file_name = "a" * 100 + ".ext"
    assert len(file_path("base", None, file_name)) == 92


@override_settings(
    ENV="production",
    MAILCHIMP_API_KEY="test-api-key-12345",
    MAILCHIMP_API_ROOT="https://us1.api.mailchimp.com/3.0",
)
class TestMailchimpJourney(TestCase):
    def setUp(self):
        self.email = "test@example.com"
        self.journey = "welcome_sq"
        self.journey_id = 24
        self.step_id = 303
        self.list_id = "20aa4a931d"
        self.subscriber_hash = hashlib.md5(self.email.lower().encode()).hexdigest()
        self.audience_url = (
            f"{settings.MAILCHIMP_API_ROOT}/lists/"
            f"{self.list_id}/members/{self.subscriber_hash}"
        )
        self.journey_url = (
            f"{settings.MAILCHIMP_API_ROOT}/customer-journeys/journeys/"
            f"{self.journey_id}/steps/{self.step_id}/actions/trigger"
        )
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"apikey {settings.MAILCHIMP_API_KEY}",
        }

    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    def test_successful_journey(self, mock_post, mock_put):
        # Mock successful API responses
        mock_put_response = MagicMock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post.return_value = mock_post_response

        # Call the function and verify
        response = mailchimp_journey(self.email, self.journey)
        mock_put.assert_called_once_with(
            self.audience_url,
            json={"email_address": self.email, "status": "subscribed"},
            headers=self.headers,
        )
        mock_post.assert_called_once_with(
            self.journey_url, json={"email_address": self.email}, headers=self.headers
        )
        assert response == mock_post_response

    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    @patch("squarelet.core.utils.logger.error")
    def test_audience_error(self, mock_logger, mock_post, mock_put):
        # Mocks an audience error
        mock_put_response = MagicMock()
        mock_put_response.status_code = 400
        mock_put_response.text = "Error message"
        mock_put.return_value = mock_put_response

        # Mocks a journey success
        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post.return_value = mock_post_response

        # Call the function and verify
        response = mailchimp_journey(self.email, self.journey)
        mock_logger.assert_called_once()
        mock_post.assert_called_once()
        assert response == mock_post_response

    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    @patch("squarelet.core.utils.logger.error")
    def test_journey_error(self, mock_logger, mock_post, mock_put):
        # Mock an audience success
        mock_put_response = MagicMock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock a journey error
        mock_post_response = MagicMock()
        mock_post_response.status_code = 400
        mock_post_response.text = "Error message"
        mock_post.return_value = mock_post_response

        # Call the function and verify
        response = mailchimp_journey(self.email, self.journey)
        mock_logger.assert_called_once()
        assert response == mock_post_response

    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    @patch("squarelet.core.utils.logger.error")
    def test_connection_error_audience(self, mock_logger, mock_post, mock_put):
        # Mock an audience connection error
        mock_put.side_effect = requests.ConnectionError("Connection error")

        # Mock a journey success
        mock_post_response = MagicMock()
        mock_post_response.status_code = 200
        mock_post.return_value = mock_post_response

        # Call the function and verify logger is called
        mailchimp_journey(self.email, self.journey)
        assert mock_logger.call_count == 1

    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    @patch("squarelet.core.utils.logger.error")
    def test_connection_error_journey(self, mock_logger, mock_post, mock_put):
        # Mock an audience success
        mock_put_response = MagicMock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock a connection error for the journey
        mock_post.side_effect = requests.ConnectionError("Connection error")

        # Call the function and verify logger is called
        mailchimp_journey(self.email, self.journey)
        assert mock_logger.call_count == 1
