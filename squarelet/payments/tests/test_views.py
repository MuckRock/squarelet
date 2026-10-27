# Django
from django.http import Http404
from django.urls import reverse
from django.utils.http import urlencode

# Third Party
import pytest
from autoslug.utils import slugify

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.payments import views


@pytest.mark.django_db()
class TestPlanRedirectViewQueryString(ViewTestMixin):
    """Test that PlanRedirectView preserves query strings"""

    view = views.PlanRedirectView
    url = "/plans/{pk}/"

    def test_redirect_preserves_query_string(
        self, rf, user_factory, plan_price_factory
    ):
        """PlanRedirectView should preserve purchase_redirect query parameter"""
        user = user_factory()
        plan = plan_price_factory(plan__name="Test Plan", plan__public=True).plan

        response = self.call_view(
            rf,
            user,
            params={"purchase_redirect": "https://example.com/callback"},
            pk=plan.pk,
        )

        assert response.status_code == 301
        assert "purchase_redirect=https" in response.url

    def test_redirect_without_query_string(self, rf, user_factory, plan_price_factory):
        """PlanRedirectView without query string should work as before"""
        user = user_factory()
        plan = plan_price_factory(plan__name="Test Plan", plan__public=True).plan

        response = self.call_view(rf, user, pk=plan.pk)

        assert response.status_code == 301
        expected_url = reverse(
            "users:plan", kwargs={"username": user.username, "plan_slug": plan.slug}
        )
        assert response.url == expected_url
        assert "?" not in response.url


@pytest.mark.django_db()
class TestPlanRedirectView(ViewTestMixin):
    """Test the Plan Redirect view that handles slug changes"""

    view = views.PlanRedirectView
    url = "/plans/{pk}/"

    def test_redirect_with_id_only(self, rf, user_factory, plan_price_factory):
        """Accessing an individual plan by ID redirects to the user's checkout"""
        user = user_factory()
        plan = plan_price_factory(plan__name="Test Plan", plan__public=True).plan

        # Access plan using ID only
        response = self.call_view(rf, user, pk=plan.pk)

        # Should return 301 permanent redirect
        assert response.status_code == 301

        expected_url = reverse(
            "users:plan", kwargs={"username": user.username, "plan_slug": plan.slug}
        )
        assert response.url == expected_url

    def test_redirect_with_slug_only(self, rf, user_factory, plan_price_factory):
        """Accessing an individual plan by slug redirects to the user's checkout"""
        user = user_factory()
        plan = plan_price_factory(plan__name="Test Plan", plan__public=True).plan

        # Access plan using slug only
        self.url = "/plans/{slug}/"
        response = self.call_view(rf, user, slug=plan.slug)

        # Should return 301 permanent redirect
        assert response.status_code == 301

        expected_url = reverse(
            "users:plan", kwargs={"username": user.username, "plan_slug": plan.slug}
        )
        assert response.url == expected_url

        # Reset URL for other tests
        self.url = "/plans/{pk}/"

    def test_redirect_with_id_returns_current_slug(
        self, rf, user_factory, plan_price_factory
    ):
        """Test that ID-based access returns current slug after name change

        This simulates what happens after our migration updates plan names:
        old links using the plan ID will redirect to the new slug.
        """
        user = user_factory()
        # Create plan with original name
        plan = plan_price_factory(
            plan__name="Sunlight Research Center - Premium", plan__public=True
        ).plan
        plan_id = plan.pk

        # Manually update slug to simulate migration changing the name
        # We update slug directly since AutoSlugField doesn't auto-update on save
        old_slug = plan.slug
        plan.name = "Sunlight Research Desk Membership - Premium"
        plan.slug = slugify(plan.name)
        plan.save()
        plan.refresh_from_db()
        new_slug = plan.slug

        # Verify slug changed
        assert old_slug != new_slug
        assert old_slug == "sunlight-research-center-premium"
        assert new_slug == "sunlight-research-desk-membership-premium"

        # Access plan using just the ID (like old bookmarks would)
        response = self.call_view(rf, user, pk=plan_id)

        # Should return 301 permanent redirect
        assert response.status_code == 301

        # Should redirect to checkout with the NEW slug
        expected_url = reverse(
            "users:plan", kwargs={"username": user.username, "plan_slug": new_slug}
        )
        assert response.url == expected_url
        assert "sunlight-research-desk-membership" in response.url

    def test_redirect_nonexistent_plan_returns_404(self, rf, user_factory):
        """Test that accessing non-existent plan returns 404"""
        user = user_factory()

        # Try to access plan that doesn't exist
        with pytest.raises(Http404):
            self.call_view(rf, user, pk=99999)

    def test_redirect_nonexistent_slug_returns_404(self, rf, user_factory):
        """Test that accessing non-existent slug returns 404"""
        user = user_factory()

        # Try to access plan with slug that doesn't exist
        self.url = "/plans/{slug}/"
        with pytest.raises(Http404):
            self.call_view(rf, user, slug="nonexistent-plan-slug")

        # Reset URL for other tests
        self.url = "/plans/{pk}/"

    @pytest.fixture
    def group_plan(self, plan_factory, plan_price_factory):
        plan = plan_factory(
            name="Group Plan", public=True, for_individuals=False, for_groups=True
        )
        plan_price_factory(plan=plan)
        return plan

    def test_an_org_plan_goes_to_an_organization_that_may_buy_it(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        organization_factory(admins=[user], name="Alpha")
        beta = organization_factory(admins=[user], name="Beta")
        group_plan.public = False
        group_plan.save()
        group_plan.private_organizations.add(beta)

        response = self.call_view(rf, user, pk=group_plan.pk)

        assert response.url == reverse(
            "organizations:plan",
            kwargs={"slug": beta.slug, "plan_slug": group_plan.slug},
        )

    def test_an_org_plan_goes_to_an_organization_the_user_runs(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        organization_factory(admins=[user], name="Zeta")
        yonder = organization_factory(admins=[user], name="Yonder")

        response = self.call_view(rf, user, pk=group_plan.pk)

        assert response.status_code == 301
        assert response.url == reverse(
            "organizations:plan",
            kwargs={"slug": yonder.slug, "plan_slug": group_plan.slug},
        )

    def test_an_org_plan_is_not_found_for_a_user_who_runs_no_organization(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        organization_factory(users=[user])

        with pytest.raises(Http404):
            self.call_view(rf, user, pk=group_plan.pk)

    def test_a_visitor_logs_in_without_the_redirect_being_cached(
        self, rf, plan_factory
    ):
        plan = plan_factory(name="Test Plan", public=True)

        response = self.call_view(
            rf, params={"purchase_redirect": "https://example.com"}, pk=plan.pk
        )

        assert response.status_code == 302
        query = urlencode({"purchase_redirect": "https://example.com"})
        assert response.url == reverse("account_login") + "?" + urlencode(
            {"next": f"/plans/{plan.pk}/?{query}"}
        )
