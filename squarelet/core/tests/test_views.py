# Django
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import Http404

# Third Party
import pytest

# Squarelet
from squarelet.core.exceptions import ContextHttp404
from squarelet.core.views import page_not_found


def _request(rf, user=None):
    """Build a request suitable for rendering the 404 page"""
    request = rf.get("/this-page-does-not-exist/")
    request.user = AnonymousUser() if user is None else user
    request.session = SessionStore()
    return request


class TestContextHttp404:
    """Unit tests for the ContextHttp404 exception"""

    def test_is_an_http404(self):
        """It must behave like a normal Http404 so Django's handler picks it up"""
        assert issubclass(ContextHttp404, Http404)
        assert isinstance(ContextHttp404(), Http404)

    def test_context_defaults_to_empty_dict(self):
        assert ContextHttp404().context == {}

    def test_explicit_none_context_becomes_empty_dict(self):
        assert ContextHttp404("missing", context=None).context == {}

    def test_carries_context_and_message(self):
        exception = ContextHttp404("missing", context={"user_orgs": []})
        assert exception.context == {"user_orgs": []}
        assert exception.args[0] == "missing"


@pytest.mark.django_db()
class TestPageNotFoundRendering:
    """Rendering tests for the 404 template driven by the custom handler"""

    def test_generic_404_shows_default_copy(self, rf):
        response = page_not_found(_request(rf), Http404())

        content = response.content.decode()
        assert response.status_code == 404
        assert "Page not found" in content
        assert "Organization not found" not in content

    def test_org_404_without_orgs_shows_org_copy_only(self, rf):
        response = page_not_found(
            _request(rf), ContextHttp404(context={"user_orgs": []})
        )

        content = response.content.decode()
        assert response.status_code == 404
        assert "Organization not found" in content
        assert "Were you looking for one of these organizations?" not in content

    def test_org_404_lists_the_users_organizations(
        self, rf, user_factory, organization_factory
    ):
        user = user_factory()
        organization = organization_factory(name="Test Newsroom", users=[user])

        response = page_not_found(
            _request(rf, user),
            ContextHttp404(context={"user_orgs": [organization]}),
        )

        content = response.content.decode()
        assert response.status_code == 404
        assert "Organization not found" in content
        assert "Were you looking for one of these organizations?" in content
        assert "Test Newsroom" in content
        assert organization.get_absolute_url() in content
