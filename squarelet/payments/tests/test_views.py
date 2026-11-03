# Django
from django.contrib import messages
from django.http import Http404
from django.urls import reverse
from django.utils.http import urlencode

# Third Party
import pytest
from autoslug.utils import slugify

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.models import Organization
from squarelet.organizations.tests.models.test_billing_on_price import plan_with_slug
from squarelet.payments import views


@pytest.mark.django_db()
class TestPlanRedirectViewQueryString(ViewTestMixin):
    """Test that PlanRedirectView preserves query strings"""

    view = views.PlanRedirectView
    url = "/plans/{pk}/"

    def test_redirect_preserves_query_string(self, rf, user_factory, plan_factory):
        """PlanRedirectView should preserve purchase_redirect query parameter"""
        user = user_factory()
        plan = plan_factory(name="Test Plan", public=True)

        response = self.call_view(
            rf,
            user,
            params={"purchase_redirect": "https://example.com/callback"},
            pk=plan.pk,
        )

        assert response.status_code == 301
        assert "purchase_redirect=https" in response.url

    def test_redirect_without_query_string(self, rf, user_factory, plan_factory):
        """PlanRedirectView without query string should work as before"""
        user = user_factory()
        plan = plan_factory(name="Test Plan", public=True)

        response = self.call_view(rf, user, pk=plan.pk)

        assert response.status_code == 301
        expected_url = reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
        assert response.url == expected_url
        assert "?" not in response.url


@pytest.mark.django_db()
class TestPlanRedirectView(ViewTestMixin):
    """Test the Plan Redirect view that handles slug changes"""

    view = views.PlanRedirectView
    url = "/plans/{pk}/"

    def test_redirect_with_id_only(self, rf, user_factory, plan_factory):
        """Test that accessing plan by ID redirects to canonical URL with slug"""
        user = user_factory()
        plan = plan_factory(name="Test Plan", public=True)

        # Access plan using ID only
        response = self.call_view(rf, user, pk=plan.pk)

        # Should return 301 permanent redirect
        assert response.status_code == 301

        # Should redirect to canonical URL with both ID and slug
        expected_url = reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
        assert response.url == expected_url

    def test_redirect_with_slug_only(self, rf, user_factory, plan_factory):
        """Test that accessing plan by slug redirects to canonical URL with ID"""
        user = user_factory()
        plan = plan_factory(name="Test Plan", public=True)

        # Access plan using slug only
        self.url = "/plans/{slug}/"
        response = self.call_view(rf, user, slug=plan.slug)

        # Should return 301 permanent redirect
        assert response.status_code == 301

        # Should redirect to canonical URL with both ID and slug
        expected_url = reverse("plan_detail", kwargs={"pk": plan.pk, "slug": plan.slug})
        assert response.url == expected_url

        # Reset URL for other tests
        self.url = "/plans/{pk}/"

    def test_redirect_with_id_returns_current_slug(
        self, rf, user_factory, plan_factory
    ):
        """Test that ID-based access returns current slug after name change

        This simulates what happens after our migration updates plan names:
        old links using the plan ID will redirect to the new slug.
        """
        user = user_factory()
        # Create plan with original name
        plan = plan_factory(name="Sunlight Research Center - Premium", public=True)
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

        # Should redirect to canonical URL with NEW slug
        expected_url = reverse("plan_detail", kwargs={"pk": plan_id, "slug": new_slug})
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


