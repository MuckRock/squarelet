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
        "tos": True,
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
        "tos": True,
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
        "tos": True,
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
        "tos": True,
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
        "tos": True,
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

    form = forms.PremiumSubscriptionForm(
        data, plan=plan, user=user
    )  # Added user parameter
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
    assert form.save(user) is False
    assert form.errors == {
        "__all__": ["Error processing payment. Please try again or contact support."]
    }


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
def test_premium_subscription_form_clean_receipt_emails_valid(
    plan_factory, user_factory
):
    """Test valid receipt emails validation"""
    user = user_factory()  # Create a user to pass to the form
    plan = plan_factory(slug="professional")
    data = {
        "organization": "new",
        "new_organization_name": "New Test Organization",
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
        "receipt_emails": "test@example.com, another@test.com",
    }

    form = forms.PremiumSubscriptionForm(
        data, plan=plan, user=user
    )  # Added user parameter
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
    # Create a real organization and then mock the subscription creation
    # to avoid testing stripe functionality
    org_create_mock = mocker.patch(
        "squarelet.organizations.models.Organization.objects.create",
        return_value=Organization(name="New Test Organization"),
    )

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

    # Mock the add_creator method too
    add_creator_mock = mocker.patch.object(
        Organization, "add_creator", return_value=None
    )
    # Mock receipt_emails functionality
    receipt_emails_mock = mocker.patch.object(Organization, "receipt_emails")
    receipt_emails_mock.filter.return_value.exists.return_value = True

    assert form.save(user)

    # Since we're mocking Organization.objects.create, we don't directly test
    # the database. Instead, check that it was called with the right parameters.
    org_create_mock.assert_called_once_with(name="New Test Organization", private=False)
    add_creator_mock.assert_called_once_with(user)
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
    assert form.save(user) is False
    assert form.errors == {"__all__": ["This organization already has a subscription."]}
