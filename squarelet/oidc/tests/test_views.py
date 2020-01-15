# Standard Library
import json

# Third Party
import pytest
from oidc_provider.models import Client
from rest_framework import status

# Squarelet
from squarelet.oidc.serializers import ClientSerializer
from squarelet.oidc.tests.factories import ClientFactory


@pytest.mark.django_db()
class TestClientAPI:
    def test_list(self, api_client, user):
        """List your clients"""
        size = 2
        api_client.force_authenticate(user=user)
        ClientFactory.create_batch(size, owner=user)
        # Create some client by other users, these should not be listed
        ClientFactory.create_batch(5)
        response = api_client.get(f"/pp-api/clients/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        assert len(response_json["results"]) == size
        for result in response_json["results"]:
            assert result["owner"] == str(user.individual_organization_id)

    def test_create(self, api_client, user):
        """Create a client"""
        api_client.force_authenticate(user=user)
        data = {
            "name": "Test",
            "client_type": "confidential",
            "website_url": "https://www.example.com/",
            "terms_url": "https://www.example.com/tos/",
            "contact_email": "admin@example.com",
            "reuse_consent": True,
            "redirect_uris": "https://www.example.com/accounts/complete/squarelet",
            "post_logout_redirect_uris": "https://www.example.com/",
        }
        response = api_client.post(f"/pp-api/clients/", data)
        assert response.status_code == status.HTTP_201_CREATED
        response_json = json.loads(response.content)
        assert response_json["owner"] == str(user.individual_organization_id)
        assert len(response_json["client_id"]) == 6
        assert len(response_json["client_secret"]) == 56
        for key, value in data.items():
            assert response_json[key] == value
        assert Client.objects.filter(pk=response_json["id"]).exists()
        client = Client.objects.get(pk=response_json["id"])
        assert client.response_types.first().value == "code"

    def test_create_anonymous(self, api_client):
        """Must be authenticated to create a client"""
        response = api_client.post(
            f"/pp-api/clients/",
            {
                "name": "Test",
                "client_type": "confidential",
                "website_url": "https://www.example.com/",
                "terms_url": "https://www.example.com/tos/",
                "contact_email": "admin@example.com",
                "reuse_consent": True,
                "redirect_uris": "https://www.example.com/accounts/complete/squarelet",
                "post_logout_redirect_uris": "https://www.example.com/",
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_retrieve(self, api_client, client):
        """Test retrieving a client"""
        api_client.force_authenticate(user=client.owner)
        response = api_client.get(f"/pp-api/clients/{client.pk}/")
        assert response.status_code == status.HTTP_200_OK
        response_json = json.loads(response.content)
        serializer = ClientSerializer(client)
        assert response_json == serializer.data

    def test_retrieve_bad(self, api_client, client, user):
        """Test retrieving a client you do not have access to"""
        api_client.force_authenticate(user=user)
        response = api_client.get(f"/pp-api/clients/{client.pk}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update(self, api_client, client):
        """Test updating a client"""
        api_client.force_authenticate(user=client.owner)
        name = "New Name"
        response = api_client.patch(f"/pp-api/clients/{client.pk}/", {"name": name})
        assert response.status_code == status.HTTP_200_OK
        client.refresh_from_db()
        assert client.name == name

    def test_update_bad(self, api_client, client, user):
        """Test updating a client you do not have access to"""
        api_client.force_authenticate(user=user)
        name = "New Name"
        response = api_client.patch(f"/pp-api/clients/{client.pk}/", {"name": name})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_destroy(self, api_client, client):
        """Test destroying a client"""
        api_client.force_authenticate(user=client.owner)
        response = api_client.delete(f"/pp-api/clients/{client.pk}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Client.objects.filter(pk=client.pk).exists()

    def test_destroy_bad(self, api_client, client, user):
        """Test destroying a client you do not have access to"""
        api_client.force_authenticate(user=user)
        response = api_client.delete(f"/pp-api/clients/{client.pk}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