@pytest.mark.django_db()
class TestPlanDetailView(ViewTestMixin):
    """A plan's page sells it to the accounts the user may buy it for."""

    view = views.PlanDetailView
    url = "/plans/{pk}-{slug}/"

    @pytest.fixture
    def personal_plan(self, plan_factory, plan_price_factory):
        plan = plan_factory(name="Personal", for_individuals=True, for_groups=False)
        plan_price_factory(plan=plan)
        return plan

    @pytest.fixture
    def group_plan(self, plan_factory, plan_price_factory):
        plan = plan_factory(name="Group", for_individuals=False, for_groups=True)
        plan_price_factory(plan=plan, interval="annual", amount=100000)
        plan_price_factory(plan=plan)
        return plan

    def view_plan(self, rf, user, plan, params=None):
        return self.call_view(rf, user, params=params, pk=plan.pk, slug=plan.slug)

    def test_a_visitor_sees_the_prices_and_is_asked_to_sign_in(self, rf, group_plan):
        response = self.view_plan(rf, None, group_plan)

        assert response.status_code == 200
        assert [p.interval for p in response.context_data["prices"]] == [
            "annual",
            "monthly",
        ]
        content = response.render().content.decode()
        nxt = urlencode({"next": f"/plans/{group_plan.pk}-{group_plan.slug}/"})
        assert f'href="{reverse("account_login")}?{nxt}"' in content
        assert f'href="{reverse("account_signup")}?{nxt}"' in content

    def test_a_personal_plan_goes_straight_to_the_users_checkout(
        self, rf, user_factory, personal_plan
    ):
        user = user_factory()

        response = self.view_plan(
            rf, user, personal_plan, params={"purchase_redirect": "https://x.test"}
        )

        assert response.status_code == 302
        checkout = reverse(
            "users:plan",
            kwargs={"username": user.username, "plan_slug": personal_plan.slug},
        )
        query = urlencode({"purchase_redirect": "https://x.test"})
        assert response.url == f"{checkout}?{query}"

    def test_an_admin_of_one_organization_goes_straight_to_its_checkout(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        organization_factory(users=[user])

        response = self.view_plan(rf, user, group_plan)

        assert response.status_code == 302
        assert response.url == reverse(
            "organizations:plan",
            kwargs={"slug": organization.slug, "plan_slug": group_plan.slug},
        )

    def test_an_admin_of_several_organizations_picks_one(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        beta = organization_factory(admins=[user], name="Beta")
        alpha = organization_factory(admins=[user], name="Alpha")

        response = self.view_plan(rf, user, group_plan)

        assert response.status_code == 200
        accounts = response.context_data["accounts"]
        assert [a["organization"] for a in accounts] == [alpha, beta]
        content = response.render().content.decode()
        for organization in (alpha, beta):
            checkout = reverse(
                "organizations:plan",
                kwargs={"slug": organization.slug, "plan_slug": group_plan.slug},
            )
            assert f'href="{checkout}"' in content

    def test_unsubscribed_organizations_are_listed_first(
        self,
        rf,
        user_factory,
        organization_factory,
        subscription_item_factory,
        group_plan,
    ):
        user = user_factory()
        subscribed = organization_factory(admins=[user], name="Alpha")
        charlie = organization_factory(admins=[user], name="Charlie")
        beta = organization_factory(admins=[user], name="Beta")
        subscription_item_factory(
            subscription__organization=subscribed, plan=group_plan
        )

        response = self.view_plan(rf, user, group_plan)

        accounts = response.context_data["accounts"]
        assert [a["organization"] for a in accounts] == [beta, charlie, subscribed]

    def test_an_organization_already_subscribed_is_offered_its_management(
        self,
        rf,
        user_factory,
        organization_factory,
        subscription_item_factory,
        group_plan,
    ):
        user = user_factory()
        subscribed = organization_factory(admins=[user], name="Alpha")
        organization_factory(admins=[user], name="Beta")
        subscription_item_factory(
            subscription__organization=subscribed, plan=group_plan
        )

        response = self.view_plan(rf, user, group_plan)

        held = {a["organization"]: a["held"] for a in response.context_data["accounts"]}
        assert held[subscribed] is True
        manage = reverse(
            "organizations:subscriptions", kwargs={"slug": subscribed.slug}
        )
        assert f'href="{manage}"' in response.render().content.decode()

    def test_a_user_who_runs_no_organization_is_offered_to_create_one(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        organization_factory(users=[user])

        response = self.view_plan(rf, user, group_plan)

        assert response.status_code == 200
        assert response.context_data["accounts"] == []
        create = reverse("organizations:create")
        assert f'href="{create}"' in response.render().content.decode()

    def test_an_organization_the_private_plan_is_not_for_is_not_offered(
        self, rf, user_factory, organization_factory, group_plan
    ):
        user = user_factory()
        organization_factory(admins=[user], name="Alpha")
        beta = organization_factory(admins=[user], name="Beta")
        group_plan.public = False
        group_plan.save()
        group_plan.private_organizations.add(beta)

        response = self.view_plan(rf, user, group_plan)

        assert response.url == reverse(
            "organizations:plan",
            kwargs={"slug": beta.slug, "plan_slug": group_plan.slug},
        )

    def test_an_enterprise_plan_offers_contact_without_redirecting(
        self, rf, user_factory, plan_factory
    ):
        user = user_factory()
        plan = plan_factory(name="Sunlight Enterprise", slug="sunlight-enterprise")

        response = self.view_plan(rf, user, plan)

        assert response.status_code == 200
        assert "calendar.app.google" in response.render().content.decode()

    def test_an_outdated_slug_still_finds_the_plan(self, rf, group_plan):
        response = self.call_view(rf, pk=group_plan.pk, slug="old-name")

        assert response.context_data["plan"] == group_plan

    def test_a_missing_plan_is_not_found(self, rf):
        with pytest.raises(Http404):
            self.call_view(rf, pk=99999, slug="gone")

    def test_a_private_plan_is_hidden_from_a_visitor(self, rf, group_plan):
        group_plan.public = False
        group_plan.save()
        group_plan.private_organizations.add(
            Organization.objects.create(name="Private")
        )

        with pytest.raises(Http404):
            self.view_plan(rf, None, group_plan)


@pytest.mark.django_db()
class TestOldPlanUrls(ViewTestMixin):
    """Old links and open tabs from the plan page that sold by plan row."""

    view = views.PlanDetailView
    url = "/plans/{pk}-{slug}/"

    @pytest.fixture
    def tier(self, plan_factory, plan_price_factory):
        tier = plan_with_slug(
            plan_factory, "Sunlight Essential", "sunlight-essential", public=True
        )
        plan_price_factory(plan=tier, interval="annual")
        return tier

    def test_an_entry_row_redirects_to_its_tier(self, rf, plan_factory, tier):
        entry = plan_with_slug(
            plan_factory, "Sunlight Essential (Annual)", "sunlight-essential-annual"
        )

        response = self.call_view(
            rf,
            params={"purchase_redirect": "https://x.test"},
            pk=entry.pk,
            slug=entry.slug,
        )

        assert response.status_code == 301
        query = urlencode({"purchase_redirect": "https://x.test"})
        assert response.url == f"{tier.get_absolute_url()}?{query}"

    def test_the_tier_itself_is_not_redirected(self, rf, tier):
        """The mapping lists each tier as its own target."""
        response = self.call_view(rf, pk=tier.pk, slug=tier.slug)

        assert response.status_code == 200
        assert response.context_data["object"] == tier

    @pytest.mark.usefixtures("tier")
    def test_a_negotiated_row_keeps_its_own_page(self, rf, plan_factory):
        row = plan_with_slug(
            plan_factory, "Sunlight Basic (Annual)", "sunlight-basic-annual"
        )

        response = self.call_view(rf, pk=row.pk, slug=row.slug)

        assert response.status_code == 200
        assert response.context_data["object"] == row

    @pytest.mark.usefixtures("tier")
    def test_a_post_from_an_open_tab_returns_to_the_page_and_says_so(
        self, rf, plan_factory
    ):
        entry = plan_with_slug(
            plan_factory, "Sunlight Essential (Annual)", "sunlight-essential-annual"
        )

        response = self.call_view(
            rf,
            data={"stripe_token": "tok_old"},
            params={"purchase_redirect": "https://x.test"},
            pk=entry.pk,
            slug=entry.slug,
        )

        assert response.status_code == 302
        query = urlencode({"purchase_redirect": "https://x.test"})
        assert response.url == f"/plans/{entry.pk}-{entry.slug}/?{query}"
        self.assert_message(
            messages.INFO,
            "This page has changed since you opened it, and nothing was "
            "charged. Please choose your plan again.",
        )
