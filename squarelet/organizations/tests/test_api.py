# Django
from django.utils import timezone

# Standard Library
import json
import time
from datetime import timedelta
from unittest.mock import Mock

# Third Party
import pytest
from oidc_provider.lib.utils.token import create_token
from oidc_provider.models import UserConsent
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory
from squarelet.organizations.models import Charge
from squarelet.organizations.tests.factories import OrganizationFactory


@pytest.mark.django_db()
class TestOrganizationAPI:
    def test_retrieve(self, user_factory, mocker):
        user = user_factory(is_staff=True)
        client = APIClient()
        client.force_authenticate(user=user)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        response = client.get(
            f"/api/organizations/{user.individual_organization.uuid}/"
        )
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert response_json["uuid"] == str(user.individual_organization.uuid)
        assert response_json["name"] == user.individual_organization.name
        assert response_json["individual"]

    def test_create_charge(self, user_factory, mocker):
        mocked = mocker.patch(
            "stripe.Charge.create",
            return_value=Mock(id="charge_id", created=time.time()),
        )
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source="default_source",
        )
        user = user_factory(is_staff=True)
        data = {
            "organization": str(user.individual_organization.uuid),
            "amount": 2700,
            "fee_amount": 5,
            "description": "This is only a test",
            "save_card": False,
        }
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post("/api/charges/", data)
        assert response.status_code == status.HTTP_201_CREATED
        response_json = json.loads(response.content)
        assert "card" in response_json
        for field in ("organization", "amount", "fee_amount", "description"):
            assert response_json[field] == data[field]
        mocked.assert_called_once()
        assert Charge.objects.filter(charge_id="charge_id").exists()

    def test_retrieve_consent(self, user_factory, client, mocker):
        user = user_factory()
        organization = OrganizationFactory(admins=[user])
        token = create_token(user=None, client=client, scope=["read_organization"])
        UserConsent.objects.create(
            user=user,
            client=client,
            expires_at=timezone.now() + timedelta(days=1),
            date_given=timezone.now(),
        )

        api_client = APIClient()
        api_client.force_authenticate(token=token)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        response = api_client.get(f"/api/organizations/{organization.uuid}/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert response_json["name"] == organization.name

    def test_retrieve_without_consent(self, user_factory, client, mocker):
        user = user_factory()
        organization = OrganizationFactory(admins=[user])
        token = create_token(user=None, client=client, scope=["read_organization"])

        api_client = APIClient()
        api_client.force_authenticate(token=token)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        response = api_client.get(f"/api/organizations/{organization.uuid}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_wrong_consent(self, user_factory, client, mocker):
        user = user_factory()
        organization = OrganizationFactory(admins=[user])
        token = create_token(user=None, client=client, scope=["read_organization"])
        another_client = ClientFactory()
        UserConsent.objects.create(
            user=user,
            client=another_client,
            expires_at=timezone.now() + timedelta(days=1),
            date_given=timezone.now(),
        )

        api_client = APIClient()
        api_client.force_authenticate(token=token)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        response = api_client.get(f"/api/organizations/{organization.uuid}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_expired_consent(self, user_factory, client, mocker):
        user = user_factory()
        organization = OrganizationFactory(admins=[user])
        token = create_token(user=None, client=client, scope=["read_organization"])
        UserConsent.objects.create(
            user=user,
            client=client,
            expires_at=timezone.now() - timedelta(days=1),
            date_given=timezone.now(),
        )

        api_client = APIClient()
        api_client.force_authenticate(token=token)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        response = api_client.get(f"/api/organizations/{organization.uuid}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
