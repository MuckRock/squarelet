# Django
from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.test import TestCase, override_settings

# Standard Library
import hashlib
from unittest.mock import MagicMock, patch

# Third Party
import requests
import stripe

# Squarelet
from squarelet.core.utils import (
    create_zendesk_ticket,
    file_path,
    format_stripe_error,
    get_redirect_url,
    mailchimp_journey,
    pluralize,
)


def test_file_path_normal():
    """File path just appends base and filename if under the limit"""
    assert file_path("base", None, "filename.ext") == "base/filename.ext"


def test_file_path_long():
    """File path truncates the file name if necessary"""
    file_name = "a" * 100 + ".ext"
    assert len(file_path("base", None, file_name)) == 92


def test_pluralize():
    # Pluralize returns plural form for counts other than 1
    assert pluralize(0, "invitation") == "invitations"
    assert pluralize(2, "invitation") == "invitations"
    assert pluralize(5, "invitation") == "invitations"
    assert pluralize(100, "invitation") == "invitations"
    assert pluralize(0, "category") == "categories"
    assert pluralize(2, "octopus") == "octopi"
    assert pluralize(5, "sheep") == "sheep"

    # Pluralize returns word itself for count of 1
    assert pluralize(1, "hamburger") == "hamburger"
    assert pluralize(1, "trophy") == "trophy"

    # Test in strings
    assert f"1 {pluralize(1, 'invitation')}" == "1 invitation"
    assert f"5 {pluralize(5, 'invitation')}" == "5 invitations"
    assert f"1 {pluralize(1, 'category')}" == "1 category"
    assert f"5 {pluralize(5, 'category')}" == "5 categories"


