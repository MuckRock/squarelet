# Standard Library
from unittest.mock import MagicMock

# Third Party
import pytest

# Squarelet
from squarelet.users import forms

# Local
from ..models import User

# pylint: disable=invalid-name


@pytest.mark.django_db
def test_clean_good(free_plan_factory):
    free_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "plan": "free",
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
        "stripe_pk": "key",
        "plan": "professional",
    }
    form = forms.SignupForm(data)
    assert not form.is_valid()
    assert len(form.errors["plan"]) == 1


@pytest.mark.django_db
def test_clean_bad_no_org_name(organization_plan_factory, mocker):
    mocker.patch("stripe.Plan.create")
    organization_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "plan": "organization",
        "stripe_token": "token",
    }
    form = forms.SignupForm(data)
    assert not form.is_valid()
    assert len(form.errors["organization_name"]) == 1


@pytest.mark.django_db
def test_save(rf, free_plan_factory):
    free_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "plan": "free",
    }
    request = rf.post("/accounts/signup/", data)
    request.session = MagicMock()
    form = forms.SignupForm(data)
    assert form.is_valid()
    form.save(request)
    assert User.objects.filter(
        username=data["username"], email=data["email"], name=data["name"]
    ).exists()


@pytest.mark.parametrize(
    "form_class,number_fields",
    [
        (forms.LoginForm, 2),
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
