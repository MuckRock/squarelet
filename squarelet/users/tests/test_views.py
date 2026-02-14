# Django
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http.response import Http404

# Standard Library
import hashlib
import hmac
import json
import time

# Third Party
import pytest
from allauth.account.models import EmailAddress

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.models import Invitation
from squarelet.organizations.models.payment import Plan
from squarelet.users import views

# pylint: disable=too-many-lines, too-many-positional-arguments

@pytest.mark.django_db()
class TestUserDetailView(ViewTestMixin):
    """Test the User Detail view"""

    view = views.UserDetailView
    url = "/users/{username}/"

    def test_get(self, rf, user_factory):
        user = user_factory()
        response = self.call_view(rf, user, username=user.username)
        assert response.status_code == 200
        assert list(response.context_data["other_orgs"]) == list(
            user.organizations.filter(individual=False)
        )

    def test_get_bad(self, rf, user_factory):
        user = user_factory()
        other_user = user_factory()
        with pytest.raises(Http404):
            self.call_view(rf, other_user, username=user.username)

    def test_primary_email_first(self, rf, user_factory):
        """Test that primary email appears first in the emails list"""

        user = user_factory()
        # Clear any existing email addresses
        EmailAddress.objects.filter(user=user).delete()

        # Assign multiple email addresses to the user,
        # such that the primary is not alphabetically first
        EmailAddress.objects.create(
            user=user, email="a-first@example.com", primary=False, verified=True
        )
        EmailAddress.objects.create(
            user=user, email="z-last@example.com", primary=True, verified=True
        )
        EmailAddress.objects.create(
            user=user,
            email="m-middle@example.com",
            primary=False,
            verified=False,
        )

        response = self.call_view(rf, user, username=user.username)
        assert response.status_code == 200

        # Get the emails from context
        emails = list(response.context_data["emails"])

        # We should have all three emails
        assert len(emails) == 3

        # The primary email should be first
        assert emails[0].primary is True
        assert emails[0].email == "z-last@example.com"

        # The other non-primary emails should follow alphabetically
        assert emails[1].primary is False
        assert emails[1].email == "a-first@example.com"
        assert emails[2].primary is False
        assert emails[2].email == "m-middle@example.com"


@pytest.mark.django_db()
class TestUserRedirectView(ViewTestMixin):
    """Test the User Redirect view"""

    view = views.UserRedirectView
    url = "/users/~redirect/"

    def test_get(self, rf, user_factory):
        user = user_factory()
        response = self.call_view(rf, user, target_view="detail")
        assert response.status_code == 302
        assert response.url == f"/users/{user.username}/"


@pytest.mark.django_db()
class TestUserUpdateView(ViewTestMixin):
    """Test the User Update view"""

    view = views.UserUpdateView
    url = "/users/~update/"

    def test_get(self, rf, user_factory):
        user = user_factory()
        response = self.call_view(rf, user, username=user.username)
        assert response.status_code == 200
        assert "username" in response.context_data["form"].fields
        assert response.context_data["object"] == user

    def test_get_username_changed(self, rf, user_factory):
        user = user_factory(can_change_username=False)
        response = self.call_view(rf, user, username=user.username)
        assert response.status_code == 200
        assert response.context_data["form"].fields["username"].disabled is True

    def test_post(self, rf, user_factory):
        user = user_factory()
        data = {"name": "John Doe", "username": "john.doe", "use_autologin": False}
        response = self.call_view(rf, user, data=data, username=user.username)
        user.refresh_from_db()
        assert response.status_code == 302
        assert response.url == "/users/john.doe/"
        assert user.name == data["name"]
        assert user.username == data["username"]
        assert not user.can_change_username
        assert user.individual_organization.name == data["username"]

    def test_bad_post(self, rf, user_factory):
        user = user_factory()
        # @ symbols not allowed in usernames
        data = {"name": "John Doe", "username": "john@doe", "use_autologin": False}
        response = self.call_view(rf, user, data=data, username=user.username)
        user.refresh_from_db()
        assert response.status_code == 200
        assert user.name != data["name"]
        assert user.username != data["username"]
        assert response.context_data["object"].username != data["username"]

    def test_username_change(self, rf, user_factory):
        user = user_factory(username="johndoe", can_change_username=False)
        data = {"name": "John Doe", "username": "johnnydoe", "use_autologin": False}
        response = self.call_view(rf, user, data=data, username=user.username)
        user.refresh_from_db()
        assert user.username != data["username"]
        # There should be no error, the username shouldn't change
        assert response.status_code == 302


@pytest.mark.django_db()
class TestLoginView(ViewTestMixin):
    """Test the User Redirect view"""

    view = views.LoginView
    url = "/accounts/login/"

    def test_get_url_auth_token(self, rf, mocker):
        """Test handling of lingering url_auth_token parameter"""
        next_url = "/target/url/"
        params = {"sesame": "token", "next": next_url}
        request = rf.get(self.url, params)
        request.user = AnonymousUser()
        request.session = mocker.MagicMock()
        response = self.view.as_view()(request)
        assert response.status_code == 302
        assert response.url == f"{settings.MUCKROCK_URL}{next_url}"


