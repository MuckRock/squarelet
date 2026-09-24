# Django
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import Http404

# Third Party
import pytest

# Squarelet
from squarelet.core.exceptions import ContextHttp404
from squarelet.core.views import SelectPlanView, page_not_found, sunlight_tiers
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
class TestSunlightTiersOnThePlanPage:
    """The Sunlight tiers are read off the canonical plans and their prices.

    They used to be assembled from the separate `sunlight-essential-annual`
    and `sunlight-nonprofit-*` rows by slug suffix, which is what kept those
    rows alive - and read `base_price` off each, which is a column on its
    way out.
    """

    @pytest.fixture(autouse=True)
    def _only_the_tiers_this_test_makes(self, db):  # pylint: disable=unused-argument
        """Release 1 seeds the three Sunlight tiers, so a test that builds
        its own has to say which ones are on the page rather than assume
        an empty table."""
        Plan.objects.including_archived().filter(product="sunlight").update(wix=False)

    def _tier(self, plan_factory, name, slug, **kwargs):
        plan = Plan.objects.including_archived().filter(slug=slug).first()
        if plan is None:
            plan = plan_factory(name=name, slug=slug)
        for field, value in {"product": "sunlight", "wix": True, **kwargs}.items():
            setattr(plan, field, value)
        plan.save()
        plan.prices.all().delete()
        return plan

    def _essential(self, plan_factory, plan_price_factory):
        plan = self._tier(
            plan_factory,
            "Sunlight Essential",
            "sunlight-essential",
            short_description="For newsrooms",
        )
        plan_price_factory(plan=plan, interval="monthly", amount=68_000)
        plan_price_factory(plan=plan, interval="annual", amount=800_000)
        plan_price_factory(
            plan=plan, interval="annual", label="nonprofit", amount=400_000
        )
        return plan

    def test_a_tier_carries_its_prices_by_interval_and_label(
        self, plan_factory, plan_price_factory
    ):
        plan = self._essential(plan_factory, plan_price_factory)

        tier = sunlight_tiers()[0]

        assert tier["name"] == "Essential"
        assert tier["plan"] == plan
        assert tier["monthly"]["standard"].amount == 68_000
        assert tier["monthly"]["nonprofit"] is None
        assert tier["annual"]["standard"].amount == 800_000
        assert tier["annual"]["nonprofit"].amount == 400_000

    def test_negotiated_and_inactive_prices_are_not_shown(
        self, plan_factory, plan_price_factory
    ):
        plan = self._essential(plan_factory, plan_price_factory)
        plan_price_factory(plan=plan, interval="annual", code="legacy-basic")
        plan_price_factory(
            plan=plan, interval="monthly", label="nonprofit", active=False
        )

        tier = sunlight_tiers()[0]

        assert tier["annual"]["standard"].code == ""
        assert tier["monthly"]["nonprofit"] is None

    def test_tiers_come_in_order_and_only_the_ones_that_exist(
        self, plan_factory, plan_price_factory
    ):
        self._essential(plan_factory, plan_price_factory)
        self._tier(plan_factory, "Sunlight Enterprise", "sunlight-enterprise")

        assert [t["name"] for t in sunlight_tiers()] == ["Essential", "Enterprise"]

    def test_the_page_renders_the_prices_and_links_the_interval(
        self, rf, plan_factory, plan_price_factory
    ):
        plan = self._essential(plan_factory, plan_price_factory)
        request = _request(rf)

        html = SelectPlanView.as_view()(request).rendered_content

        assert "$8,000" in html
        assert "$680" in html
        assert "$4,000" in html
        assert f"{plan.get_absolute_url()}?interval=annual" in html
