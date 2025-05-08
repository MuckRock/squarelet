# Standard Library
# Django
from django.forms import HiddenInput, ValidationError

from unittest.mock import MagicMock

# Third Party
import pytest
import stripe

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
    # assert Organization.objects.filter(name=data["organization_name"]).exists()


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
    plan = plan_factory()
    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, user=user)
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
    plan = plan_factory()
    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data)
    assert not form.is_valid()
    assert "stripe_token" in form.errors


@pytest.mark.django_db
def test_premium_subscription_form_save(plan_factory, user, mocker):
    """Test save method successfully creating a subscription"""
    plan = plan_factory()
    create_sub_mock = mocker.patch.object(
        Organization, "create_subscription", return_value=None
    )

    data = {
        "organization": user.individual_organization.pk,
        "plan": plan.pk,
        "stripe_token": "tok_visa",
        "stripe_pk": "pk_test_123",
    }

    form = forms.PremiumSubscriptionForm(data, user=user)
    if not form.is_valid():
        print("Form errors:", form.errors)
    assert form.is_valid()
    form.save(user)

    create_sub_mock.assert_called_once_with("tok_visa", plan, user)


@pytest.mark.django_db
def test_premium_subscription_form_save_stripe_error(plan_factory, user, mocker):
    """Test save method handling Stripe errors"""
    plan = plan_factory()
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

    form = forms.PremiumSubscriptionForm(data, user=user)
    if not form.is_valid():
        print("Form errors:", form.errors)
    assert form.is_valid()

    with pytest.raises(ValidationError) as excinfo:
        form.save(user)

    assert "Error processing payment" in str(excinfo.value)
