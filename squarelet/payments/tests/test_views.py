# Third Party
import pytest

# Squarelet
from squarelet.core.tests.mixins import ViewTestMixin
from squarelet.organizations.models import Organization
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
