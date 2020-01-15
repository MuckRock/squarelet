# Standard Library
import json
from unittest.mock import Mock

# Third Party
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db()
class TestUserAPI:
    def test_retrieve(self, user_factory, mocker):
        user = user_factory(is_staff=True)
        client = APIClient()
        client.force_authenticate(user=user)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        # user `individual_organization_id` instead of `uuid` because
        # the `uuid` AliasField fails only in tests for some reason
        response = client.get(f"/api/users/{user.individual_organization_id}/")
        assert response.status_code == 200
        response_json = json.loads(response.content)
        assert response_json["uuid"] == str(user.individual_organization_id)
        assert response_json["name"] == user.name
        assert response_json["preferred_username"] == user.username

    def test_create(self, user_factory, mocker):
        user = user_factory(is_staff=True)
        data = {
            "preferred_username": "john.doe",
            "name": "John Doe",
            "email": "john@example.com",
        }
        mocker.patch("stripe.Customer.create", return_value=Mock(id="customer_id"))
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(f"/api/users/", data)
        assert response.status_code == 201
        response_json = json.loads(response.content)
        assert response_json["name"] == data["name"]
        assert response_json["preferred_username"] == data["preferred_username"]
        assert response_json["email"] == data["email"]
