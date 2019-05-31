# Django
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

# Standard Library
from unittest.mock import Mock

# Third Party
import pytest

# Squarelet
from squarelet.core import context_processors
from squarelet.users.tests.factories import UserFactory


def test_settings():
    assert context_processors.settings(Mock())["settings"] is settings


def test_payment_failed_anonymous():
    request = Mock(user=AnonymousUser())
    assert (
        context_processors.payment_failed(request)["payment_failed_organizations"]
        is None
    )


@pytest.mark.django_db()
def test_payment_failed():
    user = UserFactory(individual_organization__payment_failed=True)
    request = Mock(user=user)
    context = context_processors.payment_failed(request)
    assert context["payment_failed_organizations"][0] == user.individual_organization
