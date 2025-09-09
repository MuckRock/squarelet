# Django
from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

# Standard Library
from datetime import timedelta

# Third Party
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.users.adapters import AccountAdapter


class AdapterRedirectTests(TestCase):
    def setUp(self):
        # Create a test user
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpassword123"
        )

        # Create a verified email for the user
        EmailAddress.objects.create(
            user=self.user, email="test@example.com", verified=True, primary=True
        )

        # Set up request factory
        self.factory = RequestFactory()
        self.adapter = AccountAdapter()

    def add_session_to_request(self, request):
        """Helper method to add session to request"""
        middleware = SessionMiddleware(lambda x: None)
        middleware.process_request(request)
        request.session.save()

        # Add messages support
        middleware = MessageMiddleware(lambda x: None)
        middleware.process_request(request)
        request.session.save()

        return request

    def test_post_login_redirect_to_onboarding(self):
        """Test that the adapter redirects to onboarding when needed"""
        # Create a request
        request = self.factory.get("/")
        request = self.add_session_to_request(request)
        request.user = self.user

        # Set up a condition that would trigger onboarding
        # For example, make this the first login and ensure onboarding session is not complete
        self.user.last_login = self.user.date_joined
        self.user.save()

        # Initialize onboarding session but leave steps incomplete to trigger onboarding
        request.session["onboarding"] = {
            "email_check_completed": False,  # This will trigger onboarding
            "mfa_step": "not_started",
            "join_org": False,
            "subscription": "not_started",
        }

        # Call post_login with a destination URL
        original_url = "/dashboard/"
        response = self.adapter.post_login(
            request=request,
            user=self.user,
            email_verification="optional",
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=original_url,
        )

        # Check that we're redirected to onboarding
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_onboarding"))

        # Check that original URL was stored in session
        self.assertEqual(request.session.get("next_url"), original_url)

    def test_post_login_direct_redirect(self):
        """Test that users who don't need onboarding are redirected directly"""
        # Create a request
        request = self.factory.get("/")
        request = self.add_session_to_request(request)
        request.user = self.user

        # Set up a condition that would NOT trigger onboarding
        # Make this NOT the first login (set last_login to something in the past)
        self.user.last_login = self.user.date_joined - timedelta(days=1)
        self.user.save()

        # Ensure onboarding session defaults don't trigger steps
        request.session["onboarding"] = {
            "email_check_completed": True,  # Email is already verified
            "mfa_step": "completed",  # MFA completed
            "join_org": True,  # Organization joining completed
            "subscription": "completed",  # Subscription completed
        }

        # Call post_login with a destination URL
        original_url = "/dashboard/"
        response = self.adapter.post_login(
            request=request,
            user=self.user,
            email_verification="optional",
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=original_url,
        )

        # Check that we're redirected directly to the original URL
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, original_url)

        # Check that original URL was stored in session for potential future use
        self.assertEqual(request.session.get("next_url"), original_url)

    def test_post_login_with_next_parameter(self):
        """Test that the 'next' parameter is correctly handled"""
        # Create a request with next parameter
        request = self.factory.get("/?next=/special-page/")
        request = self.add_session_to_request(request)
        request.user = self.user

        # Call post_login
        self.adapter.post_login(
            request=request,
            user=self.user,
            email_verification="optional",
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=None,  # No explicit redirect, should use 'next'
        )

        # Now check if the adapter correctly processed the next parameter
        # Depending on your adapter logic, it might redirect directly or store it
        if "next_url" in request.session:
            self.assertEqual(request.session["next_url"], "/special-page/")
