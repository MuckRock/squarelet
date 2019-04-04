# Standard Library
from unittest.mock import MagicMock

# Third Party
import pytest

# Local
from ..forms import SignupForm
from ..models import User

# pylint: disable=invalid-name


@pytest.mark.django_db(transaction=True)
def test_clean(free_plan_factory):
    free_plan_factory()
    data = {
        "name": "john doe",
        "username": "john",
        "email": "doe@example.com",
        "password1": "squarelet",
        "stripe_pk": "key",
        "plan": "free",
    }
    form = SignupForm(data)
    assert form.is_valid()


@pytest.mark.django_db(transaction=True)
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
    form = SignupForm(data)
    assert form.is_valid()
    form.save(request)
    assert User.objects.filter(
        username=data["username"], email=data["email"], name=data["name"]
    ).exists()
