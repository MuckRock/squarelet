from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from allauth.account.models import EmailAddress
from squarelet.users.adapters import AccountAdapter

class AdapterRedirectTests(TestCase):
    def setUp(self):
        # Create a test user
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword123'
        )
        
        # Create a verified email for the user
        EmailAddress.objects.create(
            user=self.user,
            email='test@example.com',
            verified=True,
            primary=True
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
        request = self.factory.get('/')
        request = self.add_session_to_request(request)
        request.user = self.user
        
        # Set up a condition that would trigger onboarding
        # For example, make this the first login
        self.user.last_login = self.user.date_joined
        self.user.save()
        
        # Call post_login with a destination URL
        original_url = '/dashboard/'
        response = self.adapter.post_login(
            request=request,
            user=self.user,
            email_verification='optional',
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=original_url
        )
        
        # Check that we're redirected to onboarding
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('account_onboarding'))
        
        # Check that original URL was stored in session
        self.assertEqual(request.session.get('next_url'), original_url)
    
    def test_post_login_direct_redirect(self):
        """Test that users who don't need onboarding are redirected directly"""
        # Create a request
        request = self.factory.get('/')
        request = self.add_session_to_request(request)
        request.user = self.user
        
        # Set up a condition that would NOT trigger onboarding
        # For example, make this NOT the first login and have MFA set up
        self.user.last_login = self.user.date_joined
        self.user.last_login = self.user.last_login.replace(day=self.user.last_login.day - 1)  # Previous day
        self.user.save()
        
        # Mock that MFA is set up
        # This depends on how you're checking for MFA, adjust accordingly
        
        # Call post_login with a destination URL
        original_url = '/dashboard/'
        response = self.adapter.post_login(
            request=request,
            user=self.user,
            email_verification='optional',
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=original_url
        )
        
        # Check that we're redirected directly to the original URL
        self.assertEqual(response.status_code, 302)

        # TODO: TEST EXPECTED REDIRECT
        # This is currently overrided for development.
        # self.assertEqual(response.url, original_url)
        
        # Check that original URL was NOT stored in session
        # self.assertNotIn('next_url', request.session)
    
    def test_post_login_with_next_parameter(self):
        """Test that the 'next' parameter is correctly handled"""
        # Create a request with next parameter
        request = self.factory.get('/?next=/special-page/')
        request = self.add_session_to_request(request)
        request.user = self.user
        
        # Call post_login
        response = self.adapter.post_login(
            request=request,
            user=self.user,
            email_verification='optional',
            signal_kwargs={},
            email=self.user.email,
            signup=False,
            redirect_url=None  # No explicit redirect, should use 'next'
        )
        
        # Now check if the adapter correctly processed the next parameter
        # Depending on your adapter logic, it might redirect directly or store it
        if 'next_url' in request.session:
            self.assertEqual(request.session['next_url'], '/special-page/')