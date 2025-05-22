# Standard Library
# Django
from django.forms import HiddenInput, ValidationError

from unittest.mock import MagicMock

# Third Party
import pytest
import stripe
from psycopg2 import errors
from psycopg2.errorcodes import UNIQUE_VIOLATION

# Squarelet
from squarelet.organizations.models import Organization
from squarelet.users import forms
from squarelet.users.models import User

# pylint: disable=invalid-name


@pytest.mark.django_db
def test_clean_good(plan_factory):
    plan = plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "plan": plan.slug,
    }
    form = forms.SignupForm(data)
    assert form.is_valid()


@pytest.mark.django_db
def test_clean_bad_no_pay(professional_plan_factory, mocker):
    mocker.patch("stripe.Plan.create")
    professional_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "plan": "professional",
    }
    form = forms.SignupForm(data)
    assert form.is_valid()


@pytest.mark.django_db
def test_clean_bad_no_org_name(organization_plan_factory, mocker):
    mocker.patch("stripe.Plan.create")
    organization_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "plan": "organization",
    }
    form = forms.SignupForm(data)
    assert form.is_valid()


@pytest.mark.django_db
def test_save(rf, plan_factory):
    plan = plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "plan": plan.slug,
    }
    request = rf.post("/accounts/signup/", data)
    request.session = MagicMock()
    form = forms.SignupForm(data)
    assert form.is_valid()
    form.save(request)
    assert User.objects.filter(
        username=data["username"], email=data["email"], name=data["name"]
    ).exists()


@pytest.mark.django_db
def test_save_org(rf, plan_factory, organization_plan_factory, mocker):
    # pylint: disable=protected-access
    mocker.patch("stripe.Plan.create")
    mocker.patch("squarelet.organizations.models.Organization.set_subscription")
    plan_factory()
    organization_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "stripe_token": "token",
        "plan": "organization",
        "organization_name": "my organization",
    }
    request = rf.post("/accounts/signup/", data)
    request.session = {}  # MagicMock()
    request._messages = MagicMock()
    form = forms.SignupForm(data)
    assert form.is_valid()
    form.save(request)
    assert User.objects.filter(
        username=data["username"], email=data["email"], name=data["name"]
    ).exists()


@pytest.mark.parametrize(
    "form_class,number_fields",
    [
        (forms.AddEmailForm, 1),
        (forms.ChangePasswordForm, 3),
        (forms.SetPasswordForm, 2),
        (forms.ResetPasswordForm, 1),
        (forms.ResetPasswordKeyForm, 2),
    ],
)
def test_other_forms(form_class, number_fields):
    form = form_class()
    assert len(form.helper.layout) == number_fields


@pytest.mark.django_db
def test_premium_subscription_form_init_no_params():
    """Test PremiumSubscriptionForm initialization with no parameters"""
    form = forms.PremiumSubscriptionForm()
    assert form.fields["organization"].queryset.count() == 0
    assert not form.fields["stripe_token"].required


@pytest.mark.django_db
def test_premium_subscription_form_init_with_user(user):
    """Test PremiumSubscriptionForm initialization with a user parameter"""
    # Create an organization where the user is an admin
    org = Organization.objects.create(name="Test Org")
    org.add_creator(user)

    form = forms.PremiumSubscriptionForm(user=user)
    assert (
        form.fields["organization"].queryset.count() == 2
    )  # Individual org + created org
    assert user.individual_organization in form.fields["organization"].queryset
    assert org in form.fields["organization"].queryset


@pytest.mark.django_db
def test_premium_subscription_form_init_with_plan(plan_factory):
    """Test PremiumSubscriptionForm initialization with a plan parameter"""
    plan = plan_factory()
    form = forms.PremiumSubscriptionForm(plan=plan)
    assert form.fields["plan"].initial == plan
    assert form.fields["plan"].queryset.count() == 1
    assert isinstance(form.fields["plan"].widget, HiddenInput)


@pytest.mark.django_db
def test_premium_subscription_form_clean_valid(plan_factory, user):
    """Test clean method with valid data"""
    plan = plan_factory(slug="professional")
    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan, user=user)
    if not form.is_valid():
        print("Form errors:", form.errors)
    assert form.is_valid()


@pytest.mark.django_db
def test_premium_subscription_form_clean_missing_plan(user):
    """Test clean method with missing plan"""
    data = {
        "organization": user.individual_organization.pk,
        "stripe_token": "tok_visa",
    }

    form = forms.PremiumSubscriptionForm(data)
    assert not form.is_valid()
    assert "plan" in form.errors


@pytest.mark.django_db
def test_premium_subscription_form_clean_missing_stripe_token(plan_factory, user):
    """Test clean method with missing stripe token"""
    plan = plan_factory(slug="professional")
    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan)
    assert not form.is_valid()
    assert "stripe_token" in form.errors


@pytest.mark.django_db
def test_premium_subscription_form_save(plan_factory, user, mocker):
    """Test save method successfully creating a subscription"""
    plan = plan_factory(slug="professional")
    create_sub_mock = mocker.patch.object(
        Organization, "create_subscription", return_value=None
    )

    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan, user=user)
    if not form.is_valid():
        print("Form errors:", form.errors)
    assert form.is_valid()
    form.save(user)

    create_sub_mock.assert_called_once_with("tok_visa", plan, user)


