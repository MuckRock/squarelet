# Django
from django.http import Http404
from django.urls import reverse
from django.utils.http import urlencode

# Third Party
import pytest
from autoslug.utils import slugify

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.models import Organization
from squarelet.payments import views

# pylint: disable=too-many-positional-arguments


@pytest.mark.django_db()
class TestPlanDetailViewCreateOrganization(ViewTestMixin):
    """Test the Plan Detail view with new organization creation"""

    view = views.PlanDetailView
    url = "/plans/{pk}/{slug}/"

    def test_create_new_organization_with_subscription(
        self, rf, user_factory, plan_factory, mocker
    ):
        """Test creating a new organization during plan subscription"""
        user = user_factory(email_verified=True)
        plan = plan_factory(for_groups=True, public=True)

        # Mock the add_subscription method to avoid Stripe calls
        mock_add_subscription = mocker.patch.object(
            Organization, "add_subscription", return_value=None
        )

        data = {
            "organization": "new",
            "new_organization_name": "My New Organization",
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Verify organization was created
        org = Organization.objects.get(name="My New Organization")
        assert org.private is False
        assert org.has_admin(user)

        # Verify subscription was created
        mock_add_subscription.assert_called_once_with(
            plan,
            None,
            user,
            token="tok_visa",
            payment_method="new-card",
            nonprofit=False,
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
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should re-render form with error (200, not redirect)
        assert response.status_code == 200

        # Verify no organization was created
        assert not Organization.objects.filter(name="").exists()

    def test_unverified_user_cannot_create_organization(
        self, rf, user_factory, plan_factory, mocker
    ):
        """A user without a verified email may not create a new organization"""
        user = user_factory(email_verified=False)
        plan = plan_factory(for_groups=True, public=True)

        # Guard against any subscription side effects
        mock_add_subscription = mocker.patch.object(
            Organization, "add_subscription", return_value=None
        )

        data = {
            "organization": "new",
            "new_organization_name": "Should Not Exist",
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Form is invalid: re-renders (200), no org created, no subscription
        assert response.status_code == 200
        assert not Organization.objects.filter(name="Should Not Exist").exists()
        mock_add_subscription.assert_not_called()

    def test_new_organization_adds_user_as_admin(
        self, rf, user_factory, plan_factory, mocker
    ):
        """Test that user is added as admin when creating new organization"""
        user = user_factory(email_verified=True)
        plan = plan_factory(for_groups=True, public=True)

        # Mock add_subscription
        mocker.patch.object(Organization, "add_subscription", return_value=None)

        data = {
            "organization": "new",
            "new_organization_name": "Test Org",
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        org = Organization.objects.get(name="Test Org")

        # Verify user is admin
        assert org.has_admin(user)

        # Verify user's email is set as billing email
        if user.email:
            assert org.receipt_email.email == user.email

    def test_existing_organization_flow_still_works(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Test that existing organization subscription still works"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)

        # Mock add_subscription
        mock_add_subscription = mocker.patch.object(
            Organization, "add_subscription", return_value=None
        )

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Verify subscription was created with existing org
        mock_add_subscription.assert_called_once_with(
            plan,
            None,
            user,
            token="tok_visa",
            payment_method="new-card",
            nonprofit=False,
        )

        # Should redirect to the organization
        assert response.status_code == 302
        assert response.url == org.get_absolute_url()

    def test_an_organization_on_a_comp_can_buy_its_tier(
        self,
        rf,
        user_factory,
        organization_factory,
        plan_factory,
        subscription_item_factory,
        mocker,
    ):
        """`add_subscription` replaces the comp, so it is not already subscribed."""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)
        subscription_item_factory(
            subscription__organization=org, plan=plan, subscription__kind="free"
        )
        mock_add_subscription = mocker.patch.object(
            Organization, "add_subscription", return_value=None
        )

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        mock_add_subscription.assert_called_once()

    def test_unauthenticated_user_redirected_to_login(self, rf, plan_factory):
        """Test that unauthenticated users are redirected to login"""
        plan = plan_factory(public=True)

        data = {
            "organization": "new",
            "new_organization_name": "Test Org",
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user=None, data=data, pk=plan.pk, slug=plan.slug)

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_already_subscribed_organization(
        self,
        rf,
        user_factory,
        organization_factory,
        plan_factory,
        subscription_item_factory,
    ):
        """Test that already subscribed organizations are excluded from form"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)
        org = organization_factory()
        org.add_creator(user)

        # Create existing subscription
        subscription_item_factory(
            subscription__organization=org, plan=plan, subscription__cancelled=False
        )

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Form validation should fail because org is excluded from queryset
        # Should re-render form with error (200, not redirect)
        assert response.status_code == 200

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
        mock_customer.payment_details = None
        mocker.patch.object(Organization, "customer", return_value=mock_customer)

        data = {
            "organization": str(org.pk),
            "payment_method": "existing-card",
            "stripe_token": "",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should re-render form with error (200, not redirect)
        assert response.status_code == 200

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
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should re-render form with error (200, not redirect)
        assert response.status_code == 200

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
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should re-render form with error (200, not redirect)
        assert response.status_code == 200

    def test_invoice_payment_for_annual_plan_succeeds(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Test that invoice payment works correctly for annual plans"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True, annual=True)

        # Mock add_subscription
        mock_add_subscription = mocker.patch.object(
            Organization, "add_subscription", return_value=None
        )

        data = {
            "organization": str(org.pk),
            "payment_method": "invoice",
            "stripe_pk": "pk_test",
        }

        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        # Should succeed and call add_subscription with invoice payment method
        mock_add_subscription.assert_called_once_with(
            plan,
            None,
            user,
            token="",
            payment_method="invoice",
            nonprofit=False,
        )

        # Should redirect to organization
        assert response.status_code == 302
        assert response.url == org.get_absolute_url()


@pytest.mark.django_db()
class TestPlanDetailViewPurchaseRedirect(ViewTestMixin):
    """Test purchase_redirect query parameter support"""

    view = views.PlanDetailView
    url = "/plans/{pk}/{slug}/"

    def test_purchase_redirect_on_success(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """After successful purchase, redirect to purchase_redirect URL
        instead of org page"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)
        mocker.patch.object(Organization, "add_subscription", return_value=None)

        # Register example.com as an allowed service host
        Service.objects.create(
            slug="example",
            name="Example",
            description="Test service",
            provider_name="Test",
            base_url="https://example.com",
        )

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
            "purchase_redirect": "https://example.com/callback",
        }
        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        assert response.status_code == 302
        assert response.url == "https://example.com/callback"

    def test_unsafe_purchase_redirect_ignored(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Unsafe redirect URLs (javascript:, data:, etc.) should be ignored"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)
        mocker.patch.object(Organization, "add_subscription", return_value=None)

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
            "purchase_redirect": "javascript:alert(1)",
        }
        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        assert response.status_code == 302
        assert response.url == org.get_absolute_url()

    def test_unregistered_host_purchase_redirect_ignored(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Redirect URLs with hosts not in settings, services, or OIDC clients
        should be ignored"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)
        mocker.patch.object(Organization, "add_subscription", return_value=None)

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
            "purchase_redirect": "https://evil.example.com/steal",
        }
        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        assert response.status_code == 302
        assert response.url == org.get_absolute_url()

    def test_no_purchase_redirect_defaults_to_org(
        self, rf, user_factory, organization_factory, plan_factory, mocker
    ):
        """Without purchase_redirect, redirect to org page as before"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(for_groups=True, public=True)
        mocker.patch.object(Organization, "add_subscription", return_value=None)

        data = {
            "organization": str(org.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }
        response = self.call_view(rf, user, data=data, pk=plan.pk, slug=plan.slug)

        assert response.status_code == 302
        assert response.url == org.get_absolute_url()

    def test_purchase_redirect_in_form_initial(
        self, rf, user_factory, plan_factory, mocker
    ):
        """GET request with purchase_redirect should set it as form initial value"""
        user = user_factory()
        plan = plan_factory(public=True)

        mock_customer = mocker.MagicMock()
        mock_customer.payment_details = None
        mocker.patch.object(
            user.individual_organization, "customer", return_value=mock_customer
        )

        response = self.call_view(
            rf,
            user,
            params={"purchase_redirect": "https://example.com/callback"},
            pk=plan.pk,
            slug=plan.slug,
        )

        assert response.status_code == 200
        form = response.context_data["form"]
        assert form.initial["purchase_redirect"] == "https://example.com/callback"

    def test_empty_purchase_redirect_in_form_initial(
        self, rf, user_factory, plan_factory, mocker
    ):
        """GET request without purchase_redirect should have empty initial value"""
        user = user_factory()
        plan = plan_factory(public=True)

        mock_customer = mocker.MagicMock()
        mock_customer.payment_details = None
        mocker.patch.object(
            user.individual_organization, "customer", return_value=mock_customer
        )

        response = self.call_view(rf, user, pk=plan.pk, slug=plan.slug)

        assert response.status_code == 200
        form = response.context_data["form"]
        assert form.initial.get("purchase_redirect", "") == ""


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
