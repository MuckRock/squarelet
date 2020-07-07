# Standard Library
import json
from unittest.mock import Mock

# Third Party
import pytest
from allauth.account.models import EmailAddress
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.users.serializers import PressPassUserSerializer
from squarelet.users.tests.factories import UserFactory


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
        assert response.status_code == status.HTTP_200_OK
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
        assert response.status_code == status.HTTP_201_CREATED
        response_json = json.loads(response.content)
        assert response_json["name"] == data["name"]
        assert response_json["preferred_username"] == data["preferred_username"]
        assert response_json["email"] == data["email"]

    def test_create_dupe_email(self, user_factory, mocker):
        """Ensure sign up email is not duplicated by an email address
        which is someone's non-primary email
        """
        user = user_factory(is_staff=True)
        EmailAddress.objects.create(user=user, email="john@example.com")
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
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_json = json.loads(response.content)
        assert "email" in response_json


@pytest.mark.django_db()
class TestPPUserAPI:
    def test_list(self, api_client, user):
        """List users"""
        size = 10
        api_client.force_authenticate(user=user)
        UserFactory.create_batch(size)
        response = api_client.get(f"/pp-api/users/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size + 1

    def test_retrieve(self, api_client, user):
        """Test retrieving a user"""
        api_client.force_authenticate(user=user)
        response = api_client.get(f"/pp-api/users/{user.individual_organization_id}/")
        assert response.status_code == status.HTTP_200_OK

    def test_retrieve_me(self, api_client, user):
        """Test retrieving a user using special identifier `me`"""
        api_client.force_authenticate(user=user)
        response = api_client.get(f"/pp-api/users/me/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        serializer = PressPassUserSerializer(user)
        for key, value in response_json.items():
            if key == "uuid":
                assert value == str(serializer.data[key])
            else:
                assert value == serializer.data[key]

    def test_update(self, api_client, user):
        """Test updating a user"""
        api_client.force_authenticate(user=user)
        name = "John Doe"
        assert user.name != name
        response = api_client.patch(
            f"/pp-api/users/{user.individual_organization_id}/", {"name": name}
        )
        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.name == name

    def test_update_bad(self, api_client, user):
        """Test updating a user you cannot update"""
        other_user = UserFactory()
        api_client.force_authenticate(user=user)
        name = "John Doe"
        response = api_client.patch(
            f"/pp-api/users/{other_user.individual_organization_id}/", {"name": name}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
