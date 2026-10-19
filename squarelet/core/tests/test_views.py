# Django
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import Http404

# Third Party
import pytest

# Squarelet
from squarelet.core.exceptions import ContextHttp404
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.core.views import SelectPlanView, page_not_found
from squarelet.organizations.models import Plan


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


@pytest.mark.django_db()
class TestSelectPlan(ViewTestMixin):
    """The public pricing page's Sunlight subscribe buttons."""

    view = SelectPlanView
    url = "/selectplan/"

    @pytest.fixture
    def essential(self, plan_price_factory):
        """The legacy annual row the page links, priced on its canonical tier."""
        # Keyed on slug: the migrations seed these rows on a fresh database.
        groups_only = {
            "public": True,
            "wix": True,
            "for_individuals": False,
            "for_groups": True,
        }
        tier, _ = Plan.objects.update_or_create(
            slug="sunlight-essential",
            defaults={"name": "Sunlight Essential", **groups_only},
        )
        plan_price_factory(plan=tier, interval="annual", amount=100_000)
        annual, _ = Plan.objects.update_or_create(
            slug="sunlight-essential-annual",
            defaults={"name": "Sunlight Essential Annual", **groups_only},
        )
        return annual

    def tier(self, response, name="Essential"):
        return next(
            tier
            for tier in response.context_data["sunlight_tiers"]
            if tier["name"] == name
        )

    def test_a_tier_links_to_checkout_for_an_organization_the_user_runs(
        self, rf, user_factory, organization_factory, essential
    ):
        user = user_factory()
        organization = organization_factory(admins=[user], name="Acme")

        response = self.call_view(rf, user)

        checkout = f"/organizations/{organization.slug}/plans/{essential.slug}/"
        assert self.tier(response)["checkout_url"] == checkout
        assert f'href="{checkout}"' in response.render().content.decode()

    @pytest.mark.usefixtures("essential")
    def test_a_tier_has_no_checkout_for_a_user_who_runs_no_organization(
        self, rf, user_factory
    ):
        response = self.call_view(rf, user_factory())

        assert self.tier(response)["checkout_url"] is None
        assert b"/plans/" not in response.render().content

    @pytest.mark.usefixtures("essential")
    def test_a_visitor_signs_up_and_returns_to_the_pricing_page(self, rf):
        content = self.call_view(rf).render().content.decode()

        assert "/accounts/signup/?" in content
        assert "next=%2Fselectplan%2F" in content
        assert "/plans/" not in content
