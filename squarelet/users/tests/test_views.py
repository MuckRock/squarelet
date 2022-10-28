# Django
from django.conf import settings
from django.http.response import Http404

# Standard Library
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.users import views

# pylint: disable=invalid-name


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


@pytest.mark.django_db()
class TestUserRedirectView(ViewTestMixin):
    """Test the User Redirect view"""

    view = views.UserRedirectView
    url = "/users/~redirect/"

    def test_get(self, rf, user_factory):
        user = user_factory()
        response = self.call_view(rf, user)
        assert response.status_code == 302
        assert response.url == f"/users/{user.username}/"


@pytest.mark.django_db()
class TestUserUpdateView(ViewTestMixin):
    """Test the User Update view"""

    view = views.UserUpdateView
    url = "/users/~update/"

    def test_get(self, rf, user_factory):
        user = user_factory()
        response = self.call_view(rf, user)
        assert response.status_code == 200
        assert "username" in response.context_data["form"].fields
        assert response.context_data["object"] == user

    def test_get_username_changed(self, rf, user_factory):
        user = user_factory(can_change_username=False)
        response = self.call_view(rf, user)
        assert response.status_code == 200
        assert "username" not in response.context_data["form"].fields

    def test_post(self, rf, user_factory):
        user = user_factory()
        data = {"name": "John Doe", "username": "john.doe", "use_autologin": False}
        response = self.call_view(rf, user, data=data)
        user.refresh_from_db()
        assert response.status_code == 302
        assert response.url == f"/users/{user.username}/"
        assert user.name == data["name"]
        assert user.username == data["username"]
        assert not user.can_change_username
        assert user.individual_organization.name == data["username"]

    def test_bad_post(self, rf, user_factory):
        user = user_factory()
        # @ symbols not allowed in usernames
        data = {"name": "John Doe", "username": "john@doe", "use_autologin": False}
        response = self.call_view(rf, user, data=data)
        user.refresh_from_db()
        assert response.status_code == 200
        assert user.name != data["name"]
        assert user.username != data["username"]
        assert response.context_data["object"].username != data["username"]


@pytest.mark.django_db()
class TestLoginView(ViewTestMixin):
    """Test the User Redirect view"""

    view = views.LoginView
    url = "/accounts/login/"

    def test_get(self, rf):
        url = "/target/url/"
        next_url = f"{settings.MUCKROCK_URL}?{urlencode({'next': url})}"
        params = {"url_auth_token": "token", "next": next_url}
        response = self.call_view(rf, params=params)
        assert response.status_code == 302
        assert response.url == f"{settings.MUCKROCK_URL}{url}"


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
