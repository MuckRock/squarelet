
# Standard Library
import json

# Third Party
import pytest
from rest_framework.test import APIClient

# Local
from .. import viewsets


@pytest.mark.django_db()
class TestUserAPI:
    def test_retrieve(self, user_factory):
        user = user_factory(is_staff=True)
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"/api/users/{user.uuid}/")
        assert response.status_code == 200
        response_json = json.loads(response.content)
        assert response_json["uuid"] == str(user.uuid)
        assert response_json["name"] == user.name
        assert response_json["preferred_username"] == user.username

    def test_create(self, user_factory):
        user = user_factory(is_staff=True)
        data = {
            "preferred_username": "john.doe",
            "name": "John Doe",
            "email": "john@example.com",
        }
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(f"/api/users/", data)
        assert response.status_code == 201
        response_json = json.loads(response.content)
        assert response_json["name"] == data["name"]
        assert response_json["preferred_username"] == data["preferred_username"]
        assert response_json["email"] == data["email"]