@override_settings(
    ENV="prod",
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

    @override_settings(ENV="dev", MAILCHIMP_API_KEY="test-key")
    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    def test_mailchimp_journey_skipped_in_dev_environment(self, mock_post, mock_put):
        """MailChimp journey should be skipped in dev environment"""
        result = mailchimp_journey(self.email, self.journey)
        assert result is None
        mock_put.assert_not_called()
        mock_post.assert_not_called()

    @override_settings(ENV="staging", MAILCHIMP_API_KEY="test-key")
    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    def test_mailchimp_journey_skipped_in_staging_environment(
        self, mock_post, mock_put
    ):
        """MailChimp journey should be skipped in staging environment"""
        result = mailchimp_journey(self.email, self.journey)
        assert result is None
        mock_put.assert_not_called()
        mock_post.assert_not_called()

    @override_settings(ENV="prod", MAILCHIMP_API_KEY="")
    @patch("squarelet.core.utils.requests.put")
    @patch("squarelet.core.utils.requests.post")
    def test_mailchimp_journey_skipped_without_api_key(self, mock_post, mock_put):
        """MailChimp journey should be skipped when API key is missing"""
        result = mailchimp_journey(self.email, self.journey)
        assert result is None
        mock_put.assert_not_called()
        mock_post.assert_not_called()

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


class TestFormatStripeError:
    """Test the format_stripe_error utility function"""

    def test_card_error_expired_card(self):
        """CardError with expired_card code should show detailed user message"""
        error = stripe.error.CardError(
            message="Your card has expired.",
            param="exp_month",
            code="expired_card",
        )
        user_message = format_stripe_error(error)

        assert "expired" in user_message.lower()

    def test_card_error_card_declined(self):
        """CardError with card_declined code should show detailed user message"""
        error = stripe.error.CardError(
            message="Your card was declined.",
            param="card",
            code="card_declined",
        )
        user_message = format_stripe_error(error)

        assert "declined" in user_message.lower()

    def test_card_error_insufficient_funds(self):
        """CardError with insufficient_funds code should show detailed user message"""
        error = stripe.error.CardError(
            message="Your card has insufficient funds.",
            param="card",
            code="insufficient_funds",
        )
        user_message = format_stripe_error(error)

        assert "insufficient funds" in user_message.lower()

    def test_card_error_incorrect_cvc(self):
        """CardError with incorrect_cvc code should show detailed user message"""
        error = stripe.error.CardError(
            message="Your card's security code is incorrect.",
            param="cvc",
            code="incorrect_cvc",
        )
        user_message = format_stripe_error(error)

        assert "security code" in user_message.lower() or "cvc" in user_message.lower()

    def test_card_error_processing_error(self):
        """CardError with processing_error code should show detailed user message"""
        error = stripe.error.CardError(
            message="An error occurred while processing your card.",
            param="card",
            code="processing_error",
        )
        user_message = format_stripe_error(error)

        assert (
            "processing" in user_message.lower() or "try again" in user_message.lower()
        )

    def test_card_error_generic(self):
        """Generic CardError should use Stripe's user message"""
        error = stripe.error.CardError(
            message="Your card was declined for an unknown reason.",
            param="card",
            code="generic_decline",
        )
        user_message = format_stripe_error(error)

        assert len(user_message) > 0
        assert "card" in user_message.lower() or "declined" in user_message.lower()

    def test_api_connection_error(self):
        """APIConnectionError should show generic message"""
        error = stripe.error.APIConnectionError("Network connection failed")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()
        assert "try again" in user_message.lower()

    def test_rate_limit_error(self):
        """RateLimitError should show generic message"""
        error = stripe.error.RateLimitError("Too many requests")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()
        assert "try again" in user_message.lower()

    def test_api_error(self):
        """APIError should show generic message"""
        error = stripe.error.APIError("Internal server error")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()
        assert "try again" in user_message.lower()

    def test_invalid_request_error(self):
        """InvalidRequestError should show generic message"""
        error = stripe.error.InvalidRequestError(
            message="Invalid request", param="amount"
        )
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()

    def test_authentication_error(self):
        """AuthenticationError should show generic message"""
        error = stripe.error.AuthenticationError("Invalid API key")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()

    def test_idempotency_error(self):
        """IdempotencyError should show generic message"""
        error = stripe.error.IdempotencyError("Idempotency key reused")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()
        assert "try again" in user_message.lower()

    def test_permission_error(self):
        """PermissionError should show generic message"""
        error = stripe.error.PermissionError("Insufficient permissions")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()

    def test_generic_stripe_error(self):
        """Generic StripeError should show generic message"""
        error = stripe.error.StripeError("Unknown error")
        user_message = format_stripe_error(error)

        assert "contact" in user_message.lower() or "support" in user_message.lower()

    def test_technical_error_includes_mailto_link(self):
        """Technical errors should include a mailto link with error details"""
        error = stripe.error.APIError("Internal server error")
        user_message = format_stripe_error(error)

        # Check that the message contains an HTML mailto link
        assert '<a href="mailto:info@muckrock.com' in user_message
        assert "contact support</a>" in user_message

        # Check that the subject and body are URL encoded
        assert "subject=Payment" in user_message
        assert "body=Error" in user_message

        # Check that error details are included in the body
        assert "APIError" in user_message
        assert (
            "Internal%20server%20error" in user_message
            or "Internal server error" in user_message
        )


class TestGetRedirectUrl:
    """Test the get_redirect_url utility function"""

    def test_redirect_with_referer(self):
        """Test redirect uses HTTP_REFERER when available"""
        request = HttpRequest()
        request.META["HTTP_REFERER"] = "/previous/page/"

        response = get_redirect_url(request, "/fallback/page/")

        assert isinstance(response, HttpResponseRedirect)
        assert response.url == "/previous/page/"

    def test_redirect_without_referer_string_fallback(self):
        """Test redirect uses string fallback when no HTTP_REFERER"""
        request = HttpRequest()

        response = get_redirect_url(request, "/fallback/page/")

        assert isinstance(response, HttpResponseRedirect)
        assert response.url == "/fallback/page/"

    def test_redirect_without_referer_httpresponse_fallback(self):
        """Test redirect uses HttpResponseRedirect fallback when no HTTP_REFERER"""
        request = HttpRequest()
        fallback = HttpResponseRedirect("/fallback/page/")

        response = get_redirect_url(request, fallback)

        assert response is fallback
        assert response.url == "/fallback/page/"

    def test_redirect_empty_referer(self):
        """Test redirect uses fallback when HTTP_REFERER is empty"""
        request = HttpRequest()
        request.META["HTTP_REFERER"] = ""

        response = get_redirect_url(request, "/fallback/page/")

        assert isinstance(response, HttpResponseRedirect)
        assert response.url == "/fallback/page/"


@override_settings(
    ENV="prod",
    ZENDESK_EMAIL="test@example.com",
    ZENDESK_TOKEN="test-token-12345",
    ZENDESK_SUBDOMAIN="test-subdomain",
)
class TestCreateZendeskTicket(TestCase):
    def setUp(self):
        self.subject = "Test Ticket"
        self.description = "This is a test ticket description"
        self.priority = "high"
        self.tags = ["test", "automated"]

    @override_settings(ENV="dev")
    @patch("squarelet.core.utils.Zenpy")
    def test_zendesk_ticket_skipped_in_dev_environment(self, mock_zenpy):
        """Zendesk ticket creation should be skipped in dev environment"""
        result = create_zendesk_ticket(self.subject, self.description)
        assert result is None
        mock_zenpy.assert_not_called()

    @override_settings(ENV="staging")
    @patch("squarelet.core.utils.Zenpy")
    def test_zendesk_ticket_skipped_in_staging_environment(self, mock_zenpy):
        """Zendesk ticket creation should be skipped in staging environment"""
        result = create_zendesk_ticket(self.subject, self.description)
        assert result is None
        mock_zenpy.assert_not_called()

    @override_settings(ZENDESK_EMAIL="")
    @patch("squarelet.core.utils.Zenpy")
    def test_zendesk_ticket_skipped_without_email(self, mock_zenpy):
        """Zendesk ticket creation should be skipped when email is missing"""
        result = create_zendesk_ticket(self.subject, self.description)
        assert result is None
        mock_zenpy.assert_not_called()

    @override_settings(ZENDESK_TOKEN="")
    @patch("squarelet.core.utils.Zenpy")
    def test_zendesk_ticket_skipped_without_token(self, mock_zenpy):
        """Zendesk ticket creation should be skipped when token is missing"""
        result = create_zendesk_ticket(self.subject, self.description)
        assert result is None
        mock_zenpy.assert_not_called()

    @override_settings(ZENDESK_SUBDOMAIN="")
    @patch("squarelet.core.utils.Zenpy")
    def test_zendesk_ticket_skipped_without_subdomain(self, mock_zenpy):
        """Zendesk ticket creation should be skipped when subdomain is missing"""
        result = create_zendesk_ticket(self.subject, self.description)
        assert result is None
        mock_zenpy.assert_not_called()

    @patch("squarelet.core.utils.Zenpy")
    def test_successful_ticket_creation(self, mock_zenpy):
        """Test successful ticket creation with all parameters"""
        # Mock Zenpy client and ticket creation
        mock_client_instance = MagicMock()
        mock_zenpy.return_value = mock_client_instance

        mock_created_ticket = MagicMock()
        mock_created_ticket.id = 12345
        mock_client_instance.tickets.create.return_value = mock_created_ticket

        # Call the function
        result = create_zendesk_ticket(
            self.subject, self.description, self.priority, self.tags
        )

        # Verify Zenpy was initialized with correct credentials
        mock_zenpy.assert_called_once_with(
            email=settings.ZENDESK_EMAIL,
            token=settings.ZENDESK_TOKEN,
            subdomain=settings.ZENDESK_SUBDOMAIN,
        )

        # Verify ticket was created
        mock_client_instance.tickets.create.assert_called_once()

        # Verify the created ticket was returned
        assert result == mock_created_ticket
        assert result.id == 12345

    @patch("squarelet.core.utils.Zenpy")
    def test_ticket_creation_with_default_priority(self, mock_zenpy):
        """Test ticket creation uses default priority when not specified"""
        mock_client_instance = MagicMock()
        mock_zenpy.return_value = mock_client_instance

        mock_created_ticket = MagicMock()
        mock_created_ticket.id = 12346
        mock_client_instance.tickets.create.return_value = mock_created_ticket

        # Call without specifying priority
        result = create_zendesk_ticket(self.subject, self.description)

        # Verify ticket was created
        mock_client_instance.tickets.create.assert_called_once()
        assert result == mock_created_ticket

    @patch("squarelet.core.utils.Zenpy")
    def test_ticket_creation_with_no_tags(self, mock_zenpy):
        """Test ticket creation handles no tags correctly"""
        mock_client_instance = MagicMock()
        mock_zenpy.return_value = mock_client_instance

        mock_created_ticket = MagicMock()
        mock_created_ticket.id = 12347
        mock_client_instance.tickets.create.return_value = mock_created_ticket

        # Call without tags
        result = create_zendesk_ticket(self.subject, self.description)

        # Verify ticket was created
        mock_client_instance.tickets.create.assert_called_once()
        assert result == mock_created_ticket

    @patch("squarelet.core.utils.Zenpy")
    @patch("squarelet.core.utils.logger.error")
    def test_ticket_creation_failure(self, mock_logger, mock_zenpy):
        """Test that errors during ticket creation are logged and re-raised"""
        mock_client_instance = MagicMock()
        mock_zenpy.return_value = mock_client_instance

        # Simulate an exception during ticket creation
        test_exception = Exception("Zendesk API error")
        mock_client_instance.tickets.create.side_effect = test_exception

        # Verify the exception is raised
        try:
            create_zendesk_ticket(self.subject, self.description)
            assert False, "Expected exception was not raised"
        except Exception as exc:  # pylint: disable=broad-except
            assert exc == test_exception

        # Verify error was logged
        mock_logger.assert_called_once()
        assert "Failed to create Zendesk ticket" in str(mock_logger.call_args)
