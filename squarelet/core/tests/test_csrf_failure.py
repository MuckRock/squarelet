# Django
from django.contrib.messages import get_messages
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


@pytest.fixture(name="user")
def user_fixture(user_factory):
    return user_factory(password="pw", email_verified=True)


@pytest.mark.django_db
class TestCsrfFailure:
    def test_a_stale_tab_continues_to_next_without_signing_in_again(
        self, user, user_factory
    ):
        other = user_factory(password="pw", email_verified=True)
        client, stale = stale_tab(user)
        response = client.post(login_url(), credentials(other, stale))
        assert response.status_code == 302
        assert response["Location"] == NEXT
        assert client.session["_auth_user_id"] == str(user.pk)

    def test_an_offsite_next_falls_back_to_the_login_redirect(self, user):
        client, stale = stale_tab(user, next_url="https://evil.example/")
        response = client.post(
            login_url("https://evil.example/"), credentials(user, stale)
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("users:redirect")

    def test_an_anonymous_stale_form_is_shown_again_with_next(self, user):
        client = Client(enforce_csrf_checks=True)
        client.get(login_url())
        other_token = form_token(Client().get(login_url()))
        response = client.post(login_url(), credentials(user, other_token))
        assert response.status_code == 302
        assert response["Location"] == login_url()
        assert "_auth_user_id" not in client.session
        assert [str(m) for m in get_messages(response.wsgi_request)] == [
            "Your sign-in page expired. Please try again."
        ]

    def test_a_stale_mfa_step_is_shown_again(self):
        client = Client(enforce_csrf_checks=True)
        client.get(login_url())
        url = reverse("mfa_authenticate")
        response = client.post(url, {"code": "123456", "csrfmiddlewaretoken": "x"})
        assert response.status_code == 302
        assert response["Location"] == url

    def test_a_same_origin_header_still_recovers(self, user):
        client, stale = stale_tab(user)
        response = client.post(
            login_url(), credentials(user, stale), HTTP_ORIGIN="http://testserver"
        )
        assert response.status_code == 302

    def test_a_cross_origin_post_is_forbidden(self, user):
        client, stale = stale_tab(user)
        response = client.post(
            login_url(), credentials(user, stale), HTTP_ORIGIN="https://evil.example"
        )
        assert response.status_code == 403

    def test_other_forms_are_still_forbidden(self, user):
        client, stale = stale_tab(user)
        response = client.post(
            reverse("account_reset_password"),
            {"email": user.email, "csrfmiddlewaretoken": stale},
        )
        assert response.status_code == 403

    def test_the_failure_is_logged_with_its_reason(self, user, caplog):
        client, stale = stale_tab(user)
        with caplog.at_level(logging.WARNING, logger="squarelet.core.views"):
            client.post(login_url(), credentials(user, stale))
        assert caplog.messages == [
            "Sign-in CSRF failure: reason='CSRF token from POST incorrect.' "
            "authenticated=True url_name=account_login origin=absent"
        ]
