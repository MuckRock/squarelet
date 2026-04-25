# Third Party
import pytest
from Crypto.PublicKey import RSA
from oidc_provider.models import RSAKey
from rest_framework import status
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def jwt_rsa_key(db, settings):  # pylint:disable=unused-argument

    key = RSA.generate(2048)
    private_key = key.export_key().decode()
    public_key = key.publickey().export_key()
    RSAKey.objects.create(key=private_key)
    settings.SIMPLE_JWT = {
        **settings.SIMPLE_JWT,
        "SIGNING_KEY": private_key,
        "VERIFYING_KEY": public_key,
    }


@pytest.mark.django_db()
class TestJWTConfiguration:
    """
    Guards against misconfiguration of simplejwt settings.
    These have broken on upgrades in the past — e.g. ISSUER format
    changing from a list to a string broke refresh token validation
    in the upgrade to Django 5.
    """

    def test_token_obtain_returns_access_and_refresh(self, user_factory):
        user = user_factory(password="testpassword")
        client = APIClient()
        response = client.post(
            "/api/token/",
            {"username": user.username, "password": "testpassword"},
        )
        assert response.status_code == status.HTTP_200_OK, "Token obtain failed"
        assert "access" in response.data, "Response missing access token"
        assert "refresh" in response.data, "Response missing refresh token"

    def test_refresh_token_is_accepted(self, user_factory):
        user = user_factory(password="testpassword")
        client = APIClient()
        response = client.post(
            "/api/token/",
            {"username": user.username, "password": "testpassword"},
        )
        assert response.status_code == status.HTTP_200_OK, "Token obtain failed"
        refresh_token = response.data["refresh"]
        response = client.post("/api/refresh/", {"refresh": refresh_token})
        assert response.status_code == status.HTTP_200_OK, (
            "Refresh token was rejected — check SIMPLE_JWT settings "
            "(ISSUER, ALGORITHM, SIGNING_KEY)"
        )
        assert "access" in response.data
        assert "refresh" in response.data

    def test_refresh_token_is_rotated(self, user_factory):
        user = user_factory(password="testpassword")
        client = APIClient()
        response = client.post(
            "/api/token/",
            {"username": user.username, "password": "testpassword"},
        )
        original_refresh_token = response.data["refresh"]
        response = client.post("/api/refresh/", {"refresh": original_refresh_token})
        new_refresh_token = response.data["refresh"]
        assert new_refresh_token != original_refresh_token, (
            "Refresh token was not rotated — check ROTATE_REFRESH_TOKENS "
            "in SIMPLE_JWT settings"
        )
