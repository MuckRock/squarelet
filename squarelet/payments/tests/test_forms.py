"""Tests for PlanPurchaseForm"""

# Third Party
import pytest

# Squarelet
from squarelet.organizations.models import Organization
from squarelet.payments.forms import PlanPurchaseForm


@pytest.mark.django_db
class TestPlanPurchaseFormInit:
    """Test PlanPurchaseForm initialization"""

    def test_init_no_params(self):
        """Form initializes with no parameters"""
        form = PlanPurchaseForm()
        assert form.fields["organization"].queryset.count() == 0
        assert not form.fields["stripe_token"].required

    def test_init_with_user_shows_individual_org(self, user_factory, plan_factory):
        """Form shows user's individual organization"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        form = PlanPurchaseForm(plan=plan, user=user)

        # Should include individual org
        assert user.individual_organization in form.fields["organization"].queryset

    def test_init_with_user_shows_admin_orgs(
        self, user_factory, organization_factory, plan_factory
    ):
        """Form shows organizations where user is admin"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(public=True, for_groups=True)

        form = PlanPurchaseForm(plan=plan, user=user)

        # Should include admin org
        assert org in form.fields["organization"].queryset

    def test_init_excludes_already_subscribed_orgs(
        self, user_factory, organization_factory, plan_factory, subscription_factory
    ):
        """Form excludes organizations already subscribed to the plan"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(public=True, for_groups=True)

        # Create an active subscription for the org
        subscription_factory(organization=org, plan=plan, cancelled=False)

        form = PlanPurchaseForm(plan=plan, user=user)

        # Should NOT include subscribed org
        assert org not in form.fields["organization"].queryset

    def test_init_with_individual_only_plan(self, user_factory, plan_factory):
        """Form only shows individual org for individual-only plans"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True, for_groups=False)

        form = PlanPurchaseForm(plan=plan, user=user)

        # Should only include individual org
        assert form.fields["organization"].queryset.count() == 1
        assert user.individual_organization in form.fields["organization"].queryset

    def test_init_with_group_only_plan(
        self, user_factory, organization_factory, plan_factory
    ):
        """Form only shows group orgs for group-only plans"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(public=True, for_individuals=False, for_groups=True)

        form = PlanPurchaseForm(plan=plan, user=user)

        # Should NOT include individual org, only group orgs
        assert user.individual_organization not in form.fields["organization"].queryset
        assert org in form.fields["organization"].queryset

    def test_init_with_sunlight_plan_shows_nonprofit(self, user_factory, plan_factory):
        """Nonprofit field shown for Sunlight plans"""
        user = user_factory()
        # Create a plan that looks like a Sunlight plan (slug starts with sunlight-)
        plan = plan_factory(
            slug="sunlight-test",
            public=True,
            for_individuals=True,
            for_groups=False,
        )

        form = PlanPurchaseForm(plan=plan, user=user)

        assert "is_nonprofit" in form.fields

    def test_init_with_non_sunlight_plan_hides_nonprofit(
        self, user_factory, plan_factory
    ):
        """Nonprofit field hidden for non-Sunlight plans"""
        user = user_factory()
        plan = plan_factory(
            slug="professional",
            public=True,
            for_individuals=True,
            for_groups=False,
        )

        form = PlanPurchaseForm(plan=plan, user=user)

        assert "is_nonprofit" not in form.fields

    def test_init_annual_plan_shows_invoice_option(self, user_factory, plan_factory):
        """Invoice payment option shown for annual plans"""
        user = user_factory()
        plan = plan_factory(annual=True, public=True, for_individuals=True)

        form = PlanPurchaseForm(plan=plan, user=user)

        choices = dict(form.fields["payment_method"].choices)
        assert "invoice" in choices

    def test_init_monthly_plan_hides_invoice_option(self, user_factory, plan_factory):
        """Invoice payment option hidden for monthly plans"""
        user = user_factory()
        plan = plan_factory(annual=False, public=True, for_individuals=True)

        form = PlanPurchaseForm(plan=plan, user=user)

        choices = dict(form.fields["payment_method"].choices)
        assert "invoice" not in choices


@pytest.mark.django_db
class TestPlanPurchaseFormValidation:
    """Test PlanPurchaseForm validation"""

    def test_valid_new_card_payment(self, user_factory, plan_factory):
        """Valid submission with new card"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert form.is_valid(), f"Form errors: {form.errors}"

    def test_new_card_requires_stripe_token(self, user_factory, plan_factory):
        """New card payment requires stripe token"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "new-card",
            "stripe_pk": "pk_test",
            # Missing stripe_token
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert not form.is_valid()
        assert "stripe_token" in form.errors

    def test_existing_card_requires_card_on_file(
        self, user_factory, plan_factory, mocker
    ):
        """Existing card payment requires card on file"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        # Mock that organization has NO card
        mock_customer = mocker.MagicMock()
        mock_customer.card = None
        mocker.patch.object(Organization, "customer", return_value=mock_customer)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "existing-card",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert not form.is_valid()
        assert "payment_method" in form.errors

    def test_invoice_only_for_annual_plans(self, user_factory, plan_factory):
        """Invoice payment only allowed for annual plans"""
        user = user_factory()
        plan = plan_factory(annual=False, public=True, for_individuals=True)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "invoice",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert not form.is_valid()
        assert "payment_method" in form.errors

    def test_new_organization_requires_name(self, user_factory, plan_factory):
        """Creating new organization requires name"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)

        data = {
            "organization": "new",
            "new_organization_name": "",  # Empty
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert not form.is_valid()
        assert "new_organization_name" in form.errors


@pytest.mark.django_db
class TestPlanPurchaseFormSave:
    """Test PlanPurchaseForm save method"""

    def test_save_returns_subscription_data(self, user_factory, plan_factory):
        """Save returns data needed for subscription"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert form.is_valid()

        result = form.save(user)

        assert result["organization"] == user.individual_organization
        assert result["plan"] == plan
        assert result["payment_method"] == "new-card"
        assert result["stripe_token"] == "tok_visa"

    def test_save_creates_new_organization(self, user_factory, plan_factory):
        """Save creates new organization when selected"""
        user = user_factory()
        plan = plan_factory(for_groups=True, public=True)

        data = {
            "organization": "new",
            "new_organization_name": "My New Org",
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert form.is_valid(), f"Form errors: {form.errors}"

        result = form.save(user)

        assert result["organization"].name == "My New Org"
        assert result["organization"].has_admin(user)


@pytest.mark.django_db
class TestPlanPurchaseFormOrgCards:
    """Test get_org_cards_data method"""

    def test_returns_empty_for_anonymous_user(self, plan_factory):
        """Returns empty dict for anonymous users"""
        plan = plan_factory()
        form = PlanPurchaseForm(plan=plan, user=None)

        assert not form.get_org_cards_data()

    def test_returns_card_info_for_orgs_with_cards(
        self, user_factory, plan_factory, mocker
    ):
        """Returns card info for organizations with saved cards"""
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        # Mock card on file
        mock_card = mocker.MagicMock()
        mock_card.last4 = "4242"
        mock_card.brand = "Visa"

        mock_customer = mocker.MagicMock()
        mock_customer.card = mock_card

        mocker.patch.object(Organization, "customer", return_value=mock_customer)

        form = PlanPurchaseForm(plan=plan, user=user)
        org_cards = form.get_org_cards_data()

        org_id = str(user.individual_organization.pk)
        assert org_id in org_cards
        assert org_cards[org_id]["last4"] == "4242"
        assert org_cards[org_id]["brand"] == "Visa"


@pytest.mark.django_db
class TestPlanPurchaseFormPlanData:
    """Test get_plan_data method"""

    def test_returns_plan_info(self, user_factory, plan_factory, mocker):
        """Returns plan information for frontend"""
        user = user_factory()
        # Mock stripe to avoid API calls
        mocker.patch("stripe.Plan.create")
        plan = plan_factory(
            public=True,
            for_individuals=True,
            annual=True,
            base_price=1000,
            price_per_user=100,
            minimum_users=5,
        )

        form = PlanPurchaseForm(plan=plan, user=user)
        plan_data = form.get_plan_data()

        assert plan_data["annual"] is True
        assert plan_data["base_price"] == 1000
        assert plan_data["price_per_user"] == 100
        assert plan_data["minimum_users"] == 5

    def test_returns_empty_dict_without_plan(self, user_factory):
        """Returns empty dict when no plan provided"""
        user = user_factory()
        form = PlanPurchaseForm(plan=None, user=user)

        assert not form.get_plan_data()
