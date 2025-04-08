# Standard Library
from unittest.mock import MagicMock

# Third Party
import pytest

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
    assert Organization.objects.filter(name=data["organization_name"]).exists()


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
