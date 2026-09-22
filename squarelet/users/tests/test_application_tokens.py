# Django
from django.utils import timezone

# Standard Library
from datetime import timedelta

# Third Party
import pytest
from Crypto.PublicKey import RSA
from oidc_provider.models import RSAKey
from rest_framework import status
from rest_framework_simplejwt import state
from rest_framework_simplejwt.backends import TokenBackend
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

# Squarelet
from squarelet.users.models import ApplicationToken

LOGGER = "squarelet.users.app_tokens"


@pytest.mark.django_db()
class TestApplicationTokenModel:
    """Model-level behavior for user-owned application tokens"""

    def test_generate_returns_namespaced_plaintext(self, user_factory):
        user = user_factory()
        token, plaintext = ApplicationToken.generate(user, "my script")
        assert plaintext.startswith(f"mr_{token.prefix}_")
        assert token.user == user
        assert token.name == "my script"
        assert token.expires_at is None
        assert token.allow_staff is False

    def test_plaintext_is_not_stored(self, user_factory):
        token, plaintext = ApplicationToken.generate(user_factory(), "script")
        secret = plaintext.split("_", 2)[2]
        token.refresh_from_db()
        for value in (token.prefix, token.hashed_secret, token.name):
            assert secret not in value

    def test_authenticate_round_trip(self, user_factory):
        token, plaintext = ApplicationToken.generate(user_factory(), "script")
        assert token.last_used_at is None
        assert ApplicationToken.authenticate(plaintext) == token
        token.refresh_from_db()
        assert token.last_used_at is not None

    @pytest.mark.parametrize(
        "plaintext",
        ["", "garbage", "mr_nope", "mr_abc_def", "xx_abc_def_ghi"],
    )
    def test_authenticate_malformed(self, plaintext):
        assert ApplicationToken.authenticate(plaintext) is None

    def test_authenticate_wrong_secret(self, user_factory):
        token, _plaintext = ApplicationToken.generate(user_factory(), "script")
        assert ApplicationToken.authenticate(f"mr_{token.prefix}_wrong") is None

    def test_authenticate_revoked(self, user_factory):
        token, plaintext = ApplicationToken.generate(user_factory(), "script")
        token.revoke()
        assert token.revoked_at is not None
        assert not token.is_active
        assert ApplicationToken.authenticate(plaintext) is None

    def test_authenticate_expired(self, user_factory):
        token, plaintext = ApplicationToken.generate(
            user_factory(), "script", expires_in=ApplicationToken.Expiry.WEEK
        )
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save()
        assert not token.is_active
        assert ApplicationToken.authenticate(plaintext) is None

    def test_authenticate_inactive_user(self, user_factory):
        _token, plaintext = ApplicationToken.generate(
            user_factory(is_active=False), "script"
        )
        assert ApplicationToken.authenticate(plaintext) is None

    @pytest.mark.freeze_time("2026-01-15 12:00:00")
    @pytest.mark.parametrize(
        "expires_in,days",
        [
            (ApplicationToken.Expiry.WEEK, 7),
            (ApplicationToken.Expiry.MONTH, 30),
            (ApplicationToken.Expiry.QUARTER, 90),
            (ApplicationToken.Expiry.YEAR, 365),
        ],
    )
    def test_generate_expiration_date(self, user_factory, expires_in, days):
        token, _plaintext = ApplicationToken.generate(
            user_factory(), "script", expires_in=expires_in
        )
        assert token.expires_in == days
        assert token.expires_at == timezone.now() + timedelta(days=days)

    def test_rotate(self, user_factory):
        old, old_plaintext = ApplicationToken.generate(
            user_factory(),
            "script",
            expires_in=ApplicationToken.Expiry.MONTH,
            allow_staff=True,
        )
        new, new_plaintext = old.rotate()
        old.refresh_from_db()
        assert not old.is_active
        assert new.is_active
        assert new.pk != old.pk
        assert new_plaintext != old_plaintext
        assert (new.user, new.name, new.allow_staff, new.expires_in) == (
            old.user,
            old.name,
            old.allow_staff,
            old.expires_in,
        )
        assert ApplicationToken.authenticate(old_plaintext) is None
        assert ApplicationToken.authenticate(new_plaintext) == new

    def test_log_label(self, user_factory):
        token, _plaintext = ApplicationToken.generate(
            user_factory(username="alice"), "nightly scraper"
        )
        assert token.log_label == "alice:nightly scraper"

    def test_active_queryset(self, user_factory):
        user = user_factory()
        active, _ = ApplicationToken.generate(user, "active")
        revoked, _ = ApplicationToken.generate(user, "revoked")
        revoked.revoke()
        expired, _ = ApplicationToken.generate(user, "expired", expires_in=7)
        expired.expires_at = timezone.now() - timedelta(days=1)
        expired.save()
        assert list(user.application_tokens.active()) == [active]

    def test_factory_exposes_plaintext(self, application_token_factory):
        token = application_token_factory()
        assert ApplicationToken.authenticate(token.plaintext) == token


