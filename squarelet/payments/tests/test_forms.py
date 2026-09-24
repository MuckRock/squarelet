"""Tests for PlanPurchaseForm"""

# Standard Library
from pathlib import Path

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
        self,
        user_factory,
        organization_factory,
        plan_factory,
        subscription_item_factory,
    ):
        """Form excludes organizations already subscribed to the plan"""
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(public=True, for_groups=True)

        # Create an active subscription for the org
        subscription_item_factory(
            subscription__organization=org, plan=plan, subscription__cancelled=False
        )

        form = PlanPurchaseForm(plan=plan, user=user)

        # Should NOT include subscribed org
        assert org not in form.fields["organization"].queryset

    def test_init_excludes_orgs_whose_line_is_cancelled(
        self,
        user_factory,
        organization_factory,
        plan_factory,
        subscription_item_factory,
    ):
        """A cancelled line still occupies the plan.

        `unique_together` is (subscription, plan), so there is no room for a
        second line, and `add_subscription` refuses for the same reason.
        Offering the organization here produced a form that took the choice
        and then raised SubscriptionError - a dead end that per-line
        cancellation turns from rare into routine.
        """
        user = user_factory()
        org = organization_factory()
        org.add_creator(user)
        plan = plan_factory(public=True, for_groups=True)
        subscription_item_factory(
            subscription__organization=org,
            plan=plan,
            cancelled=True,
            subscription__cancelled=False,
        )

        form = PlanPurchaseForm(plan=plan, user=user)

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

    def test_a_plan_with_a_nonprofit_rate_offers_the_box(
        self, user_factory, plan_price_factory
    ):
        """Whether the box appears is a fact about the plan's prices, not
        about which product it is marketed under."""
        user = user_factory()
        price = plan_price_factory(interval="monthly", label="standard")
        plan_price_factory(plan=price.plan, interval="monthly", label="nonprofit")

        form = PlanPurchaseForm(plan=price.plan, user=user)

        assert "is_nonprofit" in form.fields
        assert form.nonprofit_price.label == "nonprofit"

    def test_a_plan_without_a_nonprofit_rate_hides_the_box(
        self, user_factory, plan_price_factory
    ):
        user = user_factory()
        price = plan_price_factory(interval="monthly", label="standard")

        form = PlanPurchaseForm(plan=price.plan, user=user)

        assert "is_nonprofit" not in form.fields

    def test_an_annual_price_offers_invoice(self, user_factory, plan_price_factory):
        """Invoice payment option shown for annual prices"""
        user = user_factory()
        price = plan_price_factory(interval="annual")

        form = PlanPurchaseForm(plan=price.plan, user=user)

        assert form.interval == "annual"
        choices = dict(form.fields["payment_method"].choices)
        assert "invoice" in choices

    def test_a_monthly_price_does_not(self, user_factory, plan_price_factory):
        """Invoice payment option hidden for monthly prices"""
        user = user_factory()
        price = plan_price_factory(interval="monthly")

        form = PlanPurchaseForm(plan=price.plan, user=user)

        choices = dict(form.fields["payment_method"].choices)
        assert "invoice" not in choices

    def test_the_interval_asked_for_is_the_one_sold(
        self, user_factory, plan_price_factory
    ):
        """A canonical tier is one row with both; the page names one and
        the form carries it back."""
        user = user_factory()
        plan = plan_price_factory(interval="monthly", amount=10_000).plan
        plan_price_factory(plan=plan, interval="annual", amount=100_000)

        form = PlanPurchaseForm(plan=plan, user=user, interval="annual")

        assert form.price.amount == 100_000
        assert form.fields["price_interval"].initial == "annual"

    def test_a_bound_form_reads_the_interval_it_posted(
        self, user_factory, plan_price_factory
    ):
        user = user_factory()
        plan = plan_price_factory(interval="monthly", amount=10_000).plan
        plan_price_factory(plan=plan, interval="annual", amount=100_000)

        form = PlanPurchaseForm({"price_interval": "annual"}, plan=plan, user=user)

        assert form.price.amount == 100_000

    def test_an_interval_the_plan_lacks_falls_back_to_its_first(
        self, user_factory, plan_price_factory
    ):
        user = user_factory()
        price = plan_price_factory(interval="monthly")

        form = PlanPurchaseForm(plan=price.plan, user=user, interval="annual")

        assert form.interval == "monthly"
        assert form.price == price


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
        mock_customer.payment_details = None
        mocker.patch.object(Organization, "customer", return_value=mock_customer)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "existing-card",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert not form.is_valid()
        assert "payment_method" in form.errors

    def test_invoice_only_for_annual_plans(self, user_factory, plan_price_factory):
        """Invoice payment only allowed for annual prices"""
        user = user_factory()
        plan = plan_price_factory(interval="monthly").plan

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
        user = user_factory(email_verified=True)
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

    def test_new_organization_requires_verified_email(self, user_factory, plan_factory):
        """Creating a new organization requires a verified email address"""
        user = user_factory(email_verified=False)
        plan = plan_factory(for_groups=True, public=True)

        data = {
            "organization": "new",
            "new_organization_name": "My New Org",
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert not form.is_valid()
        assert "organization" in form.errors

    def test_new_organization_allowed_with_verified_email(
        self, user_factory, plan_factory
    ):
        """Verified users may create a new organization"""
        user = user_factory(email_verified=True)
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

    def test_existing_org_allowed_without_verified_email(
        self, user_factory, plan_factory
    ):
        """The verified-email constraint only applies to creating new orgs;
        an unverified user may still subscribe an existing organization."""
        user = user_factory(email_verified=False)
        plan = plan_factory(public=True, for_individuals=True)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "new-card",
            "stripe_token": "tok_visa",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert form.is_valid(), f"Form errors: {form.errors}"

    def test_existing_card_valid_when_org_has_card(
        self, user_factory, plan_factory, mocker
    ):
        """Submitting existing-card should be valid when org has a card on file.

        The JS dynamically adds an "existing-card" radio option when an org has
        a saved card. The Python form must accept "existing-card" as a valid
        choice so that Django's ChoiceField validation doesn't reject it.
        """
        user = user_factory()
        plan = plan_factory(public=True, for_individuals=True)

        # Mock that organization HAS a card on file
        mock_card = mocker.MagicMock()
        mock_card.last4 = "4242"
        mock_card.brand = "Visa"
        mock_customer = mocker.MagicMock()
        mock_customer.payment_details = mock_card
        mocker.patch.object(Organization, "customer", return_value=mock_customer)

        data = {
            "organization": str(user.individual_organization.pk),
            "payment_method": "existing-card",
            "stripe_pk": "pk_test",
        }

        form = PlanPurchaseForm(data, plan=plan, user=user)
        assert form.is_valid(), f"Form errors: {form.errors}"


class TestPlanPurchaseFormTemplate:
    """Test that the template renders as expected"""

    TEMPLATE_PATH = (
        Path(__file__).resolve().parents[2]
        / "templates"
        / "payments"
        / "forms"
        / "plan_purchase.html"
    )

    @pytest.fixture(autouse=True)
    def _load_template(self):
        self.template_content = self.TEMPLATE_PATH.read_text()

    def test_template_shows_organization_errors(self):
        """Template should render organization field errors"""
        assert "form.organization.errors" in self.template_content

    def test_template_shows_new_organization_name_errors(self):
        """Template should render new_organization_name field errors"""
        assert "form.new_organization_name.errors" in self.template_content

    def test_template_shows_payment_method_errors(self):
        """Template should render payment_method field errors"""
        assert "form.payment_method.errors" in self.template_content

    def test_template_shows_stripe_token_errors(self):
        """Template should render stripe_token field errors"""
        assert "form.stripe_token.errors" in self.template_content

    def test_template_shows_non_field_errors(self):
        """Template should render non-field errors"""
        assert "form.non_field_errors" in self.template_content

    def test_template_gates_new_org_option_on_verified_email(self):
        """The create-new-organization option must be gated on a verified email"""
        assert "has_verified_email" in self.template_content


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
        user = user_factory(email_verified=True)
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
        mock_customer.payment_details = mock_card

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

    def test_returns_the_resolved_price(self, user_factory, plan_price_factory):
        """What the page's script reads: the price, in dollars."""
        user = user_factory()
        price = plan_price_factory(interval="annual", amount=100_000)

        form = PlanPurchaseForm(plan=price.plan, user=user)
        plan_data = form.get_plan_data()

        assert plan_data == {
            "interval": "annual",
            "amount": 1000.0,
            "has_nonprofit_variant": False,
        }

    def test_returns_empty_dict_without_plan(self, user_factory):
        """Returns empty dict when no plan provided"""
        user = user_factory()
        form = PlanPurchaseForm(plan=None, user=user)

        assert not form.get_plan_data()


@pytest.mark.django_db()
class TestNonprofitPriceComesFromPlanPrice:
    """The figure shown must be the one a purchase is sold at.

    It used to be read off the separate `sunlight-nonprofit-*` `Plan` row,
    which left display and billing free to disagree and made deleting those
    rows a breaking change.
    """

    def _form(self, plan, **kwargs):
        return PlanPurchaseForm(plan=plan, **kwargs).get_plan_data()

    def test_reads_the_nonprofit_label_off_the_canonical_plan(
        self, plan_factory, plan_price_factory
    ):
        plan = plan_factory(name="Sunlight Essential", slug="sunlight-essential")
        plan_price_factory(
            plan=plan, interval="monthly", label="standard", amount=68_000
        )
        plan_price_factory(
            plan=plan, interval="monthly", label="nonprofit", amount=35_000
        )

        data = self._form(plan)

        assert data["has_nonprofit_variant"]
        assert data["nonprofit_amount"] == 350.0

    def test_the_nonprofit_rate_follows_the_interval(
        self, plan_factory, plan_price_factory
    ):
        plan = plan_factory(name="Sunlight Essential", slug="sunlight-essential")
        for interval, standard, nonprofit in [
            ("monthly", 68_000, 35_000),
            ("annual", 800_000, 400_000),
        ]:
            plan_price_factory(plan=plan, interval=interval, amount=standard)
            plan_price_factory(
                plan=plan, interval=interval, label="nonprofit", amount=nonprofit
            )

        assert self._form(plan, interval="annual")["nonprofit_amount"] == 4000.0

    def test_no_nonprofit_rate_at_all(self, plan_price_factory):
        plan = plan_price_factory(interval="monthly").plan

        assert not self._form(plan)["has_nonprofit_variant"]

    def test_a_plan_with_only_a_nonprofit_price_is_not_for_sale(
        self, plan_factory, plan_price_factory
    ):
        """No list price means nothing to sell to a stranger; the nonprofit
        rate is a discount on it, not a price of its own."""
        plan = plan_factory(name="Organization", slug="organization")
        plan_price_factory(plan=plan, interval="monthly", label="nonprofit", amount=1)

        assert not self._form(plan)
