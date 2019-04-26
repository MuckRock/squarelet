
# Django
from django.conf import settings

# Standard Library
from urllib.parse import urlencode

# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin

# Local
from .. import views


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
        next_url = "{}?{}".format(settings.MUCKROCK_URL, urlencode({"next": url}))
        params = {"url_auth_token": "token", "next": next_url}
        response = self.call_view(rf, params=params)
        assert response.status_code == 302
        assert response.url == f"{settings.MUCKROCK_URL}{url}"