@pytest.fixture
def jwt_rsa_key(db, settings, monkeypatch):  # pylint:disable=unused-argument
    key = RSA.generate(2048)
    private_key = key.export_key().decode()
    RSAKey.objects.create(key=private_key)
    settings.SIMPLE_JWT = {
        **settings.SIMPLE_JWT,
        "SIGNING_KEY": private_key,
        "VERIFYING_KEY": key.publickey().export_key(),
    }
    # simplejwt builds its token backend once, on first use, so overriding
    # settings alone does not reach it if an earlier test already used it
    jwt = settings.SIMPLE_JWT
    monkeypatch.setattr(
        state,
        "token_backend",
        TokenBackend(
            jwt["ALGORITHM"],
            jwt["SIGNING_KEY"],
            jwt["VERIFYING_KEY"],
            jwt["AUDIENCE"],
            jwt["ISSUER"],
        ),
    )


@pytest.mark.django_db()
@pytest.mark.usefixtures("jwt_rsa_key")
class TestApplicationTokenExchange:
    """Scripts exchange an application token for a short-lived JWT pair"""

    url = "/api/token/app/"

    def exchange(self, api_client, plaintext):
        return api_client.post(self.url, {"token": plaintext})

    def test_exchange_returns_jwt_pair(self, api_client, application_token_factory):
        token = application_token_factory(user__username="alice", name="scraper")
        response = self.exchange(api_client, token.plaintext)
        assert response.status_code == status.HTTP_200_OK
        access = AccessToken(response.data["access"])
        assert access["user_id"] == str(token.user.individual_organization_id)
        assert access["app_token_id"] == token.pk
        assert access["app"] == "alice:scraper"
        assert access["staff"] is False
        refresh = RefreshToken(response.data["refresh"])
        assert refresh["app_token_id"] == token.pk
        token.refresh_from_db()
        assert token.last_used_at is not None

    @pytest.mark.parametrize(
        "is_staff,allow_staff,expected",
        [(False, False, False), (False, True, False), (True, False, False)]
        + [(True, True, True)],
    )
    def test_staff_claim(  # pylint: disable=too-many-positional-arguments
        self, api_client, application_token_factory, is_staff, allow_staff, expected
    ):
        token = application_token_factory(
            user__is_staff=is_staff, allow_staff=allow_staff
        )
        response = self.exchange(api_client, token.plaintext)
        assert AccessToken(response.data["access"])["staff"] is expected

    def test_invalid_token(self, api_client):
        response = self.exchange(api_client, "mr_nope_nope")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_token(self, api_client):
        response = api_client.post(self.url, {})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_revoked_token(self, api_client, application_token_factory):
        token = application_token_factory()
        token.revoke()
        response = self.exchange(api_client, token.plaintext)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_token(self, api_client, application_token_factory):
        token = application_token_factory(expires_in=ApplicationToken.Expiry.WEEK)
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save()
        response = self.exchange(api_client, token.plaintext)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_exchange_is_logged(self, api_client, application_token_factory, caplog):
        token = application_token_factory(user__username="alice", name="scraper")
        with caplog.at_level("INFO", logger=LOGGER):
            self.exchange(api_client, token.plaintext)
        assert f"app_token=alice:scraper id={token.pk} event=exchange" in caplog.text

    def test_rejection_is_logged(self, api_client, caplog):
        with caplog.at_level("INFO", logger=LOGGER):
            self.exchange(api_client, "mr_abc123_nope")
        assert "event=rejected" in caplog.text
        assert "prefix=abc123" in caplog.text
        assert "nope" not in caplog.text.replace("prefix=abc123", "")


@pytest.mark.django_db()
@pytest.mark.usefixtures("jwt_rsa_key")
class TestApplicationTokenRefresh:
    """Refresh tokens minted from an application token honor revocation"""

    def pair(self, api_client, token):
        return api_client.post("/api/token/app/", {"token": token.plaintext}).data

    def refresh(self, api_client, refresh_token):
        return api_client.post("/api/refresh/", {"refresh": refresh_token})

    def test_refresh_keeps_claims(self, api_client, application_token_factory):
        token = application_token_factory(user__username="alice", name="scraper")
        response = self.refresh(api_client, self.pair(api_client, token)["refresh"])
        assert response.status_code == status.HTTP_200_OK
        access = AccessToken(response.data["access"])
        assert access["app"] == "alice:scraper"
        assert RefreshToken(response.data["refresh"])["app_token_id"] == token.pk

    def test_refresh_after_revoke(self, api_client, application_token_factory):
        token = application_token_factory()
        refresh_token = self.pair(api_client, token)["refresh"]
        token.revoke()
        response = self.refresh(api_client, refresh_token)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_after_rotate(self, api_client, application_token_factory):
        token = application_token_factory()
        refresh_token = self.pair(api_client, token)["refresh"]
        token.rotate()
        response = self.refresh(api_client, refresh_token)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_is_logged(self, api_client, application_token_factory, caplog):
        token = application_token_factory(user__username="alice", name="scraper")
        refresh_token = self.pair(api_client, token)["refresh"]
        with caplog.at_level("INFO", logger=LOGGER):
            self.refresh(api_client, refresh_token)
        assert f"app_token=alice:scraper id={token.pk} event=refresh" in caplog.text

    def test_password_refresh_unaffected(self, api_client, user_factory):
        user = user_factory(password="testpassword")
        pair = api_client.post(
            "/api/token/", {"username": user.username, "password": "testpassword"}
        ).data
        response = self.refresh(api_client, pair["refresh"])
        assert response.status_code == status.HTTP_200_OK
