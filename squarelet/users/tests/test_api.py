# Standard Library
# Django
from django.utils import timezone

# Standard Library
import json
from datetime import timedelta
from unittest.mock import Mock

# Third Party
import pytest
from allauth.account.models import EmailAddress
from oidc_provider.lib.utils.token import create_token
from oidc_provider.models import UserConsent
from rest_framework import status
from rest_framework.test import APIClient

# Squarelet
from squarelet.oidc.tests.factories import ClientFactory


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
        response = client.post("/api/users/", data)
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
        response = client.post("/api/users/", data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_json = json.loads(response.content)
        assert "email" in response_json

    def test_retrieve_consent(self, user_factory, client, mocker):
        user = user_factory()
        token = create_token(user=None, client=client, scope=["read_user"])
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
        # user `individual_organization_id` instead of `uuid` because
        # the `uuid` AliasField fails only in tests for some reason
        response = api_client.get(f"/api/users/{user.individual_organization_id}/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert response_json["uuid"] == str(user.individual_organization_id)
        assert response_json["name"] == user.name
        assert response_json["preferred_username"] == user.username

    def test_retrieve_without_consent(self, user_factory, client, mocker):
        user = user_factory()
        token = create_token(user=None, client=client, scope=["read_user"])

        api_client = APIClient()
        api_client.force_authenticate(token=token)
        mocker.patch(
            "squarelet.organizations.models.Customer.stripe_customer",
            default_source=None,
        )
        # user `individual_organization_id` instead of `uuid` because
        # the `uuid` AliasField fails only in tests for some reason
        response = api_client.get(f"/api/users/{user.individual_organization_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_wrong_consent(self, user_factory, client, mocker):
        user = user_factory()
        token = create_token(user=None, client=client, scope=["read_user"])
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
        # user `individual_organization_id` instead of `uuid` because
        # the `uuid` AliasField fails only in tests for some reason
        response = api_client.get(f"/api/users/{user.individual_organization_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_expired_consent(self, user_factory, client, mocker):
        user = user_factory()
        token = create_token(user=None, client=client, scope=["read_user"])
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
        # user `individual_organization_id` instead of `uuid` because
        # the `uuid` AliasField fails only in tests for some reason
        response = api_client.get(f"/api/users/{user.individual_organization_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
