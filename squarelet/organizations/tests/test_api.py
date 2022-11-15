# Standard Library
import json
import time
from unittest.mock import Mock

# Third Party
import pytest
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.organizations.models import Charge


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
