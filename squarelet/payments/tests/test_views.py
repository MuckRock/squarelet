# Django
from django.http import Http404
from django.urls import reverse

# Third Party
import pytest
from autoslug.utils import slugify

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.models import Organization, Plan
from squarelet.payments import views

# pylint: disable=invalid-name


@pytest.mark.django_db()
class TestPlanDetailViewCreateOrganization(ViewTestMixin):
    """Test the Plan Detail view with new organization creation"""

    view = views.PlanDetailView
    url = "/plans/{pk}/{slug}/"

    def test_create_new_organization_with_subscription(
        self, rf, user_factory, plan_factory, mocker
    ):
        """Test creating a new organization during plan subscription"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)

        # Mock the set_subscription method to avoid Stripe calls
        mock_set_subscription = mocker.patch.object(
            Organization, "set_subscription", return_value=None
        )

        data = {
            "organization": "new",
            "new_organization_name": "My New Organization",
            "stripe_token": "tok_visa",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Verify organization was created
        org = Organization.objects.get(name="My New Organization")
        assert org.private is False
        assert org.has_admin(user)

        # Verify subscription was created
        mock_set_subscription.assert_called_once_with(
            token="tok_visa",
            plan=plan,
            max_users=plan.minimum_users,
            user=user,
            payment_method=None,
        )

        # Should redirect to the organization
        assert response.status_code == 302
        assert response.url == org.get_absolute_url()

    def test_create_new_organization_without_name(self, rf, user_factory, plan_factory):
        """Test validation when creating organization without a name"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)

        data = {
            "organization": "new",
            "new_organization_name": "",  # Empty name
            "stripe_token": "tok_visa",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect with error message
        assert response.status_code == 302

        # Verify no organization was created
        assert not Organization.objects.filter(name="").exists()

    def test_new_organization_adds_user_as_admin(
        self, rf, user_factory, plan_factory, mocker
    ):
        """Test that user is added as admin when creating new organization"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)

        # Mock set_subscription
        mocker.patch.object(Organization, "set_subscription", return_value=None)

        data = {
            "organization": "new",
            "new_organization_name": "Test Org",
            "stripe_token": "tok_visa",
        }

        self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        org = Organization.objects.get(name="Test Org")

        # Verify user is admin
        assert org.has_admin(user)

        # Verify user's email is added as receipt email
        if user.email:
            assert org.receipt_emails.filter(email=user.email).exists()

    def test_existing_organization_flow_still_works(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Test that existing organization subscription still works"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)

        # Mock set_subscription
        mock_set_subscription = mocker.patch.object(
            Organization, "set_subscription", return_value=None
        )

        data = {
            "organization": str(org.pk),
            "stripe_token": "tok_visa",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Verify subscription was created with existing org
        mock_set_subscription.assert_called_once_with(
            token="tok_visa",
            plan=plan,
            max_users=plan.minimum_users,
            user=user,
            payment_method=None,
        )

        # Should redirect to the organization
        assert response.status_code == 302
        assert response.url == org.get_absolute_url()

    def test_unauthenticated_user_redirected_to_login(self, rf, plan_factory):
        """Test that unauthenticated users are redirected to login"""
        plan = plan_factory(public=True)

        data = {
            "organization": "new",
            "new_organization_name": "Test Org",
            "stripe_token": "tok_visa",
        }

        response = self.call_view(rf, user=None, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_already_subscribed_organization(
        self, rf, user_factory, organization_factory, plan_factory, subscription_factory
    ):
        """Test that already subscribed organizations show warning"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)
        org = organization_factory()
        org.add_creator(user)

        # Create existing subscription
        subscription_factory(organization=org, plan=plan, cancelled=False)

        data = {
            "organization": str(org.pk),
            "stripe_token": "tok_visa",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect back to plan
        assert response.status_code == 302

    def test_existing_card_without_card_on_file(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Test validation: selecting existing-card without a card on file"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)

        # Mock that organization has NO card
        mock_customer = mocker.MagicMock()
        mock_customer.card = None
        mocker.patch.object(org, "customer", return_value=mock_customer)

        data = {
            "organization": str(org.pk),
            "payment_method": "existing-card",
            "stripe_token": "",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect back to plan with error
        assert response.status_code == 302
        assert response.url == plan.get_absolute_url()

    def test_new_card_without_stripe_token(
        self, rf, user_factory, organization_factory, plan_factory
    ):
        """Test validation: selecting new-card without providing token"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "",  # No token provided
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect back to plan with error
        assert response.status_code == 302
        assert response.url == plan.get_absolute_url()

    def test_invoice_payment_for_non_annual_plan(
        self, rf, user_factory, organization_factory, plan_factory
    ):
        """Test validation: invoice payment only available for annual plans"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True, annual=False)

        data = {
            "organization": str(org.pk),
            "payment_method": "invoice",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect back to plan with error
        assert response.status_code == 302
        assert response.url == plan.get_absolute_url()

    def test_invoice_payment_for_annual_plan_succeeds(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Test that invoice payment works correctly for annual plans"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True, annual=True)

        # Mock set_subscription
        mock_set_subscription = mocker.patch.object(
            Organization, "set_subscription", return_value=None
        )

        data = {
            "organization": str(org.pk),
            "payment_method": "invoice",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should succeed and call set_subscription with invoice payment method
        mock_set_subscription.assert_called_once_with(
            token=None,
            plan=plan,
            max_users=plan.minimum_users,
            user=user,
            payment_method="invoice",
        )

        # Should redirect to organization
        assert response.status_code == 302
        assert response.url == org.get_absolute_url()


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
class TestPlanDetailViewWithSlug(ViewTestMixin):
    """Test the Plan Detail view with canonical URL format (ID + slug)"""

    view = views.PlanDetailView
    url = "/plans/{pk}-{slug}/"

    def test_canonical_url_with_correct_slug(
        self, rf, user_factory, plan_factory, mocker
    ):
        """Test that canonical URL with correct slug works"""
        user = user_factory()
        plan = plan_factory(name="Test Plan", public=True)

        # Mock Stripe customer to avoid API calls
        mock_customer = mocker.MagicMock()
        mock_customer.card = None
        mocker.patch.object(
            user.individual_organization, "customer", return_value=mock_customer
        )

        # Access plan using canonical URL format
        response = self.call_view(rf, user, pk=plan.pk, slug=plan.slug)

        # Should return 200 OK (no redirect needed)
        assert response.status_code == 200

        # Verify matching_plan is in context (should be None for non-Sunlight plans)
        assert "matching_plan" in response.context_data
        assert response.context_data["matching_plan"] is None

    def test_canonical_url_with_outdated_slug_still_works(
        self, rf, user_factory, plan_factory, mocker
    ):
        """Test that canonical URL with outdated slug still works

        Django's DetailView uses pk to fetch the object, so the slug
        parameter is not validated. This means old bookmarks with outdated
        slugs will still work without redirecting.

        This is actually desirable behavior - it means we don't break
        existing links when we rename plans.
        """
        user = user_factory()
        # Create plan with original name
        plan = plan_factory(name="Sunlight Research Center - Basic", public=True)
        plan_id = plan.pk
        old_slug = plan.slug

        # Mock Stripe customer to avoid API calls
        mock_customer = mocker.MagicMock()
        mock_customer.card = None
        mocker.patch.object(
            user.individual_organization, "customer", return_value=mock_customer
        )

        # Update the plan name and slug (simulating our migration)
        plan.name = "Sunlight Research Desk Membership - Basic"
        plan.slug = slugify(plan.name)
        plan.save()
        plan.refresh_from_db()
        new_slug = plan.slug

        # Verify slug changed
        assert old_slug != new_slug
        assert old_slug == "sunlight-research-center-basic"
        assert new_slug == "sunlight-research-desk-membership-basic"

        # Access plan using OLD slug with correct ID (like an old bookmark)
        response = self.call_view(rf, user, pk=plan_id, slug=old_slug)

        # Should return 200 OK - Django DetailView doesn't validate the slug
        # The pk is correct, so it fetches the right plan
        assert response.status_code == 200

        # The view should still work and load the correct plan
        assert response.context_data["plan"].pk == plan_id
        assert response.context_data["plan"].name == plan.name

    def test_canonical_url_with_wrong_slug_wrong_id_returns_404(
        self, rf, user_factory, plan_factory
    ):
        """Test that wrong ID returns 404, regardless of slug"""
        user = user_factory()
        plan = plan_factory(name="Test Plan", public=True)

        # Try to access with non-existent ID (slug doesn't matter)
        with pytest.raises(Http404):
            self.call_view(rf, user, pk=99999, slug=plan.slug)


@pytest.mark.django_db()
class TestGetMatchingPlanTier:
    """Test the get_matching_plan_tier helper function"""

    def test_non_sunlight_plan_returns_none(self, plan_factory):
        """Test that non-Sunlight plans return None"""
        plan = plan_factory(name="Regular Plan", public=True)

        result = views.get_matching_plan_tier(plan)
        assert result is None

    def test_finds_matching_sunlight_plan_if_exists(self):
        """Test that it finds matching Sunlight plans from the database"""
        # Try to find the actual Sunlight plans from the migration
        monthly = Plan.objects.filter(slug="sunlight-basic").first()
        annual = Plan.objects.filter(slug="sunlight-basic-annual").first()

        # Only test if both plans exist in the database
        if monthly and annual:
            result_from_monthly = views.get_matching_plan_tier(monthly)
            assert result_from_monthly == annual

            result_from_annual = views.get_matching_plan_tier(annual)
            assert result_from_annual == monthly
