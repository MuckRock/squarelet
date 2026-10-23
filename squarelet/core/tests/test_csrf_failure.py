# Django
from django.test import Client
from django.urls import reverse

# Standard Library
import logging
import re
from urllib.parse import quote

# Third Party
import pytest

NEXT = "/openid/authorize?client_id=1&state=abc"


def login_url(next_url=NEXT):
    return f"{reverse('account_login')}?next={quote(next_url)}"


def form_token(response):
    return re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()
    ).group(1)


def credentials(user, token):
    return {"login": user.username, "password": "pw", "csrfmiddlewaretoken": token}


def stale_tab(user, next_url=NEXT):
    """Open the sign-in form in two tabs and sign in through the first."""
    client = Client(enforce_csrf_checks=True)
    stale = form_token(client.get(login_url(next_url)))
    fresh = form_token(client.get(login_url(next_url)))
    response = client.post(login_url(next_url), credentials(user, fresh))
    assert response.status_code == 302
    return client, stale


def our_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "squarelet.core.views"]


@pytest.fixture(name="user")
def user_fixture(user_factory):
    return user_factory(password="pw", email_verified=True)


@pytest.mark.django_db
class TestCsrfFailure:
    def test_a_stale_tab_is_forbidden_and_leaves_the_first_sign_in(
        self, user, user_factory
    ):
        other = user_factory(password="pw", email_verified=True)
        client, stale = stale_tab(user)
        response = client.post(login_url(), credentials(other, stale))
        assert response.status_code == 403
        assert client.session["_auth_user_id"] == str(user.pk)

    def test_an_anonymous_stale_form_is_forbidden(self, user):
        client = Client(enforce_csrf_checks=True)
        client.get(login_url())
        other_token = form_token(Client().get(login_url()))
        response = client.post(login_url(), credentials(user, other_token))
        assert response.status_code == 403
        assert "_auth_user_id" not in client.session

    def test_the_failure_is_logged_with_its_reason(self, user, caplog):
        client, stale = stale_tab(user)
        with caplog.at_level(logging.WARNING, logger="squarelet.core.views"):
            client.post(login_url(), credentials(user, stale))
        assert our_messages(caplog) == [
            "Sign-in CSRF failure: reason='CSRF token from POST incorrect.' "
            "authenticated=True url_name=account_login origin=absent "
            "request_id=none"
        ]

    def test_the_failure_is_logged_with_the_heroku_request_id(self, user, caplog):
        client, stale = stale_tab(user)
        with caplog.at_level(logging.WARNING, logger="squarelet.core.views"):
            client.post(
                login_url(),
                credentials(user, stale),
                HTTP_X_REQUEST_ID="9b1f6e2e-example",
            )
        assert "request_id=9b1f6e2e-example" in caplog.text

    def test_a_stale_mfa_step_is_logged(self, caplog):
        client = Client(enforce_csrf_checks=True)
        client.get(login_url())
        with caplog.at_level(logging.WARNING, logger="squarelet.core.views"):
            response = client.post(
                reverse("mfa_authenticate"),
                {"code": "123456", "csrfmiddlewaretoken": "x"},
            )
        assert response.status_code == 403
        assert "url_name=mfa_authenticate" in caplog.text

    def test_a_cross_origin_post_is_logged_as_cross(self, user, caplog):
        client, stale = stale_tab(user)
        with caplog.at_level(logging.WARNING, logger="squarelet.core.views"):
            response = client.post(
                login_url(),
                credentials(user, stale),
                HTTP_ORIGIN="https://evil.example",
            )
        assert response.status_code == 403
        assert "origin=cross" in caplog.text

    def test_other_forms_are_not_logged(self, user, caplog):
        client, stale = stale_tab(user)
        with caplog.at_level(logging.WARNING, logger="squarelet.core.views"):
            response = client.post(
                reverse("account_reset_password"),
                {"email": user.email, "csrfmiddlewaretoken": stale},
            )
        assert response.status_code == 403
        assert not our_messages(caplog)