class TestMailgunWebhook:
    def call_view(self, rf, data):
        self.sign(data)
        request = rf.post(
            "/users/~mailgun/", json.dumps(data), content_type="application/json"
        )
        return views.mailgun_webhook(request)

    def sign(self, data):
        token = "token"
        timestamp = int(time.time())
        signature = hmac.new(
            key=settings.MAILGUN_ACCESS_KEY.encode("utf8"),
            msg=f"{timestamp}{token}".encode("utf8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        data["signature"] = {
            "token": token,
            "timestamp": timestamp,
            "signature": str(signature),
        }

    @pytest.mark.django_db()
    def test_simple(self, rf, user_factory):
        """Succesful request"""
        user = user_factory(email="mitch@example.com", email_failed=False)
        event = {"event-data": {"event": "failed", "recipient": "mitch@example.com"}}
        response = self.call_view(rf, event)
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.email_failed

    @pytest.mark.django_db()
    def test_ignored(self, rf, user_factory):
        """Non-fail events are ignored"""
        user = user_factory(email="mitch@example.com", email_failed=False)
        event = {"event-data": {"event": "bounced", "receipient": "mitch@example.com"}}
        response = self.call_view(rf, event)
        assert response.status_code == 200
        user.refresh_from_db()
        assert not user.email_failed

    def test_get(self, rf):
        """GET requests should fail"""
        request = rf.get("/users/~mailgun/")
        response = views.mailgun_webhook(request)
        assert response.status_code == 405

    def test_missing_event(self, rf):
        """Missing event-data should fail"""
        event = {"foo": "bar"}
        response = self.call_view(rf, event)
        assert response.status_code == 400

    def test_missing_recipient(self, rf):
        """Succesful request"""
        event = {"event-data": {"event": "failed"}}
        response = self.call_view(rf, event)
        assert response.status_code == 400

    def test_signature_verification(self, rf):
        """Signature verification error should fail"""
        event = {"event-data": {"event": "failed", "receipient": "mitch@example.com"}}
        request = rf.post(
            "/users/~mailgun/", json.dumps(event), content_type="application/json"
        )
        response = views.mailgun_webhook(request)
        assert response.status_code == 403

    def test_bad_json(self, rf):
        """Malformed JSON should fail"""
        request = rf.post(
            "/users/~mailgun/", "{'malformed json'", content_type="application/json"
        )
        response = views.mailgun_webhook(request)
        assert response.status_code == 400


@pytest.mark.django_db()
class TestReceipts(ViewTestMixin):
    """Test the User Receipts view"""

    view = views.Receipts
    url = "/users/~receipts/"

    def test_get_admin(self, rf, organization_factory, user_factory, charge_factory):
        user = user_factory()
        organization = organization_factory(admins=[user])
        charge_factory(organization=organization)
        response = self.call_view(rf, user, username=user.username)
        assert response.status_code == 200


@pytest.mark.django_db()
class TestUserOnboardingView(ViewTestMixin):
    """Test the User Onboarding view"""

    # pylint: disable=too-many-public-methods, disable=unused-argument

    view = views.UserOnboardingView
    url = "/accounts/onboard/"

    @pytest.fixture
    def mock_session(self):
        """Create a mock session with onboarding defaults"""
        return {
            "onboarding": {
                "email_check_completed": False,
                "mfa_step": "not_started",
                "join_org": False,
                "subscription": "not_started",
            }
        }

    @pytest.fixture
    def subscription_plans(self, mocker):
        """Mock subscription plans"""
        individual_plan = mocker.MagicMock()
        individual_plan.slug = "professional"
        individual_plan.name = "Professional"
        individual_plan.pk = 1

        group_plan = mocker.MagicMock()
        group_plan.slug = "organization"
        group_plan.name = "Organization"
        group_plan.pk = 2

        # Mock Plan.objects.get to handle both slug and pk lookups
        def get_plan(slug=None, pk=None, **kwargs):
            # Handle pk lookup
            if pk in ("1", 1):
                return individual_plan
            elif pk in ("2", 2):
                return group_plan
            # Handle slug lookup
            elif slug == "professional":
                return individual_plan
            elif slug == "organization":
                return group_plan
            else:
                raise Plan.DoesNotExist()

        mocker.patch(
            "squarelet.users.onboarding.Plan.objects.get", side_effect=get_plan
        )
        return {"individual": individual_plan, "group": group_plan}

    @pytest.fixture
    def mock_django_session(self):
        """Create a mock Django session that behaves like the real thing"""

        class MockSession(dict):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.modified = False

        return MockSession

    # ===== HELPER METHODS =====

    def _mock_user_state(self, mocker, user, **kwargs):
        """Mock common user state properties with sensible defaults"""
        defaults = {
            "has_verified_email": True,
            "has_organizations": True,
            "has_active_subscription": False,
            "has_mfa_enabled": True,
            "has_invitations": False,
            "has_unverified_emails": False,
        }
        defaults.update(kwargs)

        # Mock email verification
        mocker.patch(
            "squarelet.users.onboarding.has_verified_email",
            return_value=defaults["has_verified_email"],
        )

        # Mock organizations
        mock_org_queryset = mocker.MagicMock()
        mock_org_queryset.exists.return_value = defaults["has_organizations"]
        mocker.patch.object(
            user.organizations, "filter", return_value=mock_org_queryset
        )

        # Mock subscription status
        if hasattr(user, "individual_organization"):
            mocker.patch.object(
                user.individual_organization,
                "has_active_subscription",
                return_value=defaults["has_active_subscription"],
            )

        # Mock MFA status - patch the is_mfa_enabled function in the user model
        mocker.patch(
            "squarelet.users.models.is_mfa_enabled",
            return_value=defaults["has_mfa_enabled"],
        )

        # Mock invitations
        if defaults["has_invitations"]:
            mock_invitation = mocker.MagicMock()
            mocker.patch.object(
                user, "get_pending_invitations", return_value=[mock_invitation]
            )
        else:
            mocker.patch.object(user, "get_pending_invitations", return_value=[])

        # Mock potential organizations
        mock_potential_queryset = mocker.MagicMock()
        mock_potential_queryset.filter.return_value = []
        mocker.patch.object(
            user, "get_potential_organizations", return_value=mock_potential_queryset
        )

        # Mock unverified emails
        mock_email_queryset = mocker.MagicMock()
        mock_email_queryset.exists.return_value = defaults["has_unverified_emails"]
        mocker.patch(
            "squarelet.users.onboarding.EmailAddress.objects.filter",
            return_value=mock_email_queryset,
        )

        # Set user attributes
        if not hasattr(user, "last_mfa_prompt"):
            user.last_mfa_prompt = None

    def _mock_messages(self, mocker):
        """Mock Django messages framework to avoid middleware issues"""
        mocker.patch("squarelet.users.onboarding.messages.info")
        mocker.patch("squarelet.users.onboarding.messages.success")
        mocker.patch("squarelet.users.onboarding.messages.error")

    def _mock_mfa_forms(self, mocker, valid=True):
        """Mock MFA-related forms"""
        mock_form = mocker.MagicMock()
        mock_form.is_valid.return_value = valid
        mock_form.secret = "test_secret"
        mocker.patch(
            "allauth.mfa.totp.internal.auth.get_totp_secret", return_value="test_secret"
        )
        mocker.patch(
            "squarelet.users.onboarding.ActivateTOTPForm", return_value=mock_form
        )

        if valid:
            mocker.patch("squarelet.users.onboarding.activate_totp")

        # Mock adapter for TOTP
        mock_adapter = mocker.MagicMock()
        mock_adapter.build_totp_url.return_value = "otpauth://test"
        mock_adapter.build_totp_svg.return_value = "<svg>test</svg>"
        mocker.patch(
            "squarelet.users.onboarding.get_adapter", return_value=mock_adapter
        )
        mocker.patch(
            "squarelet.users.onboarding.base64.b64encode", return_value=b"dGVzdA=="
        )

        return mock_form

    def _mock_subscription_forms(self, mocker, valid=True):
        """Mock subscription-related forms"""
        mock_form = mocker.MagicMock()
        mock_form.is_valid.return_value = valid
        mock_form.save.return_value = valid

        mocker.patch(
            "squarelet.users.onboarding.PremiumSubscriptionForm", return_value=mock_form
        )

        return mock_form

    def _create_get_request(
        self, rf, user, mock_django_session, session_data=None, params=None
    ):
        """Create a GET request with common setup"""
        request = rf.get(self.url, params or {})
        request.user = user
        request.session = mock_django_session(session_data or {})
        return request

    def _create_post_request(
        self, rf, user, mock_django_session, data, session_data=None
    ):
        """Create a POST request with common setup"""
        request = rf.post(self.url, data)
        request.user = user
        request.session = mock_django_session(session_data or {})
        return request

    def _get_onboarding_step(self, request, mocker):
        """Get onboarding step with common mocking"""
        self._mock_messages(mocker)
        view = self.view()
        return view.get_onboarding_step(request)

    def _call_view_get(self, request, mocker, mock_email_send=True):
        """Call view GET with common mocking"""
        self._mock_messages(mocker)
        if mock_email_send:
            mocker.patch("squarelet.users.views.send_email_confirmation")
        view_instance = self.view.as_view()
        return view_instance(request)

    def _call_view_post(self, request, mocker):
        """Call view POST with common mocking"""
        self._mock_messages(mocker)
        view_instance = self.view.as_view()
        return view_instance(request)

    def _assert_step(
        self, step, expected_step, context=None, expected_context_keys=None
    ):
        """Assert onboarding step and context"""
        assert step == expected_step
        if expected_context_keys:
            for key in expected_context_keys:
                assert key in context

    def _assert_session_updated(self, session, key, expected_value):
        """Assert session was updated correctly"""
        if isinstance(key, str):
            assert session["onboarding"][key] == expected_value
        else:  # key is a dict for multiple updates
            for k, v in key.items():
                assert session["onboarding"][k] == v
        assert session.modified is True

    def _assert_redirect_to_onboard(self, response):
        """Assert redirect back to onboarding"""
        assert response.status_code == 302
        assert response.url == "/accounts/onboard/"

    def _assert_template(self, response, expected_template):
        """Assert correct template is used"""
        assert response.status_code == 200
        assert response.template_name == [expected_template]

    # ===== STEP LOGIC TESTS =====

    def test_get_onboarding_step_email_unverified(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with unverified email should get confirm_email step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)

        step, context = self._get_onboarding_step(request, mocker)

        self._assert_step(step, "confirm_email", context, ["email"])
        assert context["email"] == user.email

    def test_get_onboarding_step_email_verified(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with verified email should skip email step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=True)

        step, _ = self._get_onboarding_step(request, mocker)

        # Should skip email step and session should be updated
        assert request.session["onboarding"]["email_check_completed"] is True
        assert step is None  # Should complete onboarding

    def test_get_onboarding_step_join_org_with_invitations(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with pending invitations should get join_org step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": True, "join_org": False}},
        )

        self._mock_user_state(
            mocker, user, has_organizations=False, has_invitations=True
        )

        step, context = self._get_onboarding_step(request, mocker)

        self._assert_step(
            step,
            "join_org",
            context,
            ["invitations", "potential_orgs", "joinable_orgs_count"],
        )
        assert len(context["invitations"]) == 1
        assert context["joinable_orgs_count"] == 1

    def test_get_onboarding_step_join_org_already_has_orgs(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with existing organizations should skip join_org step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": True, "join_org": False}},
        )

        self._mock_user_state(mocker, user, has_organizations=True)

        step, _ = self._get_onboarding_step(request, mocker)

        assert step is None  # Should skip join_org and complete onboarding

    def test_get_onboarding_step_subscribe_with_valid_plan(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """User with valid plan in session should get subscribe step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                }
            },
            {"plan": "professional"},
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)

        step, context = self._get_onboarding_step(request, mocker)

        self._assert_step(step, "subscribe", context, ["plans"])
        assert context["plans"]["selected"].slug == "professional"

    def test_get_onboarding_step_subscribe_already_subscribed(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """User already subscribed to professional plan should skip subscribe step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "plan": "professional",
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                },
            },
        )

        self._mock_user_state(mocker, user, has_active_subscription=True)

        step, _ = self._get_onboarding_step(request, mocker)

        # Should mark subscription as completed and clear plan
        assert request.session["onboarding"]["subscription"] == "completed"
        assert request.session["plan"] is None
        assert step is None

    def test_get_onboarding_step_subscribe_invalid_plan(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with invalid plan should skip subscribe step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "plan": "invalid_plan",
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                },
            },
        )

        self._mock_user_state(mocker, user)
        mocker.patch(
            "squarelet.users.onboarding.Plan.objects.get",
            side_effect=Plan.DoesNotExist(),
        )

        step, _ = self._get_onboarding_step(request, mocker)

        assert step is None  # Should skip subscribe step

    def test_get_onboarding_step_mfa_opt_in(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with MFA not started should get mfa_opt_in step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "first_login": False,
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "not_started",
                },
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        step, _ = self._get_onboarding_step(request, mocker)

        assert step == "mfa_opt_in"

    def test_get_onboarding_step_mfa_setup(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User who opted in for MFA should get mfa_setup step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "first_login": False,
                "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        self._mock_mfa_forms(mocker, valid=True)

        step, _ = self._get_onboarding_step(request, mocker)

        assert step == "mfa_setup"

    def test_get_onboarding_step_mfa_confirm(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User who submitted MFA code should get mfa_confirm step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "code_submitted",
                }
            },
        )

        self._mock_user_state(mocker, user)

        step, _ = self._get_onboarding_step(request, mocker)

        assert step == "mfa_confirm"

    def test_get_onboarding_step_mfa_already_enabled(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User with MFA already enabled should skip MFA steps"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": True, "mfa_step": "not_started"}},
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=True)

        step, _ = self._get_onboarding_step(request, mocker)

        # Should mark MFA as completed
        assert request.session["onboarding"]["mfa_step"] == "completed"
        assert step is None

    def test_get_onboarding_step_first_login_skips_mfa(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """First-time login should skip MFA prompting"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "first_login": True,
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "not_started",
                },
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        step, _ = self._get_onboarding_step(request, mocker)

        # Should mark MFA as completed due to first login
        assert request.session["onboarding"]["mfa_step"] == "completed"
        assert step is None

    def test_get_onboarding_step_session_initialization(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should initialize onboarding session if it doesn't exist"""
        user = user_factory()
        request = self._create_get_request(
            rf, user, mock_django_session, {}
        )  # No onboarding session

        self._mock_user_state(mocker, user, has_verified_email=False)

        self._get_onboarding_step(request, mocker)

        # Should initialize session with defaults
        assert "onboarding" in request.session
        onboarding = request.session["onboarding"]
        assert onboarding["email_check_completed"] is False
        assert onboarding["mfa_step"] == "not_started"
        assert onboarding["join_org"] is False
        assert onboarding["subscription"] == "not_started"

    def test_get_onboarding_step_complete_flow(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User who completed all steps should return None"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "completed",
                    "join_org": True,
                    "subscription": "completed",
                }
            },
        )

        self._mock_user_state(mocker, user)

        step, context = self._get_onboarding_step(request, mocker)

        assert step is None
        assert not context

    # ===== TEMPLATE TESTS =====

    def test_get_template_names_confirm_email(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should return confirm_email template for email confirmation step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)

        view = self.view()
        view.request = request
        template_names = view.get_template_names()

        assert template_names == ["account/onboarding/confirm_email.html"]

    def test_get_template_names_join_org(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should return join_org template for organization joining step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": True, "join_org": False}},
        )

        self._mock_user_state(
            mocker, user, has_organizations=False, has_invitations=True
        )

        view = self.view()
        view.request = request
        template_names = view.get_template_names()

        assert template_names == ["account/onboarding/join_org.html"]

    def test_get_template_names_subscribe(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """Should return subscribe template for subscription step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                }
            },
            {"plan": "professional"},
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)

        view = self.view()
        view.request = request
        template_names = view.get_template_names()

        assert template_names == ["account/onboarding/subscribe.html"]

    @pytest.mark.parametrize(
        "mfa_step,expected_template",
        [
            ("not_started", "account/onboarding/mfa_opt_in.html"),
            ("opted_in", "account/onboarding/mfa_setup.html"),
            ("code_submitted", "account/onboarding/mfa_confirm.html"),
            ("completed", "account/onboarding/base.html"),
        ],
    )
    def test_mfa_templates(
        self, rf, user_factory, mocker, mock_django_session, mfa_step, expected_template
    ):
        """Should return mfa_opt_in template for MFA opt-in step"""
        user = user_factory()
        session_data = {
            "first_login": False,
            "onboarding": {"email_check_completed": True, "mfa_step": mfa_step},
        }
        request = self._create_get_request(rf, user, mock_django_session, session_data)
        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        self._mock_mfa_forms(mocker, valid=True)

        view = self.view()
        view.request = request
        template_names = view.get_template_names()

        assert template_names == [expected_template]

    # ===== CONTEXT DATA TESTS =====

    def test_get_context_data_base_context(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should include base context data for all steps"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "next_url": "/target/url/",
                "intent": "muckrock",
                "onboarding": {"email_check_completed": False},
            },
        )

        self._mock_user_state(mocker, user, has_verified_email=False)

        # Mock service lookup
        mock_service = mocker.MagicMock()
        mock_service.slug = "muckrock"
        mocker.patch(
            "squarelet.users.views.Service.objects.filter"
        ).return_value.first.return_value = mock_service

        view = self.view()
        view.request = request
        context = view.get_context_data()

        assert context["onboarding_step"] == "confirm_email"
        assert context["next_url"] == "/target/url/"
        assert context["intent"] == "muckrock"
        assert context["service"] == mock_service
        assert context["email"] == user.email

    def test_get_context_data_subscribe_step(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """Should include subscription forms and organizations for subscribe step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                }
            },
            {"plan": "professional"},
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)

        self._mock_subscription_forms(mocker, valid=True)

        # Mock user organizations queryset
        mock_group_orgs = mocker.MagicMock()
        mocker.patch.object(user.organizations, "filter", return_value=mock_group_orgs)
        mock_group_orgs.order_by.return_value = mock_group_orgs

        view = self.view()
        view.request = request
        context = view.get_context_data()

        assert context["onboarding_step"] == "subscribe"
        assert "forms" in context
        assert context["individual_org"] == user.individual_organization
        assert "group_orgs" in context

    def test_get_context_data_mfa_setup_step(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should include MFA form and TOTP data for MFA setup step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "first_login": False,
                "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        mock_form = self._mock_mfa_forms(mocker)

        view = self.view()
        view.request = request
        context = view.get_context_data()

        assert context["onboarding_step"] == "mfa_setup"
        assert context["form"] == mock_form
        assert context["totp_svg"] == "<svg>test</svg>"
        assert context["totp_svg_data_uri"] == "data:image/svg+xml;base64,dGVzdA=="
        assert context["totp_url"] == "otpauth://test"

    def test_get_context_data_join_org_step(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should include invitation and potential org data for join_org step"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": True, "join_org": False}},
        )

        self._mock_user_state(
            mocker, user, has_organizations=False, has_invitations=True
        )

        view = self.view()
        view.request = request
        context = view.get_context_data()

        assert context["onboarding_step"] == "join_org"
        assert len(context["invitations"]) == 1
        assert context["potential_orgs"] == []
        assert context["joinable_orgs_count"] == 1

    def test_get_context_data_no_step_context(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Should not include step-specific context for steps that don't need it"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "code_submitted",
                }
            },
        )

        self._mock_user_state(mocker, user)

        view = self.view()
        view.request = request
        context = view.get_context_data()

        assert context["onboarding_step"] == "mfa_confirm"
        # Should not have forms, TOTP data, or other step-specific context
        assert "forms" not in context
        assert "totp_svg" not in context
        assert "invitations" not in context

    # ===== HTTP METHOD TESTS =====

    def test_get_unauthenticated_user(self, rf):
        """Unauthenticated user should be redirected to login"""
        request = rf.get(self.url)
        request.user = AnonymousUser()
        request.session = {}

        view = self.view.as_view()
        response = view(request)

        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_get_confirm_email_sends_email_except_first_login(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Email confirmation step should send email except on first login"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"first_login": False, "onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)
        mock_send = mocker.patch("squarelet.users.views.send_email_confirmation")

        response = self._call_view_get(request, mocker, mock_email_send=False)

        assert response.status_code == 200
        mock_send.assert_called_once_with(request, user, user.email)

    def test_get_confirm_email_skips_email_on_first_login(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Email confirmation step should not send email on first login"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"first_login": True, "onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)
        mock_send = mocker.patch("squarelet.users.views.send_email_confirmation")

        response = self._call_view_get(request, mocker, mock_email_send=False)

        assert response.status_code == 200
        mock_send.assert_not_called()

    def test_get_completed_onboarding_with_next_url(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Completed onboarding with next_url should redirect to next_url"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "next_url": "/target/page/",
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "completed",
                    "join_org": True,
                    "subscription": "completed",
                },
            },
        )

        self._mock_user_state(mocker, user)

        response = self._call_view_get(request, mocker)

        assert response.status_code == 302
        assert response.url == "/target/page/"

    def test_get_completed_onboarding_without_next_url(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Completed onboarding without next_url should redirect to user detail"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "completed",
                    "join_org": True,
                    "subscription": "completed",
                }
            },
        )

        self._mock_user_state(mocker, user)

        response = self._call_view_get(request, mocker)

        assert response.status_code == 302
        assert response.url == f"/users/{user.username}/"

    def test_get_renders_correct_template_for_each_step(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Each onboarding step should render the correct template"""
        user = user_factory()
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)

        response = self._call_view_get(request, mocker)

        assert response.status_code == 200
        assert response.template_name == ["account/onboarding/confirm_email.html"]

    # ===== POST METHOD TESTS =====

    def test_post_confirm_email_step(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """POST to confirm_email step should update session"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "confirm_email"},
            {"onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "email_check_completed", True)

    def test_post_mfa_opt_in_yes(self, rf, user_factory, mocker, mock_django_session):
        """POST to mfa_opt_in step with 'yes' should update session"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_opt_in", "enable_mfa": "yes"},
            {
                "first_login": False,
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "not_started",
                },
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "opted_in")

    def test_post_mfa_opt_in_no(self, rf, user_factory, mocker, mock_django_session):
        """POST to mfa_opt_in step with 'no' should complete MFA and update user"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_opt_in", "choice": "no"},
            {
                "first_login": False,
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "not_started",
                },
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        # Mock timezone and user save
        mock_timezone_now = mocker.patch("squarelet.users.onboarding.timezone.now")
        mock_timezone_now.return_value = "2023-01-01"
        mock_user_save = mocker.patch.object(user, "save")

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "completed")
        assert user.last_mfa_prompt == "2023-01-01"
        mock_user_save.assert_called_once()

    def test_post_mfa_setup_valid_code(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """POST to mfa_setup step with valid code should activate TOTP"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_setup", "token": "123456"},
            {
                "first_login": False,
                "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        self._mock_mfa_forms(mocker, valid=True)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "code_submitted")

    def test_post_mfa_setup_invalid_code(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """POST to mfa_setup step with invalid code should show errors"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_setup", "token": "invalid"},
            {
                "first_login": False,
                "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        self._mock_mfa_forms(mocker, valid=False)

        response = self._call_view_post(request, mocker)

        # Should render template with form errors, not redirect
        self._assert_template(response, "account/onboarding/mfa_setup.html")

    def test_post_mfa_setup_skip(self, rf, user_factory, mocker, mock_django_session):
        """POST to mfa_setup step with skip should complete MFA"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_setup", "mfa_setup": "skip"},
            {
                "first_login": False,
                "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        self._mock_mfa_forms(mocker, valid=True)

        # Mock timezone and user save
        mock_timezone_now = mocker.patch("squarelet.users.onboarding.timezone.now")
        mock_timezone_now.return_value = "2023-01-01"
        mock_user_save = mocker.patch.object(user, "save")

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "completed")
        assert user.last_mfa_prompt == "2023-01-01"
        mock_user_save.assert_called_once()

    def test_post_mfa_confirm_step(self, rf, user_factory, mocker, mock_django_session):
        """POST to mfa_confirm step should complete MFA"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_confirm"},
            {
                "onboarding": {
                    "email_check_completed": True,
                    "mfa_step": "code_submitted",
                }
            },
        )

        self._mock_user_state(mocker, user)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "completed")

    def test_mfa_setup_secret_persistence_between_requests(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """TOTP secret should persist between GET and POST requests for validation"""
        user = user_factory()

        # Step 1: Initial GET request - should generate and store secret
        get_request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "first_login": False,
                "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
            },
        )

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        # Mock the adapter for TOTP generation
        mock_adapter = mocker.MagicMock()
        mock_adapter.build_totp_url.return_value = "otpauth://test"
        mock_adapter.build_totp_svg.return_value = "<svg>test</svg>"
        mocker.patch(
            "squarelet.users.onboarding.get_adapter", return_value=mock_adapter
        )
        mocker.patch(
            "squarelet.users.onboarding.base64.b64encode", return_value=b"dGVzdA=="
        )

        # Create a real form that generates a secret
        mock_form = mocker.MagicMock()
        mock_form.secret = "TESTSECRETKEY123"
        mock_form.is_valid.return_value = True

        mocker.patch(
            "squarelet.users.onboarding.ActivateTOTPForm", return_value=mock_form
        )
        mocker.patch("squarelet.users.onboarding.activate_totp")

        # Make GET request to render form
        step, context = self._get_onboarding_step(get_request, mocker)

        assert step == "mfa_setup"
        assert context["form"] == mock_form
        # Secret should be stored in session
        assert get_request.session["totp_secret"] == "TESTSECRETKEY123"
        assert get_request.session.modified is True

        # Step 2: POST request with TOTP code - should use same secret from session
        post_data = {"step": "mfa_setup", "token": "123456"}
        post_request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            post_data,
            get_request.session,  # Use session from GET request
        )

        # Create a new mock form for POST with a different initial secret
        post_mock_form = mocker.MagicMock()
        post_mock_form.is_valid.return_value = True
        post_mock_form.secret = "DIFFERENTSECRET456"

        # Reset the mock to return the new form for POST
        mocker.patch(
            "squarelet.users.onboarding.ActivateTOTPForm", return_value=post_mock_form
        )

        response = self._call_view_post(post_request, mocker)

        # The critical assertion: form.secret should be set to the session secret
        # This ensures the same secret is used for validation
        assert (
            post_mock_form.secret == "TESTSECRETKEY123"
        )  # Should be overridden from session
        assert (
            post_mock_form.secret != "DIFFERENTSECRET456"
        )  # Should NOT be the new secret

        # Verify successful completion
        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(post_request.session, "mfa_step", "code_submitted")
        # Secret should be cleared from session after successful activation
        assert "totp_secret" not in post_request.session

    def test_mfa_setup_secret_reused_on_form_error(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """TOTP secret should be reused when form validation
        fails and page re-renders"""
        user = user_factory()

        # Set up initial session with stored secret (from previous GET)
        session_data = {
            "totp_secret": "ORIGINALSECRET123",
            "first_login": False,
            "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
        }

        self._mock_user_state(mocker, user, has_mfa_enabled=False)

        # Mock adapter
        mock_adapter = mocker.MagicMock()
        mock_adapter.build_totp_url.return_value = "otpauth://test"
        mock_adapter.build_totp_svg.return_value = "<svg>test</svg>"
        mocker.patch(
            "squarelet.users.onboarding.get_adapter", return_value=mock_adapter
        )
        mocker.patch(
            "squarelet.users.onboarding.base64.b64encode", return_value=b"dGVzdA=="
        )

        # POST with invalid TOTP code
        post_data = {"step": "mfa_setup", "token": "invalid"}
        request = self._create_post_request(
            rf, user, mock_django_session, post_data, session_data
        )

        # Mock form that fails validation
        mock_form = mocker.MagicMock()
        mock_form.is_valid.return_value = False
        mock_form.secret = "NEWSECRET456"  # Form initially has different secret

        mocker.patch(
            "squarelet.users.onboarding.ActivateTOTPForm", return_value=mock_form
        )

        response = self._call_view_post(request, mocker)

        # Form should be re-rendered with errors (not redirected)
        self._assert_template(response, "account/onboarding/mfa_setup.html")

        # Critical assertion: form should use the original secret from session
        assert mock_form.secret == "ORIGINALSECRET123"
        assert mock_form.secret != "NEWSECRET456"

        # Secret should remain in session for next attempt
        assert request.session["totp_secret"] == "ORIGINALSECRET123"

    def test_mfa_setup_secret_cleared_on_skip(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """TOTP secret should be cleared from session when user skips MFA setup"""
        user = user_factory()

        # Session with stored secret
        session_data = {
            "totp_secret": "TESTSECRET123",
            "first_login": False,
            "onboarding": {"email_check_completed": True, "mfa_step": "opted_in"},
        }

        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        self._mock_mfa_forms(mocker, valid=True)

        # Mock timezone for user save
        mock_timezone_now = mocker.patch("squarelet.users.onboarding.timezone.now")
        mock_timezone_now.return_value = "2023-01-01"
        mocker.patch.object(user, "save")

        # POST to skip MFA
        post_data = {"step": "mfa_setup", "mfa_setup": "skip"}
        request = self._create_post_request(
            rf, user, mock_django_session, post_data, session_data
        )

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "completed")

        # Secret should be cleared from session when skipping
        # Note: The current implementation doesn't clear on skip,
        # but it should for security
        # This test documents the expected behavior
        assert "totp_secret" not in request.session

    def test_post_subscribe_valid_individual_form(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """POST to subscribe step with valid
        individual form should process subscription"""
        user = user_factory()
        form_data = {
            "step": "subscribe",
            "plan": "1",
            "organization": str(user.individual_organization.pk),
            "stripe_token": "tok_test123",
        }
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            form_data,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                },
                "plan": "professional",
            },
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)
        self._mock_subscription_forms(mocker, valid=True)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "subscription", "completed")

    def test_post_subscribe_invalid_form(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """POST to subscribe step with invalid form should show errors"""
        user = user_factory()
        form_data = {
            "step": "subscribe",
            "plan": "1",
            "organization": str(user.individual_organization.pk),
            "stripe_token": "invalid_token",
        }
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            form_data,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                },
                "plan": "professional",
            },
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)
        self._mock_subscription_forms(mocker, valid=False)

        # Mock user organizations queryset
        mock_group_orgs = mocker.MagicMock()
        mocker.patch.object(user.organizations, "filter", return_value=mock_group_orgs)
        mock_group_orgs.order_by.return_value = mock_group_orgs

        response = self._call_view_post(request, mocker)

        # Should render template with form errors, not redirect
        self._assert_template(response, "account/onboarding/subscribe.html")

    def test_post_subscribe_skip(self, rf, user_factory, mocker, mock_django_session):
        """POST to subscribe step with skip should complete subscription"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "subscribe", "submit-type": "skip"},
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                },
                "plan": "professional",
            },
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "subscription", "completed")

    def test_post_join_org_skip(self, rf, user_factory, mocker, mock_django_session):
        """POST to join_org step with skip should complete join_org"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "join_org", "join_org": "skip"},
            {"onboarding": {"email_check_completed": True, "join_org": False}},
        )

        self._mock_user_state(
            mocker, user, has_organizations=False, has_invitations=True
        )

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "join_org", True)

    def test_post_invalid_step(self, rf, user_factory, mocker, mock_django_session):
        """POST with invalid step should handle gracefully"""
        user = user_factory()
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "invalid_step"},
            {"onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)

        response = self._call_view_post(request, mocker)

        # Should redirect back to onboarding (handles invalid step gracefully)
        self._assert_redirect_to_onboard(response)

    # ===== INTEGRATION TESTS =====

    def test_complete_onboarding_flow_new_user_no_plan(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Complete onboarding flow for new user without subscription plan"""
        user = user_factory()

        # Step 1: Start with empty session (new user)
        session_data = {}

        self._mock_user_state(
            mocker,
            user,
            has_verified_email=False,
            has_organizations=False,
            has_invitations=False,
            has_mfa_enabled=False,
        )

        # Step 1: Email confirmation required
        request = self._create_get_request(rf, user, mock_django_session, session_data)
        step, context = self._get_onboarding_step(request, mocker)

        assert step == "confirm_email"
        assert context["email"] == user.email
        assert request.session["onboarding"]["email_check_completed"] is False

        # Step 2: Confirm email via POST
        session_data = request.session
        request = self._create_post_request(
            rf, user, mock_django_session, {"step": "confirm_email"}, session_data
        )

        # Mock email now verified
        self._mock_user_state(
            mocker,
            user,
            has_verified_email=False,
            has_organizations=False,
            has_invitations=False,
            has_mfa_enabled=False,
        )

        response = self._call_view_post(request, mocker)
        assert response.status_code == 302
        assert request.session["onboarding"]["email_check_completed"] is True

        # Step 3: Check final state - should be complete
        session_data = request.session
        request = self._create_get_request(rf, user, mock_django_session, session_data)
        response = self._call_view_get(request, mocker)
        assert response.url == f"/users/{user.username}/"
        assert response.status_code == 302

    def test_complete_onboarding_flow_with_professional_plan(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """Complete onboarding flow for user signing up for professional plan"""
        user = user_factory()

        # Start with plan in session
        session_data = {"plan": "professional"}

        self._mock_user_state(
            mocker,
            user,
            has_verified_email=True,
            has_active_subscription=False,
            has_mfa_enabled=False,
        )

        # Step 1: Should go straight to subscription (email already verified)
        request = self._create_get_request(rf, user, mock_django_session, session_data)

        step, context = self._get_onboarding_step(request, mocker)

        assert step == "subscribe"
        assert context["plans"]["selected"].slug == "professional"
        assert request.session["onboarding"]["email_check_completed"] is True

        # Step 2: Complete subscription via POST
        session_data = request.session
        form_data = {
            "step": "subscribe",
            "plan": "1",
            "organization": str(user.individual_organization.pk),
            "stripe_token": "tok_test123",
        }
        request = self._create_post_request(
            rf, user, mock_django_session, form_data, session_data
        )

        self._mock_subscription_forms(mocker, valid=True)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "subscription", "completed")

    def test_complete_onboarding_flow_with_organization_invitations(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Complete onboarding flow for user with pending organization invitations"""
        user = user_factory()

        # Mock user with verified email, no personal orgs, but has invitations
        self._mock_user_state(
            mocker,
            user,
            has_organizations=False,
            has_invitations=True,
            has_mfa_enabled=True,
        )

        # Step 1: Should go to join_org step
        request = self._create_get_request(rf, user, mock_django_session, {})
        step, context = self._get_onboarding_step(request, mocker)

        assert step == "join_org"
        assert len(context["invitations"]) == 1
        assert context["joinable_orgs_count"] == 1
        assert request.session["onboarding"]["join_org"] is False

        # Step 2: Skip organization joining
        session_data = request.session
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "join_org", "join_org": "skip"},
            session_data,
        )

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "join_org", True)

        # Step 3: Onboarding complete (MFA already enabled)
        session_data = request.session
        request = self._create_get_request(rf, user, mock_django_session, session_data)

        response = self._call_view_get(request, mocker)

        assert response.status_code == 302
        assert response.url == f"/users/{user.username}/"

    def test_onboarding_flow_interrupted_and_resumed(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """User should resume onboarding from where they left off after interruption"""
        user = user_factory()

        # Simulate user who started onboarding but didn't complete it
        # They confirmed email and opted into MFA but didn't complete setup
        session_data = {
            "onboarding": {
                "email_check_completed": True,
                "mfa_step": "opted_in",  # Stuck at this step
                "join_org": False,
                "subscription": "not_started",
            }
        }

        # Mock user state
        mocker.patch("squarelet.users.onboarding.has_verified_email", return_value=True)
        mock_org_queryset = mocker.MagicMock()
        mock_org_queryset.exists.return_value = True
        mocker.patch.object(
            user.organizations, "filter", return_value=mock_org_queryset
        )
        mocker.patch.object(
            user.individual_organization, "has_active_subscription", return_value=False
        )
        mocker.patch("squarelet.users.models.is_mfa_enabled", return_value=False)
        user.last_mfa_prompt = None

        self._mock_mfa_forms(mocker, valid=True)

        # Mock no unverified emails
        mock_email_queryset = mocker.MagicMock()
        mock_email_queryset.exists.return_value = False
        mocker.patch(
            "squarelet.users.onboarding.EmailAddress.objects.filter",
            return_value=mock_email_queryset,
        )

        # User returns - should resume at MFA setup step
        request = self._create_get_request(rf, user, mock_django_session, session_data)
        step, _ = self._get_onboarding_step(request, mocker)

        assert step == "mfa_setup"
        assert (
            request.session["onboarding"]["email_check_completed"] is True
        )  # Preserved
        assert request.session["onboarding"]["mfa_step"] == "opted_in"  # Preserved

        # Complete MFA setup to continue flow
        session_data = request.session
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            {"step": "mfa_setup", "token": "123456"},
            session_data,
        )

        self._mock_mfa_forms(mocker, valid=True)

        response = self._call_view_post(request, mocker)

        self._assert_redirect_to_onboard(response)
        self._assert_session_updated(request.session, "mfa_step", "code_submitted")

        # Continue with rest of flow...
        # [Additional steps would follow the same pattern]

    def test_onboarding_flow_with_next_url_redirect(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Completed onboarding should redirect to next_url from session"""
        user = user_factory()

        # Session with target URL
        session_data = {
            "next_url": "/target/dashboard/",
            "intent": "muckrock",
            "onboarding": {
                "email_check_completed": True,
                "mfa_step": "completed",
                "join_org": True,
                "subscription": "completed",
            },
        }

        # Mock all steps complete
        mocker.patch("squarelet.users.onboarding.has_verified_email", return_value=True)
        mock_org_queryset = mocker.MagicMock()
        mock_org_queryset.exists.return_value = True
        mocker.patch.object(
            user.organizations, "filter", return_value=mock_org_queryset
        )
        mocker.patch("squarelet.users.models.is_mfa_enabled", return_value=True)

        request = self._create_get_request(rf, user, mock_django_session, session_data)

        response = self._call_view_get(request, mocker)

        # Should redirect to next_url and remove it from session
        assert response.status_code == 302
        assert response.url == "/target/dashboard/"
        assert "next_url" not in request.session

    # ===== EDGE CASE TESTS =====

    def test_malformed_post_data_handling(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Malformed POST data should not crash the application"""
        user = user_factory()

        malformed_requests = [
            {},  # Missing step parameter
            {"step": "None"},  # Invalid step values
            {"step": ""},
            {"step": 12345},
            {"step": ["invalid", "list"]},
        ]

        for malformed_data in malformed_requests:
            request = self._create_post_request(
                rf,
                user,
                mock_django_session,
                malformed_data,
                {"onboarding": {"email_check_completed": True}},
            )

            # Should handle gracefully and not crash
            try:
                response = self._call_view_post(request, mocker)
                assert response.status_code in [200, 302]  # Either render or redirect
            except (TypeError, ValueError, AttributeError) as e:
                pytest.fail(
                    f"Should handle malformed POST data gracefully. "
                    f"Error: {e}, Data: {malformed_data}"
                )

    def test_unauthorized_access_redirects_to_login(self, rf):
        """Unauthenticated users should be redirected to login"""

        # GET request from unauthenticated user
        request = rf.get(self.url)
        request.user = AnonymousUser()

        view_instance = self.view.as_view()
        response = view_instance(request)

        assert response.status_code == 302
        assert response.url == "/accounts/login/"

    def test_email_confirmation_send_on_first_visit(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Email confirmation should be sent automatically
        on first visit (not first login)"""
        user = user_factory()

        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"first_login": False, "onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)
        mock_send_confirmation = mocker.patch(
            "squarelet.users.views.send_email_confirmation"
        )

        response = self._call_view_get(request, mocker, mock_email_send=False)

        # Should send email confirmation automatically
        mock_send_confirmation.assert_called_once_with(request, user, user.email)
        assert response.status_code == 200  # Render confirm_email template

    def test_email_confirmation_not_sent_on_first_login(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Email confirmation should NOT be sent on first login
        (already sent during signup)"""
        user = user_factory()

        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {"first_login": True, "onboarding": {"email_check_completed": False}},
        )

        self._mock_user_state(mocker, user, has_verified_email=False)
        mock_send_confirmation = mocker.patch(
            "squarelet.users.views.send_email_confirmation"
        )

        response = self._call_view_get(request, mocker, mock_email_send=False)

        # Should NOT send email confirmation (already sent during signup)
        mock_send_confirmation.assert_not_called()
        assert response.status_code == 200  # Still render confirm_email template

    def test_mfa_setup_form_validation_errors(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """MFA setup with invalid tokens should be handled properly"""
        user = user_factory()

        request = self._create_post_request(
            rf, user, mock_django_session, {"step": "mfa_setup", "token": "invalid"}
        )
        request.user = user
        request.session = mock_django_session({"onboarding": {"mfa_step": "opted_in"}})

        self._mock_user_state(mocker, user, has_mfa_enabled=False)
        self._mock_mfa_forms(mocker, valid=False)

        response = self._call_view_post(request, mocker)

        # Should re-render form with errors, not redirect
        self._assert_template(response, "account/onboarding/mfa_setup.html")

    # ===== SESSION STATE TESTING =====

    def test_session_initialization_creates_defaults(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Empty session should be initialized with proper defaults"""
        user = user_factory()
        request = rf.get(self.url)
        request.user = user
        request.session = mock_django_session({})  # Completely empty session

        # Mock dependencies to trigger session initialization
        mocker.patch("squarelet.users.onboarding.has_verified_email", return_value=True)

        view = self.view()
        view.get_onboarding_step(request)

        # Verify session was initialized with correct defaults
        assert "onboarding" in request.session
        onboarding = request.session["onboarding"]
        assert onboarding["email_check_completed"] is True
        assert onboarding["mfa_step"] == "completed"
        assert onboarding["join_org"] is False
        assert onboarding["subscription"] == "not_started"
        assert request.session.modified is True

    def test_session_initialization_uses_setdefault(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Session initialization should use setdefault to preserve existing values"""
        user = user_factory()
        request = rf.get(self.url)
        request.user = user
        request.session = mock_django_session(
            {
                "onboarding": {
                    "email_check_completed": True,  # This should be preserved
                    "mfa_step": "opted_in",  # This should be preserved
                    # Missing join_org and subscription - should get defaults
                }
            }
        )

        # Mock dependencies
        mocker.patch("squarelet.users.onboarding.has_verified_email", return_value=True)
        mock_org_queryset = mocker.MagicMock()
        mock_org_queryset.exists.return_value = True
        mocker.patch.object(
            user.organizations, "filter", return_value=mock_org_queryset
        )
        mocker.patch("squarelet.users.models.is_mfa_enabled", return_value=True)
        self._mock_mfa_forms(mocker, valid=True)

        view = self.view()
        view.get_onboarding_step(request)

        # Verify setdefault behavior - existing values preserved,
        # missing values get defaults
        onboarding = request.session["onboarding"]
        assert onboarding["email_check_completed"] is True  # Preserved
        assert onboarding["mfa_step"] == "opted_in"  # Preserved
        assert onboarding["join_org"] is False  # Default added
        assert onboarding["subscription"] == "not_started"  # Default added

    def test_session_email_verification_auto_update(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Session should auto-update email_check_completed when email is verified"""
        user = user_factory()
        request = rf.get(self.url)
        request.user = user
        request.session = mock_django_session(
            {"onboarding": {"email_check_completed": False}}  # Start as false
        )

        # Mock has_verified_email to return True (email is actually verified)
        mocker.patch("squarelet.users.onboarding.has_verified_email", return_value=True)
        mock_org_queryset = mocker.MagicMock()
        mock_org_queryset.exists.return_value = True
        mocker.patch.object(
            user.organizations, "filter", return_value=mock_org_queryset
        )
        mocker.patch("squarelet.users.models.is_mfa_enabled", return_value=True)

        view = self.view()
        view.get_onboarding_step(request)

        # Should auto-update session when email is verified
        assert request.session["onboarding"]["email_check_completed"] is True
        assert request.session.modified is True

    def test_session_plan_persistence_from_get_parameter(
        self, rf, user_factory, subscription_plans, mocker, mock_django_session
    ):
        """Plan from GET parameter should be used and stored in session"""
        user = user_factory()

        # Request with plan parameter
        request = self._create_get_request(
            rf,
            user,
            mock_django_session,
            {
                "onboarding": {
                    "email_check_completed": True,
                    "subscription": "not_started",
                }
            },
            {"plan": "professional"},
        )

        self._mock_user_state(mocker, user, has_active_subscription=False)

        step, context = self._get_onboarding_step(request, mocker)

        # The view should use the plan from GET parameter
        assert step == "subscribe"
        assert context["plans"]["selected"].slug == "professional"

    def test_database_errors_plan_doesnotexist_handling(
        self, rf, user_factory, mocker, mock_django_session, capsys
    ):
        """Plan.DoesNotExist errors should be handled gracefully"""
        user = user_factory()

        # Session with invalid plan
        session_data = {
            "plan": "nonexistent_plan",
            "onboarding": {
                "email_check_completed": True,
                "subscription": "not_started",
            },
        }

        self._mock_user_state(mocker, user)

        # Mock Plan.DoesNotExist for any plan lookup
        mocker.patch(
            "squarelet.users.onboarding.Plan.objects.get",
            side_effect=Plan.DoesNotExist(),
        )

        request = self._create_get_request(rf, user, mock_django_session, session_data)

        step, _ = self._get_onboarding_step(request, mocker)

        # Should handle DoesNotExist gracefully and skip subscription step
        assert step is None  # Onboarding complete, subscription skipped

    def test_plan_database_error_during_subscription_post(
        self, rf, user_factory, mocker, mock_django_session
    ):
        """Database errors during subscription POST should be handled"""
        user = user_factory()

        form_data = {
            "step": "subscribe",
            "plan": "999",  # Non-existent plan ID
            "organization": str(user.individual_organization.pk),
            "stripe_token": "tok_test123",
        }
        request = self._create_post_request(
            rf,
            user,
            mock_django_session,
            form_data,
            {"onboarding": {"subscription": "not_started"}},
        )

        # Mock Plan.DoesNotExist on pk lookup
        mocker.patch(
            "squarelet.users.onboarding.Plan.objects.get",
            side_effect=Plan.DoesNotExist(),
        )

        mocker.patch("squarelet.users.onboarding.messages.error")

        view_instance = self.view.as_view()

        # Should rerender the current view with form errors
        response = view_instance(request)
        # If successful, should respond gracefully
        assert response.status_code == 302


@pytest.mark.django_db()
class TestUserInvitationsView(ViewTestMixin):
    """Test the User Invitations view"""

    view = views.UserInvitationsView
    url = "/users/{username}/invitations/"

    def test_get_own_invitations(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """User can view their own invitations"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create invitations for this user
        invitation_factory.create_batch(
            3, email=user.email, organization=org, request=False
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert response.context_data["target_user"] == user
        assert response.context_data["is_own_page"] is True
        assert len(response.context_data["invitations"]) == 3

    def test_get_invitations_filters_by_request_false(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """View only shows invitations (request=False), not requests"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create invitations (should appear)
        invitation_factory.create_batch(
            2, email=user.email, organization=org, request=False
        )
        # Create requests (should NOT appear)
        invitation_factory.create_batch(
            3, email=user.email, organization=org, request=True
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        # Only invitations should appear, not requests
        assert len(response.context_data["invitations"]) == 2

    def test_get_invitations_filters_by_verified_email(
        self, rf, user_factory, organization_factory, invitation_factory, mocker
    ):
        """View only shows invitations for verified emails"""
        user = user_factory(email="verified@example.com", email_verified=True)
        org = organization_factory()

        # Mock get_verified_emails to return only verified email
        mocker.patch.object(
            user, "get_verified_emails", return_value=["verified@example.com"]
        )

        # Create invitation for verified email (should appear)
        invitation_factory(
            email="verified@example.com", organization=org, request=False
        )
        # Create invitation for unverified email (should NOT appear)
        invitation_factory(
            email="unverified@example.com", organization=org, request=False
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert len(response.context_data["invitations"]) == 1
        assert response.context_data["invitations"][0].email == "verified@example.com"

    def test_get_invitations_includes_user_field_invitations(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """View includes invitations directly assigned to user field"""
        user = user_factory(email="user@example.com", email_verified=True)
        org = organization_factory()

        # Create invitation using user field instead of email
        invitation_factory(user=user, organization=org, request=False)

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert len(response.context_data["invitations"]) >= 1

    def test_get_invitations_ordered_by_created_at_desc(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """Invitations should be ordered by created_at descending"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create multiple invitations
        invitation_factory(email=user.email, organization=org, request=False)
        invitation_factory(email=user.email, organization=org, request=False)
        invitation_factory(email=user.email, organization=org, request=False)

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        invitations = list(response.context_data["invitations"])
        # Most recent should be first
        assert invitations[0].created_at >= invitations[-1].created_at

    def test_get_invitations_pagination(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """Invitations should be paginated at 20 items per page"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create 25 invitations (more than 1 page)
        invitation_factory.create_batch(
            25, email=user.email, organization=org, request=False
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert response.context_data["is_paginated"] is True
        assert len(response.context_data["invitations"]) == 20

    def test_get_invitations_no_verified_emails(self, rf, user_factory, mocker):
        """User with no verified emails should see empty list"""
        user = user_factory(email_verified=False)

        # Mock no verified emails
        mocker.patch.object(user, "get_verified_emails", return_value=[])

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert len(response.context_data["invitations"]) == 0

    def test_staff_can_view_other_users_invitations(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """Staff users can view other users' invitations"""
        staff_user = user_factory(is_staff=True, email_verified=True)
        target_user = user_factory(email_verified=True)
        org = organization_factory()

        invitation_factory.create_batch(
            2, email=target_user.email, organization=org, request=False
        )

        response = self.call_view(rf, staff_user, username=target_user.username)

        assert response.status_code == 200
        assert response.context_data["target_user"] == target_user
        assert response.context_data["is_own_page"] is False
        assert len(response.context_data["invitations"]) == 2

    def test_post_send_new_request_creates_new_request(
        self, rf, user_factory, organization_factory, invitation_factory, mocker
    ):
        """POST with send_new_request should create a new request"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create a rejected invitation
        rejected_invitation = invitation_factory(
            email=user.email, organization=org, request=False
        )
        rejected_invitation.reject()

        # Mock the send method
        mocker.patch("squarelet.organizations.models.Invitation.send")

        data = {
            "invitation_uuid": str(rejected_invitation.uuid),
            "action": "send_new_request",
        }

        response = self.call_view(rf, user, data=data, username=user.username)

        assert response.status_code == 302
        assert response.url == f"/users/{user.username}/invitations/"

        # Verify a new request was created
        new_request = Invitation.objects.filter(
            organization=org, user=user, request=True
        ).latest("created_at")
        assert new_request is not None
        assert new_request.email == user.email

    def test_post_send_new_request_sends_notification(
        self, rf, user_factory, organization_factory, invitation_factory, mocker
    ):
        """POST with send_new_request should send notification"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        rejected_invitation = invitation_factory(
            email=user.email, organization=org, request=False
        )
        rejected_invitation.reject()

        # Mock the send method
        mock_send = mocker.patch("squarelet.organizations.models.Invitation.send")

        data = {
            "invitation_uuid": str(rejected_invitation.uuid),
            "action": "send_new_request",
        }

        self.call_view(rf, user, data=data, username=user.username)

        # Verify send was called
        mock_send.assert_called_once()

    def test_post_send_new_request_nonexistent_invitation(
        self, rf, user_factory, mocker
    ):
        """POST with invalid invitation UUID should show error"""
        user = user_factory(email_verified=True)

        # Mock messages
        mock_error = mocker.patch("squarelet.users.views.messages.error")

        data = {
            "invitation_uuid": "00000000-0000-0000-0000-000000000000",
            "action": "send_new_request",
        }

        response = self.call_view(rf, user, data=data, username=user.username)

        assert response.status_code == 302
        mock_error.assert_called_once()

    def test_post_send_new_request_non_rejected_invitation(
        self, rf, user_factory, organization_factory, invitation_factory, mocker
    ):
        """POST with non-rejected invitation should show error"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create a pending (not rejected) invitation
        pending_invitation = invitation_factory(
            email=user.email, organization=org, request=False
        )

        mock_error = mocker.patch("squarelet.users.views.messages.error")

        data = {
            "invitation_uuid": str(pending_invitation.uuid),
            "action": "send_new_request",
        }

        response = self.call_view(rf, user, data=data, username=user.username)

        assert response.status_code == 302
        mock_error.assert_called_once()


@pytest.mark.django_db()
class TestUserRequestsView(ViewTestMixin):
    """Test the User Requests view"""

    view = views.UserRequestsView
    url = "/users/{username}/requests/"

    def test_get_own_requests(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """User can view their own requests"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create requests for this user
        invitation_factory.create_batch(
            3, email=user.email, organization=org, request=True
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert response.context_data["target_user"] == user
        assert response.context_data["is_own_page"] is True
        assert len(response.context_data["requests"]) == 3

    def test_get_requests_filters_by_request_true(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """View only shows requests (request=True), not invitations"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create requests (should appear)
        invitation_factory.create_batch(
            3, email=user.email, organization=org, request=True
        )
        # Create invitations (should NOT appear)
        invitation_factory.create_batch(
            2, email=user.email, organization=org, request=False
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        # Only requests should appear, not invitations
        assert len(response.context_data["requests"]) == 3

    def test_get_requests_filters_by_verified_email(
        self, rf, user_factory, organization_factory, invitation_factory, mocker
    ):
        """View only shows requests for verified emails"""
        user = user_factory(email="verified@example.com", email_verified=True)
        org = organization_factory()

        # Mock get_verified_emails to return only verified email
        mocker.patch.object(
            user, "get_verified_emails", return_value=["verified@example.com"]
        )

        # Create request for verified email (should appear)
        invitation_factory(email="verified@example.com", organization=org, request=True)
        # Create request for unverified email (should NOT appear)
        invitation_factory(
            email="unverified@example.com", organization=org, request=True
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert len(response.context_data["requests"]) == 1
        assert response.context_data["requests"][0].email == "verified@example.com"

    def test_get_requests_includes_user_field_requests(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """View includes requests directly assigned to user field"""
        user = user_factory(email="user@example.com", email_verified=True)
        org = organization_factory()

        # Create request using user field instead of email
        invitation_factory(user=user, organization=org, request=True)

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert len(response.context_data["requests"]) >= 1

    def test_get_requests_ordered_by_created_at_desc(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """Requests should be ordered by created_at descending"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create multiple requests
        invitation_factory(email=user.email, organization=org, request=True)
        invitation_factory(email=user.email, organization=org, request=True)
        invitation_factory(email=user.email, organization=org, request=True)

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        requests = list(response.context_data["requests"])
        # Most recent should be first
        assert requests[0].created_at >= requests[-1].created_at

    def test_get_requests_pagination(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """Requests should be paginated at 20 items per page"""
        user = user_factory(email_verified=True)
        org = organization_factory()

        # Create 25 requests (more than 1 page)
        invitation_factory.create_batch(
            25, email=user.email, organization=org, request=True
        )

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert response.context_data["is_paginated"] is True
        assert len(response.context_data["requests"]) == 20

    def test_get_requests_no_verified_emails(self, rf, user_factory, mocker):
        """User with no verified emails should see empty list"""
        user = user_factory(email_verified=False)

        # Mock no verified emails
        mocker.patch.object(user, "get_verified_emails", return_value=[])

        response = self.call_view(rf, user, username=user.username)

        assert response.status_code == 200
        assert len(response.context_data["requests"]) == 0

    def test_staff_can_view_other_users_requests(
        self, rf, user_factory, organization_factory, invitation_factory
    ):
        """Staff users can view other users' requests"""
        staff_user = user_factory(is_staff=True, email_verified=True)
        target_user = user_factory(email_verified=True)
        org = organization_factory()

        invitation_factory.create_batch(
            2, email=target_user.email, organization=org, request=True
        )

        response = self.call_view(rf, staff_user, username=target_user.username)

        assert response.status_code == 200
        assert response.context_data["target_user"] == target_user
        assert response.context_data["is_own_page"] is False
        assert len(response.context_data["requests"]) == 2