@pytest.mark.django_db
def test_premium_subscription_form_save_stripe_error(plan_factory, user, mocker):
    """Test save method handling Stripe errors"""
    plan = plan_factory(slug="professional")
    mocker.patch.object(
        Organization,
        "create_subscription",
        side_effect=stripe.error.StripeError("Payment failed"),
    )

    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan, user=user)
    if not form.is_valid():
        print("Form errors:", form.errors)
    assert form.is_valid()

    with pytest.raises(ValidationError) as excinfo:
        form.save(user)

    assert "Error processing payment" in str(excinfo.value)


@pytest.mark.django_db
def test_new_organization_model_choice_field(organization_factory):
    """Test the custom ModelChoiceField that allows creating a new organization"""
    organization = organization_factory(name="Test Org")
    queryset = Organization.objects.filter(pk=organization.pk)
    field = forms.NewOrganizationModelChoiceField(queryset=queryset)

    # Test to_python with "new" value
    assert field.to_python("new") == "new"

    # Test to_python with regular value (should convert to int)
    assert isinstance(field.to_python(str(organization.pk)), Organization)

    # Test to_python with invalid value
    with pytest.raises(ValidationError):
        field.to_python("999999")

    # Test validate with "new" value (should pass)
    field.validate("new")

    # Test validate with primary key value (should pass)
    field.validate(organization.pk)


@pytest.mark.django_db
def test_premium_subscription_form_init_with_professional_plan(
    professional_plan_factory, user_factory, mocker
):
    """Test form initialization with professional plan"""
    # Create professional plan
    user = user_factory()
    mocker.patch("stripe.Plan.create")
    plan = professional_plan_factory()
    plan.slug = "professional"
    plan.save()

    form = forms.PremiumSubscriptionForm(plan=plan, user=user)

    # Professional plan should auto-select and disable individual org
    assert form.fields["organization"].initial == user.individual_organization
    assert form.fields["organization"].disabled is True
    assert isinstance(form.fields["organization"].widget, HiddenInput)


@pytest.mark.django_db
def test_premium_subscription_form_clean_receipt_emails_valid(plan_factory):
    """Test valid receipt emails validation"""
    plan = plan_factory(slug="professional")
    data = {
        "organization": "new",
        "new_organization_name": "New Test Organization",
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
        "receipt_emails": "test@example.com, another@test.com",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan)
    assert form.is_valid()
    cleaned_emails = form.cleaned_data.get("receipt_emails")

    assert cleaned_emails == ["test@example.com", "another@test.com"]


@pytest.mark.django_db
def test_premium_subscription_form_clean_receipt_emails_invalid():
    """Test invalid receipt emails validation"""
    data = {"receipt_emails": "test@example.com, invalid-email, another@test.com"}

    form = forms.PremiumSubscriptionForm(data)

    assert not form.is_valid()
    assert "receipt_emails" in form.errors
    assert "Invalid email: invalid-email" in str(form.errors["receipt_emails"])


@pytest.mark.django_db
def test_premium_subscription_form_clean_new_org_missing_name():
    """Test validation when 'new' org is selected but no name provided"""
    data = {
        "organization": "new",
        "new_organization_name": "",  # Empty name
        "plan": 1,
        "stripe_token": "tok_visa",
    }

    form = forms.PremiumSubscriptionForm(data)
    assert not form.is_valid()
    assert "new_organization_name" in form.errors


@pytest.mark.django_db
def test_premium_subscription_form_save_new_organization(plan_factory, user, mocker):
    """Test creating a new organization during subscription"""
    plan = plan_factory(slug="professional")
    create_sub_mock = mocker.patch.object(
        Organization, "create_subscription", return_value=None
    )

    data = {
        "organization": "new",
        "new_organization_name": "New Test Organization",
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
        "receipt_emails": "billing@example.com, finance@example.com",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan, user=user)
    assert form.is_valid(), f"Form errors: {form.errors}"
    form.save(user)

    # Check that a new organization was created
    assert Organization.objects.filter(name="New Test Organization").exists()
    new_org = Organization.objects.get(name="New Test Organization")

    # Check that user was added as admin
    assert new_org.has_admin(user)

    # Check that receipt emails were added
    assert new_org.receipt_emails.filter(email="billing@example.com").exists()
    assert new_org.receipt_emails.filter(email="finance@example.com").exists()

    # Check subscription was created
    create_sub_mock.assert_called_once_with("tok_visa", plan, user)


@pytest.mark.django_db
def test_premium_subscription_form_save_unique_violation(plan_factory, user, mocker):
    """Test handling unique violation errors (organization already has subscription)"""

    class MockUniqueViolation(errors.lookup(UNIQUE_VIOLATION)):
        pass

    plan = plan_factory(slug="professional")
    mocker.patch.object(
        Organization,
        "create_subscription",
        side_effect=MockUniqueViolation(
            "duplicate key value violates unique constraint"
        ),
    )

    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, plan=plan, user=user)
    assert form.is_valid()

    with pytest.raises(ValidationError) as excinfo:
        form.save(user)

    assert "already has a subscription" in str(excinfo.value)
